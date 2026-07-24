"""
virgo_menu — master TUI dashboard for the virgo agent framework.

Provides an interactive menu to launch network scans, diagnostics,
alert evaluation, auto-fix, web search, and the core pipeline.

Menu layout is loaded from ``dashboard.json`` (next to this file)
and supports dynamic reconfiguration without code changes.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import OUTDIR, log

CONFIG_PATH = os.path.join(HERE, "dashboard.json")

# ── ANSI colour helpers ───────────────────────────────────────────────────
_R = "\033[0m"       # reset
_B = "\033[1m"       # bold
_D = "\033[2m"       # dim
_I = "\033[3m"       # italic
_CY = "\033[36m"     # cyan
_GR = "\033[32m"     # green
_YL = "\033[33m"     # yellow
_RE = "\033[31m"     # red
_MA = "\033[35m"     # magenta
_BL = "\033[34m"     # blue
_WH = "\033[37m"     # white
_BG = "\033[40m"     # bg black

# Windows Terminal supports ANSI from Win10 1511+; skip for cmd.exe fallback
_ENABLE_COLOR = True
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        _ENABLE_COLOR = False


def _c(code: str, text: str) -> str:
    """Wrap *text* in ANSI escape *code* if colors are enabled."""
    return f"{code}{text}{_R}" if _ENABLE_COLOR else text


# ── Menu config loader ────────────────────────────────────────────────────

MENU_CONFIG: dict = {}
if os.path.exists(CONFIG_PATH):
    try:
        MENU_CONFIG = json.load(open(CONFIG_PATH))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", CONFIG_PATH, exc)


def get_config(key: str, default=None):
    """Look up a value in menu config, falling back to *default*."""
    return MENU_CONFIG.get(key, default)


def _build_menu_from_config() -> list[dict]:
    """Build a flat list of menu entries from dashboard.json categories."""
    categories = MENU_CONFIG.get("categories", [])
    entries = []
    for cat in categories:
        for entry in cat.get("entries", []):
            entries.append(entry)
    return entries


MENU_ENTRIES: list[dict] = _build_menu_from_config() if MENU_CONFIG else []


# ── Helpers ───────────────────────────────────────────────────────────────


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def run_script(script_cmd: str) -> None:
    """Run a virgo module by filename with optional args."""
    parts = script_cmd.split()
    script_name = parts[0]
    args = parts[1:]
    print(f"\n  {_c(_GR, '▶')} Executing {script_name} {' '.join(args)}...")
    script_path = os.path.join(HERE, script_name)
    try:
        subprocess.run([sys.executable, script_path] + args, check=True)
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    except Exception as e:
        print(f"  {_c(_RE, '✖')} Error occurred: {e}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def view_file(file_name: str) -> None:
    clear_screen()
    candidate = file_name
    if not os.path.isabs(file_name) and not os.path.exists(file_name):
        in_out = OUTDIR / file_name
        if in_out.exists():
            candidate = str(in_out)
    print(f"  {_c(_MA, '📄')} {_B}Viewing:{_R} {candidate}\n")
    if os.path.exists(candidate):
        with open(candidate) as f:
            print(f.read())
    else:
        print(f"  {_c(_YL, '⚠')} {candidate} does not exist yet.")
    input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def view_search_history() -> None:
    clear_screen()
    print(f"  {_c(_CY, '🕐')} {_B}Web Search History{_R}\n")
    search_files = sorted(glob.glob(str(OUTDIR / "virgo_search_memory_*.json")), reverse=True)
    if not search_files:
        if (OUTDIR / "virgo_search_memory.json").exists():
            search_files = [str(OUTDIR / "virgo_search_memory.json")]
    if search_files:
        for i, f in enumerate(search_files[:10], 1):
            try:
                data = json.load(open(f))
                engine = data.get("engine", "web")
                results = data.get("results", [])
                first = results[0]["title"][:60] if results else "(empty)"
                print(f"  [{i}] {f}  [{engine}]  {first}")
            except Exception:
                print(f"  [{i}] {f}  (corrupt)")
        print()
        choice = input(f"  {_c(_CY, '↩')} View file number (or ENTER to go back): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(search_files):
            view_file(search_files[int(choice) - 1])
    else:
        print("  No search history found.")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def run_pipeline() -> None:
    """Run the core virgo agent pipeline."""
    print(f"\n  {_c(_CY, '🧠')} {_B}VIRGO CORE PIPELINE{_R}")
    print(f"  {_box_line('─', 50)}")
    goal = input(f"  {_c(_CY, '↩')} Enter goal (default: Scan and parse mock_logs.txt): ").strip()
    if not goal:
        goal = "Scan and parse mock_logs.txt"
    use_llm = input(f"  {_c(_YL, '⚙')} Use LLM? (requires Ollama) [y/N]: ").strip().lower() == "y"
    cmd = [sys.executable, os.path.join(HERE, "cli.py"), "run", "--goal", goal]
    if use_llm:
        cmd.append("--llm")
    print(f'\n  {_c(_GR, "▶")} Running: virgo run --goal "{goal}"' + (" --llm" if use_llm else ""))
    try:
        subprocess.run(cmd)
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    except Exception as e:
        print(f"  {_c(_RE, '✖')} Error: {e}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _dispatch_action(entry: dict) -> bool:
    """Run the action for a menu entry. Return False to exit."""
    action = entry.get("action", "script")
    script = entry.get("script", "")

    if action == "pipeline":
        run_pipeline()
    elif action == "search_history":
        view_search_history()
    elif action == "scaffold_list":
        run_script("virgo_scaffold.py list")
    elif action == "scaffold_gen":
        name = input(
            f"  {_c(_CY, '↩')} Project name [{entry.get('default_name', 'myapp')}]: "
        ).strip() or entry.get("default_name", "myapp")
        var_flag = f"-v {entry['var_name']}" if "var_name" in entry else "-v project_name"
        run_script(
            f"virgo_scaffold.py generate {entry['scaffold']} "
            f"-o ../scaffold-output/{entry['scaffold']} "
            f"{var_flag}={name}"
        )
    elif action == "view":
        view_file(entry["file"])
    elif action == "script":
        args = entry.get("args", "")
        run_script(f"{script} {args}".strip())
    else:
        print(f"  {_c(_YL, '⚠')} Unknown action: {action}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    return True


# ── Arrow-key navigator ──────────────────────────────────────────────────


def _have_msvcrt() -> bool:
    """Return True if msvcrt is available (Windows)."""
    try:
        import msvcrt  # noqa: F401
        return True
    except ImportError:
        return False


def _arrow_prompt(options: list[dict]) -> str:
    """Display menu with arrow-key navigation (Windows) or fall back to input()."""
    if not _have_msvcrt() or not sys.stdin.isatty():
        choice = input(f"  {_c(_CY, '↩')} Select an option: ").strip().upper()
        return choice

    import msvcrt
    import shutil

    sel = 0

    def _render_list(sel_idx: int) -> None:
        cols = shutil.get_terminal_size().columns
        start = max(0, sel_idx - 8)
        end = min(len(options), sel_idx + 9)
        for i in range(start, end):
            entry = options[i]
            oid = entry.get("key", "??")
            label = entry.get("label", "???")
            is_exit = label == "Exit Dashboard"
            if is_exit:
                # Separator before exit
                print(f"  {_c(_CY, '╠' + '═' * (cols - 6) + '╣')[:cols - 1]}")
                prefix = f"  {_c(_CY, '║')}  {_c(_RE, '▸')}" if i == sel_idx else f"  {_c(_CY, '║')}   "
                suffix = f" {_c(_D, '◂')}" if i == sel_idx else ""
                line = f"{prefix}[{_c(_B + _RE, oid)}]  {_c(_RE, label)}{suffix}"
            else:
                prefix = f"  {_c(_CY, '║')}  {_c(_CY, '▸')}" if i == sel_idx else f"  {_c(_CY, '║')}   "
                suffix = f" {_c(_D, '◂')}" if i == sel_idx else ""
                line = f"{prefix}[{_c(_B + _CY, oid)}] {label}{suffix}"
            print(line.ljust(cols - 1))
        # Bottom border
        print(f"  {_c(_CY, '╚' + '═' * (cols - 6) + '╝')[:cols - 1]}")
        print()

    # Hide cursor
    print("\033[?25l", end="", flush=True)

    while True:
        _render_list(sel)

        key = msvcrt.getch()
        if key == b"\xe0":  # Arrow keys send two bytes on Windows
            key2 = msvcrt.getch()
            if key2 == b"H":  # Up
                sel = (sel - 1) % len(options)
            elif key2 == b"P":  # Down
                sel = (sel + 1) % len(options)
            elif key2 == b"M":  # Right (next page)
                sel = min(sel + 8, len(options) - 1)
            elif key2 == b"K":  # Left (prev page)
                sel = max(sel - 8, 0)
        elif key == b"\r":  # Enter
            print("\033[?25h", end="", flush=True)  # Restore cursor
            return options[sel].get("key", "")
        elif key in (b"q", b"Q", b"x", b"X"):
            print("\033[?25h", end="", flush=True)
            return "X"
        elif key.isdigit():
            print("\033[?25h", end="", flush=True)
            return chr(key[0])
        elif len(key) == 1 and key == b"\x1b":  # Escape
            print("\033[?25h", end="", flush=True)
            return "X"

        # Move cursor back up
        rows_rendered = min(len(options), 18) + 3  # +2 for border lines, +1 for spacing
        print(f"\033[{rows_rendered}A", end="", flush=True)

    print("\033[?25h", end="", flush=True)  # Restore cursor


# ── Dashboard renderer ───────────────────────────────────────────────────


def _draw_header(title: str, width: int) -> None:
    """Draw the dashboard header with box-drawing characters."""
    w = min(width - 4, 74)
    safe = w - 4

    # Constellation line
    stars = _c(_D, "  ✦  " * (safe // 5))
    tagline = _c(_I, "multi-agent state machine")
    phases = _c(_D, "discover → plan → code → test → fix")

    print()
    print(f"  {_c(_CY, '╔' + '═' * w + '╗')}")
    print(f"  {_c(_CY, '║')}  {stars:{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '║')}  {'':{safe}s}  {_c(_CY, '║')}")

    # Show ASCII logo
    try:
        import pyfiglet
        logo_text = pyfiglet.figlet_format("VIRGO", font="banner3-D")
        for line in logo_text.rstrip().split("\n"):
            lw = len(line)
            if lw <= safe:
                print(f"  {_c(_CY, '║')}  {_c(_B + _WH, line)}{' ' * (safe - lw)}  {_c(_CY, '║')}")
    except ImportError:
        logo_lines = [
            "__      _______ _____   _____  ____",
            "\\ \\    / /_   _|  __ \\ / ____|/ __ \\",
            " \\ \\  / /  | | | |__) | |  __| |  | |",
            "  \\ \\/ /   | | |  _  /| | |_ | |  | |",
            "   \\  /   _| |_| | \\ \\| |__| | |__| |",
            "    \\/    |_____|_|  \\_\\\\_____|____/",
        ]
        for line in logo_lines:
            lw = len(line)
            if lw <= safe:
                print(f"  {_c(_CY, '║')}  {_c(_B + _CY, line)}{' ' * (safe - lw)}  {_c(_CY, '║')}")

    print(f"  {_c(_CY, '║')}  {'':{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '║')}  {stars:{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '║')}  {'':{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '║')}  {tagline:^{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '║')}  {phases:^{safe}s}  {_c(_CY, '║')}")
    print(f"  {_c(_CY, '╚' + '═' * w + '╝')}")
    print()


def _draw_category_heading(heading: str, width: int) -> None:
    """Draw a category heading like ── VIRGO MODULES ──"""
    safe = width - 4
    text = f"  {_B}{heading}{_R}"
    dash = _c(_D, "─")
    padding = (safe - len(heading) - 2) // 2
    print(f"  {dash * padding}  {text}  {dash * (safe - padding - len(heading) - 2)}")


def _draw_menu_entry(oid: str, label: str) -> None:
    """Print a single menu entry with box-drawing border."""
    print(f"  {_c(_CY, '║')}  [{_c(_B + _WH, oid)}]  {label}")


def _draw_category_bottom(width: int) -> None:
    """Draw the bottom border of a category group."""
    safe = width - 4
    print(f"  {_c(_CY, '║')}  {' ' * safe}")


def _box_line(char: str, width: int) -> str:
    """Return a horizontal line made of *char*."""
    if _ENABLE_COLOR:
        return f"{_D}{char * width}{_R}"
    return char * width


def master_dashboard() -> None:
    categories = MENU_CONFIG.get("categories", [])
    exit_key = MENU_CONFIG.get("exit_key", "X")
    entries = _build_menu_from_config()

    if not entries:
        print(f"{icon('error')} No menu entries found in {CONFIG_PATH}")
        print("Ensure dashboard.json has valid category/entry definitions.")
        input("\nPress Enter to exit.")
        return

    while True:
        clear_screen()
        title = MENU_CONFIG.get("title", "VIRGO AGENT FRAMEWORK - MASTER CONTROL")

        try:
            import shutil
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 80

        box_width = min(term_width - 4, 76)
        content_width = box_width

        # ── Header ────────────────────────────────────────────────────
        _draw_header(title, box_width)

        # ── Categories ────────────────────────────────────────────────
        for cat in categories:
            heading = cat.get("heading", "MODULES")
            _draw_category_heading(heading, content_width)
            for entry in cat.get("entries", []):
                oid = entry.get("key", "??")
                label = entry.get("label", "???")
                _draw_menu_entry(oid, label)
            _draw_category_bottom(content_width)

        # ── Footer ────────────────────────────────────────────────────
        # Exit is the last selectable item in the navigation below
        # ── Key handler ───────────────────────────────────────────────

        # Add exit as a navigation option
        nav_entries = list(entries) + [{"key": exit_key, "label": "Exit Dashboard"}]
        if _have_msvcrt():
            choice = _arrow_prompt(nav_entries)
        else:
            print(f"  {_c(_D, '  ↑↓ navigate  ↵ enter  [{exit_key}] exit')}{_R}")
            choice = input(f"  {_c(_CY, '↩')} Select an option: ").strip().upper()

        if choice.upper() == exit_key:
            clear_screen()
            print()
            print(f"  {_c(_CY, '╔' + '═' * 42 + '╗')}")
            print(f"  {_c(_CY, '║')}  {_c(_B + _WH, '   ✦  VIRGO  ✦')}     {_c(_CY, '║')}")
            print(f"  {_c(_CY, '║')}  {'  multi-agent state machine':42s}{_c(_CY, '║')}")
            print(f"  {_c(_CY, '║')}  {_c(_D, '  control bridge disengaged'):42s}{_c(_CY, '║')}")
            print(f"  {_c(_CY, '╚' + '═' * 42 + '╝')}")
            print(f"\n  {_c(_GR, '✦')} See ya! {_c(_GR, '✦')}")
            print()
            break

        # Match by key (01-22, 1-22, etc.)
        matched_entry = None
        for entry in entries:
            oid = entry.get("key", "")
            if choice in (oid, oid.lstrip("0")):
                matched_entry = entry
                break

        if matched_entry is not None:
            _dispatch_action(matched_entry)
        else:
            input(f"\n  {_c(_YL, '⚠')} Invalid choice. Press Enter to try again.")


if __name__ == "__main__":
    master_dashboard()

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

# ── Load menu config ────────────────────────────────────────────────────

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


# ── Menu entries (built from JSON) ──────────────────────────────────────

MENU_ENTRIES: list[dict] = _build_menu_from_config() if MENU_CONFIG else []


# ── Helpers ─────────────────────────────────────────────────────────────


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def run_script(script_cmd: str) -> None:
    """Run a virgo module by filename with optional args.

    Uses the framework directory, not CWD, so this works from any
    working directory.
    """
    parts = script_cmd.split()
    script_name = parts[0]
    args = parts[1:]
    print(f"\n{icon('rocket')} Executing {script_name} {' '.join(args)}...")
    script_path = os.path.join(HERE, script_name)
    try:
        subprocess.run([sys.executable, script_path] + args, check=True)
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")
    except Exception as e:
        print(f"{icon('error')} Error occurred: {e}")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


def view_file(file_name: str) -> None:
    clear_screen()
    # Reports live in the shared output dir; resolve bare names there.
    candidate = file_name
    if not os.path.isabs(file_name) and not os.path.exists(file_name):
        in_out = OUTDIR / file_name
        if in_out.exists():
            candidate = str(in_out)
    print(f"{icon('file')} --- Viewing File: {candidate} ---\n")
    if os.path.exists(candidate):
        with open(candidate) as f:
            print(f.read())
    else:
        print(f"{icon('warn')} {candidate} does not exist yet. Run the corresponding tool first.")
    input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


def view_search_history() -> None:
    clear_screen()
    print(f"{icon('history')} --- Web Search History ---\n")
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
        choice = input(f"{icon('arrow')} View file number (or ENTER to go back): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(search_files):
            view_file(search_files[int(choice) - 1])
    else:
        print("  No search history found. Run a search first.")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


def run_pipeline() -> None:
    """Run the core virgo agent pipeline."""
    print(f"\n{icon('brain')} VIRGO CORE PIPELINE")
    print("------------------------")
    goal = input(f"{icon('arrow')} Enter goal (default: Scan and parse mock_logs.txt): ").strip()
    if not goal:
        goal = "Scan and parse mock_logs.txt"
    use_llm = input(f"{icon('info')} Use LLM? (requires Ollama) [y/N]: ").strip().lower() == "y"
    cmd = [sys.executable, os.path.join(HERE, "cli.py"), "run", "--goal", goal]
    if use_llm:
        cmd.append("--llm")
    print(f'\n{icon("rocket")} Running: virgo run --goal "{goal}"' + (" --llm" if use_llm else ""))
    try:
        subprocess.run(cmd)
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")
    except Exception as e:
        print(f"{icon('error')} Error: {e}")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


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
            f"{icon('arrow')} Project name [{entry.get('default_name', 'myapp')}]: "
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
        print(f"{icon('warn')} Unknown action: {action}")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")
    return True


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
        choice = input(f"{icon('arrow')} Select an option: ").strip().upper()
        return choice

    import msvcrt
    import shutil

    sel = 0

    def render() -> None:
        cols = shutil.get_terminal_size().columns
        start = max(0, sel - 8)
        end = min(len(options), sel + 9)
        for i in range(start, end):
            entry = options[i]
            oid = entry.get("key", "??")
            label = entry.get("label", "???")
            prefix = "  >" if i == sel else "   "
            suffix = " <" if i == sel else ""
            print(f"{prefix}[{oid}] {label}{suffix}".ljust(cols - 1))
        print()

    # Hide cursor
    print("\033[?25l", end="", flush=True)

    while True:
        cols = shutil.get_terminal_size().columns
        start = max(0, sel - 8)
        end = min(len(options), sel + 9)
        for i in range(start, end):
            entry = options[i]
            oid = entry.get("key", "??")
            label = entry.get("label", "???")
            prefix = "  >" if i == sel else "   "
            suffix = " <" if i == sel else ""
            line = f"{prefix}[{oid}] {label}{suffix}"
            print(line.ljust(cols - 1))

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
        elif key.isdigit() or (len(key) == 1 and key in b"\x1b"):
            print("\033[?25h", end="", flush=True)
            if key == b"\x1b":  # Escape → X
                return "X"
            return chr(key[0]) if key else ""

        # Move cursor back up
        rows = end - start + 1
        print(f"\033[{rows}A", end="", flush=True)

    print("\033[?25h", end="", flush=True)  # Restore cursor


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
        title = MENU_CONFIG.get("title", "VIRGO AGENT FRAMEWORK")
        print("=" * 60)
        print(f"          {icon('virgo')} {title}")
        print("=" * 60)

        for cat in categories:
            heading = cat.get("heading", "MODULES")
            print(f"  {heading}")
            for entry in cat.get("entries", []):
                oid = entry.get("key", "??")
                label = entry.get("label", "???")
                print(f"  [{oid}]  {label}")
            print("-" * 60)

        print(f"  [{exit_key}]  Exit Dashboard")
        print("=" * 60)

        # Use arrow-key navigation on Windows, fall back to plain input
        if _have_msvcrt():
            choice = _arrow_prompt(entries)
        else:
            choice = input(f"{icon('arrow')} Select an option: ").strip().upper()

        if choice.upper() == exit_key:
            print(f"\n{icon('done')} Shutting down Virgo control bridge. See ya!")
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
            input(f"\n{icon('error')} Invalid choice. Press Enter to try again.")


if __name__ == "__main__":
    master_dashboard()

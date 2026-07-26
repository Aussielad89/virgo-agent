"""
virgo_menu — CYBERPUNK EDITION TUI dashboard for the virgo agent framework.

Provides an interactive menu with live system stats, persona-aware styling,
mascot display, achievement notifications, and arrow-key navigation.

Menu layout is loaded from ``dashboard.json`` (next to this file)
and supports dynamic reconfiguration without code changes.

New features in Cyberpunk Edition:
  - Live CPU/RAM/disk gauges in header
  - Mascot display panel (CyberCat, GhostBot, HackFox, PixelDragon)
  - Persona-aware color theming
  - Achievement pop-up notifications
  - Activity feed showing recent events
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

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
_U = "\033[4m"       # underline
_CY = "\033[36m"     # cyan
_GR = "\033[32m"     # green
_YL = "\033[33m"     # yellow
_RE = "\033[31m"     # red
_MA = "\033[35m"     # magenta
_BL = "\033[34m"     # blue
_WH = "\033[37m"     # white
_BG = "\033[40m"     # bg black
# Extended 256-colour helpers for cyberpunk glow
_OGE = "\033[38;5;214m"  # orange (gauges)
_PNK = "\033[38;5;206m"  # pink (mascot)
_LBL = "\033[38;5;81m"   # light blue (stats)
_LGR = "\033[38;5;119m"  # light green (ok)
_LRD = "\033[38;5;196m"  # light red (error)

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


# ── Module-level lazy imports for optional features ─────────────────────

_HAS_PSUTIL = False
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    pass

_PERSONA_MODULE = None
_MASCOT_MODULE = None
_ACHIEVEMENTS_MODULE = None
_FOCUS_MODULE = None


def _try_load_persona():
    global _PERSONA_MODULE
    if _PERSONA_MODULE is None:
        try:
            import virgo_persona as p
            _PERSONA_MODULE = p
        except Exception:
            pass
    return _PERSONA_MODULE


def _try_load_mascot():
    global _MASCOT_MODULE
    if _MASCOT_MODULE is None:
        try:
            import virgo_mascot as m
            _MASCOT_MODULE = m
        except Exception:
            pass
    return _MASCOT_MODULE


def _try_load_achievements():
    global _ACHIEVEMENTS_MODULE
    if _ACHIEVEMENTS_MODULE is None:
        try:
            import virgo_achievements as a
            _ACHIEVEMENTS_MODULE = a
        except Exception:
            pass
    return _ACHIEVEMENTS_MODULE


def _try_load_focus():
    global _FOCUS_MODULE
    if _FOCUS_MODULE is None:
        try:
            import virgo_focus as f
            _FOCUS_MODULE = f
        except Exception:
            pass
    return _FOCUS_MODULE


# ── Activity feed ──────────────────────────────────────────────────────────

_ACTIVITY_LOG: list[dict] = []
_MAX_ACTIVITY = 20


def _log_activity(event: str, detail: str = "", result: str = "info") -> None:
    """Add an event to the activity feed."""
    global _ACTIVITY_LOG
    _ACTIVITY_LOG.append({
        "time": datetime.now(UTC).strftime("%H:%M:%S"),
        "event": event,
        "detail": detail,
        "result": result,
    })
    if len(_ACTIVITY_LOG) > _MAX_ACTIVITY:
        _ACTIVITY_LOG = _ACTIVITY_LOG[-_MAX_ACTIVITY:]


# ── Menu config loader ─────────────────────────────────────────────────────

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


# ── Helpers ────────────────────────────────────────────────────────────────


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
        _log_activity("script", script_name, "success")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    except Exception as e:
        print(f"  {_c(_RE, '✖')} Error occurred: {e}")
        _log_activity("script", f"{script_name} failed", "fail")
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
    _log_activity("pipeline", goal, "started")
    try:
        subprocess.run(cmd)
        _log_activity("pipeline", goal, "complete")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    except Exception as e:
        print(f"  {_c(_RE, '✖')} Error: {e}")
        _log_activity("pipeline", goal, "fail")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _dispatch_action(entry: dict) -> bool:
    """Run the action for a menu entry. Return False to exit."""
    action = entry.get("action", "script")
    script = entry.get("script", "")
    custom = entry.get("custom_action", "")

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
    elif action == "custom":
        _handle_custom_action(custom)
    else:
        print(f"  {_c(_YL, '⚠')} Unknown action: {action}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
    return True


def _handle_custom_action(custom_action: str) -> None:
    """Handle custom in-menu actions for fun features."""
    if custom_action == "persona_menu":
        _persona_menu()
    elif custom_action == "achievements_menu":
        _achievements_menu()
    elif custom_action == "mascot_menu":
        _mascot_menu()
    elif custom_action == "focus_menu":
        _focus_menu()
    else:
        print(f"  {_c(_YL, '⚠')} Unknown custom action: {custom_action}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _persona_menu() -> None:
    """Interactive persona selector."""
    p = _try_load_persona()
    if p is None:
        print(f"\n  {_c(_YL, '⚠')} Persona module not available.")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    try:
        personas = p.list_personas()
        current = p.current_persona_name()
    except Exception as e:
        print(f"\n  {_c(_RE, '✖')} Error: {e}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    clear_screen()
    print(f"\n  {_c(_MA, '🎭')} {_B}PERSONA SYSTEM{_R}")
    print(f"  {_box_line('─', 50)}")
    print(f"  Current: {_c(_B, current)}\n")

    for persona in personas:
        name = persona.get("name", "?")
        display = persona.get("display_name", name)
        style = persona.get("response_style", "")
        marker = " ◀ ACTIVE" if name == current else ""
        selected = _c(_GR, marker) if marker else ""
        print(f"  [{name:12s}] {display:20s}  {_c(_D, style)}{selected}")

    print()
    choice = input(f"  {_c(_CY, '↩')} Set persona (name) or ENTER to cancel: ").strip()
    if choice:
        try:
            p.set_persona(choice)
            print(f"\n  {_c(_GR, '✓')} Persona changed to: {_c(_B, choice)}")
            _log_activity("persona", f"changed to {choice}", "success")
            # Try to trigger achievement
            ach = _try_load_achievements()
            if ach:
                try:
                    ach.get_achievements().hook("persona_change", persona=choice)
                except Exception:
                    pass
        except KeyError:
            print(f"\n  {_c(_RE, '✖')} Unknown persona: {choice}")
    input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _achievements_menu() -> None:
    """Show achievements overview."""
    ach = _try_load_achievements()
    if ach is None:
        print(f"\n  {_c(_YL, '⚠')} Achievements module not available.")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    try:
        system = ach.get_achievements()
        progress = system.get_all_progress()
        stats = system.get_stats()
        recent = system.get_recent(limit=5)
    except Exception as e:
        print(f"\n  {_c(_RE, '✖')} Error: {e}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    clear_screen()
    print(f"\n  {_c(_YL, '🏆')} {_B}ACHIEVEMENTS & STATS{_R}")
    print(f"  {_box_line('─', 50)}")

    # Stats
    level = stats.get("level", 1)
    xp = stats.get("total_xp", 0)
    unlocked = stats.get("unlocked", 0)
    total = stats.get("total", len(progress))
    next_xp = stats.get("xp_for_next", 0)
    print(f"  Level: {_c(_B + _GR, str(level))}  |  XP: {_c(_YL, str(xp))}  "
          f"|  Unlocked: {_c(_CY, f'{unlocked}/{total}')}")
    if next_xp:
        print(f"  Next level: {_c(_D, f'{next_xp} XP needed')}")
    print()

    # Recently unlocked
    if recent:
        print(f"  {_c(_GR, '✦')} {_U}Recent Unlocks{_R}")
        for a in recent:
            xp_val = a.get("xp", 0)
            print(f"    {a.get('icon', '🏆')}  {a.get('name', '?')}  "
                  f"{_c(_D, f'(+{xp_val} XP)')}")
        print()

    # All achievements
    print(f"  {_c(_D, '── All Achievements ──')}")
    for p in progress:
        pid = p.get("id", "?")
        pname = p.get("name", "?")
        icon_c = p.get("icon", "◌")
        unlocked_p = p.get("unlocked", False)
        xp_val = p.get("xp", 0)
        if unlocked_p:
            status = _c(_GR, "✓")
            desc = _c(_D, p.get("description", ""))
        else:
            status = _c(_D, "○")
            desc = _c(_I + _D, p.get("description", ""))
        print(f"  {status} {icon_c}  {pname:25s}  {_c(_D, f'+{xp_val} XP'):>8s}  {desc}")

    input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _mascot_menu() -> None:
    """Interactive mascot selector."""
    m = _try_load_mascot()
    if m is None:
        print(f"\n  {_c(_YL, '⚠')} Mascot module not available.")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    try:
        mascots = m.list_mascots()
        current = m.current_mascot_name()
    except Exception as e:
        print(f"\n  {_c(_RE, '✖')} Error: {e}")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    clear_screen()
    print(f"\n  {_c(_PNK, '🐾')} {_B}MASCOT SIDEKICK{_R}")
    print(f"  {_box_line('─', 50)}")
    print(f"  Current: {_c(_B, current)}\n")

    for mascot in mascots:
        name = mascot.get("tag", "?")
        display = mascot.get("display", name)
        marker = " ◀ ACTIVE" if name == current else ""
        ascii_art = mascot.get("ascii", "")
        selected = _c(_GR, marker) if marker else ""
        print(f"  [{name:14s}] {display:20s}{selected}")
        if ascii_art:
            for line in ascii_art.split("\n")[:2]:
                print(f"  {'':18s}{_c(_PNK, line)}")

    print()
    choice = input(f"  {_c(_CY, '↩')} Set mascot (name) or ENTER to cancel: ").strip()
    if choice:
        try:
            m.set_mascot(choice)
            print(f"\n  {_c(_GR, '✓')} Mascot changed to: {_c(_B, choice)}")
            _log_activity("mascot", f"changed to {choice}", "success")
            ach = _try_load_achievements()
            if ach:
                try:
                    ach.get_achievements().hook("mascot_activate", mascot=choice)
                except Exception:
                    pass
            # Speak
            try:
                print(f"\n  {m.speak('Hello! Ready to code!')}")
            except Exception:
                pass
        except KeyError:
            print(f"\n  {_c(_RE, '✖')} Unknown mascot: {choice}")
    input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


def _focus_menu() -> None:
    """Interactive focus mode controller."""
    fmod = _try_load_focus()
    if fmod is None:
        print(f"\n  {_c(_YL, '⚠')} Focus mode module not available.")
        input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")
        return

    clear_screen()
    print(f"\n  {_c(_LBL, '🎧')} {_B}FOCUS MODE{_R}")
    print(f"  {_box_line('─', 50)}")

    st = fmod.status()
    if st.get("active"):
        print(f"  Status: {_c(_GR, 'ACTIVE')} — {st.get('genre_name', '?')} "
              f"({int(st.get('elapsed_minutes', 0))}m)")
        stop_choice = input(f"\n  {_c(_CY, '↩')} Stop focus mode? [y/N]: ").strip().lower()
        if stop_choice == "y":
            result = fmod.stop()
            print(f"\n  {_c(_GR, '✓')} Focus mode stopped — {result['elapsed_minutes']}m elapsed")
            _log_activity("focus", "stopped", "info")
    else:
        print(f"  Status: {_c(_D, 'inactive')}")
        print(f"  Total: {st.get('total_sessions', 0)} sessions, "
              f"{round(st.get('total_minutes', 0), 1)} minutes\n")

        print(f"  {_c(_D, 'Available genres:')}")
        genres = fmod.list_genres()
        for g in genres:
            print(f"    {g['id']:12s}  {g['name']:18s}  {g['bpm']:3d} BPM  — {g['description']}")

        print()
        choice = input(f"  {_c(_CY, '↩')} Genre to start (or ENTER to cancel): ").strip()
        if choice and choice in {g["id"] for g in genres}:
            result = fmod.start(choice)
            print(f"\n  {_c(_GR, '✓')} Focus mode started — {result.get('name', choice)}")
            _log_activity("focus", f"started {choice}", "success")
            ach = _try_load_achievements()
            if ach:
                try:
                    ach.get_achievements().hook("focus_mode", genre=choice)
                except Exception:
                    pass
        elif choice:
            print(f"\n  {_c(_RE, '✖')} Unknown genre: {choice}")

    input(f"\n  {_c(_CY, '↩')} {_c(_D, '[PRESS ENTER TO RETURN TO MENU]')}")


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


# ── Cyberpunk Dashboard renderers ────────────────────────────────────────


def _get_system_stats() -> dict:
    """Get live system stats via psutil with graceful fallback."""
    stats = {
        "cpu": "---",
        "ram": "---",
        "disk": "---",
        "cpu_bar": "",
        "ram_bar": "",
        "disk_bar": "",
    }
    if not _HAS_PSUTIL:
        stats["cpu"] = "offline"
        stats["ram"] = "offline"
        stats["disk"] = "offline"
        return stats

    try:
        cpu = psutil.cpu_percent(interval=0.1)
        stats["cpu"] = f"{cpu:.0f}%"
        stats["cpu_bar"] = _make_bar(cpu, 12)
    except Exception:
        pass

    try:
        ram = psutil.virtual_memory()
        stats["ram"] = f"{ram.percent:.0f}%"
        stats["ram_bar"] = _make_bar(ram.percent, 12)
    except Exception:
        pass

    try:
        disk = psutil.disk_usage(os.path.sep)
        disk_pct = disk.used / disk.total * 100
        stats["disk"] = f"{disk_pct:.0f}%"
        stats["disk_bar"] = _make_bar(disk_pct, 12)
    except Exception:
        pass

    return stats


def _make_bar(pct: float, width: int) -> str:
    """Create an ASCII progress bar at the given percentage."""
    filled = max(0, min(width, int(pct / 100 * width)))
    empty = width - filled
    if pct >= 80:
        color = _RE
    elif pct >= 50:
        color = _YL
    else:
        color = _GR
    return f"{color}{'█' * filled}{_D}{'░' * empty}{_R}"


def _get_mascot_panel(width: int) -> list[str]:
    """Build mascot display panel lines."""
    mascot = _try_load_mascot()
    if mascot is None:
        return []

    try:
        current_name = mascot.current_mascot_name()
        ascii_art = mascot.mascot_ascii(current_name)
        action = mascot.idle_action()
    except Exception:
        return []

    lines = []
    safe = max(width - 4, 20)
    for art_line in ascii_art.split("\n"):
        lines.append(f"  {_c(_PNK, art_line):{safe}s}")

    mascot_display = mascot.get_mascot(current_name).get("display", current_name)
    lines.append(f"  {_c(_PNK, '✦')} {_B}{mascot_display}{_R}")
    lines.append(f"  {_c(_D, action)}")
    lines.append("")
    return lines


def _get_activity_panel(width: int) -> list[str]:
    """Build activity feed panel lines."""
    global _ACTIVITY_LOG
    if not _ACTIVITY_LOG:
        return [f"  {_c(_D, 'No recent activity')}"]
    
    lines = []
    safe = max(width - 6, 30)
    # Show last 5 activities
    for entry in _ACTIVITY_LOG[-5:]:
        t = entry.get("time", "")
        ev = entry.get("event", "")
        dt = entry.get("detail", "")[:safe]
        res = entry.get("result", "info")
        if res == "success":
            color = _GR
        elif res == "fail":
            color = _RE
        else:
            color = _D
        lines.append(f"  {_c(_D, t)} {color}{ev}{_R} {_c(_D, dt)}")
    return lines


def _get_achievement_badge() -> str | None:
    """Return a recent achievement notification if any."""
    ach = _try_load_achievements()
    if ach is None:
        return None
    try:
        system = ach.get_achievements()
        recent = system.get_recent(limit=1)
        if recent:
            a = recent[0]
            return (f"  {_c(_YL, '🏆')} {_B}Achievement Unlocked:{_R} "
                    f"{a.get('icon', '')} {a.get('name', '???')} "
                    f"({a.get('xp', 0)} XP)")
    except Exception:
        pass
    return None


def _get_persona_style() -> dict:
    """Get persona-aware colors for the dashboard."""
    p = _try_load_persona()
    if p is None:
        return {"primary": _CY, "accent": _WH, "highlight": _GR}
    
    try:
        persona = p.get_persona()
        colors = persona.get("theme_colors", {})
        primary = colors.get("primary", "cyan")
        accent = colors.get("accent", "white")
        # Map named colors to ANSI codes
        color_map = {
            "green": _GR, "cyan": _CY, "purple": _MA,
            "blue": _BL, "red": _RE, "pink": _PNK,
            "gold": _OGE, "white": _WH, "lime": _LGR,
            "orange": _OGE, "yellow": _YL,
        }
        return {
            "primary": color_map.get(primary, _CY),
            "accent": color_map.get(accent, _WH),
            "highlight": color_map.get(colors.get("highlight", "green"), _GR),
            "persona_name": persona.get("display_name", persona.get("name", "virgo")),
            "style": persona.get("response_style", ""),
        }
    except Exception:
        return {"primary": _CY, "accent": _WH, "highlight": _GR}


def _get_focus_status() -> str | None:
    """Return focus mode status if active."""
    fmod = _try_load_focus()
    if fmod is None:
        return None
    try:
        st = fmod.status()
        if st.get("active"):
            mins = st.get("elapsed_minutes", 0)
            return (f"  {_c(_LBL, '🎧')} {_c(_LBL, 'FOCUS')} "
                    f"{st.get('genre_name', '?')} — {int(mins)}m")
    except Exception:
        pass
    return None


def _draw_header(title: str, width: int, persona_style: dict) -> None:
    """Draw the cyberpunk dashboard header with live stats and mascot."""
    w = min(width - 4, 74)
    safe = w - 4

    p_color = persona_style.get("primary", _CY)
    p_name = persona_style.get("persona_name", "VIRGO")

    # ── System stats panel (left) ──
    stats = _get_system_stats()
    stats_lines = [
        f"  {_c(_LBL, '⚡ CPU')} {stats['cpu']:>5s}  {stats['cpu_bar']}",
        f"  {_c(_LBL, '🅂 RAM')} {stats['ram']:>5s}  {stats['ram_bar']}",
        f"  {_c(_LBL, '💾 DSK')} {stats['disk']:>5s}  {stats['disk_bar']}",
    ]

    # ── Mascot panel (right) ──
    mascot_lines = _get_mascot_panel(w)

    # ── Build the header ──
    print()
    print(f"  {p_color}{'╔' + '═' * w + '╗'}{_R}")
    
    # Top decorative line with cyberpunk stars
    stars = _c(_D, "✦" * (safe // 4))
    print(f"  {p_color}║{_R}  {stars:{safe}s}  {p_color}║{_R}")

    # Title line with persona
    title_centered = f"{_B}{p_color}{title}{_R}"
    print(f"  {p_color}║{_R}  {title_centered:^{safe}s}  {p_color}║{_R}")
    print(f"  {p_color}║{_R}  {_c(_D, f'persona: {p_name}'):^{safe}s}  {p_color}║{_R}")
    
    # Separator
    print(f"  {p_color}║{_R}  {_c(_D, '─' * safe)}  {p_color}║{_R}")

    # ── Stats + mascot panels ──
    if mascot_lines:
        # Show stats stacked above mascot — cleaner than side-by-side
        for line in stats_lines:
            print(f"  {p_color}║{_R}  {line:{safe}s}  {p_color}║{_R}")
        
        # Mascot panel as a separate block
        print(f"  {p_color}║{_R}  {_c(_D, '── sidekick ──'):^{safe}s}  {p_color}║{_R}")
        for line in mascot_lines:
            print(f"  {p_color}║{_R}  {line:{safe}s}  {p_color}║{_R}")
    else:
        for line in stats_lines:
            print(f"  {p_color}║{_R} {line:{safe+4}s} {p_color}║{_R}")

    # ── Focus mode status ──
    focus_status = _get_focus_status()
    if focus_status:
        print(f"  {p_color}║{_R} {focus_status:^{safe+4}s} {p_color}║{_R}")

    # ── Achievement badge ──
    badge = _get_achievement_badge()
    if badge:
        print(f"  {p_color}║{_R} {badge:^{safe+4}s} {p_color}║{_R}")

    # ── Activity feed ──
    activity_lines = _get_activity_panel(w)
    if activity_lines:
        print(f"  {p_color}║{_R}  {_c(_D, '── recent activity ──'):^{safe}s}  {p_color}║{_R}")
        for line in activity_lines[-3:]:  # Show last 3
            print(f"  {p_color}║{_R} {line:{safe+4}s} {p_color}║{_R}")

    # ── Bottom border ──
    print(f"  {p_color}╚{'═' * w}{_R}╝")
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


# ── Master dashboard ──────────────────────────────────────────────────────


def master_dashboard() -> None:
    categories = MENU_CONFIG.get("categories", [])
    exit_key = MENU_CONFIG.get("exit_key", "X")
    entries = _build_menu_from_config()

    if not entries:
        print(f"{icon('error')} No menu entries found in {CONFIG_PATH}")
        print("Ensure dashboard.json has valid category/entry definitions.")
        input("\nPress Enter to exit.")
        return

    # Log startup activity
    _log_activity("dashboard", "started")

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

        # ── Cyberpunk Header (with stats, mascot, persona) ─────────────
        persona_style = _get_persona_style()
        _draw_header(title, box_width, persona_style)

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

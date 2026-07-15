"""
virgo_menu — master TUI dashboard for the virgo agent framework.

Provides an interactive menu to launch network scans, diagnostics,
alert evaluation, auto-fix, web search, and the core pipeline.

Menu layout is loaded from ``dashboard.json`` (next to this file).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import log, OUTDIR

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
    print(f"\n{icon('rocket')} Running: virgo run --goal \"{goal}\"" + (" --llm" if use_llm else ""))
    try:
        subprocess.run(cmd)
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")
    except Exception as e:
        print(f"{icon('error')} Error: {e}")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


def _get_menu_options() -> list[tuple[str, str, str | None]]:
    """Return list of (id, label, script_or_action) for the menu."""
    return [
        ("01", "Run Subnet Network Discovery Scanner",       "virgo_network_scanner.py"),
        ("02", "Run Full System Diagnostics Suite",           "virgo_diagnostics.py"),
        ("03", "Evaluate Active System & Hardware Alerts",    "virgo_alerts.py"),
        ("04", "Execute Automated Triage & Remediation Fixer","virgo_fixer.py"),
        ("05", "Workflow Connectivity Check",                 "workflow_check.py"),
        ("06", f"DuckDuckGo Web Search {icon('web')}",       "virgo_web_search.py 1"),
        ("07", f"Google Search {icon('search')}",            "virgo_web_search.py 2"),
        ("08", f"YouTube Search {icon('video')}",             "virgo_web_search.py 3"),
        ("09", "Run Agent Pipeline (virgo run)",              "__pipeline__"),
        ("10", "View Live Network Map (JSON)",                "virgo_network_map.json"),
        ("11", "View Active Alerts File (TXT)",               "ALERTS_TRIGGERED.txt"),
        ("12", "View Web Search History",                     "__search_history__"),
        ("13", f"Run Service Fingerprinter {icon('antenna')}","virgo_fingerprinter.py"),
        ("14", f"Dispatch Alert Webhook {icon('sat')}",       "virgo_webhook.py"),
        ("15", f"Open Safe Command Sandbox {icon('shield')}", "virgo_sandbox.py"),
        ("16", f"Run Scheduler / Watchdog {icon('refresh')}", "virgo_watchdog.py --cycles 3"),
        ("17", "List Available Scaffolds",                    "virgo_scaffold.py list"),
        ("18", "Generate FastAPI CRUD Project",               "__scaffold_fastapi__"),
        ("19", "Generate CLI App",                            "__scaffold_cli__"),
        ("20", "Generate Flask Web App",                      "__scaffold_flask__"),
        ("21", "Generate Python Library",                     "__scaffold_lib__"),
        ("22", "Generate Agent Tool Module",                  "__scaffold_agent__"),
    ]


def _dispatch_action(action: str | None) -> bool:
    """Run the action for a menu selection. Return False to exit."""
    if action is None:
        return True
    action_map: dict[str, callable] = {
        "__pipeline__": lambda: run_pipeline(),
        "__search_history__": lambda: view_search_history(),
        "__scaffold_fastapi__": lambda: _scaffold_prompt("fastapi-crud", "myapi",
                                                         "fastapi-crud", "-v project_name"),
        "__scaffold_cli__": lambda: _scaffold_prompt("cli-app", "mycli",
                                                     "cli-app", "-v project_name"),
        "__scaffold_flask__": lambda: _scaffold_prompt("flask-app", "mywebapp",
                                                       "flask-app", "-v project_name"),
        "__scaffold_lib__": lambda: _scaffold_prompt("python-lib", "mylib",
                                                     "python-lib", "-v project_name"),
        "__scaffold_agent__": lambda: _scaffold_prompt("agent-tool", "virgo_mytool",
                                                       "agent-tool", "-v module_name"),
    }
    if action in action_map:
        action_map[action]()
        return True
    if action == "__exit__":
        print(f"\n{icon('done')} Shutting down Virgo control bridge. See ya!")
        return False
    # File viewer or script runner
    if action.endswith(".json") or action.endswith(".txt"):
        view_file(action)
    else:
        run_script(action)
    return True


def _scaffold_prompt(scaffold: str, default: str, _scaffold_name: str, var_flag: str) -> None:
    """Prompt for a scaffold variable and run generation."""
    name = input(f"{icon('arrow')} Project name [{default}]: ").strip() or default
    run_script(
        f"virgo_scaffold.py generate {scaffold} "
        f"-o ../scaffold-output/{scaffold} "
        f"{var_flag}={name}"
    )


def _have_msvcrt() -> bool:
    """Return True if msvcrt is available (Windows)."""
    try:
        import msvcrt
        return True
    except ImportError:
        return False


def _arrow_prompt(options: list[tuple[str, str, str | None]]) -> str:
    """Display menu with arrow-key navigation (Windows) or fall back to input()."""
    if not _have_msvcrt() or not sys.stdin.isatty():
        choice = input(f"{icon('arrow')} Select an option: ").strip().upper()
        return choice

    import msvcrt
    import shutil

    # Map id to display prefix
    ids = [oid for oid, _, _ in options]
    sel = 0

    def render() -> None:
        cols = shutil.get_terminal_size().columns
        # Show options around current selection
        start = max(0, sel - 8)
        end = min(len(options), sel + 9)
        for i in range(start, end):
            oid, label, _ = options[i]
            prefix = "  >" if i == sel else "   "
            suffix = " <" if i == sel else ""
            print(f"{prefix}[{oid}] {label}{suffix}".ljust(cols - 1))
        print()

    # Hide cursor
    print("\033[?25l", end="", flush=True)

    while True:
        # Print menu from current position
        cols = shutil.get_terminal_size().columns
        start = max(0, sel - 8)
        end = min(len(options), sel + 9)
        for i in range(start, end):
            oid, label, _ = options[i]
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
            return ids[sel]
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
    options = _get_menu_options()
    total = len(options)

    while True:
        clear_screen()
        print("=" * 60)
        print(f"          {icon('virgo')} VIRGO AGENT FRAMEWORK - MASTER CONTROL")
        print("=" * 60)

        # Category breakpoints (index in options)
        cats = {"VIRGO MODULES": 0, "WEB SEARCH": 5, "CORE PIPELINE": 8,
                "DATA VIEWER": 9, "ADVANCED MODULES": 12, "SCAFFOLDING": 16}

        for cat, start in cats.items():
            print(f"  {cat}")
            end = list(cats.values())[list(cats.values()).index(start) + 1] \
                  if list(cats.values()).index(start) + 1 < len(cats) else total
            for i in range(start, end):
                oid, label, _ = options[i]
                print(f"  [{oid}]  {label}")
            print("-" * 60)

        print(f"  [X]  Exit Dashboard")
        print("=" * 60)

        # Use arrow-key navigation on Windows, fall back to plain input
        if _have_msvcrt():
            choice = _arrow_prompt(options)
        else:
            choice = input(f"{icon('arrow')} Select an option: ").strip().upper()

        if choice == "X":
            print(f"\n{icon('done')} Shutting down Virgo control bridge. See ya!")
            break

        # Match by id (01-22) or direct number (1-22)
        matched = None
        for oid, _, action in options:
            if choice in (oid, oid.lstrip("0"), oid[1:] if oid.startswith("0") else ""):
                matched = action
                break

        if matched is not None:
            _dispatch_action(matched)
        else:
            input(f"\n{icon('error')} Invalid choice. Press Enter to try again.")


if __name__ == "__main__":
    master_dashboard()

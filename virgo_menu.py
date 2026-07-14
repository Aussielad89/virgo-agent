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
from _log import log

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
    print(f"{icon('file')} --- Viewing File: {file_name} ---\n")
    if os.path.exists(file_name):
        with open(file_name) as f:
            print(f.read())
    else:
        print(f"{icon('warn')} {file_name} does not exist yet. Run the corresponding tool first.")
    input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN TO MENU]")


def view_search_history() -> None:
    clear_screen()
    print(f"{icon('history')} --- Web Search History ---\n")
    search_files = sorted(glob.glob("virgo_search_memory_*.json"), reverse=True)
    if not search_files:
        if os.path.exists("virgo_search_memory.json"):
            search_files = ["virgo_search_memory.json"]
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


def master_dashboard() -> None:
    while True:
        clear_screen()
        print("=" * 60)
        print(f"          {icon('virgo')} VIRGO AGENT FRAMEWORK - MASTER CONTROL")
        print("=" * 60)
        print("  VIRGO MODULES")
        print("  [1]  Run Subnet Network Discovery Scanner")
        print("  [2]  Run Full System Diagnostics Suite")
        print("  [3]  Evaluate Active System & Hardware Alerts")
        print("  [4]  Execute Automated Triage & Remediation Fixer")
        print("  [5]  Workflow Connectivity Check")
        print("-" * 60)
        print("  WEB SEARCH")
        print(f"  [6]  DuckDuckGo Web Search {icon('web')}")
        print(f"  [7]  Google Search {icon('search')}")
        print(f"  [8]  YouTube Search {icon('video')}")
        print("-" * 60)
        print("  CORE PIPELINE")
        print("  [9]  Run Agent Pipeline (virgo run)")
        print("-" * 60)
        print("  DATA VIEWER")
        print("  [10] View Live Network Map (JSON)")
        print("  [11] View Active Alerts File (TXT)")
        print("  [12] View Web Search History")
        print("-" * 60)
        print("  ADVANCED MODULES")
        print(f"  [13] Run Service Fingerprinter {icon('antenna')}")
        print(f"  [14] Dispatch Alert Webhook {icon('sat')}")
        print(f"  [15] Open Safe Command Sandbox {icon('shield')}")
        print(f"  [16] Run Scheduler / Watchdog {icon('refresh')}")
        print("-" * 60)
        print("  SCAFFOLDING")
        print("  [17] List Available Scaffolds")
        print("  [18] Generate FastAPI CRUD Project")
        print("  [19] Generate CLI App")
        print("  [20] Generate Flask Web App")
        print("  [21] Generate Python Library")
        print("  [22] Generate Agent Tool Module")
        print("-" * 60)
        print("  [X]  Exit Dashboard")
        print("=" * 60)

        choice = input(f"{icon('arrow')} Select an option: ").strip().upper()

        if choice == "1":
            run_script("virgo_network_scanner.py")
        elif choice == "2":
            run_script("virgo_diagnostics.py")
        elif choice == "3":
            run_script("virgo_alerts.py")
        elif choice == "4":
            run_script("virgo_fixer.py")
        elif choice == "5":
            run_script("workflow_check.py")
        elif choice == "6":
            run_script("virgo_web_search.py 1")
        elif choice == "7":
            run_script("virgo_web_search.py 2")
        elif choice == "8":
            run_script("virgo_web_search.py 3")
        elif choice == "9":
            run_pipeline()
        elif choice == "10":
            view_file("virgo_network_map.json")
        elif choice == "11":
            view_file("ALERTS_TRIGGERED.txt")
        elif choice == "12":
            view_search_history()
        elif choice == "13":
            run_script("virgo_fingerprinter.py")
        elif choice == "14":
            run_script("virgo_webhook.py")
        elif choice == "15":
            run_script("virgo_sandbox.py")
        elif choice == "16":
            run_script("virgo_watchdog.py --cycles 3")
        elif choice == "17":
            run_script("virgo_scaffold.py list")
        elif choice == "18":
            name = input(f"{icon('arrow')} Project name [myapi]: ").strip() or "myapi"
            run_script(f"virgo_scaffold.py generate fastapi-crud -o ../scaffold-output/fastapi-crud -v project_name={name}")
        elif choice == "19":
            name = input(f"{icon('arrow')} Project name [mycli]: ").strip() or "mycli"
            run_script(f"virgo_scaffold.py generate cli-app -o ../scaffold-output/cli-app -v project_name={name}")
        elif choice == "20":
            name = input(f"{icon('arrow')} Project name [mywebapp]: ").strip() or "mywebapp"
            run_script(f"virgo_scaffold.py generate flask-app -o ../scaffold-output/flask-app -v project_name={name}")
        elif choice == "21":
            name = input(f"{icon('arrow')} Project name [mylib]: ").strip() or "mylib"
            run_script(f"virgo_scaffold.py generate python-lib -o ../scaffold-output/python-lib -v project_name={name}")
        elif choice == "22":
            name = input(f"{icon('arrow')} Module name [virgo_mytool]: ").strip() or "virgo_mytool"
            run_script(f"virgo_scaffold.py generate agent-tool -o . -v module_name={name}")
        elif choice == "X":
            print(f"\n{icon('done')} Shutting down Virgo control bridge. See ya!")
            break
        else:
            input(f"\n{icon('error')} Invalid choice. Press Enter to try again.")


if __name__ == "__main__":
    master_dashboard()

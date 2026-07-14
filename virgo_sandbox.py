"""
virgo_sandbox — safe command runtime bridge.

Checks an incoming command list against a forbidden list before
execution.  Safe commands (e.g. ipconfig /all) are run via
subprocess.run and their stdout is returned cleanly.
"""

from __future__ import annotations

import subprocess
import sys
import os
import shlex

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon

# ── Forbidden patterns (case-insensitive) ──────────────────────────────
# Any command whose executable or first argument matches one of these
# patterns will be rejected without execution.
FORBIDDEN_COMMANDS: set[str] = {
    "rmdir",
    "del",
    "format",
    "diskpart",
    "fdisk",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init",
    "kill",
    "pkill",
    "taskkill",
    "reg",
    "regedit",
    "cipher",
    "icacls",
    "takeown",
    "attrib",
}

# Commands whose *entire* argument string is forbidden (e.g. destructive
# flags on otherwise-safe commands).
FORBIDDEN_ARG_PATTERNS: set[str] = {
    "/s",      # rmdir /s
    "/f",      # del /f, rmdir /f, etc.
    "/q",      # quiet / force
    "-rf",     # rm -rf
    "-r",      # rm -r (POSIX recursive)
    "-f",      # rm -f (POSIX force)
    "--force",
    "--recursive",
    "-recurse",
}


def is_command_safe(cmd: list[str]) -> tuple[bool, str]:
    """Check *cmd* against the forbidden list.

    Returns (True, "") if the command is safe, or (False, reason)
    if it matches a forbidden pattern.
    """
    if not cmd:
        return False, "Empty command list"

    executable = os.path.basename(cmd[0]).lower().split(".")[0]

    # Check the executable name
    if executable in FORBIDDEN_COMMANDS:
        return False, f"Executable '{cmd[0]}' is forbidden"

    # Check each argument for forbidden patterns
    for arg in cmd[1:]:
        lower = arg.lower()
        if lower in FORBIDDEN_ARG_PATTERNS:
            return False, f"Flag '{arg}' is forbidden on '{executable}'"

    return True, ""


COMMANDS: dict[str, list[str]] = {
    "1": ["ipconfig", "/all"],
    "2": ["systeminfo"],
    "3": ["netstat", "-an"],
    "4": ["tasklist"],
    "5": ["ping", "-n", "4", "127.0.0.1"],
}


def run_sandboxed(cmd: list[str]) -> str:
    """Run *cmd* through the sandbox and return stdout.

    Raises ValueError if the command is forbidden.
    Raises subprocess.CalledProcessError if the command fails.
    """
    safe, reason = is_command_safe(cmd)
    if not safe:
        raise ValueError(f"Blocked by sandbox: {reason}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )

    return result.stdout


def run_sandbox() -> None:
    """Interactive sandbox menu — pick a preset command or type one."""
    print(f"\n{icon('shield')} Virgo Safe Command Runtime")
    print("-" * 40)
    print("  Preset commands:")
    for key, cmd in COMMANDS.items():
        print(f"    [{key}]  {' '.join(cmd)}")
    print("  [C]   Custom command (space-separated)")
    print("  [X]   Exit")
    print()

    choice = input(f"{icon('arrow')} Select a command: ").strip()

    if choice.upper() == "X":
        print(f"{icon('info')} Sandbox closed.")
        return

    if choice.upper() == "C":
        raw = input(f"{icon('arrow')} Enter command (e.g. ipconfig /all): ").strip()
        if not raw:
            print(f"{icon('error')} No command entered.")
            return
        cmd = shlex.split(raw)
    elif choice in COMMANDS:
        cmd = COMMANDS[choice]
    else:
        print(f"{icon('error')} Invalid choice.")
        return

    # Sandbox check
    safe, reason = is_command_safe(cmd)
    if not safe:
        print(f"\n{icon('error')} {reason}")
        print(f"{icon('info')} Command rejected: {' '.join(cmd)}")
        return

    # Execute
    print(f"\n{icon('rocket')} Running: {' '.join(cmd)} ...\n")
    try:
        stdout = run_sandboxed(cmd)
        # Truncate very long output for display
        lines = stdout.splitlines()
        if len(lines) > 40:
            print("\n".join(lines[:40]))
            print(f"... ({len(lines) - 40} more lines)")
        else:
            print(stdout)
        print(f"\n{icon('ok')} Command completed (exit code 0)")
        print(f"{icon('info')} {len(stdout.encode('utf-8'))} bytes returned")
    except ValueError as exc:
        print(f"\n{icon('error')} {exc}")
    except subprocess.TimeoutExpired:
        print(f"\n{icon('error')} Command timed out after 30s")
    except subprocess.CalledProcessError as exc:
        print(f"\n{icon('error')} Command failed (exit code {exc.returncode})")
        if exc.stderr:
            print(f"  stderr: {exc.stderr.strip()[:300]}")
        if exc.stdout:
            print(f"  stdout: {exc.stdout.strip()[:300]}")

    print()


if __name__ == "__main__":
    run_sandbox()
    input("\n[PRESS ENTER TO RETURN]")

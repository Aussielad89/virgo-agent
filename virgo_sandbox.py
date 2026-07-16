"""
virgo_sandbox — safe command runtime bridge.

Checks incoming commands against an **allowlist** before execution.
Only explicitly permitted commands (and their safe flags) are allowed.
Safe commands are run via subprocess.run and their stdout is returned.

The allowlist can be set via the ``virgo.toml`` config file::

    [sandbox]
    mode = "allowlist"
    allowed_commands = ["python", "pip", "git", "ls", "cat"]
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon

# ── Allowlist ─────────────────────────────────────────────────────────
# Only these executables (basename, case-insensitive, no extension) are
# allowed. Add entries via config or by modifying this set at runtime.

ALLOWED_COMMANDS: set[str] = {
    "python", "pip", "git", "ls", "cat", "echo", "pwd",
    "head", "tail", "wc", "sort", "grep", "find", "mkdir",
    "cp", "mv", "which", "ipconfig", "systeminfo", "netstat",
    "tasklist", "ping", "hostname", "date", "time", "whoami",
    "dir", "type", "more", "help", "powershell",
}

# Safe argument prefixes for commands that accept them
# e.g. "ping -n 4 127.0.0.1" is allowed because -n, 4, 127.0.0.1 are safe
# Format: { "executable": [list of allowed flag prefixes] }
ALLOWED_FLAGS: dict[str, list[str]] = {
    "ping": ["-n", "-t", "-w", "-l", "-f"],
    "netstat": ["-a", "-n", "-o", "-b", "-e", "-f", "-p", "-r", "-s"],
    "tasklist": ["/v", "/fo", "/nh", "/fi", "/s", "/u", "/p"],
    "ipconfig": ["/all", "/release", "/renew", "/flushdns", "/displaydns"],
    "python": ["-c", "-m", "-V", "--version", "-u", "-B"],
    "pip": ["install", "list", "freeze", "show", "uninstall", "--version"],
    "git": ["status", "log", "diff", "branch", "add", "commit", "push",
            "pull", "clone", "init", "checkout", "merge", "stash"],
    "powershell": ["-Command", "-File", "-NoProfile", "-ExecutionPolicy"],
}


def _load_from_config() -> None:
    """Merge allowlist entries from ``virgo.toml`` if available."""
    try:
        from config import load as _load_cfg
        cfg = _load_cfg()  # walks up to find virgo.toml
        sandbox_cfg = cfg.get("sandbox", {})
        if sandbox_cfg.get("mode") == "allowlist":
            extra = sandbox_cfg.get("allowed_commands", [])
            ALLOWED_COMMANDS.update(cmd.lower().split(".")[0] for cmd in extra)
    except Exception:
        pass  # no config found — use defaults


_load_from_config()


def is_command_safe(cmd: list[str]) -> tuple[bool, str]:
    """Check *cmd* against the allowlist.

    Returns (True, "") if all parts of the command are allowed,
    or (False, reason) if the command or its flags are not on
    the allowlist.
    """
    if not cmd:
        return False, "Empty command list"

    executable = os.path.basename(cmd[0]).lower().split(".")[0]

    # Check executable is on the allowlist
    if executable not in ALLOWED_COMMANDS:
        return False, f"Executable '{cmd[0]}' is not on the allowlist"

    # Check flags against safe flags for this executable
    allowed_flags = ALLOWED_FLAGS.get(executable, [])
    for arg in cmd[1:]:
        lower = arg.lower()
        # Allow plain words/values (filenames, IPs, numbers, paths)
        if lower.startswith("-") or lower.startswith("/"):
            if not any(lower.startswith(flag) for flag in allowed_flags):
                return False, f"Flag '{arg}' not allowed for '{executable}'"

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

    Raises ValueError if the command is not on the allowlist.
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
    print(f"\n{icon('shield')} Virgo Safe Command Runtime (allowlist mode)")
    print("-" * 40)
    print("  Preset commands:")
    for key, cmd in COMMANDS.items():
        print(f"    [{key}]  {' '.join(cmd)}")
    print("  [C]   Custom command (space-separated)")
    print("  [L]   List allowed commands")
    print("  [X]   Exit")
    print()

    choice = input(f"{icon('arrow')} Select a command: ").strip()

    if choice.upper() == "X":
        print(f"{icon('info')} Sandbox closed.")
        return

    if choice.upper() == "L":
        print(f"\n{icon('shield')} Allowed commands ({len(ALLOWED_COMMANDS)}):")
        for cmd in sorted(ALLOWED_COMMANDS):
            flags = ALLOWED_FLAGS.get(cmd, [])
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"    {cmd}{flag_str}")
        input(f"\n{icon('arrow')} [PRESS ENTER TO RETURN]")
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

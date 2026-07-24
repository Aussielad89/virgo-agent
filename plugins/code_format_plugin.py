"""
code_format_plugin — file formatting tools for virgo agents.

Registers two tools:
  - 'format file'   — format a single file in-place (takes 'path' kwarg)
  - 'format check'  — check formatting without modifying (takes 'path' kwarg)

Preference order: ruff -> black.  Handles missing formatters gracefully.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


# ── Dependency detection ──────────────────────────────────────────────

def _find_ruff() -> str | None:
    """Return the ruff binary path, or None if not available."""
    return _find_tool("ruff")


def _find_black() -> str | None:
    """Return the black binary path, or None if not available."""
    return _find_tool("black")


def _find_tool(name: str) -> str | None:
    """Resolve *name* on PATH, or via ``pip show`` + ``sys.executable``."""
    # 1 — PATH lookup
    which = _which(name)
    if which:
        return which

    # 2 — pip-based discovery (works for pip-installed CLI tools)
    try:
        import importlib.metadata as md
        dist = md.distribution(name)
        # Black ships a console_scripts entry; ruff does too.
        for ep in dist.entry_points:
            if ep.group == "console_scripts" and ep.name == name:
                # Best effort: run via python -m <module>
                return name  # let subprocess resolve via PATH or python -m
    except (md.PackageNotFoundError, Exception):
        pass

    # 3 — python -m <name>
    try:
        result = subprocess.run(
            [sys.executable, "-m", name, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return name  # will be callable via python -m <name>
    except Exception:
        pass

    return None


def _which(name: str) -> str | None:
    """Simple PATH lookup (no shutil dependency needed)."""
    try:
        result = subprocess.run(
            ["where" if sys.platform == "win32" else "which", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return None


# ── Formatter discovery ───────────────────────────────────────────────

def _pick_formatter() -> tuple[str, str]:
    """Return (name, binary_or_module) that is available.

    Raises RuntimeError if neither ruff nor black is installed.
    """
    ruff = _find_ruff()
    if ruff:
        return ("ruff", ruff)

    black = _find_black()
    if black:
        return ("black", black)

    raise RuntimeError(
        "No supported formatter found. Install one of:\n"
        "  pip install ruff\n"
        "  pip install black"
    )


def _run_formatter(
    name: str,
    binary: str,
    path: str,
    *extra_args: str,
) -> dict[str, Any]:
    """Execute the formatter and return a structured result."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        return {"ok": False, "error": f"File not found: {path}", "path": str(resolved)}
    if not resolved.is_file():
        return {"ok": False, "error": f"Not a file: {path}", "path": str(resolved)}

    cmd = [binary, *extra_args, str(resolved)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"{name} timed out after 60s on {path}",
            "path": str(resolved),
        }
    except FileNotFoundError:
        # Binary vanished between discovery and execution
        return {
            "ok": False,
            "error": f"{name} is no longer available on PATH",
            "path": str(resolved),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": str(resolved)}

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "formatter": name,
        "path": str(resolved),
    }


# ── Public tool implementations ───────────────────────────────────────

def tool_format_file(path: str) -> dict[str, Any]:
    """Format a single Python file in-place.

    Kwargs:
        path (str): Absolute or relative path to the file to format.

    Returns:
        dict with keys: ok, formatter, path, stdout, stderr, (error)
    """
    try:
        name, binary = _pick_formatter()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "path": path}

    if name == "ruff":
        return _run_formatter(name, binary, path, "format")

    # black — no extra args needed for in-place formatting
    return _run_formatter(name, binary, path)


def tool_format_check(path: str) -> dict[str, Any]:
    """Check formatting of a Python file without modifying it.

    Kwargs:
        path (str): Absolute or relative path to the file to check.

    Returns:
        dict with keys: ok, formatter, path, needs_formatting, stdout, stderr, (error)

    ``needs_formatting`` is True when the file requires formatting changes.
    ``ok`` is True when the tool ran successfully (even if changes are needed).
    """
    try:
        name, binary = _pick_formatter()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "path": path}

    if name == "ruff":
        result = _run_formatter(name, binary, path, "format", "--check", "--diff")
    else:
        # black --check --diff
        result = _run_formatter(name, binary, path, "--check", "--diff")

    # For check mode, a non-zero returncode usually means "needs formatting",
    # not a tool failure. Let's distinguish.
    if "error" in result and not result.get("ok"):
        # Real error (file not found, timeout, etc.)
        return result

    needs_formatting = result.get("returncode", 0) != 0
    return {
        "ok": True,
        "formatter": name,
        "path": result["path"],
        "needs_formatting": needs_formatting,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


# ── Plugin registration ───────────────────────────────────────────────

def register(registry: Any) -> None:
    """Register the two formatting tools with *registry*."""
    from tools import Tool  # late import to avoid circular deps at load time

    registry.register(
        Tool(
            name="format file",
            fn=tool_format_file,
            description=(
                "Format a single Python file in-place using ruff (preferred) "
                "or black (fallback).  Takes a single 'path' kwarg pointing "
                "to the file to format.  Returns {ok, formatter, path, stdout, stderr}."
            ),
        )
    )

    registry.register(
        Tool(
            name="format check",
            fn=tool_format_check,
            description=(
                "Check whether a Python file is correctly formatted without "
                "modifying it.  Takes a single 'path' kwarg.  Returns "
                "{ok, formatter, path, needs_formatting, stdout, stderr} "
                "where needs_formatting is True if the file would be changed."
            ),
        )
    )

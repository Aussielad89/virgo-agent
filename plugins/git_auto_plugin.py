"""
git_auto_plugin — Git auto-commit tools for the Virgo agent framework.

Exports three tool_* functions auto-discovered by the plugin loader:

  - tool_git_status   → git status --short
  - tool_git_commit   → git add -A && git commit -m "<message>"
  - tool_git_diff     → git diff --stat

All operate relative to the framework root directory.  Errors are caught
and returned as structured dicts so calling code never sees an exception.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Framework root — resolved once so every tool targets the right directory
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent.parent
"""Framework root directory (parent of ``plugins/``)."""


def _git_run(*args: str) -> dict[str, object]:
    """Run ``git <args…>`` inside the framework directory.

    Parameters
    ----------
    *args:
        Git sub-command and its arguments (e.g. ``"status", "--short"``).

    Returns
    -------
    dict
        Keys: ``action``, ``returncode``, ``stdout``, ``stderr``.
        On subprocess failure (binary not found, timeout, OSError) an
        ``error`` key replaces ``returncode`` / ``stdout`` / ``stderr``.
    """
    action_label = " ".join(args) if args else "(no args)"
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(HERE),
        )
        return {
            "action": action_label,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip()[:10_000],
            "stderr": proc.stderr.strip()[:5_000],
        }
    except FileNotFoundError:
        return {
            "action": action_label,
            "error": (
                "Git executable not found.  Make sure Git is installed "
                "and on the system PATH.",
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "action": action_label,
            "error": "Git command timed out after 60 seconds.",
        }
    except OSError as exc:
        return {
            "action": action_label,
            "error": f"OS error running git: {exc}",
        }


# ===================================================================
# Public tool functions (auto-registered by plugins.py loader)
# ===================================================================


def tool_git_status() -> dict[str, object]:
    """Show working-tree status in short format.

    Returns
    -------
    dict
        With keys ``action``, ``returncode``, ``stdout`` (the short-status
        output), and ``stderr``.  If the repository has no commits yet,
        ``stderr`` may contain a helpful hint; the function still succeeds.
    """
    return _git_run("status", "--short")


def tool_git_commit(message: str = "auto-commit") -> dict[str, object]:
    """Stage all changes and commit with the given message.

    Equivalent to ``git add -A && git commit -m "<message>"``.

    Parameters
    ----------
    message:
        Commit message.  Defaults to ``"auto-commit"``.

    Returns
    -------
    dict
        On success: ``action``, ``returncode=0``, ``stdout`` (commit hash).
        On failure (nothing to commit, merge conflict, etc.): ``returncode``
        is non-zero and ``stderr`` describes the problem.
    """
    # Stage everything
    add_result = _git_run("add", "-A")
    if add_result.get("error"):
        return add_result

    # Check whether anything is staged (avoid empty-commit noise)
    status_result = _git_run("status", "--porcelain")
    if isinstance(status_result.get("stdout"), str) and not status_result["stdout"].strip():
        return {
            "action": "add -A && commit",
            "returncode": 0,
            "stdout": "Nothing to commit — working tree clean.",
            "stderr": "",
        }

    # Commit
    commit_result = _git_run("commit", "-m", message)
    if commit_result.get("error"):
        return commit_result

    # If git printed the commit hash on stdout, surface it
    stdout = commit_result.get("stdout", "")
    stderr = commit_result.get("stderr", "")

    # Handle case where nothing to commit (staged files changed since add?)
    if commit_result.get("returncode", 0) != 0:
        return {
            "action": "add -A && commit",
            "returncode": commit_result["returncode"],
            "stdout": (stdout or "") + ("; " + stderr if stderr else ""),
            "stderr": stderr,
            "note": (
                "Commit failed.  Possible causes: no changes staged, "
                "merge in progress, or pre-commit hook rejected the commit."
            ),
        }

    return {
        "action": "add -A && commit",
        "returncode": 0,
        "stdout": stdout or "Committed successfully.",
        "stderr": stderr,
    }


def tool_git_diff() -> dict[str, object]:
    """Show a summary of unstaged changes (stat).

    Returns
    -------
    dict
        With keys ``action``, ``returncode``, ``stdout`` (the diff-stat
        output), and ``stderr``.  Empty output means there are no unstaged
        changes.
    """
    return _git_run("diff", "--stat")

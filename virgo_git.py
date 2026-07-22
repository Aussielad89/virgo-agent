"""Git integration helpers for virgo: auto-commit, branching, and push."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _console import icon
from _log import log

HERE = Path(__file__).resolve().parent


def _git(*args: str, cwd: str = "") -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process.

    All arguments are forwarded to ``git <args...>``.
    """
    cmd = ["git", *args]
    workdir = cwd or str(HERE)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workdir,
        )
        return proc
    except FileNotFoundError:
        log.error("git not found — is it installed and on PATH?")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        log.error("git command timed out after 30s: %s", " ".join(cmd))
        sys.exit(1)


def auto_commit_message() -> str:
    """Generate an automatic commit message from ``git diff --stat``.

    Returns something like::

        auto: 3 files changed, 45 insertions(+), 12 deletions(-)
    """
    proc = _git("diff", "--stat")
    summary = proc.stdout.strip()
    if not summary:
        # No staged changes — check working tree
        proc = _git("diff", "--stat", cwd=HERE)
        summary = proc.stdout.strip()
    if not summary:
        return "auto: no changes detected"

    # Take the last line (the summary line)
    lines = summary.splitlines()
    last = lines[-1].strip() if lines else ""
    if last:
        return f"auto: {last}"
    return "auto: workspace update"


def git_commit(
    message: str = "",
    push: bool = False,
    amend: bool = False,
    cwd: str = "",
) -> dict[str, object]:
    """Stage all changes and commit.

    Parameters
    ----------
    message:
        Commit message.  If empty, one is auto-generated from
        ``git diff --stat``.
    push:
        If True, also run ``git push`` after a successful commit.
    amend:
        If True, use ``--amend`` (overrides *message*).
    cwd:
        Working directory for git commands (defaults to the framework root).

    Returns a dict with keys ``ok``, ``commit_hash``, ``stdout``, ``stderr``.
    """
    workdir = cwd or str(HERE)
    result: dict[str, object] = {"ok": False, "commit_hash": "", "stdout": "", "stderr": ""}

    # Stage all changes
    log.info("Staging all changes ...")
    add_proc = _git("add", "-A", cwd=workdir)
    if add_proc.returncode != 0:
        result["stderr"] = add_proc.stderr.strip()
        log.error("git add failed: %s", add_proc.stderr.strip())
        return result

    # Check if there is anything to commit
    status_proc = _git("status", "--porcelain", cwd=workdir)
    if not status_proc.stdout.strip():
        log.info("Nothing to commit — working tree clean.")
        result["ok"] = True
        result["stdout"] = "Nothing to commit — working tree clean."
        return result

    # Build the commit command
    commit_args = ["commit"]
    if amend:
        commit_args.append("--amend")
        if message:
            commit_args.extend(["-m", message])
        # --amend without -m opens editor — use --no-edit to keep previous message
        if not message:
            commit_args.append("--no-edit")
    else:
        msg = message or auto_commit_message()
        commit_args.extend(["-m", msg])

    log.info("Committing ...")
    commit_proc = _git(*commit_args, cwd=workdir)
    if commit_proc.returncode != 0:
        result["stderr"] = commit_proc.stderr.strip()
        log.error("Commit failed: %s", commit_proc.stderr.strip())
        return result

    result["ok"] = True
    result["stdout"] = commit_proc.stdout.strip()

    # Extract short hash from git output like "[master abc1234] message"
    commit_out = commit_proc.stdout.strip()
    for token in commit_out.split():
        if len(token) >= 7 and token.isalnum() or "-g" in token:
            # git shows "abc1234" or "HEAD -> branch, origin/branch abc1234"
            for part in token.replace(",", " ").split():
                clean = part.strip("()")
                if len(clean) >= 7 and all(c in "0123456789abcdef" for c in clean):
                    result["commit_hash"] = clean
                    break
            if result["commit_hash"]:
                break

    print(f"  {icon('ok')} Commit: {commit_out.split(chr(10))[0] if commit_out else 'done'}")

    # Push
    if push:
        log.info("Pushing ...")
        push_proc = _git("push", cwd=workdir)
        if push_proc.returncode != 0:
            result["push_error"] = push_proc.stderr.strip()
            log.error("Push failed: %s", push_proc.stderr.strip())
            print(f"  {icon('error')} Push failed: {push_proc.stderr.strip()}")
        else:
            print(f"  {icon('ok')} Push successful")
            result["push_ok"] = True

    return result


def git_branch(name: str, cwd: str = "") -> dict[str, object]:
    """Create a new branch and switch to it.

    If the branch already exists, it is checked out without error.

    Parameters
    ----------
    name:
        Name of the branch to create / switch to.
    cwd:
        Working directory for git commands.

    Returns a dict with keys ``ok``, ``stdout``, ``stderr``.
    """
    workdir = cwd or str(HERE)
    result: dict[str, object] = {"ok": False, "stdout": "", "stderr": ""}

    # Check if branch exists
    check = _git("rev-parse", "--verify", name, cwd=workdir)
    if check.returncode == 0:
        # Branch exists — just checkout
        log.info("Switching to existing branch '%s' ...", name)
        proc = _git("checkout", name, cwd=workdir)
    else:
        # Create and switch
        log.info("Creating and switching to branch '%s' ...", name)
        proc = _git("checkout", "-b", name, cwd=workdir)

    if proc.returncode != 0:
        result["stderr"] = proc.stderr.strip()
        log.error("Branch operation failed: %s", proc.stderr.strip())
        return result

    result["ok"] = True
    result["stdout"] = proc.stdout.strip()
    print(f"  {icon('ok')} Switched to branch: {name}")
    return result


def cmd_commit(args: object) -> None:
    """CLI handler for ``virgo commit``."""
    # Import here to avoid circular dependency on cli.py's argparse Namespace
    import argparse

    ns = args if isinstance(args, argparse.Namespace) else argparse.Namespace()
    msg: str = getattr(ns, "message", "")
    do_push: bool = getattr(ns, "push", False)
    do_amend: bool = getattr(ns, "amend", False)

    if do_amend and not msg:
        print(f"  {icon('info')} Amending previous commit (no new message)\n")

    result = git_commit(message=msg, push=do_push, amend=do_amend)

    if result.get("ok"):
        if result.get("commit_hash"):
            print(f"  {icon('done')} {result.get('commit_hash')}")
        sys.exit(0)
    else:
        err = result.get("stderr", "unknown error")
        print(f"  {icon('error')} {err}")
        sys.exit(1)

"""
virgo_archaeology — codebase archaeology through git history.

Answer 'who wrote this?', 'when was this bug introduced?', and
'what was the original intent?' with an interactive timeline.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
ARCH_DIR = HERE / ".virgo_archaeology"
ARCH_DIR.mkdir(exist_ok=True)


def _git(args: list[str], cwd: Path | None = None) -> str | None:
    cwd = cwd or HERE
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as exc:
        log.error("archaeology: git %s failed: %s", args, exc)
        return None


def blame(file_path: str, line: int | None = None) -> list[dict[str, str]]:
    args = ["blame", "--line-porcelain", file_path]
    if line:
        args += ["-L", f"{line},{line}"]
    out = _git(args)
    if not out:
        return []
    commits: dict[str, dict[str, str]] = {}
    current_hash = ""
    for raw_line in out.splitlines():
        if raw_line.startswith(("author", "author-mail", "author-time", "summary", "filename")):
            pass
        if re.match(r"^\^?[0-9a-f]{40}$", raw_line.strip()):
            # porcelain header is "<sha> <orig> <final> [<count>]"; handle a
            # bare-hash line too in case a future git drops the numbers
            current_hash = raw_line.strip().lstrip("^")
            commits[current_hash] = {"hash": current_hash}
        else:
            hdr = re.match(r"^\^?([0-9a-f]{40})\s+\d+\s+\d+", raw_line.strip())
            if hdr:
                current_hash = hdr.group(1)
                commits[current_hash] = {"hash": current_hash}
            elif raw_line.startswith("author "):
                commits[current_hash]["author"] = raw_line[7:]
            elif raw_line.startswith("author-mail "):
                commits[current_hash]["email"] = raw_line[12:]
            elif raw_line.startswith("author-time "):
                ts = int(raw_line[12:])
                commits[current_hash]["date"] = datetime.fromtimestamp(ts).isoformat()
            elif raw_line.startswith("summary "):
                commits[current_hash]["message"] = raw_line[8:]
    return list(commits.values())


def log_for_file(file_path: str, n: int = 20) -> list[dict[str, str]]:
    out = _git(["log", "--follow", f"-n{n}", "--pretty=format:%H|%an|%ae|%ai|%s", "--", file_path])
    if not out:
        return []
    entries = []
    for line in out.splitlines():
        parts = line.split("|", 4)
        if len(parts) >= 5:
            entries.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "message": parts[4],
            })
    return entries


def bisect_intro(file_path: str, pattern: str) -> dict[str, Any] | None:
    out = _git(["log", "-S", pattern, "--pretty=format:%H|%an|%ai|%s", "-n", "1", "--", file_path])
    if not out:
        return None
    parts = out.split("|", 3)
    if len(parts) < 4:
        return None
    return {
        "hash": parts[0],
        "author": parts[1],
        "date": parts[2],
        "message": parts[3],
        "pattern": pattern,
        "file": file_path,
    }


def timeline(file_path: str, n: int = 10) -> dict[str, Any]:
    entries = log_for_file(file_path, n)
    return {
        "file": file_path,
        "entries": entries,
        "total": len(entries),
    }


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Codebase Archaeology")
    p.add_argument("file")
    p.add_argument("--line", type=int)
    p.add_argument("--bisect", help="Pattern/bug string to bisect")
    p.add_argument("--timeline", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.bisect:
        res = bisect_intro(args.file, args.bisect)
        out = res or {"error": "not found"}
    elif args.timeline:
        out = timeline(args.file)
    else:
        out = blame(args.file, args.line)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        if isinstance(out, list):
            for c in out:
                print(f"{c.get('hash','?')[:8]}  {c.get('author','?')}  {c.get('date','?')}  {c.get('message','')}")
        elif isinstance(out, dict):
            print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    cli()

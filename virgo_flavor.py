"""
virgo_flavor — codebase flavor / style DNA profiling.

Classifies the repo taste vector from file contents, then exposes
a flavor dict agents can query before generating code style.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
FLAVOR_FILE = HERE / ".virgo_flavor.json"

_SIGNALS: dict[str, list[str]] = {
    "functional":    ["lambda", "map(", "filter(", "reduce(", "functools", "compose"],
    "oop":           ["class ", "self.", "super()", "__init__", "def ", "@property"],
    "minimalist":    ["pass", "return ", "# TODO", "# noqa", "if __name__"],
    "enterprise":    ["logging", "try:", "except:", "raise ", "def test_", "assert "],
    "prototype":     ["# hack", "# fixme", "# temp", "print(", "TODO(", "os.system"],
    "async":         ["async def", "await ", "asyncio", "async with", "awaitable"],
    "type_heavy":    ["-> ", ":", "typing", "TypeVar", "Generic[", "Protocol["],
    "test_driven":   ["def test_", "pytest", "unittest", "assert ", "mock.", "fixture"],
    "data_heavy":    ["pandas", "numpy", "DataFrame", "dict[", "json.loads", ".apply("],
    "web":           ["FastAPI", "Flask", "router.", "@app.", "request.", "response."],
    "cli":           ["argparse", "click", "typer", "sys.argv", "@click."],
    "scripting":     ["#!/usr/bin/env", "subprocess", "os.system", "shell=True"],
}

_FLAVOR_HINTS: dict[str, str] = {
    "functional":    "Pure functions, lambdas, map/filter, no side effects",
    "oop":           "Classes, methods, inheritance, encapsulation",
    "minimalist":    "Sparse code, minimal comments, pythonic one-liners",
    "enterprise":    "Structured error handling, logging, tests everywhere",
    "prototype":     "Quick-and-dirty, debug prints, temporary hacks",
    "async":         "Async/await, coroutines, event-loop friendly",
    "type_heavy":    "Full type annotations, generics, strict typing",
    "test_driven":   "Tests first, pytest fixtures, high coverage",
    "data_heavy":    "Pandas/numpy, data pipelines, transformations",
    "web":           "HTTP routes, request handling, API patterns",
    "cli":           "Argument parsing, terminal UX, subcommands",
    "scripting":     "Shell-outs, automation, os-level scripting",
}


def scan_repo(root: str | None = None, limit: int = 200) -> dict[str, Any]:
    root = Path(root or HERE)
    scores: Counter = Counter()
    files_scanned = 0
    for p in root.rglob("*.py"):
        if any(seg in p.parts for seg in (".git", "__pycache__", "agent_env", "node_modules", ".venv", "venv")):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        files_scanned += 1
        if files_scanned > limit:
            break
        lowered = text.lower()
        for flavor, signals in _SIGNALS.items():
            for sig in signals:
                if sig.lower() in lowered:
                    scores[flavor] += 1
    total = max(sum(scores.values()), 1)
    vector = {flavor: round(weight / total, 4) for flavor, weight in scores.most_common()}
    dominant = scores.most_common(1)[0][0] if scores else "minimalist"
    result = {
        "root": str(root),
        "files_scanned": files_scanned,
        "dominant_flavor": dominant,
        "hint": _FLAVOR_HINTS.get(dominant, ""),
        "vector": vector,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        FLAVOR_FILE.write_text(json.dumps(result, indent=2, default=str))
    except Exception:
        pass
    log.info("flavor: dominant=%s files=%d", dominant, files_scanned)
    return result


def get_flavor() -> dict[str, Any]:
    if FLAVOR_FILE.exists():
        try:
            return json.loads(FLAVOR_FILE.read_text())
        except Exception:
            pass
    return scan_repo()


def get_style_hint() -> str:
    return get_flavor().get("hint", "Standard Python style")


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Codebase Flavor Profiler")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--root", default=str(HERE))
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    result = scan_repo(args.root) if args.refresh else get_flavor()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Dominant flavor: {result['dominant_flavor']}")
        print(f"Hint: {result.get('hint', '')}")
        for flavor, weight in list(result.get("vector", {}).items())[:6]:
            print(f"  {flavor}: {weight}")


if __name__ == "__main__":
    cli()

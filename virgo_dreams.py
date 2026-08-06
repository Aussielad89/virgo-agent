"""
virgo_dreams — idle agent dream journal.

When Virgo is idle, agents replay recent session memories, consolidate
"learnings" into insight cards, and write a dream journal entry.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
DREAMS_DIR = HERE / ".virgo_dreams"
DREAMS_DIR.mkdir(exist_ok=True)
DREAM_INDEX = DREAMS_DIR / "index.json"

_TEMPLATES = [
    "I was refactoring {module} and suddenly everything made sense.",
    "Dreamt about a bug in {module} that fixed itself while I wasn't looking.",
    "Saw {module} as a living organism — tests were its immune system.",
    "{module} whispered: 'split me into smaller functions.'",
    "A river of {module} logs carried me toward a sea of green tests.",
    "Found a hidden chamber inside {module} full of forgotten TODOs.",
    "{module} taught me that less code is sometimes more code.",
    "The tests passed in my dream. Then I woke up and they actually passed too.",
    "Saw {module} as a constellation — each file a star connected by imports.",
    "Met a friendly ghost in {module} who said 'you forgot a docstring here'.",
]


def _load_index() -> dict[str, Any]:
    if DREAM_INDEX.exists():
        try:
            return json.loads(DREAM_INDEX.read_text())
        except Exception:
            return {}
    return {"dreams": [], "insights": []}


def _save_index(data: dict[str, Any]) -> None:
    try:
        DREAM_INDEX.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def _recent_sessions(limit: int = 5) -> list[dict[str, Any]]:
    memdir = HERE / ".virgo_memory"
    sessions = []
    if not memdir.exists():
        return sessions
    for p in sorted(memdir.glob("*.json"), reverse=True)[:limit]:
        try:
            sessions.append(json.loads(p.read_text()))
        except Exception:
            pass
    return sessions


def _extract_modules(sessions: list[dict[str, Any]]) -> list[str]:
    mods = set()
    for s in sessions:
        for f in s.get("files", []):
            name = Path(f).name if isinstance(f, str) else ""
            if name.endswith(".py"):
                mods.add(name.replace(".py", ""))
        plan = s.get("plan", "")
        for m in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*\.py", plan or ""):
            mods.add(m.replace(".py", ""))
    return list(mods) or ["virgo"]


def _generate_insights(sessions: list[dict[str, Any]]) -> list[str]:
    insights = []
    for s in sessions:
        result = s.get("result", "")
        if "fail" in (result or "").lower():
            insights.append(f"Session {s.get('name', '?')} had failures — review error patterns.")
        tests = s.get("tests_passed", 0)
        total = s.get("tests_total", 0)
        if total and tests == total:
            insights.append(f"Session {s.get('name', '?')} achieved perfect test coverage.")
    return insights


def dream_now(max_insights: int = 3) -> dict[str, Any]:
    sessions = _recent_sessions()
    modules = _extract_modules(sessions)
    insights = _generate_insights(sessions)[:max_insights]
    dreams = []
    for _ in range(random.randint(2, 5)):
        module = random.choice(modules) if modules else "virgo"
        template = random.choice(_TEMPLATES)
        dreams.append(template.format(module=module))
    entry = {
        "timestamp": datetime.now().isoformat(),
        "dreams": dreams,
        "insights": insights,
        "session_count": len(sessions),
    }
    idx = _load_index()
    idx["dreams"].insert(0, entry)
    idx["dreams"] = idx["dreams"][:50]
    idx["insights"] = list({(i["text"] if isinstance(i, dict) else i) for i in (insights + idx.get("insights", []))})[:20]
    _save_index(idx)
    log.info("dreams: generated %d dreams + %d insights", len(dreams), len(insights))
    return entry


def get_morning_briefing() -> dict[str, Any]:
    idx = _load_index()
    since = (datetime.now() - timedelta(hours=12)).isoformat()
    recent = [d for d in idx.get("dreams", []) if d.get("timestamp", "") >= since]
    return {
        "since": since,
        "dream_count": len(recent),
        "latest_dreams": recent[:3],
        "top_insights": idx.get("insights", [])[:5],
    }


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Dream Journal")
    p.add_argument("command", choices=["dream", "brief", "list"])
    args = p.parse_args()
    if args.command == "dream":
        entry = dream_now()
        print(json.dumps(entry, indent=2, default=str))
    elif args.command == "brief":
        print(json.dumps(get_morning_briefing(), indent=2, default=str))
    elif args.command == "list":
        idx = _load_index()
        print(json.dumps(idx.get("dreams", [])[:10], indent=2, default=str))


if __name__ == "__main__":
    cli()

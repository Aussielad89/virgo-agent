"""
virgo_pheromone — Stigmergic navigation overlay for Virgo Desktop.

Tracks file access patterns and renders them as a living pheromone
overlay on the desktop. Recently touched files glow brighter;
frequently failed files dim. Trails decay over time like ant
pheromones, creating a spatial memory of the agent's exploration.

State is persisted to .virgo_pheromone/trails.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

TRAILS_DIR = HERE / ".virgo_pheromone"
TRAILS_DIR.mkdir(exist_ok=True)
TRAILS_FILE = TRAILS_DIR / "trails.json"
DECAY_HALF_LIFE_HOURS = 48
MAX_TRAILS = 200


def _now() -> datetime:
    return datetime.now()


def _load() -> dict[str, Any]:
    if TRAILS_FILE.exists():
        try:
            return json.loads(TRAILS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict[str, Any]) -> None:
    try:
        TRAILS_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _decay(value: float, age_hours: float) -> float:
    if age_hours <= 0:
        return value
    return value * (0.5 ** (age_hours / DECAY_HALF_LIFE_HOURS))


@dataclass
class Trail:
    path: str
    kind: str = "edit"
    amount: float = 1.0
    timestamp: str = ""
    failures: int = 0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now().isoformat()


def deposit(path: str, kind: str = "edit", amount: float = 1.0) -> None:
    data = _load()
    now = _now()
    entry = data.get(path, {"trails": [], "failures": 0, "visits": 0})
    entry["visits"] = entry.get("visits", 0) + 1
    if kind == "fail":
        entry["failures"] = entry.get("failures", 0) + 1
    entry.setdefault("trails", []).append({
        "t": now.isoformat(),
        "v": amount,
        "kind": kind,
    })
    entry["trails"] = entry.get("trails", [])[-50:]
    data[path] = entry
    _save(data)
    log.info("pheromone: deposit %s +%.1f (%s)", path, amount, kind)


def fail(path: str) -> None:
    deposit(path, kind="fail", amount=-2.0)


def heatmap(root: Path | None = None, limit: int = 50) -> dict[str, Any]:
    root = root or HERE
    data = _load()
    now = _now()
    scored: dict[str, float] = {}
    for rel, entry in data.items():
        latest = now
        for t in entry.get("trails", []):
            ts = t.get("t", "")
            if ts:
                try:
                    parsed = datetime.fromisoformat(ts)
                    if parsed > latest:
                        latest = parsed
                except Exception:
                    pass
        age = (now - latest).total_seconds() / 3600
        base = sum(t.get("v", 0) for t in entry.get("trails", []))
        fail_penalty = entry.get("failures", 0) * 2.0
        score = max(0.0, _decay(base, age) - fail_penalty)
        if score > 0.01:
            scored[rel] = round(score, 4)
    ranked = sorted(scored.items(), key=lambda x: -x[1])[:limit]
    return {
        "root": str(root),
        "hot_files": [{"path": p, "score": s} for p, s in ranked],
        "total_tracked": len(scored),
        "timestamp": now.isoformat(),
    }


def recent_trails(limit: int = 20) -> list[dict[str, Any]]:
    data = _load()
    now = _now()
    out = []
    for rel, entry in data.items():
        latest = now
        for t in entry.get("trails", []):
            ts = t.get("t", "")
            if ts:
                try:
                    parsed = datetime.fromisoformat(ts)
                    if parsed > latest:
                        latest = parsed
                except Exception:
                    pass
        age_hours = (now - latest).total_seconds() / 3600
        out.append({
            "path": rel,
            "visits": entry.get("visits", 0),
            "failures": entry.get("failures", 0),
            "age_hours": round(age_hours, 2),
            "score": round(_decay(
                sum(t.get("v", 0) for t in entry.get("trails", [])),
                age_hours,
            ), 4),
        })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def clear_trails() -> None:
    _save({})
    log.info("pheromone: trails cleared")


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Pheromone Trails")
    sub = p.add_subparsers(dest="command")
    dep = sub.add_parser("deposit")
    dep.add_argument("path")
    dep.add_argument("--kind", default="edit")
    dep.add_argument("--amount", type=float, default=1.0)
    sub.add_parser("heatmap")
    sub.add_parser("recent")
    sub.add_parser("clear")
    args = p.parse_args()
    if args.command == "deposit":
        deposit(args.path, args.kind, args.amount)
    elif args.command == "heatmap":
        print(json.dumps(heatmap(), indent=2, default=str))
    elif args.command == "recent":
        print(json.dumps(recent_trails(), indent=2, default=str))
    elif args.command == "clear":
        clear_trails()
        print("Trails cleared.")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
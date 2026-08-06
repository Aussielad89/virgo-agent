"""
virgo_stigmergy — stigmergic codebase heatmap.

Agents leave 'pheromone trails': recently-touched files glow brighter,
frequently-failed tests get marked as 'danger zones,' and untouched
legacy code fades. Cross-session persistence with decay.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
STIG_DIR = HERE / ".virgo_stigmergy"
STIG_DIR.mkdir(exist_ok=True)
STIG_FILE = STIG_DIR / "pheromones.json"
DECAY_HALF_LIFE_HOURS = 72


def _now() -> datetime:
    return datetime.now()


def _load() -> dict[str, Any]:
    if STIG_FILE.exists():
        try:
            return json.loads(STIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict[str, Any]) -> None:
    try:
        STIG_FILE.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def _decay(value: float, age_hours: float) -> float:
    half_life = DECAY_HALF_LIFE_HOURS
    if age_hours <= 0:
        return value
    return value * (0.5 ** (age_hours / half_life))


def deposit(rel_path: str, amount: float = 1.0, kind: str = "edit") -> None:
    data = _load()
    now = _now()
    entry = data.get(rel_path, {"trails": [], "failures": 0, "visits": 0})
    entry["visits"] = entry.get("visits", 0) + 1
    if kind == "fail":
        entry["failures"] = entry.get("failures", 0) + 1
    entry.setdefault("trails", []).append({"t": now.isoformat(), "v": amount, "kind": kind})
    entry["trails"] = entry.get("trails", [])[-50:]
    data[rel_path] = entry
    _save(data)
    log.info("stigmergy: deposit %s +%.1f (%s)", rel_path, amount, kind)


def heatmap(root: Path | None = None, pattern: str = "*.py") -> dict[str, Any]:
    root = root or HERE
    data = _load()
    now = _now()
    scores: dict[str, float] = {}
    for rel, entry in data.items():
        age = (now - datetime.fromisoformat(entry.get("updated", entry.get("trails", [{}])[-1].get("t", now.isoformat())))).total_seconds() / 3600
        base = sum(t.get("v", 0) for t in entry.get("trails", []))
        fail_penalty = entry.get("failures", 0) * 2.0
        score = max(0.0, _decay(base, age) - fail_penalty)
        if score > 0.01:
            scores[rel] = round(score, 4)
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:50]
    return {
        "root": str(root),
        "hot_files": [{"path": p, "score": s} for p, s in ranked],
        "total_tracked": len(scores),
        "timestamp": now.isoformat(),
    }


def danger_zones(min_failures: int = 2) -> list[dict[str, Any]]:
    data = _load()
    return [
        {"path": rel, "failures": meta.get("failures", 0)}
        for rel, meta in data.items()
        if meta.get("failures", 0) >= min_failures
    ]


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Stigmergic Heatmap")
    sub = p.add_subparsers(dest="command")
    dep = sub.add_parser("deposit")
    dep.add_argument("path")
    dep.add_argument("--amount", type=float, default=1.0)
    dep.add_argument("--kind", default="edit")
    h = sub.add_parser("heatmap")
    h.add_argument("--json", action="store_true")
    dz = sub.add_parser("danger")
    sub.add_parser("list")
    args = p.parse_args()
    if args.command == "deposit":
        deposit(args.path, args.amount, args.kind)
    elif args.command == "heatmap":
        print(json.dumps(heatmap(), indent=2, default=str))
    elif args.command == "danger":
        print(json.dumps(danger_zones(), indent=2))
    elif args.command == "list":
        print(json.dumps(_load(), indent=2, default=str))
    else:
        p.print_help()


if __name__ == "__main__":
    cli()

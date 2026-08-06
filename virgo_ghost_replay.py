"""
virgo_ghost_replay — Visual pipeline replay for Virgo Desktop.

Renders previous pipeline runs as an animated flow visualization.
Files being created/modified appear as nodes, tool calls as edges,
and test results as color-coded checkpoints. The user can scrub
through the timeline to see exactly what happened at each step.

Reads from .virgo_memory/sessions/<id>/events.jsonl (session_store format).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

REPLAY_DIR = HERE / ".virgo_replay"
REPLAY_DIR.mkdir(exist_ok=True)
REPLAY_INDEX = REPLAY_DIR / "index.json"


@dataclass
class ReplayNode:
    id: str
    type: str
    label: str
    timestamp: str
    status: str = "ok"
    details: str = ""
    x: float = 0.0
    y: float = 0.0


@dataclass
class ReplayEdge:
    source: str
    target: str
    label: str
    weight: int = 1


@dataclass
class ReplaySession:
    session_id: str
    goal: str
    nodes: list[ReplayNode] = field(default_factory=list)
    edges: list[ReplayEdge] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    status: str = "done"


def _load_sessions_dir() -> Path:
    return HERE / ".virgo_memory" / "sessions"


def _parse_events(events_file: Path) -> list[dict[str, Any]]:
    events = []
    if not events_file.exists():
        return events
    try:
        for line in events_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return events


def _build_graph(events: list[dict[str, Any]]) -> ReplaySession:
    nodes: list[ReplayNode] = []
    edges: list[ReplayEdge] = []
    checkpoints: list[dict[str, Any]] = []
    node_map: dict[str, str] = {}

    for i, evt in enumerate(events):
        evt_type = evt.get("type", "unknown")
        evt_id = evt.get("id", f"evt_{i}")
        ts = evt.get("timestamp", "")
        detail = evt.get("detail", evt.get("message", ""))

        if evt_type == "phase":
            phase = evt.get("phase", "unknown")
            node = ReplayNode(
                id=f"phase_{phase}_{i}",
                type="phase",
                label=phase.capitalize(),
                timestamp=ts,
                status="ok",
                details=detail,
            )
            nodes.append(node)
            node_map[phase] = node.id

        elif evt_type == "tool_call":
            tool = evt.get("tool", "unknown")
            node = ReplayNode(
                id=f"tool_{tool}_{i}",
                type="tool",
                label=tool,
                timestamp=ts,
                status="ok",
                details=detail[:200],
            )
            nodes.append(node)
            if i > 0:
                prev_id = f"evt_{i-1}"
                edges.append(ReplayEdge(
                    source=prev_id,
                    target=node.id,
                    label=tool,
                    weight=1,
                ))

        elif evt_type == "file_write":
            path = evt.get("path", "unknown")
            node = ReplayNode(
                id=f"file_{path}_{i}",
                type="file_write",
                label=f"Write {Path(path).name}",
                timestamp=ts,
                status="ok",
                details=path,
            )
            nodes.append(node)

        elif evt_type == "file_error":
            path = evt.get("path", "unknown")
            node = ReplayNode(
                id=f"file_err_{path}_{i}",
                type="file_error",
                label=f"Error {Path(path).name}",
                timestamp=ts,
                status="error",
                details=detail,
            )
            nodes.append(node)

        elif evt_type == "test_result":
            passed = evt.get("passed", True)
            node = ReplayNode(
                id=f"test_{i}",
                type="test",
                label="Test Pass" if passed else "Test Fail",
                timestamp=ts,
                status="ok" if passed else "error",
                details=detail,
            )
            nodes.append(node)
            checkpoints.append({
                "id": node.id,
                "passed": passed,
                "timestamp": ts,
                "details": detail,
            })

        elif evt_type == "session_end":
            node = ReplayNode(
                id=f"end_{i}",
                type="end",
                label="Done",
                timestamp=ts,
                status=evt.get("status", "ok"),
                details=detail,
            )
            nodes.append(node)

    # Deduplicate edges by source+target
    seen_edges: set[tuple[str, str]] = set()
    unique_edges: list[ReplayEdge] = []
    for e in edges:
        key = (e.source, e.target)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(e)

    return ReplaySession(
        session_id=events[0].get("session_id", "unknown") if events else "unknown",
        goal=events[0].get("goal", "") if events else "",
        nodes=nodes,
        edges=unique_edges,
        checkpoints=checkpoints,
        duration_seconds=0.0,
        status="done",
    )


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    sessions_dir = _load_sessions_dir()
    if not sessions_dir.exists():
        return []
    results = []
    for p in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append({
                "session_id": data.get("session_id", p.stem),
                "goal": data.get("goal", ""),
                "status": data.get("status", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "file": p.name,
            })
        except Exception:
            pass
    return results


def load_replay(session_id: str) -> ReplaySession | None:
    sessions_dir = _load_sessions_dir()
    if not sessions_dir.exists():
        return None
    for p in sessions_dir.glob(f"{session_id}.json"):
        events = _parse_events(p)
        return _build_graph(events)
    # Try events.jsonl format
    for p in sessions_dir.glob(f"{session_id}"):
        if p.is_dir():
            for ef in p.glob("events.jsonl"):
                events = _parse_events(ef)
                return _build_graph(events)
    return None


def export_replay(session_id: str, dest: Path | None = None) -> str:
    session = load_replay(session_id)
    if session is None:
        return f"No replay data found for session '{session_id}'"
    dest = dest or REPLAY_DIR / f"{session_id}_replay.json"
    try:
        data = {
            "session_id": session.session_id,
            "goal": session.goal,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "label": n.label,
                    "timestamp": n.timestamp,
                    "status": n.status,
                    "details": n.details,
                    "x": n.x,
                    "y": n.y,
                }
                for n in session.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "label": e.label,
                    "weight": e.weight,
                }
                for e in session.edges
            ],
            "checkpoints": session.checkpoints,
            "duration_seconds": session.duration_seconds,
            "status": session.status,
        }
        dest.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return f"Exported replay to {dest}"
    except Exception as exc:
        return f"Export failed: {exc}"


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Ghost Replay")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("list", help="List available sessions")
    ls = sub.add_parser("load")
    ls.add_argument("session_id")
    sub.add_parser("export", help="Export replay data")
    args = p.parse_args()
    if args.command == "list":
        sessions = list_sessions()
        for s in sessions:
            print(f"{s['session_id']}: {s['goal']} [{s['status']}]")
    elif args.command == "load":
        session = load_replay(args.session_id)
        if session:
            print(json.dumps({
                "session_id": session.session_id,
                "goal": session.goal,
                "nodes": len(session.nodes),
                "edges": len(session.edges),
                "checkpoints": len(session.checkpoints),
                "status": session.status,
            }, indent=2))
        else:
            print(f"No replay data for '{args.session_id}'")
    elif args.command == "export":
        print(export_replay(args.session_id))
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
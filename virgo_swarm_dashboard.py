"""
virgo_swarm_dashboard — Multi-agent swarm monitoring for Virgo Desktop.

Real-time dashboard showing multiple agent instances working
in parallel. Each agent gets its own lane with task status,
resource usage, communication patterns, and conflict resolution.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

SWARM_DIR = HERE / ".virgo_swarm"
SWARM_DIR.mkdir(exist_ok=True)
SWARM_STATE_FILE = SWARM_DIR / "state.json"


@dataclass
class AgentLane:
    agent_id: str
    name: str = "unknown"
    status: str = "idle"
    current_task: str = ""
    cpu_pct: float = 0.0
    memory_mb: float = 0.0
    messages_sent: int = 0
    messages_received: int = 0
    conflicts: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_heartbeat: str = ""


@dataclass
class SwarmState:
    agents: list[AgentLane] = field(default_factory=list)
    swarm_health: float = 1.0
    total_messages: int = 0
    total_conflicts: int = 0
    active_since: str = ""
    bottleneck_agents: list[str] = field(default_factory=list)


def _load_state() -> dict[str, Any]:
    if SWARM_STATE_FILE.exists():
        try:
            return json.loads(SWARM_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"agents": [], "swarm_health": 1.0}


def _save_state(state: dict[str, Any]) -> None:
    try:
        SWARM_STATE_FILE.write_text(
            json.dumps(state, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def register_agent(agent_id: str, name: str = "") -> AgentLane:
    state = _load_state()
    name = name or agent_id
    lane = AgentLane(
        agent_id=agent_id,
        name=name,
        status="active",
        last_heartbeat=__import__("datetime").datetime.now().isoformat(),
    )
    # Update or add
    existing = None
    for a in state["agents"]:
        if a.get("agent_id") == agent_id:
            existing = a
            break
    if existing:
        existing["status"] = "active"
        existing["name"] = name
        existing["last_heartbeat"] = lane.last_heartbeat
    else:
        state["agents"].append({
            "agent_id": agent_id,
            "name": name,
            "status": "active",
            "current_task": "",
            "cpu_pct": 0.0,
            "memory_mb": 0.0,
            "messages_sent": 0,
            "messages_received": 0,
            "conflicts": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "last_heartbeat": lane.last_heartbeat,
        })
    if not state.get("active_since"):
        state["active_since"] = lane.last_heartbeat
    _save_state(state)
    return lane


def update_agent(agent_id: str, **kwargs: Any) -> AgentLane | None:
    state = _load_state()
    for a in state["agents"]:
        if a.get("agent_id") == agent_id:
            for key, val in kwargs.items():
                if key in a:
                    a[key] = val
            a["last_heartbeat"] = __import__("datetime").datetime.now().isoformat()
            _save_state(state)
            return AgentLane(**a)
    return None


def record_message(from_agent: str, to_agent: str) -> None:
    state = _load_state()
    for a in state["agents"]:
        if a.get("agent_id") == from_agent:
            a["messages_sent"] = a.get("messages_sent", 0) + 1
        if a.get("agent_id") == to_agent:
            a["messages_received"] = a.get("messages_received", 0) + 1
    state["total_messages"] = state.get("total_messages", 0) + 1
    _save_state(state)


def record_conflict(agent_id: str) -> None:
    state = _load_state()
    for a in state["agents"]:
        if a.get("agent_id") == agent_id:
            a["conflicts"] = a.get("conflicts", 0) + 1
    state["total_conflicts"] = state.get("total_conflicts", 0) + 1
    _save_state(state)


def compute_health() -> float:
    state = _load_state()
    if not state["agents"]:
        return 1.0
    active = sum(1 for a in state["agents"] if a.get("status") == "active")
    total = len(state["agents"])
    if total == 0:
        return 1.0
    health = active / total
    # Penalize for conflicts
    conflict_penalty = min(state.get("total_conflicts", 0) * 0.1, 0.5)
    return max(0.0, min(1.0, health - conflict_penalty))


def detect_bottlenecks() -> list[str]:
    state = _load_state()
    bottlenecks = []
    for a in state["agents"]:
        sent = a.get("messages_sent", 0)
        recv = a.get("messages_received", 0)
        if sent > 0 and recv == 0:
            bottlenecks.append(a.get("agent_id", "unknown"))
    return bottlenecks


def get_swarm_state() -> SwarmState:
    state = _load_state()
    lanes = []
    for a in state["agents"]:
        lanes.append(AgentLane(
            agent_id=a.get("agent_id", ""),
            name=a.get("name", ""),
            status=a.get("status", "idle"),
            current_task=a.get("current_task", ""),
            cpu_pct=a.get("cpu_pct", 0.0),
            memory_mb=a.get("memory_mb", 0.0),
            messages_sent=a.get("messages_sent", 0),
            messages_received=a.get("messages_received", 0),
            conflicts=a.get("conflicts", 0),
            tasks_completed=a.get("tasks_completed", 0),
            tasks_failed=a.get("tasks_failed", 0),
            last_heartbeat=a.get("last_heartbeat", ""),
        ))
    return SwarmState(
        agents=lanes,
        swarm_health=compute_health(),
        total_messages=state.get("total_messages", 0),
        total_conflicts=state.get("total_conflicts", 0),
        active_since=state.get("active_since", ""),
        bottleneck_agents=detect_bottlenecks(),
    )


def reset_swarm() -> None:
    _save_state({"agents": [], "swarm_health": 1.0})


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Swarm Dashboard")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("status", help="Show swarm status")
    reg = sub.add_parser("register")
    reg.add_argument("agent_id")
    reg.add_argument("--name", default="")
    up = sub.add_parser("update")
    up.add_argument("agent_id")
    up.add_argument("--status", default="")
    up.add_argument("--task", default="")
    msg = sub.add_parser("message")
    msg.add_argument("from_agent")
    msg.add_argument("to_agent")
    conf = sub.add_parser("conflict")
    conf.add_argument("agent_id")
    sub.add_parser("reset", help="Reset swarm state")
    args = p.parse_args()
    if args.command == "status":
        swarm = get_swarm_state()
        print(json.dumps({
            "health": swarm.swarm_health,
            "agents": len(swarm.agents),
            "messages": swarm.total_messages,
            "conflicts": swarm.total_conflicts,
            "bottlenecks": swarm.bottleneck_agents,
        }, indent=2))
    elif args.command == "register":
        lane = register_agent(args.agent_id, args.name)
        print(f"Registered: {lane.name}")
    elif args.command == "update":
        kwargs = {}
        if args.status:
            kwargs["status"] = args.status
        if args.task:
            kwargs["current_task"] = args.task
        lane = update_agent(args.agent_id, **kwargs)
        if lane:
            print(f"Updated: {lane.name} -> {lane.status}")
        else:
            print(f"Agent '{args.agent_id}' not found")
    elif args.command == "message":
        record_message(args.from_agent, args.to_agent)
        print(f"Message: {args.from_agent} -> {args.to_agent}")
    elif args.command == "conflict":
        record_conflict(args.agent_id)
        print(f"Conflict recorded for {args.agent_id}")
    elif args.command == "reset":
        reset_swarm()
        print("Swarm state reset.")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
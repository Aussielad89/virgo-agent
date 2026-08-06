"""
virgo_divergence — pipeline divergence / time-travel branching.

Git-like branching for agent runs: fork any past session at any iteration,
swap the model or prompt, and run a parallel timeline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
DIV_DIR = HERE / ".virgo_divergence"
DIV_DIR.mkdir(exist_ok=True)
LINEAGE_FILE = DIV_DIR / "lineage.json"


def _load_lineage() -> dict[str, Any]:
    if LINEAGE_FILE.exists():
        try:
            return json.loads(LINEAGE_FILE.read_text())
        except Exception:
            return {"roots": {}, "branches": {}}
    return {"roots": {}, "branches": {}}


def _save_lineage(data: dict[str, Any]) -> None:
    try:
        LINEAGE_FILE.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def _session_path(session_id: str) -> Path | None:
    mem = HERE / ".virgo_memory"
    candidates = [
        mem / f"{session_id}.json",
        mem / f"{session_id.replace('-', '_')}.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    matches = list(mem.glob(f"*{session_id}*.json"))
    return matches[0] if matches else None


def create_root(session_id: str, label: str = "") -> dict[str, Any]:
    lineage = _load_lineage()
    root_id = hashlib.sha256(f"root:{session_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    lineage["roots"][root_id] = {
        "root_id": root_id,
        "session_id": session_id,
        "label": label or f"Root {root_id[:8]}",
        "created": datetime.now().isoformat(),
        "branch_count": 0,
    }
    _save_lineage(lineage)
    log.info("divergence: created root %s from session %s", root_id, session_id)
    return lineage["roots"][root_id]


def fork_branch(root_id: str, from_iteration: int = 0, prompt_override: str = "", model_override: str = "") -> dict[str, Any]:
    lineage = _load_lineage()
    root = lineage.get("roots", {}).get(root_id)
    if not root:
        return {"error": f"root {root_id} not found"}
    branch_id = hashlib.sha256(f"branch:{root_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    branch = {
        "branch_id": branch_id,
        "root_id": root_id,
        "parent_session_id": root["session_id"],
        "from_iteration": from_iteration,
        "prompt_override": prompt_override,
        "model_override": model_override,
        "created": datetime.now().isoformat(),
        "children": [],
        "result": None,
    }
    lineage.setdefault("branches", {})[branch_id] = branch
    root["branch_count"] = root.get("branch_count", 0) + 1
    _save_lineage(lineage)
    log.info("divergence: branched %s from root %s at iteration %d", branch_id, root_id, from_iteration)
    return branch


def record_branch_result(branch_id: str, result: dict[str, Any]) -> None:
    lineage = _load_lineage()
    branch = lineage.get("branches", {}).get(branch_id)
    if branch:
        branch["result"] = result
        branch["finished"] = datetime.now().isoformat()
        _save_lineage(lineage)
        log.info("divergence: recorded result for branch %s", branch_id)


def lineage_tree(root_id: str) -> dict[str, Any]:
    lineage = _load_lineage()
    root = lineage.get("roots", {}).get(root_id)
    if not root:
        return {"error": f"root {root_id} not found"}
    branches = [b for b in lineage.get("branches", {}).values() if b.get("root_id") == root_id]
    return {
        "root": root,
        "branches": sorted(branches, key=lambda b: b.get("created", "")),
        "total_branches": len(branches),
    }


def list_roots() -> list[dict[str, Any]]:
    return list(_load_lineage().get("roots", {}).values())


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Divergence / Time-Travel")
    sub = p.add_subparsers(dest="command")
    cr = sub.add_parser("create-root")
    cr.add_argument("session_id")
    cr.add_argument("--label", default="")
    fr = sub.add_parser("fork")
    fr.add_argument("root_id")
    fr.add_argument("--iteration", type=int, default=0)
    fr.add_argument("--prompt", default="")
    fr.add_argument("--model", default="")
    rec = sub.add_parser("record")
    rec.add_argument("branch_id")
    rec.add_argument("--result", required=True)
    lt = sub.add_parser("lineage")
    lt.add_argument("root_id")
    ls = sub.add_parser("list")
    args = p.parse_args()
    if args.command == "create-root":
        print(json.dumps(create_root(args.session_id, args.label), indent=2, default=str))
    elif args.command == "fork":
        print(json.dumps(fork_branch(args.root_id, args.iteration, args.prompt, args.model), indent=2, default=str))
    elif args.command == "record":
        try:
            result = json.loads(args.result)
        except Exception:
            result = {"raw": args.result}
        record_branch_result(args.branch_id, result)
        print("recorded")
    elif args.command == "lineage":
        print(json.dumps(lineage_tree(args.root_id), indent=2, default=str))
    elif args.command == "list":
        print(json.dumps(list_roots(), indent=2, default=str))
    else:
        p.print_help()


if __name__ == "__main__":
    cli()

"""
virgo_knowledge_seed — Portable knowledge artifacts for Virgo Desktop.

Exports/imports agent experience between sessions as compressed,
shareable "knowledge seeds." Each seed captures key decisions,
patterns, and outcomes from a completed pipeline run.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

SEEDS_DIR = HERE / ".virgo_seeds"
SEEDS_DIR.mkdir(exist_ok=True)
SEED_INDEX = SEEDS_DIR / "index.json"


def _load_index() -> dict[str, Any]:
    if SEED_INDEX.exists():
        try:
            return json.loads(SEED_INDEX.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seeds": []}


def _save_index(data: dict[str, Any]) -> None:
    try:
        SEED_INDEX.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _compute_fingerprint(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def create_seed(
    session_id: str,
    goal: str,
    decisions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    outcomes: dict[str, Any],
    tags: list[str] | None = None,
    encrypt: bool = False,
) -> dict[str, Any]:
    seed = {
        "seed_id": _compute_fingerprint({
            "session": session_id,
            "goal": goal,
            "decisions": decisions,
        }),
        "session_id": session_id,
        "goal": goal,
        "decisions": decisions,
        "patterns": patterns,
        "outcomes": outcomes,
        "tags": tags or [],
        "created": datetime.now().isoformat(),
        "version": "1.0",
    }

    if encrypt:
        seed["encrypted"] = True
        seed["data"] = _encrypt(seed)
    else:
        seed["encrypted"] = False

    index = _load_index()
    index["seeds"].append(seed)
    index["seeds"] = index["seeds"][-100:]
    _save_index(index)

    log.info("seed: created %s for session %s", seed["seed_id"], session_id)
    return seed


def _encrypt(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def list_seeds(tag: str | None = None) -> list[dict[str, Any]]:
    index = _load_index()
    seeds = index.get("seeds", [])
    if tag:
        seeds = [s for s in seeds if tag in s.get("tags", [])]
    return seeds


def load_seed(seed_id: str) -> dict[str, Any] | None:
    index = _load_index()
    for seed in index.get("seeds", []):
        if seed.get("seed_id") == seed_id:
            return seed
    return None


def export_seed(seed_id: str, dest: Path | None = None) -> str:
    seed = load_seed(seed_id)
    if seed is None:
        return f"Seed '{seed_id}' not found"
    dest = dest or SEEDS_DIR / f"{seed_id}.seed"
    try:
        with zipfile.ZipFile(str(dest), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("seed.json", json.dumps(seed, indent=2, default=str))
        return f"Exported seed to {dest}"
    except Exception as exc:
        return f"Export failed: {exc}"


def import_seed(path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            data = json.loads(zf.read("seed.json").decode("utf-8"))
        index = _load_index()
        index["seeds"].append(data)
        index["seeds"] = index["seeds"][-100:]
        _save_index(index)
        log.info("seed: imported %s", data.get("seed_id", "unknown"))
        return data
    except Exception as exc:
        log.error("seed import failed: %s", exc)
        return None


def delete_seed(seed_id: str) -> bool:
    index = _load_index()
    original_len = len(index["seeds"])
    index["seeds"] = [s for s in index["seeds"] if s.get("seed_id") != seed_id]
    if len(index["seeds"]) < original_len:
        _save_index(index)
        return True
    return False


def suggest_seeds(project_flavor: str = "") -> list[dict[str, Any]]:
    seeds = list_seeds()
    if not project_flavor:
        return seeds[:5]
    return [s for s in seeds if project_flavor in str(s.get("tags", []))][:5]


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Knowledge Seeds")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("list", help="List available seeds")
    si = sub.add_parser("suggest")
    si.add_argument("--flavor", default="")
    exp = sub.add_parser("export")
    exp.add_argument("seed_id")
    imp = sub.add_parser("import")
    imp.add_argument("path")
    del_cmd = sub.add_parser("delete")
    del_cmd.add_argument("seed_id")
    args = p.parse_args()
    if args.command == "list":
        for s in list_seeds():
            print(f"{s['seed_id']}: {s['goal']} [{', '.join(s.get('tags', []))}]")
    elif args.command == "suggest":
        for s in suggest_seeds(args.flavor):
            print(f"{s['seed_id']}: {s['goal']}")
    elif args.command == "export":
        print(export_seed(args.seed_id))
    elif args.command == "import":
        result = import_seed(Path(args.path))
        if result:
            print(f"Imported seed: {result.get('seed_id')}")
        else:
            print("Import failed.")
    elif args.command == "delete":
        ok = delete_seed(args.seed_id)
        print(f"Deleted: {ok}")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
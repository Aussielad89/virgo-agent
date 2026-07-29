"""Pipeline snapshot I/O in .virgo_memory/snapshots/."""

import json
import os
from pathlib import Path

_ROOT = Path(".virgo_memory")
_SNAP_DIR = _ROOT / "snapshots"


def _ensure_dirs() -> None:
    _SNAP_DIR.mkdir(parents=True, exist_ok=True)


def list_snapshots() -> list[dict]:
    _ensure_dirs()
    snapshots = []
    for path in sorted(_SNAP_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("id", path.stem)
            snapshots.append(data)
        except Exception:
            continue
    return snapshots


def load_snapshot(snapshot_id: str) -> dict:
    _ensure_dirs()
    path = _SNAP_DIR / f"{snapshot_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_snapshot(state: dict) -> str:
    _ensure_dirs()
    snapshot_id = state.get("id") or _next_id()
    state["id"] = snapshot_id
    path = _SNAP_DIR / f"{snapshot_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return snapshot_id


def _next_id() -> str:
    import time
    return str(int(time.time() * 1000))

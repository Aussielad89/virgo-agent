"""
virgo_ghost — pipeline ghost mode.

Run speculative code edits in an invisible overlay: the agent writes to
.virgo_ghost/ instead of the real tree. Manifest changes later, or discard.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
GHOST_ROOT = HERE / ".virgo_ghost"
GHOST_INDEX = GHOST_ROOT / ".ghost_index.json"


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _ensure() -> None:
    GHOST_ROOT.mkdir(exist_ok=True)


def _load_index() -> dict[str, Any]:
    if GHOST_INDEX.exists():
        try:
            return json.loads(GHOST_INDEX.read_text())
        except Exception:
            return {"files": {}}
    return {"files": {}}


def _save_index(idx: dict[str, Any]) -> None:
    try:
        GHOST_INDEX.write_text(json.dumps(idx, indent=2, default=str))
    except Exception:
        pass


def ghost_write(rel_path: str, content: str, root: Path | None = None) -> Path:
    root = root or HERE
    _ensure()
    target = GHOST_ROOT / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    idx = _load_index()
    idx["files"][rel_path] = {
        "ghost_path": str(target),
        "real_path": str(root / rel_path),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "size": len(content),
        "timestamp": datetime.now().isoformat(),
    }
    _save_index(idx)
    log.info("ghost: wrote %s", rel_path)
    return target


def ghost_read(rel_path: str) -> str | None:
    target = GHOST_ROOT / rel_path
    if not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except Exception:
        return None


def manifest(rel_path: str, root: Path | None = None, backup: bool = True) -> bool:
    root = root or HERE
    ghost = GHOST_ROOT / rel_path
    real = root / rel_path
    if not ghost.exists():
        return False
    try:
        if backup and real.exists():
            bak = real.with_suffix(real.suffix + ".ghostbak")
            shutil.copy2(real, bak)
        real.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ghost, real)
        log.info("ghost: manifested %s", rel_path)
        return True
    except Exception as exc:
        log.error("ghost: manifest failed for %s: %s", rel_path, exc)
        return False


def discard(rel_path: str) -> bool:
    ghost = GHOST_ROOT / rel_path
    if not ghost.exists():
        return False
    try:
        ghost.unlink()
        idx = _load_index()
        idx["files"].pop(rel_path, None)
        _save_index(idx)
        log.info("ghost: discarded %s", rel_path)
        return True
    except Exception:
        return False


def diff(rel_path: str, root: Path | None = None) -> dict[str, Any]:
    root = root or HERE
    ghost = ghost_read(rel_path)
    real_path = root / rel_path
    real = real_path.read_text(encoding="utf-8", errors="replace") if real_path.exists() else ""
    if ghost is None:
        return {"error": "no ghost version"}
    return {
        "rel_path": rel_path,
        "ghost_exists": True,
        "real_exists": real_path.exists(),
        "ghost_lines": len(ghost.splitlines()),
        "real_lines": len(real.splitlines()),
        "ghost_changed": ghost != real,
    }


def list_ghosts(root: Path | None = None) -> list[dict[str, Any]]:
    _ensure()
    idx = _load_index()
    out = []
    for rel, meta in idx.get("files", {}).items():
        g = GHOST_ROOT / rel
        out.append({
            "rel_path": rel,
            "ghost_exists": g.exists(),
            "size": meta.get("size", 0),
            "timestamp": meta.get("timestamp", ""),
        })
    out.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return out


def purge_ghosts(root: Path | None = None) -> int:
    _ensure()
    idx = _load_index()
    count = 0
    for rel in list(idx.get("files", {}).keys()):
        if discard(rel):
            count += 1
    return count


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Ghost Mode")
    sub = p.add_subparsers(dest="command")
    w = sub.add_parser("write")
    w.add_argument("path")
    w.add_argument("file", type=argparse.FileType("r"))
    m = sub.add_parser("manifest")
    m.add_argument("path")
    d = sub.add_parser("discard")
    d.add_argument("path")
    df = sub.add_parser("diff")
    df.add_argument("path")
    ls = sub.add_parser("list")
    purge = sub.add_parser("purge")
    args = p.parse_args()
    if args.command == "write":
        ghost_write(args.path, args.file.read())
    elif args.command == "manifest":
        print("manifested" if manifest(args.path) else "failed")
    elif args.command == "discard":
        print("discarded" if discard(args.path) else "not found")
    elif args.command == "diff":
        print(json.dumps(diff(args.path), indent=2))
    elif args.command == "list":
        print(json.dumps(list_ghosts(), indent=2))
    elif args.command == "purge":
        print(f"purged {purge_ghosts()} ghost files")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()

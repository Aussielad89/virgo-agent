"""Per-run isolated virtualenv sandboxes."""

import os
import shutil
import subprocess
import venv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_ROOT = Path(".virgo_memory") / "sandboxes"
_RETENTION_DAYS = 7


def _root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def create_sandbox(name: str) -> Path:
    root = _root()
    path = root / name
    if path.exists():
        raise FileExistsError(f"Sandbox already exists: {path}")
    venv.create(path, with_pip=True)
    pip = path / "Scripts" / "pip"
    subprocess.run([str(pip), "install", "virgo-agent"], check=False)
    return path


def destroy_sandbox(path: str | Path) -> None:
    p = Path(path)
    if p.exists() and p.is_dir():
        shutil.rmtree(p)


def list_sandboxes() -> list[dict[str, Any]]:
    root = _root()
    items = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        created = datetime.fromtimestamp(p.stat().st_ctime)
        items.append({
            "name": p.name,
            "path": str(p),
            "created": created.isoformat(),
            "age_days": (datetime.now() - created).days,
        })
    return items


def _cleanup() -> None:
    cutoff = datetime.now() - timedelta(days=_RETENTION_DAYS)
    for p in _root().iterdir():
        if not p.is_dir():
            continue
        created = datetime.fromtimestamp(p.stat().st_ctime)
        if created < cutoff:
            shutil.rmtree(p)

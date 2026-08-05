"""virgo_backup — zip & restore virgo config + output data.

Usage::

    import virgo_backup
    path = virgo_backup.backup()                # -> output/backup_virgo_YYYYMMDD-HHMMSS.zip
    n = virgo_backup.restore(path)              # -> number of files restored
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

from _log import OUTDIR

HERE = Path(__file__).resolve().parent
_MAX_FILE_BYTES = 20 * 1024 * 1024  # skip anything bigger than 20MB


def _collect_sources() -> list[tuple[Path, str]]:
    """Return (absolute path, archive name) pairs for a backup zip."""
    items: list[tuple[Path, str]] = []

    virgo_toml = HERE / "virgo.toml"
    if virgo_toml.exists():
        items.append((virgo_toml, "virgo.toml"))

    if OUTDIR.is_dir():
        for p in sorted(OUTDIR.rglob("*.json")):
            items.append((p, f"output/{p.relative_to(OUTDIR).as_posix()}"))
        sessions = OUTDIR / "sessions"
        if sessions.is_dir():
            for p in sorted(sessions.rglob("*")):
                if p.is_file():
                    items.append((p, f"output/sessions/{p.relative_to(sessions).as_posix()}"))
        for name in ("REMOTE_PROVIDERS.json", "memory_store.json"):
            for p in sorted(OUTDIR.rglob(name)):
                items.append((p, f"output/{p.relative_to(OUTDIR).as_posix()}"))

    # Deduplicate by archive name (the json glob may already cover the stores).
    seen: set[str] = set()
    result: list[tuple[Path, str]] = []
    for abs_path, arc in items:
        if arc in seen:
            continue
        seen.add(arc)
        result.append((abs_path, arc))
    return result


def backup(dest_dir: str | None = None) -> str:
    """Zip virgo.toml + output/* (json reports, sessions, provider/memory
    stores) into a timestamped archive and return the created zip path.

    Files larger than 20MB are skipped.  Default destination is OUTDIR.
    """
    dest = Path(dest_dir) if dest_dir else OUTDIR
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = dest / f"backup_virgo_{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arc in _collect_sources():
            try:
                if abs_path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                zf.write(abs_path, arc)
            except OSError:
                continue
    return str(zip_path)


def restore(zip_path: str) -> int:
    """Extract virgo.toml + output/* from a backup zip back over the project.

    Overwrites existing files and returns the number of files restored.
    """
    root = HERE.resolve()
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member != "virgo.toml" and not member.startswith("output/"):
                continue
            target = (root / member).resolve()
            if not str(target).startswith(str(root)):  # zip-slip guard
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            count += 1
    return count


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(f"restored {restore(sys.argv[1])} file(s)")
    else:
        print(f"backup saved to {backup()}")

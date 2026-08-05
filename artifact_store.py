"""
artifact_store — versioned, diffable outputs for Virgo agent runs.

Every artifact produced by an agent run (files, reports, transcripts,
results) can be stored under a stable name. Each store operation bumps a
version; any two versions can be diffed, so "what changed between run 1
and run 3" is a one-liner.

Layout under ``.virgo_memory/artifacts/<name>/``::

    manifest.json    list of {version, ts, meta, path}
    v0001.json       version payload (any JSON-serializable data)

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import difflib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_ROOT = Path(".virgo_memory") / "artifacts"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_name(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return cleaned.strip("._") or "artifact"


class ArtifactStore:
    """JSON payloads versioned per artifact name, with text diff support."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # ── paths ─────────────────────────────────────────────────────────
    def _dir(self, name: str) -> Path:
        return self.root / _safe_name(name)

    def _manifest_path(self, name: str) -> Path:
        return self._dir(name) / "manifest.json"

    def _version_path(self, name: str, version: int) -> Path:
        return self._dir(name) / f"v{version:04d}.json"

    # ── public API ────────────────────────────────────────────────────

    def store(
        self,
        name: str,
        data: Any,
        meta: dict[str, Any] | None = None,
        as_text: bool = False,
    ) -> int:
        """Store *data* as the next version of artifact *name*.

        Returns the new version number. When *as_text* is True the payload
        is stored as a string (so text diffs work naturally).
        """
        safe = _safe_name(name)
        d = self._dir(safe)
        d.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest(safe)
        version = (manifest[-1]["version"] if manifest else 0) + 1

        if as_text:
            payload: Any = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
        else:
            payload = data

        self._version_path(safe, version).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        entry = {
            "version": version,
            "ts": _now(),
            "meta": meta or {},
            "as_text": bool(as_text),
            "size": len(json.dumps(payload, ensure_ascii=False)),
        }
        manifest.append(entry)
        self._write_manifest(safe, manifest)
        log.info("artifact: stored %s v%d", safe, version)
        return version

    def versions(self, name: str) -> list[dict]:
        """Return the manifest list (newest last) for *name*."""
        return self._load_manifest(_safe_name(name))

    def get(self, name: str, version: int | None = None) -> dict:
        """Return {version, ts, meta, data} for *name*.

        Without *version*, the latest version is returned. Raises
        KeyError when the artifact or version does not exist.
        """
        safe = _safe_name(name)
        manifest = self._load_manifest(safe)
        if not manifest:
            raise KeyError(f"artifact '{name}' has no versions")
        if version is None:
            version = manifest[-1]["version"]
        entry = next((e for e in manifest if e["version"] == version), None)
        if entry is None:
            raise KeyError(f"artifact '{name}' has no version {version}")
        path = self._version_path(safe, version)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise KeyError(f"artifact '{name}' v{version} unreadable: {exc}") from exc
        return {"version": version, "ts": entry["ts"], "meta": entry.get("meta", {}), "data": data}

    def diff(self, name: str, v1: int | None = None, v2: int | None = None) -> str:
        """Unified text diff between two versions (defaults: latest two).

        Works on the raw payloads; non-text payloads are JSON-pretty-printed
        first so the diff stays readable. Returns '' when versions match.
        """
        safe = _safe_name(name)
        manifest = self._load_manifest(safe)
        if len(manifest) < 2:
            return "(need at least two versions to diff)"
        v2 = v2 or manifest[-1]["version"]
        v1 = v1 or manifest[-2]["version"]
        a = self.get(safe, v1)["data"]
        b = self.get(safe, v2)["data"]
        a_text = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False, indent=2)
        b_text = b if isinstance(b, str) else json.dumps(b, ensure_ascii=False, indent=2)
        if a_text == b_text:
            return f"(artifact '{safe}': v{v1} and v{v2} are identical)"
        diff = difflib.unified_diff(
            a_text.splitlines(),
            b_text.splitlines(),
            fromfile=f"{safe} v{v1}",
            tofile=f"{safe} v{v2}",
            lineterm="",
        )
        return "\n".join(diff)

    def list(self) -> list[dict]:
        """Summarize every artifact and its latest version."""
        rows: list[dict] = []
        if not self.root.exists():
            return rows
        for d in sorted(self.root.iterdir()):
            if not d.is_dir():
                continue
            manifest = self._load_manifest(d.name)
            if not manifest:
                continue
            latest = manifest[-1]
            rows.append(
                {
                    "name": d.name,
                    "versions": len(manifest),
                    "latest": latest["version"],
                    "updated_at": latest["ts"],
                    "meta": latest.get("meta", {}),
                }
            )
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return rows

    def delete(self, name: str) -> bool:
        """Delete an artifact entirely. Returns False when absent."""
        d = self._dir(name)
        if not d.exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    # ── internals ─────────────────────────────────────────────────────
    def _load_manifest(self, safe: str) -> list[dict]:
        path = self._manifest_path(safe)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("artifact: corrupt manifest %s: %s", path, exc)
            return []
        return data if isinstance(data, list) else []

    def _write_manifest(self, safe: str, manifest: list[dict]) -> None:
        self._manifest_path(safe).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: ArtifactStore | None = None


def get_artifacts(root: str | Path | None = None) -> ArtifactStore:
    """Lazy process-wide ArtifactStore singleton."""
    global _INSTANCE
    if root is not None:
        _INSTANCE = ArtifactStore(root)
    elif _INSTANCE is None:
        _INSTANCE = ArtifactStore()
    return _INSTANCE

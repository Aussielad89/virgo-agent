"""
session_store — durable checkpoint/resume for Virgo agent runs.

Lets an autonomous agent run be paused and resumed later, even across
process restarts. Every significant event is appended to a JSONL events
file (which doubles as a live timeline for the desktop GUI), and a
checkpoint JSON captures the full ReAct state: goal, messages, transcript,
tool usage, step/retry counters and config.

Layout under ``.virgo_memory/sessions/<session_id>/``::

    events.jsonl      every progress event (phase, message, detail, ts)
    checkpoint.json   last saved snapshot (goal, messages, transcript, ...)
    transcript.txt    final human-readable transcript when finished

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_ROOT = Path(".virgo_memory") / "sessions"
LIVE_ID = "live"  # session id used by the desktop live-timeline page

# Characters that are safe inside a session id directory name.
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def slugify(text: str, max_len: int = 40) -> str:
    """Turn free text into a filesystem-safe identifier."""
    slug = _SAFE_ID_RE.sub("-", text.strip().lower()).strip("-._")
    return slug[:max_len] or "task"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class SessionSnapshot:
    """A checkpointable snapshot of agent run state."""

    session_id: str
    goal: str
    status: str = "running"  # running | paused | done | failed
    steps_used: int = 0
    retries_used: int = 0
    tools_used: list[str] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "steps_used": self.steps_used,
            "retries_used": self.retries_used,
            "tools_used": list(self.tools_used),
            "transcript": list(self.transcript),
            "messages": list(self.messages),
            "config": self.config,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionSnapshot":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class SessionStore:
    """Filesystem-backed checkpoint store for agent runs."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── path helpers ──────────────────────────────────────────────────
    def _dir(self, session_id: str) -> Path:
        return self.root / session_id

    def _events_path(self, session_id: str) -> Path:
        return self._dir(session_id) / "events.jsonl"

    def _checkpoint_path(self, session_id: str) -> Path:
        return self._dir(session_id) / "checkpoint.json"

    def _transcript_path(self, session_id: str) -> Path:
        return self._dir(session_id) / "transcript.txt"

    # ── lifecycle ────────────────────────────────────────────────────
    def new_session(self, goal: str, session_id: str | None = None) -> SessionSnapshot:
        """Create a fresh snapshot and an on-disk session directory."""
        sid = session_id or f"{slugify(goal)}_{uuid.uuid4().hex[:8]}"
        snap = SessionSnapshot(session_id=sid, goal=goal)
        self._dir(sid).mkdir(parents=True, exist_ok=True)
        self.save_checkpoint(snap)
        return snap

    def save_checkpoint(self, snap: SessionSnapshot) -> None:
        """Persist a snapshot atomically (write temp then rename)."""
        snap.updated_at = _now()
        path = self._checkpoint_path(snap.session_id)
        tmp = path.with_suffix(".tmp")
        with self._lock:
            self._dir(snap.session_id).mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(snap.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            shutil.move(str(tmp), str(path))

    def load_checkpoint(self, session_id: str) -> SessionSnapshot | None:
        """Load a saved snapshot, or None when missing/corrupt."""
        path = self._checkpoint_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("session_store: corrupt checkpoint %s: %s", path, exc)
            return None
        return SessionSnapshot.from_dict(data)

    def mark_done(
        self,
        session_id: str,
        status: str = "done",
        transcript_text: str = "",
    ) -> None:
        """Finalize a session: set status and write the transcript."""
        snap = self.load_checkpoint(session_id)
        if snap is None:
            return
        snap.status = status
        self.save_checkpoint(snap)
        if transcript_text:
            self._transcript_path(session_id).write_text(
                transcript_text, encoding="utf-8"
            )

    # ── events (live timeline feed) ───────────────────────────────────
    def append_event(
        self,
        session_id: str,
        phase: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        """Append one progress event to the session's JSONL feed."""
        entry = {
            "session_id": session_id,
            "ts": _now(),
            "phase": phase,
            "message": message,
            "detail": detail,
        }
        with self._lock:
            self._dir(session_id).mkdir(parents=True, exist_ok=True)
            with self._events_path(session_id).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_events(self, session_id: str, after_ts: str = "") -> list[dict]:
        """Return events (newest last) optionally filtered by timestamp."""
        path = self._events_path(session_id)
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if after_ts and (ev.get("ts") or "") <= after_ts:
                    continue
                out.append(ev)
        except OSError:
            return []
        return out

    def list_sessions(self, limit: int = 50) -> list[dict]:
        """Summarize every session directory (newest first)."""
        rows: list[dict] = []
        if not self.root.exists():
            return rows
        for d in sorted(self.root.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            snap = self.load_checkpoint(d.name)
            if snap is None:
                continue
            rows.append(
                {
                    "session_id": snap.session_id,
                    "goal": snap.goal,
                    "status": snap.status,
                    "steps_used": snap.steps_used,
                    "tools_used": snap.tools_used,
                    "started_at": snap.started_at,
                    "updated_at": snap.updated_at,
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def delete(self, session_id: str) -> bool:
        """Remove a session directory. Returns False when absent."""
        d = self._dir(session_id)
        if not d.exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True


# ── Live session singleton (used by the desktop timeline + runtime) ──

_LIVE: SessionStore | None = None


def get_store(root: str | Path | None = None) -> SessionStore:
    """Lazy process-wide SessionStore singleton."""
    global _LIVE
    if root is not None:
        _LIVE = SessionStore(root)
    elif _LIVE is None:
        _LIVE = SessionStore()
    return _LIVE


def live() -> SessionStore:
    """Convenience alias returning the singleton store."""
    return get_store()

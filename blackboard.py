"""
blackboard — shared message space for agent-to-agent communication.

A lightweight publish/subscribe dict that lets swarm agents exchange
findings, delegate sub-tasks, and coordinate work without direct coupling.

Usage::

    from blackboard import Blackboard

    bb = Blackboard()

    # Agent A posts findings
    bb.post("network/hosts", ["192.168.1.1"], source="scanner")

    # Agent B reads them
    hosts = bb.get("network/hosts")   # → ["192.168.1.1"]

    # Agent B waits for data that hasn't been posted yet
    ports = bb.wait_for("network/ports", timeout=30)
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


# ── Entry type ──────────────────────────────────────────────────────

@dataclass
class BoardEntry:
    """A single post on the blackboard."""
    topic: str
    content: Any
    source: str = ""
    entry_id: int = 0
    timestamp: str = ""
    phase: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ── Blackboard ─────────────────────────────────────────────────────

class Blackboard:
    """Thread-safe shared knowledge space for swarm agents.

    Agents can post findings, read each other's data, and optionally
    block-wait for data that hasn't been produced yet (ordered mode).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._topics: dict[str, list[BoardEntry]] = {}
        self._next_id: int = 1
        self._events: dict[str, threading.Event] = {}

    # ── Public API ──────────────────────────────────────────────────

    def post(
        self,
        topic: str,
        content: Any,
        *,
        source: str = "",
        phase: str = "",
    ) -> int:
        """Publish *content* under *topic*.

        Returns the entry ID (monotonic per-board).
        """
        with self._lock:
            entry = BoardEntry(
                topic=topic,
                content=content,
                source=source,
                entry_id=self._next_id,
                phase=phase,
            )
            self._topics.setdefault(topic, []).append(entry)
            eid = self._next_id
            self._next_id += 1

            # Wake up any wait_for() callers
            ev = self._events.get(topic)
            if ev is not None:
                ev.set()

        return eid

    def get(
        self,
        topic: str,
        *,
        latest: bool = True,
    ) -> Optional[Any]:
        """Read content for *topic*.

        If *latest* is True (default) returns the most recent entry's
        content.  If False, returns a list of all entries for the topic.
        Returns None if the topic has no entries.
        """
        with self._lock:
            entries = self._topics.get(topic)
            if not entries:
                return None
            if latest:
                return entries[-1].content
            return [e.content for e in entries]

    def get_entry(self, topic: str, *, latest: bool = True) -> Optional[BoardEntry]:
        """Like ``get()`` but returns the full ``BoardEntry`` object."""
        with self._lock:
            entries = self._topics.get(topic)
            if not entries:
                return None
            if latest:
                return entries[-1]
            return entries

    def entries(self, topic: str) -> list[BoardEntry]:
        """Return every entry for a topic (oldest first)."""
        with self._lock:
            return list(self._topics.get(topic, []))

    def topics(self) -> list[str]:
        """Return all topic keys."""
        with self._lock:
            return list(self._topics.keys())

    def search(self, pattern: str) -> list[BoardEntry]:
        """Find entries whose topic or JSON content matches *pattern* (regex)."""
        compiled = re.compile(pattern, re.IGNORECASE)
        hits: list[BoardEntry] = []
        with self._lock:
            for entries in self._topics.values():
                for e in entries:
                    text = f"{e.topic} {json.dumps(e.content, default=str)}"
                    if compiled.search(text):
                        hits.append(e)
        return hits

    def wait_for(
        self,
        topic: str,
        *,
        timeout: float = 30.0,
    ) -> Optional[Any]:
        """Block until *topic* has at least one entry, then return its content.

        Returns None on timeout.
        """
        with self._lock:
            entries = self._topics.get(topic)
            if entries:
                return entries[-1].content
            if topic not in self._events:
                self._events[topic] = threading.Event()

        ev = self._events[topic]
        ev.wait(timeout=timeout)
        ev.clear()

        with self._lock:
            entries = self._topics.get(topic)
            return entries[-1].content if entries else None

    def clear(self, topic: Optional[str] = None) -> None:
        """Remove all entries, or just those under *topic*."""
        with self._lock:
            if topic:
                self._topics.pop(topic, None)
            else:
                self._topics.clear()
                self._next_id = 1

    # ── Serialisation ───────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire board (for saving to disk)."""
        topics_dict: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            for topic, entries in self._topics.items():
                topics_dict[topic] = [asdict(e) for e in entries]
        return {
            "next_id": self._next_id,
            "topics": topics_dict,
        }

    def to_json(self, indent: int = 2) -> str:
        """JSON dump of the board."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blackboard:
        """Restore a board from ``to_dict()`` output."""
        bb = cls()
        bb._next_id = data.get("next_id", 1)
        for topic, raw_entries in data.get("topics", {}).items():
            entries = [BoardEntry(**e) for e in raw_entries]
            bb._topics[topic] = entries
        return bb

    @classmethod
    def from_json(cls, text: str) -> Blackboard:
        """Restore a board from ``to_json()`` output."""
        return cls.from_dict(json.loads(text))

    # ── Summary for display ─────────────────────────────────────────

    def summary(self) -> str:
        """Human-readable summary of board contents."""
        with self._lock:
            if not self._topics:
                return "  (empty blackboard)"
            lines: list[str] = []
            for topic in sorted(self._topics):
                entries = self._topics[topic]
                last = entries[-1]
                src = f" by {last.source}" if last.source else ""
                content_preview = str(last.content)
                if len(content_preview) > 80:
                    content_preview = content_preview[:77] + "..."
                lines.append(
                    f"  {topic} ({len(entries)} post(s){src})"
                    f"\n    → {content_preview}"
                )
            return "\n".join(lines)

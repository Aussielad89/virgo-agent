"""
experience.py — experience memory for the virgo agent framework.

Lets the agent learn from past tasks so it stops re-solving the same
problems. Experiences are stored as JSON lines in a `.jsonl` file and
ranked for recall by keyword overlap (Jaccard) with a query goal.

Stdlib-only. Conventions: PascalCase classes, snake_case functions,
logging via `_log.log`, no raw emoji.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from _log import log

# Default storage location (relative to the current working directory).
DEFAULT_PATH = ".virgo_memory/experience.jsonl"

# Light stopword list to keep keywords meaningful.
_STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "will", "your", "what", "when",
        "were", "been", "they", "them", "their", "then", "than", "here", "there",
        "would", "could", "should", "which", "while", "about", "after", "before",
        "being", "where", "these", "those", "some", "such", "into", "over", "also",
        "because", "other", "then", "more", "most", "very", "just", "like", "than",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _keywords(text: str) -> set[str]:
    """Return lowercase alpha tokens of length >= 4, stopword-filtered.

    Used for both stored-entry keyword extraction and query goals.
    """
    if not text:
        return set()
    tokens = _TOKEN_RE.findall(text.lower())
    return {tok for tok in tokens if len(tok) >= 4 and tok not in _STOPWORDS}


def _overlap(query_kw: set[str], entry_kw: set[str]) -> float:
    """Jaccard similarity between two keyword sets (0.0 when either empty)."""
    if not query_kw or not entry_kw:
        return 0.0
    inter = len(query_kw & entry_kw)
    union = len(query_kw | entry_kw)
    return inter / union if union else 0.0


class ExperienceMemory:
    """Append-only store of past task experiences, ranked by relevance."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path) if path else Path(DEFAULT_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict] = []
        self._next_id = 1
        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        """Read the JSONL file, skipping any malformed lines."""
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem edge case
            log.warning("experience: cannot read %s: %s", self.path, exc)
            return
        max_id = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError) as exc:
                log.warning("experience: skipping corrupt line in %s: %s", self.path, exc)
                continue
            if not isinstance(entry, dict):
                log.warning("experience: skipping non-object line in %s", self.path)
                continue
            self._entries.append(entry)
            try:
                max_id = max(max_id, int(entry.get("id", 0)))
            except (TypeError, ValueError):
                pass
        self._next_id = max_id + 1

    def _persist(self, entry: dict) -> None:
        """Append a single entry as one JSON line."""
        line = json.dumps(entry, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ── public API ───────────────────────────────────────────────────

    def add(
        self,
        goal: str,
        approach: str,
        tools_used: list[str],
        outcome: str,
        success: bool,
        lesson: str = "",
    ) -> dict:
        """Record a completed task and persist it. Returns the stored dict."""
        entry_id = self._next_id
        self._next_id += 1
        entry = {
            "id": entry_id,
            "ts": datetime.now().astimezone().isoformat(),
            "goal": goal,
            "approach": approach,
            "tools_used": list(tools_used),
            "outcome": outcome,
            "success": bool(success),
            "lesson": lesson,
            "keywords": sorted(_keywords(goal + " " + approach + " " + lesson)),
        }
        self._entries.append(entry)
        self._persist(entry)
        return entry

    def recall(self, goal: str, k: int = 3) -> list[dict]:
        """Return the top-k entries ranked by keyword overlap with `goal`.

        Only entries with non-zero overlap are returned. Most-recent wins
        ties (higher insertion index first). Returns [] if the store is
        empty or nothing overlaps.
        """
        if not self._entries:
            return []
        query_kw = _keywords(goal)
        scored = []
        for idx, entry in enumerate(self._entries):
            score = _overlap(query_kw, set(entry.get("keywords", [])))
            if score > 0:
                scored.append((score, idx, entry))
        # Highest score first; ties broken by most recent (largest idx).
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [entry for _, _, entry in scored[:k]]

    def format_for_prompt(self, goal: str, k: int = 3) -> str:
        """Compact multiline block of past lessons for an LLM prompt.

        Only entries that succeeded or carry a non-empty lesson are shown.
        Returns 'PAST EXPERIENCE: (none)' when there is nothing relevant.
        """
        recalled = self.recall(goal, k)
        lines = []
        for entry in recalled:
            if not entry.get("success") and not entry.get("lesson"):
                continue
            status = "OK" if entry.get("success") else "FAIL"
            goal_text = entry.get("goal", "")
            if len(goal_text) > 60:
                goal_text = goal_text[:57] + "..."
            takeaway = entry.get("lesson") or entry.get("outcome", "")
            lines.append(f"- [{status}] {goal_text} -> {takeaway}")
        if not lines:
            return "PAST EXPERIENCE: (none)"
        return "PAST EXPERIENCE:\n" + "\n".join(lines)

    def stats(self) -> dict:
        """Return {count, successes, failures}."""
        count = len(self._entries)
        successes = sum(1 for e in self._entries if e.get("success"))
        failures = count - successes
        return {"count": count, "successes": successes, "failures": failures}


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: Optional[ExperienceMemory] = None


def get_memory(path: Optional[str] = None) -> ExperienceMemory:
    """Lazy, process-wide singleton ExperienceMemory.

    The first call (without a path) creates the default store. Subsequent
    calls return the same instance unless `path` is explicitly provided,
    in which case a fresh instance for that path is created and cached.
    """
    global _INSTANCE
    if path is not None:
        _INSTANCE = ExperienceMemory(path)
    elif _INSTANCE is None:
        _INSTANCE = ExperienceMemory()
    return _INSTANCE

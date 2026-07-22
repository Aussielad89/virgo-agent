"""
experience.py — experience memory for the virgo agent framework.

Lets the agent learn from past tasks so it stops re-solving the same
problems. Experiences are stored as JSON lines in a `.jsonl` file and
ranked for recall by keyword overlap (Jaccard) with a query goal.

Also supports **semantic embeddings** via Ollama for richer retrieval
when the ``LLM_BASE_URL`` env var points to an Ollama instance.

Stdlib-only. Conventions: PascalCase classes, snake_case functions,
logging via `_log.log`, no raw emoji.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from _log import log

# Default storage location (relative to the current working directory).
DEFAULT_PATH = ".virgo_memory/experience.jsonl"

# Light stopword list to keep keywords meaningful.
_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "have",
        "will",
        "your",
        "what",
        "when",
        "were",
        "been",
        "they",
        "them",
        "their",
        "then",
        "than",
        "here",
        "there",
        "would",
        "could",
        "should",
        "which",
        "while",
        "about",
        "after",
        "before",
        "being",
        "where",
        "these",
        "those",
        "some",
        "such",
        "into",
        "over",
        "also",
        "because",
        "other",
        "more",
        "most",
        "very",
        "just",
        "like",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z]+")

# ── Optional embedding support via Ollama ─────────────────────────────

_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen2.5-coder:7b")
_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")


def _get_embedding(text: str) -> list[float] | None:
    """Get an embedding vector from Ollama's embedding endpoint.

    Returns None if the endpoint is unreachable or returns an error.
    """
    try:
        req = urllib.request.Request(
            f"{_LLM_BASE_URL.rstrip('/')}/embeddings",
            data=json.dumps({"model": _EMBEDDING_MODEL, "input": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            # OpenAI-compatible format: {"data": [{"embedding": [...]}]}
            data = body.get("data", body.get("data", [body]))
            if isinstance(data, list) and len(data) > 0:
                return data[0] if isinstance(data[0], list) else data[0].get("embedding")
            # Ollama format: {"embedding": [...]}
            if "embedding" in body:
                return body["embedding"]
    except Exception as exc:
        log.debug("experience: embedding unavailable (%s)", exc)
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# ── Keyword helpers ──────────────────────────────────────────────────


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

    def __init__(self, path: str | None = None) -> None:
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
        # Compute keywords + optional embedding
        kw = sorted(_keywords(goal + " " + approach + " " + lesson))
        embedding = _get_embedding(goal + " " + approach)
        entry = {
            "id": entry_id,
            "ts": datetime.now().astimezone().isoformat(),
            "goal": goal,
            "approach": approach,
            "tools_used": list(tools_used),
            "outcome": outcome,
            "success": bool(success),
            "lesson": lesson,
            "keywords": kw,
        }
        if embedding is not None:
            entry["embedding"] = embedding
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

    def recall_semantic(self, goal: str, k: int = 3) -> list[dict]:
        """Return top-k entries by cosine similarity of embeddings.

        Falls back to keyword recall when embeddings are not available
        or the embedding endpoint is unreachable.
        """
        if not self._entries:
            return []
        query_emb = _get_embedding(goal)
        if query_emb is None:
            # Fall back to keyword recall
            return self.recall(goal, k)

        scored = []
        for idx, entry in enumerate(self._entries):
            entry_emb = entry.get("embedding")
            if entry_emb:
                score = _cosine_similarity(query_emb, entry_emb)
                scored.append((score, idx, entry))
        if not scored:
            # No entries with embeddings; fall back to keywords
            return self.recall(goal, k)
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [entry for _, _, entry in scored[:k]]

    def format_for_prompt(self, goal: str, k: int = 3, semantic: bool = True) -> str:
        """Compact multiline block of past lessons for an LLM prompt.

        Uses semantic recall by default (embeddings), falling back to
        keyword overlap when embeddings are unavailable.
        Only entries that succeeded or carry a non-empty lesson are shown.
        Returns 'PAST EXPERIENCE: (none)' when there is nothing relevant.
        """
        recalled = self.recall_semantic(goal, k) if semantic else self.recall(goal, k)
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
        """Return {count, successes, failures, embeddings}."""
        count = len(self._entries)
        successes = sum(1 for e in self._entries if e.get("success"))
        failures = count - successes
        with_embeddings = sum(1 for e in self._entries if "embedding" in e)
        return {
            "count": count,
            "successes": successes,
            "failures": failures,
            "with_embeddings": with_embeddings,
        }


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: ExperienceMemory | None = None


def get_memory(path: str | None = None) -> ExperienceMemory:
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

"""
memory_store — one API over every Virgo memory backend.

Virgo has grown several memory systems (experience.py JSONL, learning_engine
SQLite, optional mem0/cognee spikes). This module presents a single unified
interface so the agent (and the desktop Memory page) can ask one question —
"have I solved something like this before?" — and get answers from all of
them, plus a long-term user profile that persists across sessions.

Backends
--------
* ExperienceMemory  (JSONL, keyword + optional embeddings)
* LearningEngine    (SQLite + FTS5)
* ProfileStore      (JSON facts about the user/agent, long-lived)
* semantic backend  (best-effort import of _mem0_memory; None when absent)

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_ROOT = Path(".virgo_memory")
PROFILE_FILE = "profile.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ── Long-term profile ──────────────────────────────────────────────────


class ProfileStore:
    """Key-value facts about the user/agent, remembered across sessions.

    Facts are stored with a timestamp so the agent can answer "who am I
    talking to" and "what do they prefer" without a fresh prompt every run.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            self.path = DEFAULT_ROOT / PROFILE_FILE
        else:
            self.path = Path(root) / PROFILE_FILE
        self._facts: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("profile: corrupt profile %s: %s", self.path, exc)
            return
        self._facts = data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._facts, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def set(self, key: str, value: Any) -> None:
        """Remember (or update) a fact. Returns nothing."""
        self._facts[key] = {"value": value, "ts": _now()}
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        fact = self._facts.get(key)
        return fact["value"] if fact else default

    def remove(self, key: str) -> bool:
        if key in self._facts:
            del self._facts[key]
            self._save()
            return True
        return False

    def all(self) -> dict[str, Any]:
        """Return {key: value} for every remembered fact."""
        return {k: v.get("value") for k, v in self._facts.items()}

    def facts(self) -> list[dict[str, Any]]:
        """Return raw fact records (key, value, ts), oldest first."""
        return [
            {"key": k, "value": v.get("value"), "ts": v.get("ts", "")}
            for k, v in sorted(self._facts.items(), key=lambda kv: kv[1].get("ts", ""))
        ]

    def format_for_prompt(self) -> str:
        """Compact block of known facts for an LLM prompt."""
        if not self._facts:
            return "USER PROFILE: (nothing learned yet)"
        lines = [f"  - {k}: {v.get('value')}" for k, v in self._facts.items()]
        return "USER PROFILE:\n" + "\n".join(lines)


# ── Semantic backend adapter (mem0, optional) ──────────────────────────


def _semantic_backend() -> Any | None:
    """Return an optional semantic memory backend, or None.

    Wraps _mem0_memory if importable; any failure degrades to None so the
    unified memory always works with just the stdlib backends.
    """
    try:
        from _mem0_memory import get_mem0_memory  # type: ignore

        return get_mem0_memory()
    except Exception:
        return None


# ── Unified memory ─────────────────────────────────────────────────────


class UnifiedMemory:
    """Single entry point for remembering and recalling across backends."""

    def __init__(
        self,
        root: str | Path | None = None,
        experience: Any = None,
        learning: Any = None,
        profile: ProfileStore | None = None,
        semantic: Any | None = None,
    ) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        if experience is None:
            try:
                from experience import ExperienceMemory

                experience = ExperienceMemory(self.root / "experience.jsonl")
            except Exception as exc:  # pragma: no cover
                log.warning("memory_store: experience unavailable (%s)", exc)
        if learning is None:
            try:
                from learning_engine import LearningEngine

                learning = LearningEngine(self.root / "learning.db")
            except Exception as exc:  # pragma: no cover
                log.warning("memory_store: learning unavailable (%s)", exc)
        self.experience = experience
        self.learning = learning
        self.profile = profile or ProfileStore(self.root)
        self.semantic = semantic if semantic is not None else _semantic_backend()

    # ── remember ─────────────────────────────────────────────────────
    def remember(
        self,
        goal: str,
        approach: str,
        tools_used: list[str],
        outcome: str,
        success: bool,
        lesson: str = "",
        task_type: str = "agent",
    ) -> None:
        """Record a completed task in every writable backend."""
        if self.experience is not None:
            try:
                self.experience.add(
                    goal=goal,
                    approach=approach,
                    tools_used=tools_used,
                    outcome=outcome,
                    success=success,
                    lesson=lesson,
                )
            except Exception as exc:  # pragma: no cover
                log.warning("memory_store: experience write failed: %s", exc)
        if self.learning is not None:
            try:
                self.learning.record(
                    task_type=task_type,
                    goal=goal[:500],
                    approach=approach,
                    tools_used=tools_used,
                    outcome=outcome,
                    success=success,
                    lesson=lesson,
                    session_id="",
                )
            except Exception as exc:  # pragma: no cover
                log.warning("memory_store: learning write failed: %s", exc)
        if self.semantic is not None:
            try:
                self.semantic.remember(
                    text=f"{goal}\n{approach}\n{lesson}",
                    meta={
                        "goal": goal,
                        "success": success,
                        "outcome": outcome,
                    },
                )
            except Exception as exc:  # pragma: no cover
                log.debug("memory_store: semantic write skipped (%s)", exc)

    # ── recall ───────────────────────────────────────────────────────
    def recall(self, query: str, k: int = 3) -> list[dict]:
        """Return top-k merged results from all backends, scored by source.

        Semantic backend first (when available), then experience, then
        learning. Entries are deduplicated by goal text.
        """
        merged: list[dict] = []
        seen: set[str] = set()

        def _push(entries: list[dict], source: str) -> None:
            for e in entries or []:
                key = str(e.get("goal", ""))[:120]
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append({**e, "source": source})

        if self.semantic is not None:
            try:
                _push(self.semantic.recall(query, k=k), "semantic")
            except Exception as exc:  # pragma: no cover
                log.debug("memory_store: semantic recall skipped (%s)", exc)
        if self.experience is not None:
            try:
                _push(self.experience.recall_semantic(query, k=k), "experience")
            except Exception:  # pragma: no cover
                try:
                    _push(self.experience.recall(query, k=k), "experience")
                except Exception:
                    pass
        if self.learning is not None:
            try:
                _push(self.learning.search(query, limit=k), "learning")
            except Exception:
                try:
                    _push(self.learning.search_by_keywords(query, limit=k), "learning")
                except Exception:
                    pass
        return merged[:k]

    def format_for_prompt(self, query: str, k: int = 3) -> str:
        """Combine recalled lessons + user profile into one prompt block."""
        blocks = [self.profile.format_for_prompt()]
        recalled = self.recall(query, k=k)
        if recalled:
            lines = []
            for e in recalled:
                status = "OK" if e.get("success") else "FAIL"
                goal = str(e.get("goal", ""))[:72]
                lesson = str(e.get("lesson") or e.get("outcome") or "")[:180]
                src = e.get("source", "?")
                lines.append(f"  - [{status}][{src}] {goal}")
                if lesson:
                    lines.append(f"    lesson: {lesson}")
            blocks.append("PAST EXPERIENCE:\n" + "\n".join(lines))
        else:
            blocks.append("PAST EXPERIENCE: (none)")
        return "\n\n".join(blocks)

    def stats(self) -> dict[str, Any]:
        """Per-backend statistics."""
        out: dict[str, Any] = {"profile_facts": len(self._facts_count())}
        if self.experience is not None:
            try:
                out["experience"] = self.experience.stats()
            except Exception:
                out["experience"] = {}
        if self.learning is not None:
            try:
                out["learning"] = self.learning.stats()
            except Exception:
                out["learning"] = {}
        out["semantic"] = "available" if self.semantic is not None else "none"
        return out

    def _facts_count(self) -> dict:
        return self.profile.all()


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: UnifiedMemory | None = None


def get_unified(root: str | Path | None = None) -> UnifiedMemory:
    """Lazy process-wide UnifiedMemory singleton."""
    global _INSTANCE
    if root is not None:
        _INSTANCE = UnifiedMemory(root)
    elif _INSTANCE is None:
        _INSTANCE = UnifiedMemory()
    return _INSTANCE

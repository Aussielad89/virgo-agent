"""
learning_engine — persistent agent memory & learning engine for Virgo.

Stores successful/failed outcomes per task type across sessions in SQLite,
and automatically injects relevant past lessons into new runs so the agent
improves planning, generation, and fixing based on what worked before.

Uses only stdlib ``sqlite3`` — no extra dependencies.
Storage root: ``.virgo_memory/learning.db`` (gitignored).

Conventions
-----------
- ``from __future__ import annotations``
- Full type hints on all public methods
- ``icon()`` from ``_console.py`` for UI output
- Logging via ``_log.log``
- Module-level ``get_learning()`` singleton factory
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _log import log

# ── Default storage ────────────────────────────────────────────────────

DEFAULT_DB_DIR = ".virgo_memory"
DEFAULT_DB_NAME = "learning.db"

# Light stopword list to keep keywords meaningful.
_STOPWORDS: frozenset[str] = frozenset(
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
        "and",
        "the",
        "are",
        "not",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def _keywords(text: str) -> list[str]:
    """Extract meaningful keywords from *text* for FTS and tag matching."""
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    return sorted(
        {tok for tok in tokens if len(tok) >= 3 and tok not in _STOPWORDS}
    )


# ── Schema ──────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type       TEXT    NOT NULL DEFAULT '',
    goal            TEXT    NOT NULL DEFAULT '',
    approach        TEXT    NOT NULL DEFAULT '',
    tools_used      TEXT    NOT NULL DEFAULT '[]',    -- JSON list
    outcome         TEXT    NOT NULL DEFAULT '',
    success         INTEGER NOT NULL DEFAULT 1,        -- 0/1
    lesson          TEXT    NOT NULL DEFAULT '',
    session_id      TEXT    NOT NULL DEFAULT '',
    tags            TEXT    NOT NULL DEFAULT '[]',      -- JSON list of keywords
    created_at      REAL    NOT NULL,                  -- Unix timestamp
    expires_at      REAL                              -- NULL = never expires
);

CREATE INDEX IF NOT EXISTS idx_lessons_task_type ON lessons(task_type);
CREATE INDEX IF NOT EXISTS idx_lessons_success  ON lessons(success);
CREATE INDEX IF NOT EXISTS idx_lessons_created  ON lessons(created_at);

-- Full-text search virtual table
CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    goal,
    approach,
    outcome,
    lesson,
    content='lessons',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON lessons BEGIN
    INSERT INTO lessons_fts(rowid, goal, approach, outcome, lesson)
    VALUES (new.id, new.goal, new.approach, new.outcome, new.lesson);
END;

CREATE TRIGGER IF NOT EXISTS lessons_ad AFTER DELETE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, goal, approach, outcome, lesson)
    VALUES ('delete', old.id, old.goal, old.approach, old.outcome, old.lesson);
END;

CREATE TRIGGER IF NOT EXISTS lessons_au AFTER UPDATE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, goal, approach, outcome, lesson)
    VALUES ('delete', old.id, old.goal, old.approach, old.outcome, old.lesson);
    INSERT INTO lessons_fts(rowid, goal, approach, outcome, lesson)
    VALUES (new.id, new.goal, new.approach, new.outcome, new.lesson);
END;
"""


# ── The engine ──────────────────────────────────────────────────────────


class LearningEngine:
    """SQLite-backed persistent memory for agent experiences and lessons.

    Stores every task run so the agent can recall what worked (and what
    didn't) in similar future situations.  Uses FTS5 for full-text search
    and keyword tagging for lightweight similarity matching.

    Thread-safe: each operation opens/closes its own connection so the
    engine can be used across threads without a shared connection object.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else (
            Path.cwd() / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── connection helpers ───────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Open a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes on first use."""
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    # ── CRUD ─────────────────────────────────────────────────────────

    def record(
        self,
        *,
        task_type: str = "",
        goal: str = "",
        approach: str = "",
        tools_used: list[str] | None = None,
        outcome: str = "",
        success: bool = True,
        lesson: str = "",
        session_id: str = "",
        tags: list[str] | None = None,
        ttl_days: int | None = None,
    ) -> dict[str, Any]:
        """Record a completed task and persist it.  Returns the stored row.

        Parameters
        ----------
        task_type:
            Category of task (e.g. ``"planner"``, ``"generator"``, ``"fixer"``).
        goal:
            The user's objective or the sub-goal that was attempted.
        approach:
            What the agent did (plan, code approach, fix strategy).
        tools_used:
            Tool names involved in the task.
        outcome:
            Free-text description of what happened.
        success:
            Whether the task succeeded.
        lesson:
            The key takeaway — what should be done differently next time.
        session_id:
            The pipeline run or agent session this belongs to.
        tags:
            Explicit keyword tags for filtering (auto-extracted from goal
            + approach + lesson if omitted).
        ttl_days:
            If set, the entry expires after this many days (prune target).
        """
        tools_json = json.dumps(tools_used or [])
        kw = tags or _keywords(goal + " " + approach + " " + lesson)
        tags_json = json.dumps(kw)
        now = time.time()
        expires = (now + ttl_days * 86400) if ttl_days else None

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO lessons
                   (task_type, goal, approach, tools_used, outcome,
                    success, lesson, session_id, tags, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_type,
                    goal,
                    approach,
                    tools_json,
                    outcome,
                    1 if success else 0,
                    lesson,
                    session_id,
                    tags_json,
                    now,
                    expires,
                ),
            )
            row_id = cur.lastrowid
            conn.commit()

        log.info(
            "learning: recorded lesson %d (success=%s, type=%r)",
            row_id,
            success,
            task_type,
        )
        return self.get(row_id)  # type: ignore[return-value]

    def get(self, lesson_id: int) -> dict[str, Any] | None:
        """Return a single lesson by its id, or ``None``."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM lessons WHERE id = ?", (lesson_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        task_type: str | None = None,
        success: bool | None = None,
        sort_by: str = "created_at",
        sort_order: str = "DESC",
    ) -> list[dict[str, Any]]:
        """List lessons with optional filtering and pagination."""
        allowed_sort = {"created_at", "id", "task_type", "success"}
        if sort_by not in allowed_sort:
            sort_by = "created_at"
        if sort_order.upper() not in ("ASC", "DESC"):
            sort_order = "DESC"

        where = []
        params: list[Any] = []
        if task_type is not None:
            where.append("task_type = ?")
            params.append(task_type)
        if success is not None:
            where.append("success = ?")
            params.append(1 if success else 0)

        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (
            f"SELECT * FROM lessons {clause} "
            f"ORDER BY {sort_by} {sort_order} "
            f"LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Full-text search across goals, approaches, outcomes and lessons.

        Returns rows ranked by FTS5 relevance.  Each row includes a
        ``_score`` key (0.0 – 1.0).
        """
        if not query.strip():
            return []

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT l.*, rank AS _score
                   FROM lessons_fts
                   JOIN lessons l ON l.id = lessons_fts.rowid
                   WHERE lessons_fts MATCH ?
                   ORDER BY rank DESC
                   LIMIT ?""",
                (query, limit),
            ).fetchall()

        results = []
        for r in rows:
            d = self._row_to_dict(r)
            raw_score = r["_score"] if "_score" in r.keys() else 0.0
            # FTS5 bm25 rank: negative = more relevant, clamp to 0..1
            d["_score"] = max(0.0, min(1.0, -raw_score / 10.0))
            if d["_score"] >= min_score:
                results.append(d)
        return results

    def search_by_keywords(
        self,
        text: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Jaccard keyword overlap search (fallback when FTS is unavailable).

        Used as a lightweight alternative that doesn't require the FTS
        virtual table.  Good for short query strings like a goal.
        """
        if not text.strip():
            return []
        query_kw = set(_keywords(text))
        if not query_kw:
            return []

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lessons ORDER BY created_at DESC"
            ).fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            d = self._row_to_dict(r)
            entry_kw = set(d.get("tags", []))
            inter = len(query_kw & entry_kw)
            union = len(query_kw | entry_kw)
            score = inter / union if union else 0.0
            if score > 0:
                scored.append((score, d))

        scored.sort(key=lambda t: (-t[0], -t[1].get("id", 0)))
        return [d for _, d in scored[:limit]]

    # ── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the learning store."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            successes = conn.execute(
                "SELECT COUNT(*) FROM lessons WHERE success = 1"
            ).fetchone()[0]
            task_types = conn.execute(
                """SELECT task_type, COUNT(*) as cnt, SUM(success) as ok
                   FROM lessons GROUP BY task_type ORDER BY cnt DESC"""
            ).fetchall()

            # Recent activity (last 7 days)
            week_ago = time.time() - 7 * 86400
            recent = conn.execute(
                "SELECT COUNT(*) FROM lessons WHERE created_at >= ?",
                (week_ago,),
            ).fetchone()[0]

            # Expired / prunable
            now = time.time()
            expired = conn.execute(
                "SELECT COUNT(*) FROM lessons WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            ).fetchone()[0]

        return {
            "total": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": round(successes / total, 3) if total else 0.0,
            "task_types": {
                r["task_type"] or "(none)": {
                    "count": r["cnt"],
                    "successes": r["ok"],
                }
                for r in task_types
            },
            "recent_7d": recent,
            "expired": expired,
        }

    # ── Maintenance ──────────────────────────────────────────────────

    def prune(self, older_than_days: int = 90) -> int:
        """Remove lessons older than *older_than_days*.

        Also removes any lessons where ``expires_at`` is in the past.
        Returns the number of rows deleted.
        """
        cutoff = time.time() - older_than_days * 86400
        with self._conn() as conn:
            # Remove expired entries
            cur = conn.execute(
                "DELETE FROM lessons WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (time.time(),),
            )
            expired = cur.rowcount
            # Remove old entries
            cur = conn.execute(
                "DELETE FROM lessons WHERE created_at < ?", (cutoff,)
            )
            old = cur.rowcount
            conn.commit()
        deleted = expired + old
        if deleted:
            log.info("learning: pruned %d lesson(s)", deleted)
        return deleted

    def rebuild_fts(self) -> None:
        """Rebuild the FTS index (useful after bulk import/delete)."""
        with self._conn() as conn:
            conn.execute("INSERT INTO lessons_fts(lessons_fts) VALUES('rebuild')")
            conn.commit()

    def clear(self) -> int:
        """Delete all lessons.  Returns count of removed rows."""
        with self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            conn.execute("DELETE FROM lessons")
            conn.execute("INSERT INTO lessons_fts(lessons_fts) VALUES('rebuild')")
            conn.commit()
        log.info("learning: cleared %d lesson(s)", count)
        return count

    # ── Prompt injection ─────────────────────────────────────────────

    def format_for_prompt(
        self,
        goal: str,
        k: int = 3,
    ) -> str:
        """Compact multi-line block of past lessons for an LLM prompt.

        Uses FTS5 search (falling back to keyword overlap) to find the
        most relevant past experiences.  Only entries with non-empty
        lessons or notable outcomes are included.

        Returns ``"RELEVANT PAST EXPERIENCE: (none)"`` when nothing is
        found.
        """
        results = self.search(goal, limit=k)
        if not results:
            results = self.search_by_keywords(goal, limit=k)
        if not results:
            return "RELEVANT PAST EXPERIENCE: (none)"

        lines: list[str] = []
        for entry in results:
            if not entry.get("lesson") and not entry.get("outcome"):
                continue
            status = "OK" if entry.get("success") else "FAIL"
            goal_text = entry.get("goal", "") or ""
            if len(goal_text) > 72:
                goal_text = goal_text[:69] + "..."
            takeaway = entry.get("lesson") or entry.get("outcome", "") or ""
            type_tag = entry.get("task_type", "")
            type_prefix = f"[{type_tag}] " if type_tag else ""
            lines.append(f"  - [{status}] {type_prefix}{goal_text}")
            if takeaway:
                # Truncate long lessons
                if len(takeaway) > 200:
                    takeaway = takeaway[:197] + "..."
                lines.append(f"    lesson: {takeaway}")

        if not lines:
            return "RELEVANT PAST EXPERIENCE: (none)"

        return "RELEVANT PAST EXPERIENCE:\n" + "\n".join(lines)

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a ``sqlite3.Row`` to a plain dict with parsed JSON fields."""
        d: dict[str, Any] = dict(row)
        # Convert SQLite integer to Python bool
        if "success" in d:
            d["success"] = bool(d["success"])
        # Parse JSON fields
        for key in ("tools_used", "tags"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = [] if key == "tools_used" else []
        # Convert timestamps to ISO datetime strings for display
        if "created_at" in d and isinstance(d["created_at"], (int, float)):
            d["created_at_iso"] = datetime.fromtimestamp(
                d["created_at"], tz=timezone.utc
            ).isoformat()
        if "expires_at" in d and isinstance(d["expires_at"], (int, float)):
            d["expires_at_iso"] = datetime.fromtimestamp(
                d["expires_at"], tz=timezone.utc
            ).isoformat()
        return d


# ── Singleton factory ──────────────────────────────────────────────────

_INSTANCE: LearningEngine | None = None


def get_learning(db_path: str | Path | None = None) -> LearningEngine:
    """Lazy, process-wide singleton ``LearningEngine``.

    First call without *db_path* creates the default store at
    ``.virgo_memory/learning.db``.  Subsequent calls return the same
    instance unless ``db_path`` is explicitly provided (which replaces
    the cached instance).
    """
    global _INSTANCE
    if db_path is not None:
        _INSTANCE = LearningEngine(db_path)
    elif _INSTANCE is None:
        _INSTANCE = LearningEngine()
    return _INSTANCE

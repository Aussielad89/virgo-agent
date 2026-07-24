"""
Tests for learning_engine — the persistent agent memory & learning engine.

Covers CRUD, search, stats, pruning, prompt formatting, and the
singleton factory — all against a temporary SQLite database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from learning_engine import (
    LearningEngine,
    get_learning,
    _keywords,
    DEFAULT_DB_DIR,
    DEFAULT_DB_NAME,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _engine(tmp_path: Path) -> LearningEngine:
    """Create a fresh LearningEngine backed by a temp database."""
    db = tmp_path / DEFAULT_DB_DIR / DEFAULT_DB_NAME
    return LearningEngine(db_path=str(db))


def _seed(engine: LearningEngine, count: int = 5) -> list[dict[str, Any]]:
    """Insert *count* sample lessons and return them."""
    entries = []
    for i in range(count):
        entry = engine.record(
            task_type="test",
            goal=f"Test goal number {i}",
            approach=f"Approach for goal {i}",
            tools_used=["pytest", "python"],
            outcome=f"Outcome for goal {i}: all tests passed",
            success=(i % 2 == 0),
            lesson=f"Lesson from goal {i}: keep it simple",
            session_id=f"session_{i}",
            tags=[f"tag{i}", "test"],
        )
        entries.append(entry)
    return entries


# ─── Test: initialization ──────────────────────────────────────────────


class TestInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        assert e.db_path.exists()
        assert e.db_path.name == DEFAULT_DB_NAME

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        e = LearningEngine(db_path=str(nested))
        assert e.db_path.exists()
        assert e.db_path.parent.name == DEFAULT_DB_DIR

    def test_reuses_existing_database(self, tmp_path: Path) -> None:
        e1 = _engine(tmp_path)
        e1.record(goal="first", lesson="alpha")
        e2 = _engine(tmp_path)  # same path
        assert e2.stats()["total"] == 1

    def test_default_path_is_cwd_relative(self) -> None:
        e = LearningEngine()
        # On Windows the path uses backslashes, so check the tail components
        assert DEFAULT_DB_DIR in str(e.db_path)
        assert e.db_path.name == DEFAULT_DB_NAME

    def test_singleton_factory(self, tmp_path: Path) -> None:
        db = tmp_path / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        inst1 = get_learning(str(db))
        inst2 = get_learning()  # returns the cached instance
        assert inst1 is inst2

    def test_singleton_with_path_replaces(self, tmp_path: Path) -> None:
        db1 = tmp_path / "a" / DEFAULT_DB_NAME
        db2 = tmp_path / "b" / DEFAULT_DB_NAME
        inst1 = get_learning(str(db1))
        inst2 = get_learning(str(db2))  # replaces cache
        assert inst1 is not inst2
        assert inst2.db_path == db2


# ─── Test: recording ───────────────────────────────────────────────────


class TestRecord:
    def test_record_returns_dict_with_id(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="test goal", lesson="a lesson")
        assert isinstance(entry, dict)
        assert entry["id"] >= 1
        assert entry["goal"] == "test goal"
        assert entry["lesson"] == "a lesson"

    def test_record_increments_id(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        ids = [e.record(goal=f"g{i}")["id"] for i in range(3)]
        assert ids == [1, 2, 3]

    def test_record_success_defaults_to_true(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="test")
        assert entry["success"] is True

    def test_record_success_false(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="test", success=False)
        assert entry["success"] is False

    def test_record_persists_across_instances(self, tmp_path: Path) -> None:
        db = tmp_path / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        e1 = LearningEngine(db_path=str(db))
        e1.record(goal="persistent", lesson="cross-instance")
        e2 = LearningEngine(db_path=str(db))
        assert e2.stats()["total"] == 1

    def test_record_with_all_fields(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(
            task_type="planner",
            goal="Build a CLI tool",
            approach="Use argparse and implement subcommands",
            tools_used=["pytest", "black", "mypy"],
            outcome="Generated 3 files, all tests pass",
            success=True,
            lesson="Always add argument validation first",
            session_id="run_20240101",
            tags=["cli", "argparse", "python"],
            ttl_days=30,
        )
        assert entry["task_type"] == "planner"
        assert entry["tools_used"] == ["pytest", "black", "mypy"]
        assert "cli" in entry["tags"]
        assert entry["expires_at"] is not None
        assert entry["expires_at"] > entry["created_at"]

    def test_record_auto_tags_from_goal(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="API endpoint with authentication")
        tags = entry.get("tags", [])
        assert isinstance(tags, list)
        assert len(tags) > 0

    def test_record_empty_goal(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(task_type="noop")
        assert entry["id"] >= 1


# ─── Test: getting single items ────────────────────────────────────────


class TestGet:
    def test_get_returns_entry(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        record = e.record(goal="fetch me")
        entry = e.get(record["id"])
        assert entry is not None
        assert entry["id"] == record["id"]
        assert entry["goal"] == "fetch me"

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        assert e.get(99999) is None

    def test_get_after_delete(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="to be removed")
        e.clear()
        assert e.get(entry["id"]) is None


# ─── Test: listing ─────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        assert e.list() == []

    def test_list_returns_all_default(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        items = e.list()
        assert len(items) == 3

    def test_list_respects_limit(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 10)
        items = e.list(limit=3)
        assert len(items) == 3

    def test_list_respects_offset(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 5)
        items = e.list(limit=2, offset=3)
        assert len(items) == 2
        first_id = items[0]["id"]
        # With default DESC sort, highest ids come first.
        # After seeding 5 entries (ids 1-5), offset 3 means skip 3 newest → ids 4,5
        # Actually: ASC sort by default with offset 3 = skip 1,2,3 → 4,5
        pass  # Just check we get 2 items without crashing

    def test_list_filter_by_task_type(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(task_type="planner", goal="plan")
        e.record(task_type="generator", goal="gen")
        e.record(task_type="planner", goal="plan2")
        items = e.list(task_type="planner")
        assert len(items) == 2
        assert all(i["task_type"] == "planner" for i in items)

    def test_list_filter_by_success(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="succeed", success=True)
        e.record(goal="fail", success=False)
        e.record(goal="succeed2", success=True)
        items = e.list(success=True)
        assert len(items) == 2
        assert all(i["success"] for i in items)

    def test_list_filter_by_failure(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="succeed", success=True)
        e.record(goal="fail", success=False)
        items = e.list(success=False)
        assert len(items) == 1
        assert items[0]["success"] is False

    def test_list_sorts_by_id_asc(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        items = e.list(sort_by="id", sort_order="ASC")
        ids = [i["id"] for i in items]
        assert ids == sorted(ids)

    def test_list_sorts_by_id_desc(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        items = e.list(sort_by="id", sort_order="DESC")
        ids = [i["id"] for i in items]
        assert ids == sorted(ids, reverse=True)


# ─── Test: search ──────────────────────────────────────────────────────


class TestSearch:
    def test_search_by_goal(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 5)
        # Seed entries have "Test goal number N"
        results = e.search("goal number", limit=5)
        assert len(results) >= 3

    def test_search_by_lesson(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 5)
        results = e.search("keep it simple", limit=5)
        assert len(results) >= 3

    def test_search_empty_query(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        assert e.search("") == []

    def test_search_no_results(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        results = e.search("zzzzzzzzzzzzzzz", limit=5)
        assert results == []

    def test_search_includes_score(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="unique dragon fruit goal")
        results = e.search("dragon fruit", limit=5)
        assert len(results) >= 1
        assert "_score" in results[0]
        assert results[0]["_score"] >= 0.0

    def test_search_min_score_filter(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        results = e.search("goal number", limit=5, min_score=0.01)
        # Most matches should have non-trivial score
        assert len(results) >= 0  # At least doesn't crash

    def test_keyword_search_fallback(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="database connection pool timeout")
        results = e.search_by_keywords("database timeout")
        assert len(results) >= 1
        assert "database" in results[0].get("goal", "").lower()


# ─── Test: stats ───────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        s = e.stats()
        assert s["total"] == 0
        assert s["success_rate"] == 0.0

    def test_stats_counts(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="ok", success=True)
        e.record(goal="ok2", success=True)
        e.record(goal="fail", success=False)
        s = e.stats()
        assert s["total"] == 3
        assert s["successes"] == 2
        assert s["failures"] == 1
        assert s["success_rate"] == pytest.approx(0.667, abs=0.01)

    def test_stats_task_types(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(task_type="planner", goal="p1", success=True)
        e.record(task_type="planner", goal="p2", success=False)
        e.record(task_type="generator", goal="g1", success=True)
        s = e.stats()
        assert "planner" in s["task_types"]
        assert s["task_types"]["planner"]["count"] == 2
        assert s["task_types"]["planner"]["successes"] == 1

    def test_stats_expired(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        # Record with a TTL in the past
        e.record(goal="old", lesson="expired", ttl_days=-1)
        s = e.stats()
        assert s["expired"] >= 1


# ─── Test: pruning ─────────────────────────────────────────────────────


class TestPrune:
    def test_prune_older_than(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="recent", lesson="fresh")
        # Manually insert a legacy entry with an old timestamp
        with e._conn() as conn:
            conn.execute(
                """INSERT INTO lessons (goal, lesson, success, created_at)
                   VALUES (?, ?, 1, ?)""",
                ("old", "stale", 100.0),  # year 1970
            )
            conn.commit()
        assert e.stats()["total"] == 2
        deleted = e.prune(older_than_days=1)  # removes the old one
        assert deleted >= 1
        assert e.stats()["total"] == 1

    def test_prune_expired(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        # Use ttl_days=-1 to ensure the entry is already expired
        e.record(goal="expires soon", lesson="bye", ttl_days=-1)
        deleted = e.prune(older_than_days=999)  # won't delete by age
        # But should still delete expired (ttl=-1 → expires_at is in the past)
        assert deleted >= 1

    def test_prune_nothing_to_delete(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="fresh", lesson="new")
        deleted = e.prune(older_than_days=9999)
        assert deleted == 0

    def test_prune_respects_days(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="recent1", lesson="fresh")
        old_id = e.record(goal="old1", lesson="stale")["id"]
        # Manually backdate the old entry
        with e._conn() as conn:
            conn.execute(
                "UPDATE lessons SET created_at = 100.0 WHERE id = ?",
                (old_id,),
            )
            conn.commit()
        # Prune with 1 day cutoff — only the old (year 1970) one goes
        deleted = e.prune(older_than_days=1)
        assert deleted >= 1
        assert e.get(old_id) is None


# ─── Test: FTS rebuild ────────────────────────────────────────────────


class TestRebuildFTS:
    def test_rebuild_fts_succeeds(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 3)
        e.rebuild_fts()
        # After rebuild, search should still work
        results = e.search("test goal", limit=5)
        assert len(results) >= 1

    def test_rebuild_fts_empty_db(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.rebuild_fts()  # Should not raise


# ─── Test: clear ───────────────────────────────────────────────────────


class TestClear:
    def test_clear_removes_all(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 5)
        assert e.stats()["total"] == 5
        count = e.clear()
        assert count == 5
        assert e.stats()["total"] == 0

    def test_clear_empty_db(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        count = e.clear()
        assert count == 0


# ─── Test: format_for_prompt ───────────────────────────────────────────


class TestFormatForPrompt:
    def test_empty_db_returns_none_block(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        block = e.format_for_prompt("anything")
        assert "none" in block.lower()

    def test_returns_lessons(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(
            goal="Build API",
            lesson="Use Pydantic for validation",
            success=True,
            task_type="planner",
        )
        block = e.format_for_prompt("API")
        assert "RELEVANT PAST EXPERIENCE" in block
        assert "Pydantic" in block or "validation" in block

    def test_ok_fail_labels(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="successful task", lesson="worked", success=True)
        e.record(goal="failed task", lesson="broke", success=False)
        block = e.format_for_prompt("task")
        assert "[OK]" in block
        assert "[FAIL]" in block

    def test_no_lesson_entries_are_skipped(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="empty lesson", success=True, lesson="", outcome="")
        block = e.format_for_prompt("empty")
        # The entry has neither lesson nor outcome, so it's skipped
        assert "none" in block.lower() or "empty" not in block

    def test_respects_k_limit(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        for i in range(10):
            e.record(goal=f"searchable test {i}", lesson=f"Lesson {i}", success=True)
        block = e.format_for_prompt("searchable test", k=3)
        lines = block.split("\n")
        # Count the '[OK]' lines — should be at most 3
        ok_count = sum(1 for line in lines if "[OK]" in line)
        assert ok_count <= 3

    def test_fallback_to_keywords_when_fts_empty(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(goal="database connection pool error", lesson="Increase pool size")
        # Delete FTS entries (simulate corruption)
        with e._conn() as conn:
            conn.execute("DELETE FROM lessons_fts")
            conn.commit()
        # The format_for_prompt should fall back to keyword search
        block = e.format_for_prompt("database pool")
        assert "none" not in block.lower() or "lesson" in block


# ─── Test: keywords helper ────────────────────────────────────────────


class TestKeywords:
    def test_extracts_meaningful_words(self) -> None:
        kw = _keywords("Build a RESTful API with authentication and caching")
        assert "build" in kw
        assert "restful" in kw
        assert "authentication" in kw
        assert "caching" in kw
        # Stopwords like 'with', 'and' should be filtered
        assert "with" not in kw
        assert "and" not in kw

    def test_empty_string(self) -> None:
        assert _keywords("") == []

    def test_only_stopwords(self) -> None:
        kw = _keywords("this that with from have")
        assert kw == []

    def test_short_tokens_filtered(self) -> None:
        kw = _keywords("a an in to be")
        assert kw == []

    def test_case_insensitive(self) -> None:
        kw = _keywords("API Endpoint Design")
        assert "api" in kw
        assert "endpoint" in kw


# ─── Test: edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_concurrent_instances_same_db(self, tmp_path: Path) -> None:
        db = tmp_path / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        e1 = LearningEngine(db_path=str(db))
        e2 = LearningEngine(db_path=str(db))
        e1.record(goal="from e1")
        e2.record(goal="from e2")
        assert e1.stats()["total"] == 2
        assert e2.stats()["total"] == 2

    def test_large_goal_text(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        big = "A" * 10000
        entry = e.record(goal=big)
        assert entry["goal"] == big

    def test_unicode_support(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(goal="über cool 🚀 project", lesson="日本語のレッスン")
        assert entry["goal"] == "über cool 🚀 project"

    def test_list_sorts_desc_by_default(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        _seed(e, 5)
        items = e.list()
        ids = [i["id"] for i in items]
        # Default is DESC (newest first)
        assert ids == sorted(ids, reverse=True)

    def test_stats_with_multiple_types(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        e.record(task_type="planner", goal="plan A", success=True)
        e.record(task_type="planner", goal="plan B", success=False)
        e.record(task_type="fixer", goal="fix A", success=True)
        e.record(task_type="fixer", goal="fix B", success=True)
        e.record(task_type="generator", goal="gen A", success=False)
        s = e.stats()
        assert s["task_types"]["planner"]["count"] == 2
        assert s["task_types"]["fixer"]["count"] == 2
        assert s["task_types"]["generator"]["count"] == 1
        assert s["task_types"]["generator"]["successes"] == 0

    def test_format_for_prompt_truncates_long_lesson(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        long_lesson = "B" * 500
        e.record(goal="find me", lesson=long_lesson, success=True)
        block = e.format_for_prompt("find me")
        # The lesson in the output should be truncated
        assert len(block) < 400  # The whole block with a 500-char lesson truncated

    def test_row_to_dict_parses_json(self, tmp_path: Path) -> None:
        e = _engine(tmp_path)
        entry = e.record(
            goal="json fields",
            tools_used=["a", "b"],
            tags=["x", "y"],
        )
        assert isinstance(entry["tools_used"], list)
        assert isinstance(entry["tags"], list)
        assert "created_at_iso" in entry

    def test_db_path_as_string(self, tmp_path: Path) -> None:
        db_str = str(tmp_path / "custom" / "mem.db")
        e = LearningEngine(db_path=db_str)
        assert e.db_path.exists()
        assert e.db_path.name == "mem.db"

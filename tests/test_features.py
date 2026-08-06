"""Tests for the three new feature modules: diffusal, debate, selfheal."""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════════
# virgo_diffusal tests
# ═══════════════════════════════════════════════════════════════════════


class TestDiffusalEngine:
    """Tests for DiffusalEngine — live code diff emission."""

    def test_import(self):
        from virgo_diffusal import DiffusalEngine
        assert DiffusalEngine is not None

    def test_emit_returns_event(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        event = engine.emit("foo.py", "old\n", "old\nnew\n", 1, "assert fail")
        assert event.file == "foo.py"
        assert event.iteration == 1
        assert event.error_msg == "assert fail"

    def test_diff_counts(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        event = engine.emit("bar.py", "a\nb\nc\n", "a\nx\nc\nd\n", 1, "")
        assert event.added >= 1
        assert event.removed >= 1

    def test_history_tracks_all(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        engine.emit("a.py", "x", "y", 1, "")
        engine.emit("b.py", "p", "q", 1, "")
        assert len(engine.events) == 2

    def test_format_last_shows_diff(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        engine.emit("test.py", "old\n", "new\n", 1, "")
        text = engine.format_last()
        assert "test.py" in text or "+new" in text or "-old" in text

    def test_clear_resets(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        engine.emit("a.py", "x", "y", 1, "")
        engine.clear()
        assert len(engine.events) == 0

    def test_format_last_no_emit(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        result = engine.format_last()
        assert result == "" or "no diff" in result.lower()

    def test_on_diff_callback(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        received = []
        engine.on_diff = lambda e: received.append(e)
        engine.emit("cb.py", "a", "b", 1, "")
        assert len(received) == 1
        assert received[0].file == "cb.py"

    def test_format_event(self):
        from virgo_diffusal import DiffusalEngine
        engine = DiffusalEngine()
        event = engine.emit("fmt.py", "line1\n", "line1\nline2\n", 1, "")
        text = engine.format_event(event)
        assert "fmt.py" in text
        assert "line2" in text


# ═══════════════════════════════════════════════════════════════════════
# virgo_debate tests
# ═══════════════════════════════════════════════════════════════════════


class TestDebateEngine:
    """Tests for DebateEngine — agent-to-agent argumentation."""

    def test_import(self):
        from virgo_debate import DebateEngine
        assert DebateEngine is not None

    def test_debate_result_structure(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("build a web scraper")
        assert result.goal == "build a web scraper"
        assert result.winner in ("performer", "critic")
        assert result.winner_approach

    def test_debate_rounds_have_agents(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("parse CSV files")
        agents = {r.agent for r in result.rounds}
        assert "performer" in agents
        assert "critic" in agents

    def test_debate_auto_judge(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("build an API")
        assert result.auto_picked is True

    def test_format_round(self):
        from virgo_debate import DebateEngine, DebateRound
        r = DebateRound(agent="performer", role="Performer", approach="fast", argument="use cache", round_num=1)
        text = DebateEngine.format_round(r)
        assert "PERFORMER" in text
        assert "fast" in text

    def test_debate_returns_duration(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("test timing")
        assert result.duration >= 0

    def test_debate_with_context(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("fix bug", context="error: TypeError on line 42")
        assert result.goal == "fix bug"

    def test_debate_result_summary(self):
        from virgo_debate import DebateEngine
        engine = DebateEngine(llm_client=None, auto_judge=True)
        result = engine.debate("test summary")
        summary = result.summary
        assert result.winner.upper() in summary
        assert "Approach" in summary


# ═══════════════════════════════════════════════════════════════════════
# virgo_selfheal tests
# ═══════════════════════════════════════════════════════════════════════


class TestSelfHealEngine:
    """Tests for SelfHealEngine — web research after repeated failures."""

    def test_import(self):
        from virgo_selfheal import SelfHealEngine
        assert SelfHealEngine is not None

    def test_record_failure_tracking(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=3)
        assert engine.record_failure("a.py") == 1
        assert engine.record_failure("a.py") == 2
        assert engine.record_failure("a.py") == 3

    def test_should_heal_threshold(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=3)
        engine.record_failure("a.py")
        engine.record_failure("a.py")
        assert not engine.should_heal("a.py")  # 2 < 3
        engine.record_failure("a.py")
        assert engine.should_heal("a.py")  # 3 >= 3

    def test_record_success_resets(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=3)
        engine.record_failure("a.py")
        engine.record_failure("a.py")
        engine.record_success("a.py")
        assert not engine.should_heal("a.py")

    def test_independent_files(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=3)
        engine.record_failure("a.py")
        engine.record_failure("a.py")
        engine.record_failure("a.py")
        assert engine.should_heal("a.py")
        assert not engine.should_heal("b.py")

    def test_heal_returns_result(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=1)
        engine.record_failure("a.py")
        result = engine.heal("a.py", "NameError: undefined", 1, "print(x)")
        assert result.file == "a.py"
        assert result.total_duration >= 0

    def test_heal_history(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=1)
        engine.record_failure("a.py")
        engine.heal("a.py", "error", 1, "code")
        engine.record_failure("b.py")
        engine.heal("b.py", "error", 1, "code")
        stats = engine.get_stats()
        assert stats["total_attempts"] >= 2

    def test_heal_research_captured(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=1)
        engine.record_failure("a.py")
        result = engine.heal("a.py", "ImportError: missing", 1, "import foo")
        assert result.total_research >= 0  # may or may not find results

    def test_get_stats(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=3)
        engine.record_failure("a.py")
        engine.record_failure("a.py")
        stats = engine.get_stats()
        assert stats["total_attempts"] >= 0
        assert "recovered" in stats
        assert "success_rate" in stats

    def test_heal_result_summary(self):
        from virgo_selfheal import SelfHealEngine
        engine = SelfHealEngine(failure_threshold=1)
        engine.record_failure("a.py")
        result = engine.heal("a.py", "error", 1, "code")
        summary = result.summary
        assert "Self-heal" in summary
        assert "a.py" in summary

"""
Tests for experience.py — ExperienceMemory (add / recall / format_for_prompt / stats).

Focus areas required by the spec:
  - add
  - recall ranking
  - format_for_prompt (empty + populated)
  - stats
  - corrupt-line handling
  - keyword overlap correctness
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from experience import ExperienceMemory, get_memory, _keywords, _overlap


@pytest.fixture
def mem_path(tmp_path: Path) -> Path:
    return tmp_path / "experience.jsonl"


@pytest.fixture
def fresh_memory(mem_path: Path) -> ExperienceMemory:
    return ExperienceMemory(path=str(mem_path))


class TestAdd:
    def test_add_returns_dict(self, fresh_memory: ExperienceMemory) -> None:
        entry = fresh_memory.add(
            goal="parse log file",
            approach="use regex",
            tools_used=["file_sampler", "code_patcher"],
            outcome="done",
            success=True,
            lesson="regex is faster",
        )
        assert isinstance(entry, dict)
        assert entry["success"] is True
        assert entry["lesson"] == "regex is faster"

    def test_add_assigns_incrementing_ids(self, fresh_memory: ExperienceMemory) -> None:
        a = fresh_memory.add("g1", "a1", [], "o1", True)
        b = fresh_memory.add("g2", "a2", [], "o2", False)
        assert a["id"] == 1
        assert b["id"] == 2

    def test_add_includes_required_fields(self, fresh_memory: ExperienceMemory) -> None:
        entry = fresh_memory.add("goal text", "approach text", ["t"], "out", False)
        for key in ("id", "ts", "goal", "approach", "tools_used", "outcome", "success", "lesson", "keywords"):
            assert key in entry, f"missing key {key}"

    def test_add_persists_line(self, fresh_memory: ExperienceMemory, mem_path: Path) -> None:
        fresh_memory.add("persist me", "do it", [], "ok", True)
        lines = mem_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["goal"] == "persist me"

    def test_add_extracts_keywords(self, fresh_memory: ExperienceMemory) -> None:
        entry = fresh_memory.add("deploy database cluster", "use terraform", [], "ok", True, "terraform works")
        kws = set(entry["keywords"])
        assert "deploy" in kws
        assert "database" in kws
        assert "terraform" in kws
        # short tokens / stopwords filtered
        assert "use" not in kws  # length < 4
        assert "the" not in kws if "the" in entry["goal"] + entry["approach"] else True


class TestRecall:
    def test_recall_empty_returns_empty(self, fresh_memory: ExperienceMemory) -> None:
        assert fresh_memory.recall("anything") == []

    def test_recall_ranking_by_overlap(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("deploy database cluster with terraform", "use terraform", [], "ok", True)
        fresh_memory.add("parse the log file quickly", "regex scan", [], "ok", True)
        results = fresh_memory.recall("deploy database cluster using terraform", k=3)
        assert results
        assert "terraform" in results[0]["keywords"]
        assert results[0]["goal"].startswith("deploy")

    def test_recall_respects_k(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("alpha beta gamma delta", "x", [], "ok", True)
        fresh_memory.add("alpha beta gamma epsilon", "x", [], "ok", True)
        fresh_memory.add("alpha beta zeta", "x", [], "ok", True)
        results = fresh_memory.recall("alpha beta", k=2)
        assert len(results) == 2

    def test_recall_no_overlap_returns_empty(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("deploy database cluster", "x", [], "ok", True)
        assert fresh_memory.recall("unrelated completely different words") == []

    def test_recall_recent_wins_tie(self, fresh_memory: ExperienceMemory) -> None:
        # Both entries share equal keywords but differ in recency.
        fresh_memory.add("alpha beta gamma", "older", [], "ok", True)
        fresh_memory.add("alpha beta gamma", "newer", [], "ok", True)
        results = fresh_memory.recall("alpha beta gamma", k=1)
        assert len(results) == 1
        assert results[0]["approach"] == "newer"


class TestFormatForPrompt:
    def test_format_empty(self, fresh_memory: ExperienceMemory) -> None:
        assert fresh_memory.format_for_prompt("anything") == "PAST EXPERIENCE: (none)"

    def test_format_populated_shows_lessons(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("parse logs", "regex", [], "ok", True, lesson="regex is fast")
        block = fresh_memory.format_for_prompt("parse logs with regex")
        assert block.startswith("PAST EXPERIENCE:")
        assert "regex is fast" in block

    def test_format_excludes_irrelevant(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("parse logs", "regex", [], "ok", True, lesson="keep this")
        block = fresh_memory.format_for_prompt("totally unrelated query here")
        assert block == "PAST EXPERIENCE: (none)"

    def test_format_skips_failures_without_lesson(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("broken task", "tried", [], "failed", False)
        block = fresh_memory.format_for_prompt("broken task attempt")
        assert block == "PAST EXPERIENCE: (none)"

    def test_format_includes_failure_with_lesson(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("fragile task", "tried", [], "failed", False, lesson="avoid this path")
        block = fresh_memory.format_for_prompt("fragile task")
        assert "FAIL" in block
        assert "avoid this path" in block


class TestStats:
    def test_stats_empty(self, fresh_memory: ExperienceMemory) -> None:
        assert fresh_memory.stats() == {"count": 0, "successes": 0, "failures": 0, "with_embeddings": 0}

    def test_stats_counts(self, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("g1", "a1", [], "o", True)
        fresh_memory.add("g2", "a2", [], "o", True)
        fresh_memory.add("g3", "a3", [], "o", False)
        assert fresh_memory.stats() == {"count": 3, "successes": 2, "failures": 1, "with_embeddings": 0}


class TestCorruptLines:
    def test_corrupt_lines_skipped(self, mem_path: Path, fresh_memory: ExperienceMemory) -> None:
        # Write some garbage + one valid line, then reload via a new instance.
        good = fresh_memory.add("valid task", "approach", [], "ok", True)
        with mem_path.open("a", encoding="utf-8") as fh:
            fh.write("this is not valid json {{{}\n")
            fh.write("\n")  # blank line ignored
            fh.write("12345\n")  # valid json but not a dict
        reloaded = ExperienceMemory(path=str(mem_path))
        # The corrupt lines are skipped; only the valid entry survives.
        assert reloaded.stats()["count"] == 1
        assert reloaded.recall("valid task")[0]["id"] == good["id"]

    def test_reload_preserves_entries_and_ids(self, mem_path: Path, fresh_memory: ExperienceMemory) -> None:
        fresh_memory.add("first", "a", [], "o", True)
        fresh_memory.add("second", "b", [], "o", False)
        reloaded = ExperienceMemory(path=str(mem_path))
        assert reloaded.stats()["count"] == 2
        assert reloaded.recall("first", k=1)[0]["goal"] == "first"


class TestKeywordsOverlap:
    def test_keywords_filters_short_and_stopwords(self) -> None:
        kws = _keywords("The cat sat on the mat with database")
        assert "database" in kws
        assert "with" not in kws  # stopword
        assert "cat" not in kws  # length < 4
        assert "the" not in kws  # stopword

    def test_overlap_jaccard(self) -> None:
        a = {"alpha", "beta", "gamma"}
        b = {"alpha", "beta", "delta"}
        # intersection 2, union 4 -> 0.5
        assert _overlap(a, b) == pytest.approx(0.5)

    def test_overlap_empty(self) -> None:
        assert _overlap(set(), {"x"}) == 0.0
        assert _overlap({"x"}, set()) == 0.0


class TestGetMemory:
    def test_get_memory_singleton(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Isolate default path so the singleton does not hit real disk state.
        target = tmp_path / "experience.jsonl"
        monkeypatch.setattr("experience.DEFAULT_PATH", str(target))
        monkeypatch.setattr("experience._INSTANCE", None)
        m1 = get_memory()
        m2 = get_memory()
        assert m1 is m2

    def test_get_memory_explicit_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("experience._INSTANCE", None)
        m = get_memory(path=str(tmp_path / "exp.jsonl"))
        assert isinstance(m, ExperienceMemory)
        assert m.path.name == "exp.jsonl"

"""Tests for virgo_achievements — gamification layer with SQLite backend."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from virgo_achievements import (
    BUILTIN_ACHIEVEMENTS,
    HOOK_FOCUS_MODE,
    HOOK_MASCOT_ACTIVATE,
    HOOK_NETWORK_SCAN,
    HOOK_PERSONA_CHANGE,
    HOOK_PIPELINE_COMPLETE,
    HOOK_PIPELINE_ITERATION,
    HOOK_SWARM_RUN,
    AchievementSystem,
    cmd_achievements_list,
    cmd_achievements_recent,
    cmd_achievements_stats,
    get_achievements,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db() -> str:
    """Yield a temporary file path for the achievement DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def system(tmp_db: str) -> AchievementSystem:
    """Return a fresh AchievementSystem backed by a temporary DB."""
    sys = AchievementSystem(db_path=tmp_db)
    for ach in BUILTIN_ACHIEVEMENTS:
        sys.register(ach)
    return sys


# ── Singleton ───────────────────────────────────────────────────────────


class TestGetAchievements:
    def test_singleton_returns_instance(self) -> None:
        """get_achievements() returns an AchievementSystem."""
        inst = get_achievements()
        assert isinstance(inst, AchievementSystem)

    def test_singleton_is_same_object(self) -> None:
        """Repeated calls to get_achievements() return the same object."""
        a = get_achievements()
        b = get_achievements()
        assert a is b

    def test_singleton_has_builtins(self) -> None:
        """Singleton registers all built-in achievements on first init."""
        inst = get_achievements()
        progress = inst.get_all_progress()
        assert len(progress) == len(BUILTIN_ACHIEVEMENTS)


# ── Register / get_all_progress ─────────────────────────────────────────


class TestRegisterAndProgress:
    def test_get_all_progress_shows_all(self, system: AchievementSystem) -> None:
        """get_all_progress() returns an entry for every registered achievement."""
        progress = system.get_all_progress()
        assert len(progress) == len(BUILTIN_ACHIEVEMENTS)

    def test_all_achievements_initially_locked(self, system: AchievementSystem) -> None:
        """All achievements are locked at start."""
        for p in system.get_all_progress():
            assert p["unlocked"] is False, f"{p['id']} should be locked"

    def test_register_custom_achievement(self, system: AchievementSystem) -> None:
        """Registering a custom achievement adds it to the system."""
        custom = {
            "id": "custom_test",
            "name": "Test Achievement",
            "description": "A custom test achievement",
            "icon": "\U0001f4a1",
            "xp": 42,
            "category": "special",
            "condition": {"one_shot": True},
        }
        system.register(custom)
        progress = system.get_all_progress()
        ids = [p["id"] for p in progress]
        assert "custom_test" in ids

    def test_get_progress_returns_details(self, system: AchievementSystem) -> None:
        """get_progress() returns full details for a single achievement."""
        p = system.get_progress("first_run")
        assert p["id"] == "first_run"
        assert p["name"] == "First Pipeline"
        assert p["unlocked"] is False


# ── unlock ──────────────────────────────────────────────────────────────


class TestUnlock:
    def test_unlock_returns_achievement(self, system: AchievementSystem) -> None:
        """First unlock returns the achievement dict."""
        result = system.unlock("first_run")
        assert result is not None
        assert result["id"] == "first_run"
        assert result["name"] == "First Pipeline"

    def test_unlock_twice_returns_none(self, system: AchievementSystem) -> None:
        """Unlocking an already-unlocked achievement returns None."""
        system.unlock("first_run")
        result = system.unlock("first_run")
        assert result is None

    def test_unlock_marks_as_unlocked(self, system: AchievementSystem) -> None:
        """After unlock, get_progress shows unlocked=True."""
        system.unlock("first_run")
        p = system.get_progress("first_run")
        assert p["unlocked"] is True
        assert p["unlocked_at"] is not None

    def test_unlock_unknown_achievement(self, system: AchievementSystem) -> None:
        """Unlocking a non-registered id returns None."""
        result = system.unlock("nonexistent")
        assert result is None


# ── trigger ─────────────────────────────────────────────────────────────


class TestTrigger:
    def test_trigger_works_when_condition_met(self, system: AchievementSystem) -> None:
        """trigger() unlocks when condition is implicitly met (one-shot)."""
        # first_run is one-shot with no field requirement
        result = system.trigger("first_run")
        assert result is not None
        assert result["id"] == "first_run"

    def test_trigger_returns_none_if_owned(self, system: AchievementSystem) -> None:
        """trigger() returns None for already-unlocked achievements."""
        system.unlock("first_run")
        result = system.trigger("first_run")
        assert result is None

    def test_trigger_unknown_achievement(self, system: AchievementSystem) -> None:
        """trigger() on a non-registered id returns None."""
        result = system.trigger("nonexistent")
        assert result is None


# ── get_level ───────────────────────────────────────────────────────────


class TestGetLevel:
    def test_level_1_at_0_xp(self) -> None:
        """0 XP → level 1."""
        assert AchievementSystem.get_level(0) == 1

    def test_level_2_at_50_xp(self) -> None:
        """50 XP → level 2."""
        assert AchievementSystem.get_level(50) == 2

    def test_level_3_at_200_xp(self) -> None:
        """200 XP → level 3."""
        assert AchievementSystem.get_level(200) == 3

    def test_level_4_at_500_xp(self) -> None:
        """500 XP → level 4."""
        assert AchievementSystem.get_level(500) == 4

    def test_level_5_at_800_xp(self) -> None:
        """800 XP → level 5."""
        assert AchievementSystem.get_level(800) == 5

    def test_level_25_at_28800_xp(self) -> None:
        """28800 XP → level 25 (verify high level)."""
        assert AchievementSystem.get_level(28800) == 25


# ── get_stats ───────────────────────────────────────────────────────────


class TestGetStats:
    def test_stats_empty(self, system: AchievementSystem) -> None:
        """Fresh system has zero XP and level 1."""
        stats = system.get_stats()
        assert stats["total_xp"] == 0
        assert stats["unlocked_count"] == 0
        assert stats["level"] == 1
        assert stats["registered_count"] == len(BUILTIN_ACHIEVEMENTS)

    def test_stats_after_unlock(self, system: AchievementSystem) -> None:
        """Unlocking achievements increases XP."""
        system.unlock("first_run")  # 10 XP
        stats = system.get_stats()
        assert stats["total_xp"] == 10
        assert stats["unlocked_count"] == 1
        assert stats["level"] == 1  # still level 1 (need 50 XP)

    def test_stats_with_multiple_unlocks(self, system: AchievementSystem) -> None:
        """Multiple unlocks accumulate XP correctly."""
        system.unlock("first_run")  # 10 XP
        system.unlock("first_scan")  # 10 XP
        system.unlock("persona_try")  # 15 XP
        stats = system.get_stats()
        assert stats["total_xp"] == 35
        assert stats["unlocked_count"] == 3
        assert stats["level"] == 1

    def test_stats_level_up(self, system: AchievementSystem) -> None:
        """Enough XP pushes the level up."""
        # first_run=10, first_scan=10, persona_try=15, first_swarm=25, first_bot=25
        # total = 85 → level 2 (need 50 XP)
        system.unlock("first_run")
        system.unlock("first_scan")
        system.unlock("persona_try")
        system.unlock("first_swarm")
        system.unlock("first_bot")
        stats = system.get_stats()
        assert stats["total_xp"] == 85
        assert stats["level"] == 2

    def test_next_level_xp(self) -> None:
        """get_xp_for_next_level returns correct thresholds."""
        assert AchievementSystem.get_xp_for_next_level(1) == 50
        assert AchievementSystem.get_xp_for_next_level(2) == 200
        assert AchievementSystem.get_xp_for_next_level(3) == 450
        assert AchievementSystem.get_xp_for_next_level(4) == 800
        assert AchievementSystem.get_xp_for_next_level(10) == 5000


# ── hook ────────────────────────────────────────────────────────────────


class TestHook:
    def test_hook_triggers_one_shot(self, system: AchievementSystem) -> None:
        """Calling a hook triggers one-shot achievements."""
        new = system.hook(HOOK_PIPELINE_COMPLETE, total_runs=1)
        assert len(new) == 1
        assert new[0]["id"] == "first_run"

    def test_hook_does_not_repeat(self, system: AchievementSystem) -> None:
        """Second hook call does not re-unlock the same achievement."""
        system.hook(HOOK_PIPELINE_COMPLETE, total_runs=1)
        new = system.hook(HOOK_PIPELINE_COMPLETE, total_runs=2)
        # first_run already unlocked; perfect_run needs first_iteration_pass
        assert len(new) == 0

    def test_hook_count_based(self, system: AchievementSystem) -> None:
        """Count-based achievements unlock when threshold met."""
        new = system.hook(HOOK_FOCUS_MODE, total_uses=5)
        assert len(new) == 1
        assert new[0]["id"] == "focus_mode"

    def test_hook_count_below_threshold(self, system: AchievementSystem) -> None:
        """Count-based achievements do NOT unlock below threshold."""
        new = system.hook(HOOK_FOCUS_MODE, total_uses=3)
        assert len(new) == 0

    def test_hook_multiple_new(self, system: AchievementSystem) -> None:
        """A single hook can trigger multiple achievements at once."""
        new = system.hook(HOOK_PIPELINE_COMPLETE, total_runs=100, first_iteration_pass=1)
        # triggers: first_run (one-shot), pit_master (100 runs), perfect_run (first pass)
        ids = {n["id"] for n in new}
        assert "first_run" in ids
        assert "pit_master" in ids
        assert "perfect_run" in ids

    def test_hook_unrelated_hook_does_nothing(self, system: AchievementSystem) -> None:
        """An unrelated hook does not unlock anything."""
        new = system.hook("unrelated_event")
        assert len(new) == 0


# ── get_recent ──────────────────────────────────────────────────────────


class TestGetRecent:
    def test_recent_empty(self, system: AchievementSystem) -> None:
        """get_recent returns empty list when nothing unlocked."""
        assert system.get_recent() == []

    def test_recent_returns_newest_first(self, system: AchievementSystem) -> None:
        """get_recent orders by newest unlock time first."""
        system.unlock("first_run")  # first
        system.unlock("first_scan")  # second
        system.unlock("first_bot")  # third (most recent)
        recent = system.get_recent(limit=10)
        assert len(recent) == 3
        assert recent[0]["id"] == "first_bot"
        assert recent[1]["id"] == "first_scan"
        assert recent[2]["id"] == "first_run"

    def test_recent_respects_limit(self, system: AchievementSystem) -> None:
        """get_recent(limit=N) returns at most N items."""
        system.unlock("first_run")
        system.unlock("first_scan")
        system.unlock("first_bot")
        recent = system.get_recent(limit=2)
        assert len(recent) == 2


# ── Persistence ─────────────────────────────────────────────────────────


class TestPersistence:
    def test_unlock_survives_reinit(self, tmp_db: str) -> None:
        """Unlocking an achievement persists across AchievementSystem instances."""
        # First instance
        sys1 = AchievementSystem(db_path=tmp_db)
        for ach in BUILTIN_ACHIEVEMENTS:
            sys1.register(ach)
        sys1.unlock("first_run")
        assert sys1.get_progress("first_run")["unlocked"] is True

        # Second instance — same DB file
        sys2 = AchievementSystem(db_path=tmp_db)
        for ach in BUILTIN_ACHIEVEMENTS:
            sys2.register(ach)
        assert sys2.get_progress("first_run")["unlocked"] is True

    def test_empty_db_fresh_start(self, tmp_db: str) -> None:
        """A brand-new DB starts with all achievements locked."""
        sys = AchievementSystem(db_path=tmp_db)
        for ach in BUILTIN_ACHIEVEMENTS:
            sys.register(ach)
        for p in sys.get_all_progress():
            assert p["unlocked"] is False


# ── CLI handlers (smoke) ────────────────────────────────────────────────


class TestCLIHandlers:
    def test_cmd_list_runs(self, system: AchievementSystem, capsys) -> None:
        """cmd_achievements_list prints without error."""
        # Override the global singleton so the CLI uses our system
        # (they call get_achievements() internally; we just test they run)
        cmd_achievements_list(None)
        captured = capsys.readouterr()
        assert "VIRGO ACHIEVEMENTS" in captured.out
        assert "First Pipeline" in captured.out

    def test_cmd_recent_empty(self, capsys) -> None:
        """cmd_achievements_recent shows 'none' when nothing unlocked."""
        cmd_achievements_recent(None)
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_cmd_stats_runs(self, system: AchievementSystem, capsys) -> None:
        """cmd_achievements_stats prints without error."""
        cmd_achievements_stats(None)
        captured = capsys.readouterr()
        assert "ACHIEVEMENT STATS" in captured.out
        assert "Level:" in captured.out

    def test_cmd_list_with_unlocks(self, system: AchievementSystem, capsys) -> None:
        """cmd_achievements_list shows unlocked achievements."""
        system.unlock("first_run")
        cmd_achievements_list(None)
        captured = capsys.readouterr()
        # unlocked achievements appear in the output
        assert "First Pipeline" in captured.out

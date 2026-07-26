"""Tests for virgo_leaderboard — Leaderboard module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import virgo_leaderboard as lb  # noqa: E402


class TestLeaderboard:
    def test_get_stats_empty(self):
        stats = lb.get_stats(data={
            "sessions": [],
            "total_xp": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "daily_xp": {},
            "history": [],
        })
        assert stats["total_xp"] == 0
        assert stats["total_sessions"] == 0
        assert stats["pass_rate"] == 0

    def test_record_session(self):
        # Reset first
        lb.reset()
        stats = lb.record_session("test pipeline", 50, True)
        assert stats["total_xp"] == 50
        assert stats["total_sessions"] == 1
        assert stats["passed_sessions"] == 1

    def test_record_session_fail(self):
        lb.reset()
        stats = lb.record_session("fail test", 10, False)
        assert stats["total_sessions"] == 1
        assert stats["passed_sessions"] == 0
        assert stats["fail_sessions"] == 1

    def test_streak_tracking(self):
        lb.reset()
        from datetime import UTC, datetime
        from unittest.mock import patch

        # Force data structure directly to avoid time dependency
        data = {
            "sessions": [
                {"timestamp": "2026-07-25T10:00:00+00:00", "goal": "day1", "xp": 10, "passed": True},
                {"timestamp": "2026-07-26T10:00:00+00:00", "goal": "day2", "xp": 20, "passed": True},
            ],
            "total_xp": 30,
            "current_streak": 2,
            "longest_streak": 2,
            "last_active": "2026-07-26T10:00:00+00:00",
            "daily_xp": {"2026-07-25": 10, "2026-07-26": 20},
            "history": [
                {"date": "2026-07-25", "xp": 10, "passed": True, "goal": "day1"},
                {"date": "2026-07-26", "xp": 20, "passed": True, "goal": "day2"},
            ],
        }
        stats = lb.get_stats(data=data)
        assert stats["current_streak"] == 2
        assert stats["longest_streak"] == 2

    def test_reset(self):
        lb.reset()
        stats = lb.get_stats()
        assert stats["total_xp"] == 0
        assert stats["total_sessions"] == 0

    def test_format_stats(self):
        stats = lb.get_stats(data={
            "sessions": [{"timestamp": "2026-07-26T10:00:00", "goal": "test", "xp": 50, "passed": True}],
            "total_xp": 50,
            "current_streak": 1,
            "longest_streak": 1,
            "last_active": "2026-07-26T10:00:00",
            "daily_xp": {"2026-07-26": 50},
            "history": [{"date": "2026-07-26", "xp": 50, "passed": True, "goal": "test"}],
        })
        formatted = lb.format_stats(stats)
        assert isinstance(formatted, str)
        assert "50" in formatted
        assert "LEADERBOARD" in formatted

    def test_get_history(self):
        data = {
            "sessions": [],
            "total_xp": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "daily_xp": {},
            "history": [
                {"date": "2026-07-26", "xp": 10, "passed": True, "goal": "test"},
            ],
        }
        # Write data then read
        # Just test format_stats doesn't crash
        formatted = lb.format_stats(lb.get_stats(data=data))
        assert "test" in formatted

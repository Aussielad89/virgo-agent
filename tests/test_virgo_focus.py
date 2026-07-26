"""Tests for virgo_focus — focus mode module."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import virgo_focus as focus  # noqa: E402


class TestFocusBasic:
    """Basic function tests that don't start audio threads."""

    def test_import(self):
        """Module imports without error."""
        assert hasattr(focus, "start")
        assert hasattr(focus, "stop")
        assert hasattr(focus, "status")
        assert hasattr(focus, "list_genres")

    def test_list_genres(self):
        """list_genres returns all 4 built-in genres."""
        genres = focus.list_genres()
        assert len(genres) == 4
        genre_ids = {g["id"] for g in genres}
        assert genre_ids == {"lofi", "synthwave", "ambient", "silence"}
        for g in genres:
            assert "name" in g
            assert "bpm" in g
            assert "description" in g

    def test_status_inactive_by_default(self):
        """status returns inactive before any start."""
        st = focus.status()
        assert st["active"] is False

    def test_list_genres_details(self):
        """Each genre has expected properties."""
        genres = focus.list_genres()
        for g in genres:
            assert g["bpm"] >= 0
            assert isinstance(g["name"], str)
            assert isinstance(g["description"], str)

    def test_start_invalid_genre(self):
        """start() with unknown genre returns error."""
        result = focus.start("nonexistent")
        assert "error" in result

    def test_start_stop_cycle(self):
        """start and stop work correctly."""
        result = focus.start("silence")
        assert result["status"] == "started"
        assert result["genre"] == "silence"

        # Should now be active
        st = focus.status()
        assert st["active"] is True
        assert st["genre"] == "silence"

        # Stop
        result2 = focus.stop()
        assert result2["status"] == "stopped"
        assert result2["elapsed_seconds"] >= 0

        # Should now be inactive
        st2 = focus.status()
        assert st2["active"] is False

    def test_double_stop(self):
        """Stopping when not active returns 'not_active'."""
        focus.stop()  # Ensure stopped
        result = focus.stop()
        assert result["status"] == "not_active"

    def test_restart_changes_genre(self):
        """Starting again with different genre updates it."""
        focus.start("silence")
        focus.stop()

        focus.start("lofi")
        st = focus.status()
        assert st["genre"] == "lofi"
        focus.stop()

    def test_format_status_text(self):
        """format_status_text returns non-empty string."""
        text = focus.format_status_text({"active": False, "total_sessions": 0, "total_minutes": 0})
        assert isinstance(text, str)
        assert len(text) > 0

    def test_format_status_active(self):
        """format_status_text for active state."""
        text = focus.format_status_text({
            "active": True,
            "genre": "lofi",
            "genre_name": "Lo-Fi Beats",
            "elapsed_minutes": 5.0,
            "elapsed_seconds": 300.0,
            "session": 1,
        })
        assert isinstance(text, str)
        assert "Lo-Fi Beats" in text
        assert "5m" in text

    def test_cli_handler_functions_exist(self):
        """All CLI handler functions are defined."""
        assert hasattr(focus, "cmd_focus_on")
        assert hasattr(focus, "cmd_focus_off")
        assert hasattr(focus, "cmd_focus_status")
        assert hasattr(focus, "cmd_focus_genre")

    def test_session_count_increments(self):
        """Each start increments session count."""
        focus.stop()  # reset
        s1 = focus.status()
        before = s1.get("total_sessions", 0)

        focus.start("silence")
        focus.stop()

        s2 = focus.status()
        assert s2["total_sessions"] == before + 1

    def test_genre_has_silent(self):
        """Silent mode exists and has 0 BPM."""
        silent = [g for g in focus.list_genres() if g["id"] == "silence"]
        assert len(silent) == 1
        assert silent[0]["bpm"] == 0

    def test_GENRES_constant_exists(self):
        """GENRES dict has all required keys per genre."""
        for gid, cfg in focus.GENRES.items():
            for key in ("name", "bpm", "description", "frequencies", "duration_ms", "pattern"):
                assert key in cfg, f"Missing key '{key}' in genre '{gid}'"

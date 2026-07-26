"""Tests for virgo_screensaver — Terminal Screensaver module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import virgo_screensaver as ss  # noqa: E402


class TestScreensaver:
    def test_list_modes(self):
        modes = ss.list_modes()
        assert len(modes) >= 3
        mode_ids = {m["id"] for m in modes}
        assert "matrix" in mode_ids
        assert "crawl" in mode_ids
        assert "stats" in mode_ids

    def test_status_default(self):
        st = ss.status()
        assert "active" in st
        assert st["active"] is False
        assert "timeout" in st
        assert st["timeout"] >= 10

    def test_set_timeout(self):
        result = ss.set_timeout(60)
        assert result["timeout"] == 60
        ss.set_timeout(120)

    def test_set_timeout_minimum(self):
        result = ss.set_timeout(1)
        assert result["timeout"] >= 10

    def test_start_unknown(self):
        result = ss.start("unknown")
        assert "error" in result

    def test_start_stop_matrix(self):
        result = ss.start("matrix")
        assert result["status"] == "started"
        assert result["mode"] == "matrix"

        result = ss.stop()
        assert result["status"] == "stopped"

    def test_start_stop_stats(self):
        result = ss.start("stats")
        assert result["status"] == "started"
        ss.stop()

    def test_double_stop_safe(self):
        ss.stop()
        result = ss.stop()
        assert result["status"] == "stopped"

    def test_register_activity(self):
        ss.register_activity()  # Should not crash
        assert True

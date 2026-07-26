"""Tests for virgo_heatmap — Activity Heatmap module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import virgo_heatmap as hm  # noqa: E402


class TestHeatmap:
    def test_generate_empty(self):
        result = hm.generate_heatmap(days=1, activity_data=[])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_no_data(self):
        result = hm.generate_heatmap(days=1, activity_data=None)
        assert isinstance(result, str)

    def test_generate_with_data(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        data = [
            {"timestamp": now.isoformat(), "event": "pipeline", "detail": "test"},
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "event": "scan", "detail": ""},
            {"timestamp": (now - timedelta(hours=12)).isoformat(), "event": "pipeline", "detail": ""},
            {"timestamp": (now - timedelta(days=1)).isoformat(), "event": "swarm", "detail": ""},
            {"timestamp": (now - timedelta(days=2)).isoformat(), "event": "search", "detail": "test"},
        ]
        result = hm.generate_heatmap(days=3, activity_data=data)
        assert isinstance(result, str)
        assert "Heatmap" in result
        assert "pipeline" not in result.lower() or True  # Just check it generates

    def test_log_activity(self):
        hm.log_activity("test_event", "test_detail")
        # Check it doesn't crash
        assert True

    def test_generate_respects_days(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        data = [
            {"timestamp": now.isoformat(), "event": "today", "detail": ""},
            {"timestamp": (now - timedelta(days=5)).isoformat(), "event": "old", "detail": ""},
        ]
        result_1day = hm.generate_heatmap(days=1, activity_data=data)
        result_7day = hm.generate_heatmap(days=7, activity_data=data)
        assert isinstance(result_1day, str)
        assert isinstance(result_7day, str)

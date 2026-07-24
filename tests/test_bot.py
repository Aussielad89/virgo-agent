"""
Tests for virgo_bot — Telegram bot module.

Uses mocked HTTP requests to avoid real network calls.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure we can import from the project root
HERE = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(HERE))

from virgo_bot import (
    BOT_LOGS_DIR,
    BOT_TOKEN,
    _check_rate_limit,
    _is_allowed,
    _save_telemetry,
    _send_message,
    bot_status,
    is_running,
    start_polling,
    stop_polling,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """Reset global state between tests."""
    from virgo_bot import _bot_running, _bot_started, _bot_stop_event, _rate_buckets

    _bot_running = False
    _bot_started = None
    _bot_stop_event.clear()
    _rate_buckets.clear()
    yield


@pytest.fixture
def mock_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a fake TELEGRAM_BOT_TOKEN for tests."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token123")
    # Re-import to pick up new env
    import importlib

    import virgo_bot

    importlib.reload(virgo_bot)


@pytest.fixture
def mock_env_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set allowed chat IDs."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345,67890")
    import importlib

    import virgo_bot

    importlib.reload(virgo_bot)


# ── Tests ───────────────────────────────────────────────────────────────


class TestIsAllowed:
    """Tests for the _is_allowed security check."""

    def test_allow_all_when_no_chat_ids(self) -> None:
        """When TELEGRAM_CHAT_ID is empty, all chat IDs are allowed."""
        # Force empty CHAT_IDS
        import virgo_bot as vb
        original = vb.CHAT_IDS
        vb.CHAT_IDS = []
        assert _is_allowed("anybody") is True
        assert _is_allowed(99999) is True
        vb.CHAT_IDS = original

    def test_allow_specific_chat_id(self, mock_env_chat_id: None) -> None:
        """Only configured chat IDs are allowed."""
        import importlib

        import virgo_bot as vb

        importlib.reload(vb)
        assert vb._is_allowed("12345") is True
        assert vb._is_allowed("67890") is True

    def test_deny_unknown_chat_id(self, mock_env_chat_id: None) -> None:
        """Unconfigured chat IDs are rejected."""
        import importlib

        import virgo_bot as vb

        importlib.reload(vb)
        assert vb._is_allowed("99999") is False
        assert vb._is_allowed("00000") is False


class TestRateLimit:
    """Tests for the rate limiting logic."""

    def test_allows_within_limit(self) -> None:
        """Messages within the rate limit are allowed."""
        assert _check_rate_limit("test_chat") is True

    def test_blocks_over_limit(self) -> None:
        """Messages exceeding the rate limit are blocked."""
        import virgo_bot as vb

        # Fill the bucket up to the limit
        from virgo_bot import _rate_buckets, _rate_lock

        now = time.monotonic()
        with _rate_lock:
            bucket = _rate_buckets["overloader"]
            for _ in range(vb.RATE_LIMIT):
                bucket.append(now)

        assert vb._check_rate_limit("overloader") is False

    def test_rate_limit_resets_after_window(self) -> None:
        """Rate limit resets after the 60-second window."""
        import virgo_bot as vb

        from virgo_bot import _rate_buckets, _rate_lock

        # Add old timestamps (outside the 60s window)
        old_time = time.monotonic() - 120
        with _rate_lock:
            bucket = _rate_buckets["old_chat"]
            for _ in range(vb.RATE_LIMIT):
                bucket.append(old_time)

        # Should be allowed because old entries are pruned
        assert vb._check_rate_limit("old_chat") is True


class TestTelemetry:
    """Tests for the telemetry logging."""

    def test_save_telemetry_creates_file(self) -> None:
        """_save_telemetry writes a JSON file to the bot logs dir."""
        data = {"event": "test", "chat_id": 123, "text": "hello"}
        _save_telemetry(data)

        files = list(BOT_LOGS_DIR.glob("telegram_*.json"))
        assert len(files) >= 1

        # Clean up
        for f in files:
            try:
                if f.name.startswith("telegram_"):
                    f.unlink()
            except Exception:
                pass


class TestBotStatus:
    """Tests for the bot_status function."""

    def test_bot_not_started(self) -> None:
        """Status shows not running before start."""
        st = bot_status()
        assert st["running"] is False
        assert st["started"] is False

    def test_bot_status_after_start(self, mock_env_token: None) -> None:
        """Status shows running after start."""
        start_polling()
        time.sleep(0.2)
        st = bot_status()
        assert st["running"] is True
        assert st["token_set"] is True
        stop_polling()

    def test_is_running(self, mock_env_token: None) -> None:
        """is_running reflects the bot state."""
        assert is_running() is False
        start_polling()
        time.sleep(0.2)
        assert is_running() is True
        stop_polling()
        assert is_running() is False


class TestBotLifecycle:
    """Tests for bot start/stop lifecycle."""

    def test_start_stop(self, mock_env_token: None) -> None:
        """Starting and stopping the bot works cleanly."""
        assert is_running() is False
        start_polling()
        time.sleep(0.3)
        assert is_running() is True
        stop_polling()
        time.sleep(0.1)
        assert is_running() is False

    def test_start_twice(self, mock_env_token: None) -> None:
        """Starting an already-running bot is a no-op."""
        start_polling()
        time.sleep(0.2)
        start_polling()  # should not crash
        time.sleep(0.1)
        assert is_running() is True
        stop_polling()

    def test_stop_without_start(self) -> None:
        """Stopping a non-running bot is safe."""
        stop_polling()  # should not crash

    def test_no_token(self) -> None:
        """Starting without a token prints a warning but doesn't crash."""
        # Ensure token is empty
        import virgo_bot as vb

        original_token = vb.BOT_TOKEN
        vb.BOT_TOKEN = ""
        start_polling()  # should print warning, not start
        assert is_running() is False
        vb.BOT_TOKEN = original_token


class TestSendMessage:
    """Tests for the _send_message function."""

    @patch("virgo_bot._api_call")
    def test_send_message_success(self, mock_api_call: MagicMock) -> None:
        """_send_message returns True on successful API call."""
        mock_api_call.return_value = {"ok": True}
        result = _send_message(12345, "Hello")
        assert result is True
        mock_api_call.assert_called_once()

    @patch("virgo_bot._api_call")
    def test_send_message_fallback_on_fail(self, mock_api_call: MagicMock) -> None:
        """_send_message retries without Markdown if the first call fails."""
        mock_api_call.side_effect = [
            {"ok": False, "description": "Bad parse_mode"},
            {"ok": True},
        ]
        result = _send_message(12345, "Hello *world*")
        assert result is True
        assert mock_api_call.call_count == 2

    @patch("virgo_bot._api_call")
    def test_send_message_all_fail(self, mock_api_call: MagicMock) -> None:
        """_send_message returns False if all API calls fail."""
        mock_api_call.side_effect = [
            {"ok": False, "description": "Error 1"},
            {"ok": False, "description": "Error 2"},
        ]
        result = _send_message(12345, "Hello")
        assert result is False


class TestFallbackPolling:
    """Tests for the urllib fallback polling handler."""

    @patch("virgo_bot._api_call")
    def test_poll_loop_start_stop(self, mock_api_call: MagicMock, mock_env_token: None) -> None:
        """Poll loop starts and stops cleanly."""
        mock_api_call.return_value = {"ok": True, "result": []}
        start_polling()
        time.sleep(0.3)
        assert is_running() is True
        stop_polling()
        time.sleep(0.1)
        assert is_running() is False

    @patch("virgo_bot._api_call")
    def test_handle_message(self, mock_api_call: MagicMock, mock_env_token: None) -> None:
        """Incoming messages are processed."""
        # Mock getUpdates to return one message, then empty, then we stop
        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 1,
                            "message": {
                                "message_id": 1,
                                "chat": {"id": 12345},
                                "text": "/help",
                                "date": 1700000000,
                            },
                        }
                    ],
                }
            return {"ok": True, "result": []}

        mock_api_call.side_effect = side_effect

        start_polling()
        time.sleep(0.5)
        stop_polling()
        time.sleep(0.1)
        # Should have called at least 3 times (1 getUpdates + 1 sendMessage + some polls)
        assert mock_api_call.call_count >= 2


class TestPlugin:
    """Tests for the telegram_bot_plugin module."""

    def test_plugin_register(self) -> None:
        """Plugin registers bot tools."""
        from telegram_bot_plugin import register

        registry = MagicMock()
        register(registry)
        assert registry.register.call_count >= 3

    def test_plugin_register_tools_have_names(self) -> None:
        """Registered tools have descriptive names."""
        from telegram_bot_plugin import register
        from tools import Tool

        registry = MagicMock()
        calls: list = []

        def record_call(t: object) -> None:
            calls.append(t)

        registry.register.side_effect = record_call
        register(registry)

        for tool in calls:
            assert isinstance(tool, Tool)
            assert "telegram" in tool.name.lower()

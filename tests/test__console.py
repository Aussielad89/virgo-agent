"""Tests for _console.py — emoji/ASCII icon helper."""

from __future__ import annotations

from unittest.mock import patch

import _console


def test_icon_known_keys() -> None:
    """Every known icon key returns a non-empty string."""
    keys = [
        "rocket", "error", "file", "warn", "arrow", "brain", "virgo",
        "web", "search", "video", "tool", "fix", "check", "sat", "ok",
        "shield", "refresh", "save", "bolt", "sparkle", "done", "alert",
        "antenna", "goal", "discover", "code", "test", "pass", "fail",
        "info", "syntax",
    ]
    for key in keys:
        val = _console.icon(key)
        assert isinstance(val, str), f"{key} -> {type(val)}"
        assert len(val) > 0, f"{key} returned empty string"


def test_icon_unknown_key() -> None:
    """Unknown key falls back to bracketed name."""
    assert _console.icon("foobar") == "[foobar]"


def test_icon_ascii_fallback() -> None:
    """Fallback produces ASCII-safe tags."""
    with patch.object(_console, "_use_emoji", False):
        assert _console.icon("ok") == "[OK]"
        assert _console.icon("error") == "[ERR]"
        assert _console.icon("rocket") == "[RUN]"
        assert _console.icon("done") == "[DONE]"


def test_icon_emoji_mode() -> None:
    """Emoji is returned when terminal supports it."""
    with patch.object(_console, "_use_emoji", True):
        assert _console.icon("ok") == "\u2705"

"""Tests for virgo_persona.py — persona system for Virgo Agent."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import virgo_persona as vp


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_persona_state() -> None:
    """Remove persona file before each test and reset to default."""
    if vp.PERSONA_FILE.exists():
        vp.PERSONA_FILE.unlink()
    vp._load_persona_state()
    assert vp.current_persona_name() == "hacker"
    yield
    # Clean up after test in case a persona was persisted
    if vp.PERSONA_FILE.exists():
        vp.PERSONA_FILE.unlink()
    vp._load_persona_state()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_builtin_personas_exist() -> None:
    """All 5 built-in personas load without error."""
    for name in ("hacker", "poet", "pirate", "cybercat", "sage"):
        p = vp.get_persona(name)
        assert isinstance(p, dict)
        assert p["name"] == name
        assert "display_name" in p
        assert "banner_ascii" in p and len(p["banner_ascii"]) > 0
        assert "theme_colors" in p
        assert "catchphrases" in p and len(p["catchphrases"]) > 0
        assert "message_prefix" in p
        assert "response_style" in p


def test_get_persona_returns_current() -> None:
    """get_persona(None) returns the current active persona."""
    vp.set_persona("sage")
    p = vp.get_persona()
    assert p["name"] == "sage"


def test_get_persona_unknown_raises_keyerror() -> None:
    """get_persona('unknown') raises KeyError."""
    with pytest.raises(KeyError, match="unknown"):
        vp.get_persona("unknown")


def test_set_persona_saves_and_loads() -> None:
    """set_persona() persists to file and returns the persona dict."""
    p = vp.set_persona("cybercat")
    assert p["name"] == "cybercat"
    assert vp.current_persona_name() == "cybercat"
    # Verify file was written
    assert vp.PERSONA_FILE.exists()
    data = json.loads(vp.PERSONA_FILE.read_text(encoding="utf-8"))
    assert data["name"] == "cybercat"
    # Verify we can read it back
    p2 = vp.get_persona()
    assert p2["name"] == "cybercat"


def test_set_persona_unknown_raises_keyerror() -> None:
    """set_persona('unknown') raises KeyError."""
    with pytest.raises(KeyError, match="unknown"):
        vp.set_persona("unknown")


def test_list_personas_returns_five() -> None:
    """list_personas() returns exactly 5 entries, one per built-in."""
    personas = vp.list_personas()
    assert len(personas) == 5
    names = {p["name"] for p in personas}
    assert names == {"hacker", "poet", "pirate", "cybercat", "sage"}


def test_catchphrase_returns_non_empty_string() -> None:
    """catchphrase() returns a non-empty string from the current persona."""
    vp.set_persona("hacker")
    phrase = vp.catchphrase()
    assert isinstance(phrase, str)
    assert len(phrase) > 0


def test_catchphrase_from_pirate() -> None:
    """catchphrase() works for every persona."""
    for name in ("hacker", "poet", "pirate", "cybercat", "sage"):
        vp.set_persona(name)
        phrase = vp.catchphrase()
        assert isinstance(phrase, str) and len(phrase) > 0


def test_color_returns_ansi_wrapped() -> None:
    """color() wraps text in ANSI escape codes when COLORS_ENABLED is True."""
    with patch.object(vp, "COLORS_ENABLED", True):
        vp.set_persona("hacker")
        result = vp.color("hello", "primary")
        assert result.startswith("\033[")
        assert result.endswith("\033[0m")
        assert "hello" in result
        assert "32" in result  # green primary → ANSI code 32


def test_color_returns_plain_when_disabled() -> None:
    """color() returns text unchanged when COLORS_ENABLED is False."""
    with patch.object(vp, "COLORS_ENABLED", False):
        vp.set_persona("hacker")
        result = vp.color("hello", "primary")
        assert result == "hello"


def test_color_with_different_keys() -> None:
    """color() accepts secondary, accent, highlight, and dim keys."""
    with patch.object(vp, "COLORS_ENABLED", True):
        vp.set_persona("sage")
        for key in ("primary", "secondary", "accent", "highlight", "dim"):
            result = vp.color("test", key)
            assert result.startswith("\033["), f"key={key!r} failed"
            assert "test" in result


def test_apply_style_adds_prefix() -> None:
    """apply_style() prepends the current persona's message prefix."""
    vp.set_persona("poet")
    styled = vp.apply_style("Hello world")
    assert styled == "[✧] Hello world"


def test_apply_style_with_persona_name() -> None:
    """apply_style() uses the specified persona when persona_name is given."""
    styled = vp.apply_style("Test", persona_name="pirate")
    assert styled == "[☠] Test"


def test_apply_style_default_persona() -> None:
    """apply_style() falls back to current persona when name is None."""
    vp.set_persona("sage")
    styled = vp.apply_style("Reflect")
    assert styled == "[✦] Reflect"


def test_persona_banner_returns_string() -> None:
    """persona_banner() returns non-empty ASCII art for current persona."""
    vp.set_persona("sage")
    banner = vp.persona_banner()
    assert isinstance(banner, str)
    assert len(banner) > 0


def test_persona_banner_specific() -> None:
    """persona_banner(name) returns the banner for that specific persona."""
    banner = vp.persona_banner("hacker")
    assert isinstance(banner, str)
    assert len(banner) > 0
    assert "╔" in banner


def test_current_persona_name_defaults_to_hacker() -> None:
    """current_persona_name() returns 'hacker' when no file exists."""
    assert vp.current_persona_name() == "hacker"


def test_current_persona_name_after_set() -> None:
    """current_persona_name() reflects the last set_persona() call."""
    vp.set_persona("pirate")
    assert vp.current_persona_name() == "pirate"
    vp.set_persona("poet")
    assert vp.current_persona_name() == "poet"


def test_set_persona_returns_full_dict() -> None:
    """The dict returned by set_persona() has all expected keys."""
    p = vp.set_persona("sage")
    for key in (
        "name",
        "display_name",
        "banner_ascii",
        "theme_colors",
        "catchphrases",
        "message_prefix",
        "response_style",
    ):
        assert key in p, f"missing key {key!r}"

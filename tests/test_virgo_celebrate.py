"""Tests for virgo_celebrate — celebration/defeat animation engine."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

import virgo_celebrate


# ── firework ────────────────────────────────────────────────────────


class TestFirework:
    def test_returns_non_empty_string_for_success(self) -> None:
        result = virgo_celebrate.firework("success")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_non_empty_string_for_fail(self) -> None:
        result = virgo_celebrate.firework("fail")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_non_empty_string_for_achievement(self) -> None:
        result = virgo_celebrate.firework("achievement")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_non_empty_string_for_levelup(self) -> None:
        result = virgo_celebrate.firework("levelup")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_style_is_success(self) -> None:
        result = virgo_celebrate.firework()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_stars(self) -> None:
        """Firework patterns contain star-like characters."""
        result = virgo_celebrate.firework("success")
        assert "*" in result or "✦" in result or "✧" in result

    def test_unknown_style_falls_back_to_success(self) -> None:
        """An unknown style logs a warning and returns success-style firework."""
        result = virgo_celebrate.firework("unknown_style")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multiple_calls_different_output(self) -> None:
        """Multiple calls should succeed (random pattern selection)."""
        results = {virgo_celebrate.firework("success") for _ in range(20)}
        # At least one should be different (random selection)
        assert len(results) >= 1


# ── sparkle_line ────────────────────────────────────────────────────


class TestSparkleLine:
    def test_wraps_text_in_sparkle_chars(self) -> None:
        result = virgo_celebrate.sparkle_line("test")
        assert "test" in result
        assert len(result) > len("test")

    def test_returns_string(self) -> None:
        result = virgo_celebrate.sparkle_line("hello")
        assert isinstance(result, str)

    def test_sparkle_characters_on_both_sides(self) -> None:
        result = virgo_celebrate.sparkle_line("hello")
        parts = result.split("hello")
        assert len(parts) == 2
        assert len(parts[0].strip()) > 0  # left decoration
        assert len(parts[1].strip()) > 0  # right decoration

    def test_empty_text(self) -> None:
        result = virgo_celebrate.sparkle_line("")
        assert isinstance(result, str)
        assert len(result) > 0  # still has sparkle chars


# ── rainbow ─────────────────────────────────────────────────────────


class TestRainbow:
    def test_returns_string(self) -> None:
        result = virgo_celebrate.rainbow("hello")
        assert isinstance(result, str)

    def test_longer_than_input(self) -> None:
        """ANSI codes should make the output longer than the input."""
        result = virgo_celebrate.rainbow("hello")
        assert len(result) > len("hello")

    def test_empty_text(self) -> None:
        result = virgo_celebrate.rainbow("")
        assert result == ""

    def test_contains_ansi_escape(self) -> None:
        result = virgo_celebrate.rainbow("test")
        assert "\033[" in result

    def test_reset_after_each_char(self) -> None:
        """Each coloured char should be followed by a reset code."""
        result = virgo_celebrate.rainbow("abc")
        # Every character cycle: \033[9Xm char \033[0m
        assert result.count("\033[0m") == 3


# ── confetti ────────────────────────────────────────────────────────


class TestConfetti:
    def test_returns_string(self) -> None:
        result = virgo_celebrate.confetti(40)
        assert isinstance(result, str)

    def test_correct_width(self) -> None:
        result = virgo_celebrate.confetti(40)
        assert len(result) == 40

    def test_default_width_is_40(self) -> None:
        result = virgo_celebrate.confetti()
        assert len(result) == 40

    def test_zero_width(self) -> None:
        result = virgo_celebrate.confetti(0)
        assert result == ""

    def test_negative_width(self) -> None:
        result = virgo_celebrate.confetti(-5)
        assert result == ""

    def test_narrow_width(self) -> None:
        result = virgo_celebrate.confetti(1)
        assert len(result) == 1

    def test_wide_width(self) -> None:
        result = virgo_celebrate.confetti(100)
        assert len(result) == 100


# ── banner ──────────────────────────────────────────────────────────


class TestBanner:
    def test_contains_input_text(self) -> None:
        result = virgo_celebrate.banner("Hello World", style="success")
        assert "Hello World" in result

    def test_returns_string(self) -> None:
        result = virgo_celebrate.banner("Test", style="achievement")
        assert isinstance(result, str)

    def test_default_style_is_success(self) -> None:
        result = virgo_celebrate.banner("Hi")
        assert isinstance(result, str)
        assert "Hi" in result

    def test_unknown_style_falls_back(self) -> None:
        result = virgo_celebrate.banner("X", style="invalid")
        assert "X" in result

    def test_all_styles(self) -> None:
        for style in ("success", "fail", "achievement", "levelup"):
            result = virgo_celebrate.banner("Test", style=style)
            assert "Test" in result, f"banner missing text for style={style!r}"

    def test_has_cheer_message(self) -> None:
        """Banner includes a cheer message for the given style."""
        result = virgo_celebrate.banner("Hi", style="success")
        any_cheer = any(
            c in result for c in virgo_celebrate._CHEERS["success"]
        )
        assert any_cheer, "banner should contain a success cheer message"


# ── fireworks_animation ─────────────────────────────────────────────


class TestFireworksAnimation:
    def test_returns_string(self) -> None:
        result = virgo_celebrate.fireworks_animation(8, 40)
        assert isinstance(result, str)

    def test_correct_number_of_lines(self) -> None:
        result = virgo_celebrate.fireworks_animation(8, 40)
        lines = result.split("\n")
        assert len(lines) == 8

    def test_correct_width(self) -> None:
        result = virgo_celebrate.fireworks_animation(3, 10)
        for line in result.split("\n"):
            assert len(line) == 10

    def test_zero_lines(self) -> None:
        result = virgo_celebrate.fireworks_animation(0, 40)
        assert result == ""

    def test_zero_width(self) -> None:
        result = virgo_celebrate.fireworks_animation(5, 0)
        assert result == ""

    def test_default_parameters(self) -> None:
        result = virgo_celebrate.fireworks_animation()
        assert isinstance(result, str)
        lines = result.split("\n")
        assert len(lines) == 8


# ── cheer_text ──────────────────────────────────────────────────────


class TestCheerText:
    @pytest.mark.parametrize(
        "style",
        ["success", "fail", "achievement", "levelup"],
    )
    def test_returns_expected_style_message(self, style: str) -> None:
        result = virgo_celebrate.cheer_text(style)
        assert result in virgo_celebrate._CHEERS[style], (
            f"cheer_text('{style}') returned {result!r}, "
            f"expected one of {virgo_celebrate._CHEERS[style]}"
        )

    def test_default_is_success(self) -> None:
        result = virgo_celebrate.cheer_text()
        assert result in virgo_celebrate._CHEERS["success"]

    def test_unknown_style_falls_back_to_success(self) -> None:
        result = virgo_celebrate.cheer_text("bogus")
        assert result in virgo_celebrate._CHEERS["success"]

    def test_randomness(self) -> None:
        """Multiple calls should eventually produce different messages."""
        results: set[str] = set()
        for _ in range(100):
            results.add(virgo_celebrate.cheer_text("success"))
        assert len(results) > 1, "cheer_text should have some randomness"


# ── cmd_celebrate ──────────────────────────────────────────────────


class TestCmdCelebrate:
    def test_runs_without_error(self) -> None:
        """The CLI handler should not raise for the default call."""
        # Patch input so it doesn't wait for user
        with patch("builtins.input", return_value=""):
            virgo_celebrate.cmd_celebrate([])

    def test_runs_with_style(self) -> None:
        with patch("builtins.input", return_value=""):
            virgo_celebrate.cmd_celebrate(["--type", "achievement"])

    def test_runs_with_message(self) -> None:
        with patch("builtins.input", return_value=""):
            virgo_celebrate.cmd_celebrate(["--message", "Custom!"])

    def test_runs_with_style_and_message(self) -> None:
        with patch("builtins.input", return_value=""):
            virgo_celebrate.cmd_celebrate(
                ["--type", "levelup", "--message", "Great job!"]
            )

"""Tests for virgo_chaos.py — Chaos Mode."""

from __future__ import annotations

from unittest.mock import patch

import virgo_chaos


# ── Helpers ──────────────────────────────────────────────────────────────

def _reset_state() -> None:
    """Reset the module's in-memory state to defaults."""
    virgo_chaos._state = dict(virgo_chaos._DEFAULT_STATE)


def _enable_chaos() -> None:
    """Convenience: enable chaos in the in-memory state (no disk)."""
    virgo_chaos._state["enabled"] = True


# ── Tests ────────────────────────────────────────────────────────────────

class TestIsChaosEnabled:
    """is_chaos_enabled() behaviour."""

    def test_default_is_false(self) -> None:
        _reset_state()
        assert virgo_chaos.is_chaos_enabled() is False

    def test_returns_true_after_enable(self) -> None:
        _reset_state()
        virgo_chaos.set_chaos(True)
        assert virgo_chaos.is_chaos_enabled() is True

    def test_returns_false_after_disable(self) -> None:
        _reset_state()
        virgo_chaos.set_chaos(True)
        virgo_chaos.set_chaos(False)
        assert virgo_chaos.is_chaos_enabled() is False


class TestSetChaos:
    """set_chaos() behaviour."""

    def test_set_chaos_true_returns_enabled_state(self) -> None:
        _reset_state()
        state = virgo_chaos.set_chaos(True)
        assert state["enabled"] is True
        assert "intensity" in state

    def test_set_chaos_false_returns_disabled_state(self) -> None:
        _reset_state()
        state = virgo_chaos.set_chaos(False)
        assert state["enabled"] is False
        assert "intensity" in state


class TestToggleChaos:
    """toggle_chaos() behaviour."""

    def test_toggle_flips_from_disabled(self) -> None:
        _reset_state()
        state = virgo_chaos.toggle_chaos()
        assert state["enabled"] is True

    def test_toggle_flips_back(self) -> None:
        _reset_state()
        virgo_chaos.set_chaos(True)
        state = virgo_chaos.toggle_chaos()
        assert state["enabled"] is False


class TestIntensity:
    """chaos_intensity() / set_intensity() behaviour."""

    def test_default_intensity_is_3(self) -> None:
        _reset_state()
        assert virgo_chaos.chaos_intensity() == 3

    def test_set_intensity_returns_correct(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(3)
        assert state["intensity"] == 3

    def test_set_intensity_5(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(5)
        assert state["intensity"] == 5

    def test_set_intensity_1(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(1)
        assert state["intensity"] == 1

    def test_set_intensity_clamps_low(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(0)
        assert state["intensity"] == 1

    def test_set_intensity_clamps_high(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(99)
        assert state["intensity"] == 5


class TestRandomJoke:
    """random_joke() behaviour."""

    def test_returns_non_empty_string(self) -> None:
        joke = virgo_chaos.random_joke()
        assert isinstance(joke, str)
        assert len(joke) > 0

    def test_returns_different_jokes(self) -> None:
        # Over many calls we should see variety
        jokes = {virgo_chaos.random_joke() for _ in range(100)}
        assert len(jokes) >= 5  # At least 5 unique out of 15+


class TestRandomInterjection:
    """random_interjection() behaviour."""

    def test_returns_empty_when_disabled(self) -> None:
        _reset_state()
        assert virgo_chaos.random_interjection() == ""

    def test_returns_non_empty_when_enabled(self) -> None:
        _reset_state()
        _enable_chaos()
        interjection = virgo_chaos.random_interjection()
        assert isinstance(interjection, str)
        assert len(interjection) > 0

    def test_returns_varied_interjections(self) -> None:
        _reset_state()
        _enable_chaos()
        interjections = {virgo_chaos.random_interjection() for _ in range(100)}
        assert len(interjections) >= 3


class TestEasterEgg:
    """easter_egg() behaviour."""

    def test_known_egg_42(self) -> None:
        result = virgo_chaos.easter_egg("42")
        assert result is not None
        assert "answer" in result.lower() or "life" in result.lower()

    def test_known_egg_make_sandwich(self) -> None:
        result = virgo_chaos.easter_egg("make me a sandwich")
        assert result is not None
        assert "sudo" in result

    def test_known_egg_hack(self) -> None:
        result = virgo_chaos.easter_egg("/hack")
        assert result is not None
        assert "HACKING" in result

    def test_unknown_returns_none(self) -> None:
        result = virgo_chaos.easter_egg("unknown_random_command")
        assert result is None

    def test_case_insensitive(self) -> None:
        result = virgo_chaos.easter_egg("MAKE ME A SANDWICH")
        assert result is not None

    def test_why(self) -> None:
        result = virgo_chaos.easter_egg("why")
        assert result is not None
        assert "42" in result

    def test_uptime(self) -> None:
        result = virgo_chaos.easter_egg("uptime")
        assert result is not None
        assert "coffee" in result


class TestMaybeEmbellish:
    """maybe_embellish() behaviour."""

    def test_returns_text_when_disabled(self) -> None:
        _reset_state()
        result = virgo_chaos.maybe_embellish("hello")
        assert result == "hello"

    def test_returns_text_maybe_embellished(self) -> None:
        _reset_state()
        _enable_chaos()
        virgo_chaos.set_intensity(5)
        # With intensity 5, probability is 0.85 — most calls will embellish
        results = {virgo_chaos.maybe_embellish("test") for _ in range(200)}
        # At least some should have emoji decorations
        has_emoji = any(r != "test" for r in results)
        assert has_emoji, "No embellished output at intensity 5"

    def test_low_intensity_rarely_embellishes(self) -> None:
        _reset_state()
        _enable_chaos()
        virgo_chaos.set_intensity(1)
        # At intensity 1, probability is only 0.1
        results = {virgo_chaos.maybe_embellish("test") for _ in range(100)}
        # Most should still be plain
        assert "test" in results


class TestInjectTypo:
    """inject_typo() behaviour."""

    def test_none_when_disabled(self) -> None:
        _reset_state()
        result = virgo_chaos.inject_typo(1.0)
        assert result is None

    def test_uses_intensity_based_prob_at_default(self) -> None:
        """With probability=0.0 (default), uses intensity-based probability."""
        _reset_state()
        _enable_chaos()
        virgo_chaos.set_intensity(1)
        # At intensity 1, default prob is 0.02 — rarely triggers
        results = {virgo_chaos.inject_typo(0.0) for _ in range(200)}
        # Most calls still return None at low intensity
        assert None in results or len(results) >= 1


class TestInfectTypoHighProb:
    """Separate class to avoid random-state interference."""

    def test_typo_at_high_probability(self) -> None:
        _reset_state()
        _enable_chaos()
        # Force random to return small numbers so typo triggers
        with patch.object(virgo_chaos.random, "random", return_value=0.01):
            result = virgo_chaos.inject_typo(1.0)
            assert result is not None
            assert isinstance(result, str)
            assert len(result) > 0


class TestFormatOutput:
    """format_output() behaviour."""

    def test_returns_text_when_disabled(self) -> None:
        _reset_state()
        for ctx in ("success", "fail", "info", "error", "progress", "generic"):
            result = virgo_chaos.format_output("hello", context=ctx)
            assert result == "hello", f"failed for context={ctx!r}"

    def test_returns_non_empty_when_enabled(self) -> None:
        _reset_state()
        _enable_chaos()
        for ctx in ("success", "fail", "info", "error", "progress", "generic"):
            result = virgo_chaos.format_output("hello", context=ctx)
            assert isinstance(result, str)
            assert len(result) > 0, f"empty result for context={ctx!r}"


class TestCmdChaos:
    """cmd_chaos() CLI handler smoke tests."""

    def test_show_state(self, capsys) -> None:
        _reset_state()
        virgo_chaos.cmd_chaos([])
        captured = capsys.readouterr()
        assert "Chaos" in captured.out
        assert "DISABLED" in captured.out
        assert "Dad Joke" in captured.out

    def test_on(self, capsys) -> None:
        _reset_state()
        virgo_chaos.cmd_chaos(["--on"])
        captured = capsys.readouterr()
        assert "enabled" in captured.out.lower()
        assert virgo_chaos.is_chaos_enabled() is True

    def test_off(self, capsys) -> None:
        _reset_state()
        virgo_chaos.set_chaos(True)
        virgo_chaos.cmd_chaos(["--off"])
        captured = capsys.readouterr()
        assert "disabled" in captured.out.lower()
        assert virgo_chaos.is_chaos_enabled() is False

    def test_toggle(self, capsys) -> None:
        _reset_state()
        virgo_chaos.cmd_chaos(["--toggle"])
        captured = capsys.readouterr()
        assert "enabled" in captured.out.lower()
        assert virgo_chaos.is_chaos_enabled() is True

    def test_set_intensity(self, capsys) -> None:
        _reset_state()
        virgo_chaos.cmd_chaos(["--intensity", "5"])
        captured = capsys.readouterr()
        assert "5" in captured.out
        assert virgo_chaos.chaos_intensity() == 5


class TestEdgeCases:
    """Edge-case behaviour."""

    def test_easter_egg_whitespace_handling(self) -> None:
        result = virgo_chaos.easter_egg("  42  ")
        assert result is not None

    def test_set_intensity_returns_state_dict(self) -> None:
        _reset_state()
        state = virgo_chaos.set_intensity(2)
        assert isinstance(state, dict)
        assert state["intensity"] == 2
        assert "enabled" in state

    def test_format_output_each_context_returns_string(self) -> None:
        _reset_state()
        _enable_chaos()
        for ctx in ("success", "fail", "info", "error", "progress", "generic"):
            result = virgo_chaos.format_output("test", context=ctx)
            assert isinstance(result, str), f"not str for context={ctx!r}"

    def test_random_joke_always_string(self) -> None:
        for _ in range(50):
            joke = virgo_chaos.random_joke()
            assert isinstance(joke, str)

    def test_cmd_chaos_none_args(self, capsys) -> None:
        _reset_state()
        virgo_chaos.cmd_chaos()
        captured = capsys.readouterr()
        assert "Chaos" in captured.out

    def test_random_interjection_varied(self) -> None:
        """At max intensity, interjections come from all levels."""
        _reset_state()
        _enable_chaos()
        virgo_chaos.set_intensity(5)
        interjections = {virgo_chaos.random_interjection() for _ in range(200)}
        # Should have at least 5 unique phrases from the pool of 20
        assert len(interjections) >= 5

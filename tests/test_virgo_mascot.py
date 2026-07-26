"""Tests for virgo_mascot — persistent AI sidekick mascot."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import virgo_mascot


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_mascot_file(tmp_path: pytest.TempPathFactory) -> None:
    """Redirect the mascot config file to a temp path so tests don't
    clobber the real .virgo_mascot.json or each other."""
    fake_file = tmp_path / ".virgo_mascot.json"
    fake_file.write_text(json.dumps({"mascot": "cybercat"}), encoding="utf-8")
    with patch.object(virgo_mascot, "_MASCOT_FILE", fake_file):
        # Re-seed the module-level cache so the patched path is used
        virgo_mascot._MASCOTS["cybercat"]  # ensure loaded
        yield


# ── list_mascots ────────────────────────────────────────────────────────


class TestListMascots:
    def test_all_four_mascots_present(self) -> None:
        mascots = virgo_mascot.list_mascots()
        assert len(mascots) == 4

    def test_cybercat_in_list(self) -> None:
        tags = {m["tag"] for m in virgo_mascot.list_mascots()}
        assert "cybercat" in tags

    def test_ghostbot_in_list(self) -> None:
        tags = {m["tag"] for m in virgo_mascot.list_mascots()}
        assert "ghostbot" in tags

    def test_hackfox_in_list(self) -> None:
        tags = {m["tag"] for m in virgo_mascot.list_mascots()}
        assert "hackfox" in tags

    def test_pixeldragon_in_list(self) -> None:
        tags = {m["tag"] for m in virgo_mascot.list_mascots()}
        assert "pixeldragon" in tags

    def test_each_mascot_has_required_keys(self) -> None:
        required = {"tag", "display", "ascii", "idle_animations", "reactions"}
        for mascot in virgo_mascot.list_mascots():
            assert required.issubset(mascot.keys()), (
                f"{mascot['tag']} missing keys: {required - mascot.keys()}"
            )

    def test_each_mascot_has_non_empty_ascii(self) -> None:
        for mascot in virgo_mascot.list_mascots():
            assert len(mascot["ascii"]) > 0, f"{mascot['tag']} has empty ascii"

    def test_each_mascot_has_at_least_one_idle(self) -> None:
        for mascot in virgo_mascot.list_mascots():
            assert len(mascot["idle_animations"]) >= 1, (
                f"{mascot['tag']} has no idle animations"
            )

    def test_each_mascot_has_three_reaction_buckets(self) -> None:
        for mascot in virgo_mascot.list_mascots():
            reactions = mascot["reactions"]
            for bucket in ("success", "fail", "alert"):
                assert bucket in reactions, (
                    f"{mascot['tag']} missing reaction bucket {bucket!r}"
                )
                assert len(reactions[bucket]) >= 1, (
                    f"{mascot['tag']} has empty reaction bucket {bucket!r}"
                )


# ── get_mascot ──────────────────────────────────────────────────────────


class TestGetMascot:
    def test_get_current_defaults_to_cybercat(self) -> None:
        mascot = virgo_mascot.get_mascot()
        assert mascot["tag"] == "cybercat"

    def test_get_by_name(self) -> None:
        mascot = virgo_mascot.get_mascot("ghostbot")
        assert mascot["tag"] == "ghostbot"

    def test_get_returns_copy_not_mutable_original(self) -> None:
        mascot = virgo_mascot.get_mascot("hackfox")
        mascot["tag"] = "mutated"
        original = virgo_mascot.get_mascot("hackfox")
        assert original["tag"] == "hackfox"

    def test_get_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            virgo_mascot.get_mascot("nonexistent")


# ── set_mascot ──────────────────────────────────────────────────────────


class TestSetMascot:
    def test_set_returns_mascot(self) -> None:
        mascot = virgo_mascot.set_mascot("ghostbot")
        assert mascot["tag"] == "ghostbot"

    def test_set_persists_to_disk(self) -> None:
        virgo_mascot.set_mascot("pixeldragon")
        saved = json.loads(virgo_mascot._MASCOT_FILE.read_text(encoding="utf-8"))
        assert saved["mascot"] == "pixeldragon"

    def test_set_changes_get_mascot_without_arg(self) -> None:
        virgo_mascot.set_mascot("hackfox")
        current = virgo_mascot.get_mascot()
        assert current["tag"] == "hackfox"

    def test_set_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            virgo_mascot.set_mascot("unicorn")


# ── current_mascot_name ─────────────────────────────────────────────────


class TestCurrentMascotName:
    def test_default_name(self) -> None:
        with patch.object(virgo_mascot, "_MASCOT_FILE") as mock_file:
            mock_file.exists.return_value = False
            assert virgo_mascot.current_mascot_name() == "cybercat"

    def test_after_set_returns_new_name(self) -> None:
        virgo_mascot.set_mascot("hackfox")
        assert virgo_mascot.current_mascot_name() == "hackfox"


# ── idle_action ─────────────────────────────────────────────────────────


class TestIdleAction:
    def test_returns_non_empty_string(self) -> None:
        action = virgo_mascot.idle_action()
        assert isinstance(action, str)
        assert len(action) > 0

    def test_returns_a_random_idle_from_current(self) -> None:
        mascot = virgo_mascot.get_mascot()
        animations = mascot["idle_animations"]
        action = virgo_mascot.idle_action()
        assert action in animations

    def test_changes_with_different_mascot(self) -> None:
        virgo_mascot.set_mascot("pixeldragon")
        action = virgo_mascot.idle_action()
        dragon = virgo_mascot.get_mascot("pixeldragon")
        assert action in dragon["idle_animations"]


# ── react ───────────────────────────────────────────────────────────────


class TestReact:
    def test_returns_non_empty_string(self) -> None:
        msg = virgo_mascot.react("pipeline")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_reaction_from_correct_bucket(self) -> None:
        virgo_mascot.set_mascot("pixeldragon")
        msg = virgo_mascot.react("build", result="fail")
        dragon = virgo_mascot.get_mascot("pixeldragon")
        assert msg in dragon["reactions"]["fail"]

    def test_alert_reaction(self) -> None:
        msg = virgo_mascot.react("alert", result="success")
        assert len(msg) > 0


# ── cheer ───────────────────────────────────────────────────────────────


class TestCheer:
    def test_returns_non_empty_string(self) -> None:
        msg = virgo_mascot.cheer()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_cheer_with_fail(self) -> None:
        msg = virgo_mascot.cheer("fail")
        assert len(msg) > 0

    def test_cheer_defaults_to_success_bucket(self) -> None:
        mascot = virgo_mascot.get_mascot()
        msg = virgo_mascot.cheer()
        assert msg in mascot["reactions"]["success"]


# ── speak ───────────────────────────────────────────────────────────────


class TestSpeak:
    def test_includes_mascot_display_name(self) -> None:
        output = virgo_mascot.speak("Hello world")
        assert "CyberCat" in output

    def test_includes_text(self) -> None:
        output = virgo_mascot.speak("Test message")
        assert "Test message" in output

    def test_speak_named_mascot(self) -> None:
        output = virgo_mascot.speak("Beep boop", mascot_name="ghostbot")
        assert "GhostBot" in output
        assert "Beep boop" in output

    def test_includes_ascii_art(self) -> None:
        output = virgo_mascot.speak("Hi")
        ascii_art = virgo_mascot.mascot_ascii()
        # ASCII art should appear somewhere in the output
        for line in ascii_art.split("\n"):
            assert line.strip() in output or line.lstrip() in output

    def test_speak_respects_unknown_mascot(self) -> None:
        with pytest.raises(KeyError):
            virgo_mascot.speak("hello", mascot_name="nope")


# ── mascot_ascii ────────────────────────────────────────────────────────


class TestMascotAscii:
    def test_returns_non_empty_string(self) -> None:
        art = virgo_mascot.mascot_ascii()
        assert isinstance(art, str)
        assert len(art) > 0

    def test_returns_current_mascot_ascii(self) -> None:
        virgo_mascot.set_mascot("pixeldragon")
        art = virgo_mascot.mascot_ascii()
        dragon = virgo_mascot.get_mascot("pixeldragon")
        assert art == dragon["ascii"]

    def test_returns_named_mascot_ascii(self) -> None:
        art = virgo_mascot.mascot_ascii("cybercat")
        cat = virgo_mascot.get_mascot("cybercat")
        assert art == cat["ascii"]


# ── utility functions ───────────────────────────────────────────────────


class TestMascotColor:
    def test_returns_colour_for_known_mascot(self) -> None:
        color = virgo_mascot.mascot_color("cybercat")
        assert isinstance(color, str)
        assert len(color) > 0

    def test_returns_string_for_all_mascots(self) -> None:
        for mascot in virgo_mascot.list_mascots():
            color = virgo_mascot.mascot_color(mascot["tag"])
            assert isinstance(color, str)


class TestColoredAscii:
    def test_returns_string(self) -> None:
        result = virgo_mascot.colored_ascii()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_ascii_art(self) -> None:
        art = virgo_mascot.mascot_ascii("cybercat")
        result = virgo_mascot.colored_ascii("cybercat")
        # ASCII art lines should be present (color codes wrap lines)
        for line in art.split("\n"):
            if line.strip():
                assert line.strip() in result


# ── CLI handlers ────────────────────────────────────────────────────────


class TestCmdMascotList:
    def test_prints_mascots(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_list()
        captured = capsys.readouterr()
        assert "CyberCat" in captured.out
        assert "GhostBot" in captured.out
        assert "HackFox" in captured.out
        assert "PixelDragon" in captured.out


class TestCmdMascotSet:
    def test_set_via_cli(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_set(["ghostbot"])
        captured = capsys.readouterr()
        assert "GhostBot" in captured.out
        assert virgo_mascot.current_mascot_name() == "ghostbot"

    def test_set_unknown_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_set(["unicorn"])
        captured = capsys.readouterr()
        assert "Unknown mascot" in captured.out

    def test_set_no_args_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_set([])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdMascotSpeak:
    def test_speak_via_cli(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_speak(["Hello", "world"])
        captured = capsys.readouterr()
        assert "CyberCat" in captured.out
        assert "Hello world" in captured.out

    def test_speak_no_args_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_speak([])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdMascotShow:
    def test_show_current(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_show()
        captured = capsys.readouterr()
        assert "CyberCat" in captured.out

    def test_show_named_mascot(self, capsys: pytest.CaptureFixture[str]) -> None:
        virgo_mascot.cmd_mascot_show(["hackfox"])
        captured = capsys.readouterr()
        assert "HackFox" in captured.out

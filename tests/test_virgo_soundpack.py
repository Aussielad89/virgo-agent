"""Tests for virgo_soundpack — Sound Effects module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import virgo_soundpack as sp  # noqa: E402


class TestSoundPack:
    def test_list_packs(self):
        packs = sp.list_packs()
        assert len(packs) >= 3
        pack_ids = {p["id"] for p in packs}
        assert "retro" in pack_ids
        assert "cyberpunk" in pack_ids
        assert "nature" in pack_ids

    def test_list_events(self):
        events = sp.list_events()
        assert len(events) >= 5
        assert "startup" in events
        assert "success" in events
        assert "failure" in events
        assert "achievement" in events

    def test_get_pack_default(self):
        result = sp.get_pack()
        assert "pack" in result
        assert "name" in result

    def test_set_pack_changes(self):
        sp.set_pack("nature")
        result = sp.get_pack()
        assert result["pack"] == "nature"
        sp.set_pack("retro")

    def test_set_pack_unknown_raises(self):
        with pytest.raises(KeyError):
            sp.set_pack("nonexistent")

    def test_mute_unmute(self):
        sp.unmute()
        result = sp.mute()
        assert result["status"] == "muted"

        result = sp.unmute()
        assert result["status"] == "unmuted"

    def test_toggle(self):
        sp.unmute()
        result = sp.toggle()
        assert result["status"] == "muted"
        result = sp.toggle()
        assert result["status"] == "unmuted"

    def test_pack_has_sounds(self):
        for pack_id, pack_def in sp.SOUND_PACKS.items():
            assert "sounds" in pack_def
            assert len(pack_def["sounds"]) >= 5
            for event, sound in pack_def["sounds"].items():
                assert "freq" in sound
                assert "duration" in sound
                assert sound["freq"] > 0
                assert sound["duration"] > 0

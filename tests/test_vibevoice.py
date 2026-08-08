"""Tests for virgo_vibevoice wrapper module."""
from __future__ import annotations

import pytest


def _voices_available() -> bool:
    """VibeVoice demo voice presets are a local-only asset, not in the repo."""
    from virgo_vibevoice import VOICES_DIR

    return VOICES_DIR.exists() and any(VOICES_DIR.glob("*.wav"))


requires_voices = pytest.mark.skipif(
    not _voices_available(),
    reason="VibeVoice demo voices directory not present (local-only asset)",
)


class TestVibeVoiceWrapper:
    """Tests for the VibeVoice wrapper (no model loading)."""

    def test_import(self):
        from virgo_vibevoice import VibeVoiceTTS, TTSConfig
        assert VibeVoiceTTS is not None
        assert TTSConfig is not None

    def test_config_defaults(self):
        from virgo_vibevoice import TTSConfig
        cfg = TTSConfig()
        assert cfg.model_size == "1.5B"
        assert cfg.device == "auto"
        assert cfg.speaker == "Alice"
        assert cfg.sample_rate == 24000

    def test_parse_script_single(self):
        from virgo_vibevoice import parse_script
        segments = parse_script("Hello world, this is a test.")
        assert len(segments) == 1
        assert segments[0][0] == "Hello world, this is a test."

    def test_parse_script_multi(self):
        from virgo_vibevoice import parse_script
        text = "Alice: Hello there!\nFrank: Hi Alice, how are you?"
        segments = parse_script(text)
        assert len(segments) == 2
        assert segments[0] == ("Hello there!", "Alice")
        assert segments[1] == ("Hi Alice, how are you?", "Frank")

    def test_parse_script_speaker_numbers(self):
        from virgo_vibevoice import parse_script
        text = "Speaker 1: First line\nSpeaker 2: Second line"
        segments = parse_script(text)
        assert len(segments) == 2
        assert segments[0][1] == "Speaker 1"
        assert segments[1][1] == "Speaker 2"

    @requires_voices
    def test_list_speakers(self):
        from virgo_vibevoice import list_speakers
        speakers = list_speakers()
        assert len(speakers) > 0
        assert "Alice" in speakers or "alice" in speakers

    @requires_voices
    def test_get_voice_path(self):
        from virgo_vibevoice import get_voice_path
        path = get_voice_path("Alice")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".wav"

    @requires_voices
    def test_get_voice_path_partial(self):
        from virgo_vibevoice import get_voice_path
        path = get_voice_path("en-Frank")
        assert path is not None
        assert "Frank" in path.name

    def test_get_voice_path_unknown(self):
        from virgo_vibevoice import get_voice_path
        path = get_voice_path("NonexistentSpeaker999")
        assert path is None

    def test_tts_not_loaded_initially(self):
        from virgo_vibevoice import VibeVoiceTTS
        tts = VibeVoiceTTS()
        assert not tts.is_loaded

    def test_model_map(self):
        from virgo_vibevoice import VibeVoiceTTS
        tts = VibeVoiceTTS()
        assert "1.5B" in tts.MODEL_MAP
        assert "7B" in tts.MODEL_MAP
        assert "0.5B" in tts.MODEL_MAP

    def test_device_resolution(self):
        from virgo_vibevoice import VibeVoiceTTS, TTSConfig
        tts = VibeVoiceTTS(TTSConfig(device="cpu"))
        assert tts._resolve_device() == "cpu"

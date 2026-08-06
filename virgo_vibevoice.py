"""
virgo_vibevoice — VibeVoice TTS integration for Virgo Agent Framework.

Wraps the VibeVoice model for text-to-speech generation, supporting:
  • Single and multi-speaker synthesis
  • Voice cloning from preset WAV files
  • CPU and GPU inference
  • Pipeline result announcements
  • Gradio-style web UI integration

Requirements:
  pip install -e ./VibeVoice  (in the agent-framework directory)

Usage (CLI):
    python virgo_vibevoice.py --text "Hello world" --speaker Alice
    python virgo_vibevoice.py --file script.txt --speaker Alice Frank
    python virgo_vibevoice.py --text "Pipeline complete" --announce --session my_run

Usage (Programmatic):
    from virgo_vibevoice import VibeVoiceTTS
    tts = VibeVoiceTTS(model_size="1.5B")
    tts.load()
    output = tts.speak("Hello world", speaker="Alice")
    tts.save(output, "output.wav")
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).resolve().parent

# ── Voice preset paths ───────────────────────────────────────────────
VOICES_DIR = HERE / "VibeVoice" / "demo" / "voices"

VOICE_PRESETS: dict[str, Path] = {}

# Speaker label aliases
_SPEAKER_ALIASES: dict[str, str] = {
    "alice": "en-Alice_woman",
    "carter": "en-Carter_man",
    "frank": "en-Frank_man",
    "mary": "en-Mary_woman_bgm",
    "maya": "en-Maya_woman",
    "samuel": "in-Samuel_man",
    "anchen": "zh-Anchen_man_bgm",
    "bowen": "zh-Bowen_man",
    "xinran": "zh-Xinran_woman",
}


def _discover_voices() -> dict[str, Path]:
    """Scan the voices directory for available WAV presets."""
    global VOICE_PRESETS
    if VOICE_PRESETS:
        return VOICE_PRESETS

    if not VOICES_DIR.exists():
        log.warning("vibevoice: voices directory not found at %s", VOICES_DIR)
        return {}

    for wav in sorted(VOICES_DIR.glob("*.wav")):
        name = wav.stem  # e.g. "en-Alice_woman"
        VOICE_PRESETS[name] = wav
        # Also register short alias
        short = name.split("_")[0].split("-")[-1].lower()
        if short not in VOICE_PRESETS:
            VOICE_PRESETS[short] = wav

    log.info("vibevoice: discovered %d voice presets", len(VOICE_PRESETS))
    return VOICE_PRESETS


def get_voice_path(speaker: str) -> Path | None:
    """Resolve a speaker name to a voice WAV path."""
    voices = _discover_voices()
    speaker_lower = speaker.lower().strip()

    # Exact match
    if speaker_lower in voices:
        return voices[speaker_lower]

    # Alias match
    if speaker_lower in _SPEAKER_ALIASES:
        alias = _SPEAKER_ALIASES[speaker_lower]
        if alias in voices:
            return voices[alias]

    # Partial match
    for name, path in voices.items():
        if speaker_lower in name.lower() or name.lower() in speaker_lower:
            return path

    return None


def list_speakers() -> list[str]:
    """Return list of available speaker names."""
    voices = _discover_voices()
    return sorted(set(
        name.split("_")[0].split("-")[-1]
        for name in voices.keys()
        if "_" in name or "-" in name
    ))


# ── Script parsing ───────────────────────────────────────────────────

def parse_script(text: str) -> list[tuple[str, str]]:
    """Parse a multi-speaker script into (speaker_text, speaker_label) pairs.

    Supports formats:
      - "Speaker 1: Hello"
      - "Alice: Hello"
      - Plain text (single speaker)
    """
    lines = text.strip().split("\n")
    segments: list[tuple[str, str]] = []

    # Pattern: "Speaker N: ..." or "Name: ..."
    pattern = re.compile(r"^(Speaker\s+\d+|[A-Za-z][A-Za-z\s]*?):\s*(.+)$", re.IGNORECASE)

    current_speaker = "Speaker 1"
    current_text = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = pattern.match(line)
        if match:
            if current_text:
                segments.append((current_text.strip(), current_speaker))
            current_speaker = match.group(1).strip()
            current_text = match.group(2).strip()
        else:
            current_text += " " + line

    if current_text:
        segments.append((current_text.strip(), current_speaker))

    # If no speaker labels found, treat as single speaker
    if not segments and text.strip():
        segments = [(text.strip(), "Speaker 1")]

    return segments


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class TTSConfig:
    """Configuration for VibeVoice TTS generation."""
    model_size: str = "1.5B"       # "0.5B", "1.5B", or "7B"
    device: str = "auto"            # "auto", "cpu", "cuda", "mps"
    speaker: str = "Alice"          # Default speaker name
    output_dir: str = "outputs"     # Output directory for WAV files
    sample_rate: int = 24000        # Audio sample rate
    cfg_scale: float = 1.3          # Classifier-free guidance scale
    ddpm_steps: int = 10            # Diffusion steps
    disable_prefill: bool = False   # Disable voice cloning


@dataclass
class TTSOutput:
    """Result of a TTS generation."""
    audio: Any = None               # Audio tensor/array
    text: str = ""
    speaker: str = ""
    duration: float = 0.0           # Audio duration in seconds
    generation_time: float = 0.0    # Time to generate
    output_path: str = ""
    sample_rate: int = 24000


# ── Main TTS engine ──────────────────────────────────────────────────

class VibeVoiceTTS:
    """VibeVoice text-to-speech engine for Virgo.

    Lazy-loads the model on first use to avoid memory overhead.
    """

    MODEL_MAP = {
        "0.5B": "microsoft/VibeVoice-Realtime-0.5B",
        "1.5B": str(HERE / "models" / "VibeVoice-1.5B"),
        "7B": "vibevoice/VibeVoice-7B",
    }

    def __init__(self, config: TTSConfig | None = None) -> None:
        self.config = config or TTSConfig()
        self._model = None
        self._processor = None
        self._loaded = False
        self._device = self._resolve_device()

    def _resolve_device(self) -> str:
        """Determine the best device for inference."""
        try:
            import torch
        except ImportError:
            return "cpu"

        if self.config.device != "auto":
            return self.config.device

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the VibeVoice model and processor."""
        if self._loaded:
            return

        try:
            import torch
            from vibevoice.modular.modeling_vibevoice_inference import (
                VibeVoiceForConditionalGenerationInference,
            )
            from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor
        except ImportError as exc:
            raise ImportError(
                "VibeVoice not installed. Run: cd VibeVoice && pip install -e ."
            ) from exc

        model_path = self.MODEL_MAP.get(self.config.model_size)
        if not model_path:
            raise ValueError(f"Unknown model size: {self.config.model_size}")

        log.info("vibevoice: loading model %s on %s", model_path, self._device)
        t0 = time.time()

        # Determine dtype and attention
        if self._device == "cuda":
            load_dtype = torch.bfloat16
            attn_impl = "flash_attention_2"
        else:
            load_dtype = torch.float32
            attn_impl = "sdpa"

        try:
            self._processor = VibeVoiceProcessor.from_pretrained(model_path)
            self._model = VibeVoiceForConditionalGenerationInference.from_pretrained(
                model_path,
                torch_dtype=load_dtype,
                device_map=self._device if self._device != "mps" else None,
                attn_implementation=attn_impl,
            )
            if self._device == "mps":
                self._model.to("mps")
        except Exception as e:
            if attn_impl == "flash_attention_2":
                log.warning("vibevoice: flash_attention failed, falling back to sdpa")
                self._model = VibeVoiceForConditionalGenerationInference.from_pretrained(
                    model_path,
                    torch_dtype=load_dtype,
                    device_map=self._device if self._device in ("cuda", "cpu") else None,
                    attn_implementation="sdpa",
                )
                if self._device == "mps":
                    self._model.to("mps")
            else:
                raise

        self._model.eval()
        self._model.set_ddpm_inference_steps(num_steps=self.config.ddpm_steps)
        self._loaded = True

        elapsed = time.time() - t0
        log.info("vibevoice: model loaded in %.1fs", elapsed)

    def unload(self) -> None:
        """Unload the model to free memory."""
        self._model = None
        self._processor = None
        self._loaded = False
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def speak(
        self,
        text: str,
        speaker: str | None = None,
        *,
        voice_path: str | Path | None = None,
        speakers: list[str] | None = None,
    ) -> TTSOutput:
        """Generate speech from text.

        Parameters
        ----------
        text:
            The text to synthesize. Can be plain text or multi-speaker script.
        speaker:
            Speaker name for single-speaker mode (e.g. "Alice").
        voice_path:
            Path to a custom voice WAV for cloning. Overrides speaker.
        speakers:
            List of speaker names for multi-speaker mode.
        """
        if not self._loaded:
            self.load()

        import torch

        speaker = speaker or self.config.speaker

        # Parse multi-speaker script
        segments = parse_script(text)

        if len(segments) == 1 and not speakers:
            # Single speaker mode
            script_text = f"Speaker 1: {segments[0][0]}"
            if voice_path:
                voice_samples = [[str(voice_path)]]
            else:
                vp = get_voice_path(speaker)
                voice_samples = [[str(vp)] if vp else []]
            speaker_names_used = [speaker]
        else:
            # Multi-speaker mode
            speaker_map: dict[str, str] = {}
            if speakers:
                unique_speakers = list(dict.fromkeys(s for _, s in segments))
                for i, s in enumerate(unique_speakers):
                    if i < len(speakers):
                        speaker_map[s] = speakers[i]

            script_lines = []
            voice_samples_inner: list[str] = []
            seen_speakers: list[str] = []

            for seg_text, seg_speaker in segments:
                mapped_name = speaker_map.get(seg_speaker, seg_speaker)
                script_lines.append(f"Speaker 1: {seg_text}")
                vp = get_voice_path(mapped_name)
                if vp and mapped_name not in seen_speakers:
                    voice_samples_inner.append(str(vp))
                    seen_speakers.append(mapped_name)

            script_text = "\n".join(script_lines)
            voice_samples = [voice_samples_inner] if voice_samples_inner else [[]]
            speaker_names_used = seen_speakers or [speaker]

        # Run generation
        log.info("vibevoice: generating speech (%d segments, speaker=%s)", len(segments), speaker)

        # Process inputs
        inputs = self._processor(
            text=[script_text],
            voice_samples=voice_samples,
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        )

        target_device = self._device
        for k, v in inputs.items():
            if torch.is_tensor(v):
                inputs[k] = v.to(target_device)

        # Generate
        t0 = time.time()
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=None,
                cfg_scale=self.config.cfg_scale,
                tokenizer=self._processor.tokenizer,
                generation_config={"do_sample": False},
                verbose=False,
                is_prefill=not self.config.disable_prefill,
            )
        gen_time = time.time() - t0

        # Extract audio
        audio = outputs.speech_outputs[0] if outputs.speech_outputs else None
        duration = 0.0
        if audio is not None:
            audio_samples = audio.shape[-1] if len(audio.shape) > 0 else len(audio)
            duration = audio_samples / self.config.sample_rate

        return TTSOutput(
            audio=audio,
            text=text,
            speaker=", ".join(speaker_names_used),
            duration=duration,
            generation_time=gen_time,
            sample_rate=self.config.sample_rate,
        )

    def save(self, output: TTSOutput, path: str | Path | None = None) -> str:
        """Save TTS output to a WAV file."""
        if output.audio is None:
            raise ValueError("No audio to save")

        if path is None:
            out_dir = HERE / self.config.output_dir
            out_dir.mkdir(exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = out_dir / f"tts_{timestamp}.wav"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self._processor.save_audio(output.audio, output_path=str(path))
        output.output_path = str(path)
        log.info("vibevoice: saved %s (%.1fs audio)", path, output.duration)
        return str(path)

    def speak_and_save(
        self,
        text: str,
        speaker: str | None = None,
        path: str | Path | None = None,
        **kwargs: Any,
    ) -> str:
        """Convenience: generate speech and save to file."""
        output = self.speak(text, speaker=speaker, **kwargs)
        return self.save(output, path)

    def announce_pipeline(
        self,
        session_name: str,
        result: str,
        speaker: str | None = None,
    ) -> str | None:
        """Announce pipeline completion with TTS.

        Parameters
        ----------
        session_name:
            Name of the pipeline session.
        result:
            Pipeline result summary (e.g. "PASS — 3 files, 2 iterations").
        speaker:
            Speaker voice to use.
        """
        text = f"Pipeline session {session_name} has completed. {result}"
        try:
            return self.speak_and_save(text, speaker=speaker)
        except Exception as exc:
            log.warning("vibevoice: announcement failed: %s", exc)
            return None


# ── CLI entry point ──────────────────────────────────────────────────

def main() -> None:
    """CLI interface for VibeVoice TTS."""
    parser = argparse.ArgumentParser(
        description="VibeVoice TTS — generate speech from text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python virgo_vibevoice.py --text "Hello world" --speaker Alice
  python virgo_vibevoice.py --file script.txt --speaker Alice Frank
  python virgo_vibevoice.py --text "Done" --announce --session my_run
  python virgo_vibevoice.py --list-speakers
  python virgo_vibevoice.py --text "Hello" --output hello.wav
        """,
    )
    parser.add_argument("--text", "-t", help="Text to synthesize")
    parser.add_argument("--file", "-f", help="Text file to synthesize")
    parser.add_argument(
        "--speaker", "-s", default="Alice",
        help="Speaker name (e.g. Alice, Frank, Maya)",
    )
    parser.add_argument(
        "--speakers", nargs="+",
        help="Multiple speaker names for multi-speaker scripts",
    )
    parser.add_argument("--output", "-o", help="Output WAV file path")
    parser.add_argument(
        "--model", "-m", default="1.5B", choices=["0.5B", "1.5B", "7B"],
        help="Model size (default: 1.5B)",
    )
    parser.add_argument(
        "--device", "-d", default="auto",
        help="Device: auto, cpu, cuda, mps (default: auto)",
    )
    parser.add_argument("--announce", action="store_true", help="Announce pipeline completion")
    parser.add_argument("--session", help="Pipeline session name (for --announce)")
    parser.add_argument("--result", help="Pipeline result text (for --announce)")
    parser.add_argument("--list-speakers", action="store_true", help="List available speakers")
    parser.add_argument("--cfg-scale", type=float, default=1.3, help="CFG scale (default: 1.3)")
    parser.add_argument("--no-voice-clone", action="store_true", help="Disable voice cloning")

    args = parser.parse_args()

    # List speakers
    if args.list_speakers:
        speakers = list_speakers()
        print("Available speakers:")
        for s in speakers:
            vp = get_voice_path(s)
            print(f"  {s:12s}  → {vp.name if vp else '(no voice)'}")
        return

    # Get text
    text = args.text
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    if not text:
        parser.error("Provide --text or --file")

    # Configure
    config = TTSConfig(
        model_size=args.model,
        device=args.device,
        speaker=args.speaker,
        cfg_scale=args.cfg_scale,
        disable_prefill=args.no_voice_clone,
    )

    tts = VibeVoiceTTS(config)

    # Announce mode
    if args.announce:
        session = args.session or "unknown"
        result = args.result or "completed"
        output_path = tts.announce_pipeline(session, result, speaker=args.speaker)
        if output_path:
            print(f"Announcement saved: {output_path}")
        return

    # Generate speech
    print(f"Generating speech with {config.model_size} model...")
    output = tts.speak(
        text,
        speaker=args.speaker,
        speakers=args.speakers,
    )

    # Save
    path = tts.save(output, args.output)
    print(f"Generated: {output.duration:.1f}s audio in {output.generation_time:.1f}s")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()

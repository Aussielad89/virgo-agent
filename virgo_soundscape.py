"""
virgo_soundscape — Ambient soundtrack engine for Virgo Desktop.

Generates continuous ambient audio whose timbre, tempo, and harmonic
content shift based on pipeline activity. Idle = soft pad, running =
rhythmic pulse, error = dissonant undertone.

Uses winsound on Windows for actual audio. Graceful fallback to
visual-only mode on other platforms.

State is persisted to .virgo_soundscape/state.json.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

STATE_DIR = HERE / ".virgo_soundscape"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "state.json"

_PHASE_CFG: dict[str, dict[str, Any]] = {
    "idle": {
        "base_freq": 220,
        "drift_range": 20,
        "tempo_bpm": 40,
        "dissonance": 0.0,
        "label": "Idle",
    },
    "discover": {
        "base_freq": 262,
        "drift_range": 30,
        "tempo_bpm": 60,
        "dissonance": 0.0,
        "label": "Discover",
    },
    "plan": {
        "base_freq": 294,
        "drift_range": 25,
        "tempo_bpm": 70,
        "dissonance": 0.1,
        "label": "Plan",
    },
    "generate": {
        "base_freq": 330,
        "drift_range": 35,
        "tempo_bpm": 80,
        "dissonance": 0.2,
        "label": "Generate",
    },
    "test": {
        "base_freq": 392,
        "drift_range": 40,
        "tempo_bpm": 100,
        "dissonance": 0.3,
        "label": "Test",
    },
    "fix": {
        "base_freq": 349,
        "drift_range": 45,
        "tempo_bpm": 90,
        "dissonance": 0.5,
        "label": "Fix",
    },
    "error": {
        "base_freq": 196,
        "drift_range": 50,
        "tempo_bpm": 120,
        "dissonance": 0.8,
        "label": "Error",
    },
    "done": {
        "base_freq": 523,
        "drift_range": 20,
        "tempo_bpm": 60,
        "dissonance": 0.0,
        "label": "Done",
    },
}


@dataclass
class SoundscapeState:
    active: bool = False
    phase: str = "idle"
    volume: float = 0.5
    genre: str = "ambient"
    elapsed_seconds: float = 0.0
    total_sessions: int = 0


_state = SoundscapeState()


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "active": False,
        "phase": "idle",
        "volume": 0.5,
        "genre": "ambient",
        "elapsed_seconds": 0.0,
        "total_sessions": 0,
    }


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _beep(frequency: int, duration: int) -> None:
    try:
        if sys.platform == "win32":
            import winsound  # noqa: PLC0415

            winsound.Beep(int(frequency), int(dur))
        else:
            os.system("printf '\\a' >/dev/null 2>&1 || true")
    except Exception:
        pass


def _play_ambient(stop_event: threading.Event, phase: str, volume: float) -> None:
    cfg = _PHASE_CFG.get(phase, _PHASE_CFG["idle"])
    base_freq = cfg["base_freq"]
    drift = cfg["drift_range"]
    tempo = cfg["tempo_bpm"]
    dissonance = cfg["dissonance"]

    beat_interval = 60.0 / max(tempo, 1)
    note_duration = int(beat_interval * 1000 * 0.6)
    start_time = time.time()

    while not stop_event.is_set():
        elapsed = time.time() - start_time
        # Drift the frequency over time
        drift_offset = math.sin(elapsed * 0.5) * drift
        freq = int(base_freq + drift_offset)
        # Add dissonant overtone at high dissonance levels
        if dissonance > 0.3:
            overtone = int(freq * (1.0 + dissonance * 0.5))
            _beep(overtone, note_duration // 2)
        _beep(freq, note_duration)
        # Wait for the rest of the beat
        sleep_time = beat_interval - (note_duration / 1000.0)
        if sleep_time > 0:
            stop_event.wait(sleep_time)


def start(phase: str = "idle", volume: float = 0.5) -> dict[str, Any]:
    global _state  # noqa: PLW0603

    if _state.active:
        stop()

    _state.phase = phase
    _state.volume = max(0.0, min(1.0, volume))
    _state.active = True
    _state.start_time = time.time()
    _state.total_sessions += 1
    _state.stop_event = threading.Event()

    _state.thread = threading.Thread(
        target=_play_ambient,
        args=(_state.stop_event, phase, _state.volume),
        daemon=True,
    )
    _state.thread.start()

    cfg = _PHASE_CFG.get(phase, _PHASE_CFG["idle"])
    return {
        "status": "started",
        "phase": phase,
        "label": cfg["label"],
        "tempo_bpm": cfg["tempo_bpm"],
        "dissonance": cfg["dissonance"],
        "session": _state.total_sessions,
    }


def stop() -> dict[str, Any]:
    global _state  # noqa: PLW0603

    if not _state.active:
        return {"status": "not_active"}

    _state.stop_event.set()
    if _state.thread and _state.thread.is_alive():
        _state.thread.join(timeout=2.0)

    elapsed = time.time() - _state.start_time
    _state.elapsed_seconds += elapsed
    _state.active = False

    return {
        "status": "stopped",
        "elapsed_seconds": round(elapsed, 1),
        "total_sessions": _state.total_sessions,
    }


def set_phase(phase: str) -> dict[str, Any]:
    global _state  # noqa: PLW0603

    _state.phase = phase
    if _state.active:
        # Restart with new phase
        stop()
        start(phase, _state.volume)
    return {"phase": phase, "label": _PHASE_CFG.get(phase, {}).get("label", phase)}


def set_volume(volume: float) -> dict[str, Any]:
    global _state  # noqa: PLW0603

    _state.volume = max(0.0, min(1.0, volume))
    return {"volume": _state.volume}


def status() -> dict[str, Any]:
    if _state.active:
        elapsed = time.time() - _state.start_time
        return {
            "active": True,
            "phase": _state.phase,
            "label": _PHASE_CFG.get(_state.phase, {}).get("label", _state.phase),
            "elapsed_seconds": round(elapsed, 1),
            "volume": _state.volume,
            "session": _state.total_sessions,
        }
    return {
        "active": False,
        "total_seconds": round(_state.elapsed_seconds, 1),
        "total_sessions": _state.total_sessions,
        "last_phase": _state.phase,
    }


def list_phases() -> list[dict[str, Any]]:
    return [
        {
            "phase": pid,
            "label": cfg["label"],
            "tempo_bpm": cfg["tempo_bpm"],
            "dissonance": cfg["dissonance"],
        }
        for pid, cfg in sorted(_PHASE_CFG.items())
    ]


def save_state() -> None:
    _save_state({
        "active": _state.active,
        "phase": _state.phase,
        "volume": _state.volume,
        "genre": _state.genre,
        "elapsed_seconds": _state.elapsed_seconds,
        "total_sessions": _state.total_sessions,
    })


def load_state() -> dict[str, Any]:
    return _load_state()


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Soundscape")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("start", help="Start soundscape")
    sub.add_parser("stop", help="Stop soundscape")
    sub.add_parser("status", help="Show status")
    sub.add_parser("phases", help="List available phases")
    args = p.parse_args()
    if args.command == "start":
        result = start()
        print(json.dumps(result, indent=2))
    elif args.command == "stop":
        result = stop()
        print(json.dumps(result, indent=2))
    elif args.command == "status":
        print(json.dumps(status(), indent=2))
    elif args.command == "phases":
        print(json.dumps(list_phases(), indent=2))
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
"""
virgo_focus — Background focus mode with ambient audio for Virgo.

Generates lo-fi / synthwave / nature ambient tones using winsound
(on Windows) or beep sequences. Designed to create a focused coding
environment while the pipeline runs.

Usage:
    virgo focus on                     # Start focus mode (default: lofi)
    virgo focus on --genre synthwave   # Start with specific genre
    virgo focus off                    # Stop focus mode
    virgo focus status                 # Show current state
    virgo focus genre                  # List available genres

Supports genres:
  - lofi       : Soft rhythmic beeps at 60 BPM (default)
  - synthwave  : Retro wave arpeggios at 90 BPM
  - ambient    : Gentle nature-style tones at 40 BPM
  - silence    : No audio, just timer tracking
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon

# ── Genre definitions ────────────────────────────────────────────────────

GENRES: dict[str, dict[str, Any]] = {
    "lofi": {
        "name": "Lo-Fi Beats",
        "bpm": 60,
        "description": "Soft rhythmic pulses — ideal for deep work",
        "frequencies": [262, 294, 330, 349, 330, 294, 262, 247],  # C D E F E D C B
        "duration_ms": 150,
        "pattern": "arpeggio",
    },
    "synthwave": {
        "name": "Synthwave",
        "bpm": 90,
        "description": "Retro wave arpeggios — cyberpunk coding vibes",
        "frequencies": [440, 554, 659, 880, 659, 554, 440, 554],  # A C#5 E5 A5 E5 C#5 A C#5
        "duration_ms": 180,
        "pattern": "arpeggio",
    },
    "ambient": {
        "name": "Nature Ambient",
        "bpm": 40,
        "description": "Gentle ambient drones — calm and focused",
        "frequencies": [220, 247, 262, 294],  # A3 B3 C4 D4
        "duration_ms": 500,
        "pattern": "drone",
    },
    "silence": {
        "name": "Silent Timer",
        "bpm": 0,
        "description": "No audio, just session timing",
        "frequencies": [],
        "duration_ms": 0,
        "pattern": "silent",
    },
}

# ── State ─────────────────────────────────────────────────────────────────


@dataclass
class FocusState:
    active: bool = False
    genre: str = "lofi"
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    start_time: float = 0.0
    elapsed_minutes: float = 0.0
    session_count: int = 0


_state = FocusState()


def _beep(frequency: int, duration: int) -> None:
    """Platform-aware beep. Uses winsound on Windows, fallback on others."""
    if os.name == "nt":
        try:
            import winsound  # noqa: PLC0415

            winsound.Beep(frequency, duration)
        except (ImportError, RuntimeError):
            pass  # Silently fail — no audio possible
    else:
        # On Linux/Mac: print a visual pulse instead of beeping
        char = "▁▂▃▄▅▆▇█" if sys.stdout.encoding and "utf" in sys.stdout.encoding.lower() else "*"
        bar = char * max(1, frequency // 100) if frequency else "·"
        print(f"\r  {bar}  ", end="", flush=True)


def _play_genre(genre: str, stop: threading.Event) -> None:
    """Background thread: play tones for the selected genre."""
    cfg = GENRES.get(genre, GENRES["lofi"])
    bpm = cfg["bpm"]
    frequencies = cfg["frequencies"]
    duration = cfg["duration_ms"]
    pattern = cfg["pattern"]

    if not frequencies or bpm == 0:
        # Silent mode — just mark time
        while not stop.is_set():
            stop.wait(1.0)
        return

    beat_interval = 60.0 / bpm  # seconds between notes
    idx = 0

    while not stop.is_set():
        freq = frequencies[idx % len(frequencies)]
        _beep(freq, duration)
        idx += 1
        # Wait for the rest of the beat interval
        sleep_time = beat_interval - (duration / 1000.0)
        if sleep_time > 0:
            stop.wait(sleep_time)
        # In drone mode, hold longer
        if pattern == "drone":
            stop.wait(beat_interval * 2)


def start(genre: str = "lofi") -> dict:
    """Start focus mode with the given genre. Returns state dict."""
    global _state  # noqa: PLW0603

    if genre not in GENRES:
        return {"error": f"Unknown genre '{genre}'. Use: {', '.join(GENRES)}"}

    if _state.active:
        stop()

    _state.genre = genre
    _state.stop_event = threading.Event()
    _state.active = True
    _state.start_time = time.time()
    _state.session_count += 1

    _state.thread = threading.Thread(
        target=_play_genre, args=(genre, _state.stop_event), daemon=True
    )
    _state.thread.start()

    cfg = GENRES[genre]
    return {
        "status": "started",
        "genre": genre,
        "name": cfg["name"],
        "description": cfg["description"],
        "session": _state.session_count,
    }


def stop() -> dict:
    """Stop focus mode. Returns final state."""
    global _state  # noqa: PLW0603

    if not _state.active:
        return {"status": "not_active"}

    _state.stop_event.set()
    if _state.thread and _state.thread.is_alive():
        _state.thread.join(timeout=2.0)

    elapsed = time.time() - _state.start_time
    _state.elapsed_minutes += elapsed / 60.0
    _state.active = False

    return {
        "status": "stopped",
        "elapsed_seconds": round(elapsed, 1),
        "elapsed_minutes": round(elapsed / 60.0, 1),
        "total_session_minutes": round(_state.elapsed_minutes, 1),
        "total_sessions": _state.session_count,
        "genre": _state.genre,
    }


def status() -> dict:
    """Return current focus state."""
    if _state.active:
        elapsed = time.time() - _state.start_time
        return {
            "active": True,
            "genre": _state.genre,
            "genre_name": GENRES.get(_state.genre, {}).get("name", _state.genre),
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_minutes": round(elapsed / 60.0, 1),
            "session": _state.session_count,
        }
    return {
        "active": False,
        "total_minutes": round(_state.elapsed_minutes, 1),
        "total_sessions": _state.session_count,
        "last_genre": _state.genre,
    }


def list_genres() -> list[dict]:
    """Return all available genres with descriptions."""
    return [
        {
            "id": gid,
            "name": cfg["name"],
            "description": cfg["description"],
            "bpm": cfg["bpm"],
        }
        for gid, cfg in sorted(GENRES.items())
    ]


def format_status_text(state: dict | None = None) -> str:
    """Format focus status as a human-readable string."""
    if state is None:
        state = status()

    if state.get("active"):
        genre_name = state.get("genre_name", state.get("genre", "?"))
        mins = state.get("elapsed_minutes", 0)
        secs = state.get("elapsed_seconds", 0)
        return (f"  {icon('brain')} Focus Mode: {genre_name} "
                f"[{int(mins)}m {int(secs % 60)}s]")
    return (f"  {icon('history')} Focus Mode: inactive "
            f"({state.get('total_sessions', 0)} sessions, "
            f"{round(state.get('total_minutes', 0), 1)} total minutes)")


# ── CLI handler functions (wired from cli.py) ─────────────────────────────


def cmd_focus_on(args: Any) -> None:
    """Turn focus mode on with optional genre."""
    genre = getattr(args, "genre", "lofi")
    result = start(genre)
    if "error" in result:
        print(f"\n  {icon('error')} {result['error']}")
        return
    cfg = GENRES[genre]
    print(f"\n  {icon('brain')} Focus Mode started — {cfg['name']}")
    print(f"  {cfg['description']}")
    print(f"  BPM: {cfg['bpm']}  |  Session #{result['session']}")


def cmd_focus_off(_args: Any) -> None:
    """Turn focus mode off."""
    result = stop()
    if result["status"] == "not_active":
        print(f"\n  {icon('arrow')} Focus mode is not active.")
        return
    print(f"\n  {icon('history')} Focus Mode stopped — "
          f"{result['elapsed_minutes']} minute(s)")
    print(f"  Total: {result['total_session_minutes']} minutes across "
          f"{result['total_sessions']} session(s)")


def cmd_focus_status(_args: Any) -> None:
    """Show focus mode status."""
    print(f"\n{format_status_text()}")


def cmd_focus_genre(_args: Any) -> None:
    """List available genres."""
    print(f"\n  {icon('brain')} Focus Mode — Available Genres")
    print(f"  {'─' * 50}")
    for g in list_genres():
        print(f"  {g['id']:12s}  {g['name']:18s}  {g['bpm']:3d} BPM  — {g['description']}")
    print()


# ── Self-test / standalone entry ─────────────────────────────────────────


def main() -> None:
    """Standalone entry for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Virgo Focus Mode")
    sub = parser.add_subparsers(dest="command")

    p_on = sub.add_parser("on", help="Start focus mode")
    p_on.add_argument("--genre", "-g", default="lofi",
                      choices=list(GENRES), help="Audio genre")

    sub.add_parser("off", help="Stop focus mode")
    sub.add_parser("status", help="Show status")
    sub.add_parser("genre", help="List genres")

    args = parser.parse_args()

    if args.command == "on":
        cmd_focus_on(args)
    elif args.command == "off":
        cmd_focus_off(args)
    elif args.command == "status":
        cmd_focus_status(args)
    elif args.command == "genre":
        cmd_focus_genre(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

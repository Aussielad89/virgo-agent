"""
virgo_soundpack — Event-triggered sound effects for Virgo.

Builds on the focus mode system to add contextual sound effects:
startup chimes, success fanfares, error buzzes, achievement dings.

Uses winsound on Windows for actual audio. Graceful fallback to
visual-only display on other platforms.

Usage:
    virgo soundpack list                    # List available packs
    virgo soundpack set retro               # Set active pack
    virgo soundpack test                    # Test current pack
    virgo soundpack off                     # Disable sound effects
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── Sound Pack Definitions ────────────────────────────────────────────────

SOUND_PACKS: dict[str, dict[str, Any]] = {
    "retro": {
        "name": "Retro Arcade",
        "description": "Classic 8-bit arcade beeps and boops",
        "sounds": {
            "startup": {"freq": 440, "duration": 150, "repeat": 2, "delay": 100},
            "success": {"freq": 880, "duration": 200, "repeat": 3, "delay": 80},
            "failure": {"freq": 220, "duration": 300, "repeat": 2, "delay": 150},
            "achievement": {"freq": 1047, "duration": 100, "repeat": 5, "delay": 50},
            "levelup": {"freq": 1319, "duration": 150, "repeat": 4, "delay": 100},
            "error": {"freq": 180, "duration": 400, "repeat": 1, "delay": 0},
            "notification": {"freq": 660, "duration": 100, "repeat": 2, "delay": 100},
            "scan": {"freq": 523, "duration": 80, "repeat": 8, "delay": 60},
            "mascot": {"freq": 784, "duration": 120, "repeat": 3, "delay": 90},
        },
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "description": "Dark synthwave-inspired tones",
        "sounds": {
            "startup": {"freq": 554, "duration": 200, "repeat": 3, "delay": 150},
            "success": {"freq": 740, "duration": 250, "repeat": 2, "delay": 200},
            "failure": {"freq": 185, "duration": 500, "repeat": 1, "delay": 0},
            "achievement": {"freq": 1109, "duration": 120, "repeat": 6, "delay": 60},
            "levelup": {"freq": 880, "duration": 180, "repeat": 5, "delay": 120},
            "error": {"freq": 150, "duration": 600, "repeat": 1, "delay": 0},
            "notification": {"freq": 698, "duration": 100, "repeat": 3, "delay": 80},
            "scan": {"freq": 440, "duration": 100, "repeat": 10, "delay": 50},
            "mascot": {"freq": 659, "duration": 150, "repeat": 4, "delay": 100},
        },
    },
    "nature": {
        "name": "Nature Ambient",
        "description": "Soft, organic tones inspired by nature",
        "sounds": {
            "startup": {"freq": 392, "duration": 300, "repeat": 1, "delay": 0},
            "success": {"freq": 523, "duration": 400, "repeat": 2, "delay": 200},
            "failure": {"freq": 196, "duration": 500, "repeat": 1, "delay": 0},
            "achievement": {"freq": 659, "duration": 250, "repeat": 3, "delay": 150},
            "levelup": {"freq": 784, "duration": 300, "repeat": 3, "delay": 200},
            "error": {"freq": 165, "duration": 600, "repeat": 1, "delay": 0},
            "notification": {"freq": 440, "duration": 200, "repeat": 1, "delay": 0},
            "scan": {"freq": 349, "duration": 150, "repeat": 6, "delay": 100},
            "mascot": {"freq": 587, "duration": 200, "repeat": 2, "delay": 150},
        },
    },
}

SOUND_EVENTS = sorted({
    event
    for pack in SOUND_PACKS.values()
    for event in pack.get("sounds", {})
})

# ── State ─────────────────────────────────────────────────────────────────

_state: dict[str, Any] = {
    "active": False,
    "pack": None,
    "muted": False,
}


def _load_state() -> dict:
    """Load persisted state from virgo_soundpack.json."""
    state_file = HERE / ".virgo_soundpack.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pack": "retro", "muted": False}


def _save_state() -> None:
    """Save state to virgo_soundpack.json."""
    state_file = HERE / ".virgo_soundpack.json"
    try:
        state_file.write_text(
            json.dumps({"pack": _state["pack"], "muted": _state["muted"]}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Failed to save soundpack state: %s", exc)


def _beep(freq: int, duration: int) -> None:
    """Single beep via winsound (Windows) or visual fallback."""
    if _state.get("muted"):
        return
    if os.name == "nt":
        try:
            import winsound  # noqa: PLC0415
            winsound.Beep(freq, duration)
        except (ImportError, RuntimeError):
            pass
    else:
        # Visual pulse fallback
        bar = "█" * max(1, freq // 100)
        print(f"\r  ♪ {bar}  ", end="", flush=True)
        time.sleep(duration / 1000)


def _play_sound(event: str) -> None:
    """Play a sound event from the active pack."""
    if _state.get("muted") or not _state.get("active"):
        return

    pack = _state.get("pack", "retro")
    pack_def = SOUND_PACKS.get(pack, SOUND_PACKS["retro"])
    sound = pack_def.get("sounds", {}).get(event)

    if not sound:
        return

    freq = sound["freq"]
    duration = sound["duration"]
    repeat = sound.get("repeat", 1)
    delay = sound.get("delay", 100)

    for _ in range(repeat):
        _beep(freq, duration)
        if delay > 0:
            time.sleep(delay / 1000)


def play(event: str) -> None:
    """Play a sound event in a background thread (non-blocking)."""
    if not _state.get("active") or _state.get("muted"):
        return
    t = threading.Thread(target=_play_sound, args=(event,), daemon=True)
    t.start()


def set_pack(name: str) -> dict:
    """Set the active sound pack."""
    if name not in SOUND_PACKS:
        raise KeyError(f"Unknown sound pack '{name}'. Available: {', '.join(SOUND_PACKS)}")
    _state["pack"] = name
    _state["active"] = True
    _save_state()
    pack = SOUND_PACKS[name]
    log.info("Sound pack set to '%s' (%s)", name, pack["name"])
    return {"pack": name, "name": pack["name"], "active": True}


def get_pack() -> dict:
    """Get current sound pack info."""
    loaded = _load_state()
    _state["pack"] = loaded.get("pack", "retro")
    _state["muted"] = loaded.get("muted", False)
    _state["active"] = not _state["muted"]
    pack = SOUND_PACKS.get(_state["pack"], SOUND_PACKS["retro"])
    return {"pack": _state["pack"], "name": pack["name"], "active": _state["active"]}


def list_packs() -> list[dict]:
    """List all available sound packs."""
    return [
        {"id": pid, "name": cfg["name"], "description": cfg["description"],
         "sounds": len(cfg.get("sounds", {}))}
        for pid, cfg in SOUND_PACKS.items()
    ]


def list_events() -> list[str]:
    """List all available sound event types."""
    return SOUND_EVENTS


def mute() -> dict:
    """Mute all sound effects."""
    _state["muted"] = True
    _state["active"] = False
    _save_state()
    return {"status": "muted"}


def unmute() -> dict:
    """Unmute sound effects."""
    _state["muted"] = False
    _state["active"] = True
    _save_state()
    return {"status": "unmuted"}


def toggle() -> dict:
    """Toggle sounds on/off."""
    if _state.get("muted") or not _state.get("active"):
        return unmute()
    return mute()


def test_pack() -> None:
    """Play all sounds in the current pack as a test."""
    pack = SOUND_PACKS.get(_state.get("pack", "retro"), SOUND_PACKS["retro"])
    pack_name = pack["name"]
    print(f"\n  {icon('brain')} Testing Sound Pack: {pack_name}")
    for event in pack.get("sounds", {}):
        print(f"  ♪ {event}...")
        _play_sound(event)
        time.sleep(0.2)
    print(f"  {icon('rocket')} Sound pack test complete.\n")


# ── Init ──────────────────────────────────────────────────────────────────

def init() -> None:
    """Initialize sound pack from saved state."""
    loaded = _load_state()
    _state["pack"] = loaded.get("pack", "retro")
    _state["muted"] = loaded.get("muted", False)
    _state["active"] = not _state["muted"]


# ── CLI handlers ──────────────────────────────────────────────────────────

init()


def cmd_soundpack(args: Any) -> None:
    """Handle soundpack subcommands."""
    cmd = getattr(args, "soundpack_command", None)

    if cmd == "list" or not cmd:
        packs = list_packs()
        current = _state.get("pack", "retro")
        print(f"\n  {icon('brain')} Sound Packs")
        print(f"  {'─' * 50}")
        for p in packs:
            marker = " ◀" if p["id"] == current else ""
            print(f"  [{p['id']:12s}] {p['name']:20s}  {p['description']}{marker}")
        print(f"\n  Events: {', '.join(list_events())}")
        print()

    elif cmd == "set":
        try:
            result = set_pack(args.name)
            print(f"\n  {icon('rocket')} Sound pack set to: {result['name']}")
        except KeyError as e:
            print(f"\n  {icon('error')} {e}")

    elif cmd == "test":
        test_pack()

    elif cmd == "off":
        result = mute()
        print(f"\n  {icon('history')} Sound effects: {result['status']}")

    elif cmd == "on":
        result = unmute()
        print(f"\n  {icon('rocket')} Sound effects: {result['status']}")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virgo Sound Pack System")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="List packs")
    p_set = sub.add_parser("set", help="Set active pack")
    p_set.add_argument("name", choices=list(SOUND_PACKS), help="Pack name")
    sub.add_parser("test", help="Test all sounds")
    sub.add_parser("off", help="Mute")
    sub.add_parser("on", help="Unmute")
    args = parser.parse_args()

    if args.command == "list":
        packs = list_packs()
        for p in packs:
            print(f"  {p['id']:12s}  {p['name']:20s}  {p['description']}")
    elif args.command == "set":
        result = set_pack(args.name)
        print(f"Set to: {result['name']}")
    elif args.command == "test":
        test_pack()
    elif args.command == "off":
        mute()
        print("Muted")
    elif args.command == "on":
        unmute()
        print("Unmuted")
    else:
        parser.print_help()

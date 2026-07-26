"""
virgo_mascot — persistent AI sidekick mascot for Virgo.

Provides a collection of terminal mascots (CyberCat, GhostBot, HackFox,
PixelDragon) that idle, react to events, and speak via ASCII art.
The active mascot is persisted in .virgo_mascot.json in the project root.
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── ANSI color helpers ───────────────────────────────────────────────────
_R = "\033[0m"  # Reset
_B = "\033[1m"  # Bold
_I = "\033[3m"  # Italic
_U = "\033[4m"  # Underline

# Theme colors
_CYAN = "\033[96m"
_PINK = "\033[95m"
_ORANGE = "\033[33m"
_GREEN = "\033[92m"
_GOLD = "\033[93m"
_WHITE = "\033[97m"
_RED = "\033[91m"


# ── Mascot definitions ───────────────────────────────────────────────────

_MASCOTS: dict[str, dict] = {
    "cybercat": {
        "tag": "cybercat",
        "display": "CyberCat",
        "ascii": (
            "  /\\_/\\\n"
            " ( o.o )\n"
            "  > ^ <"
        ),
        "idle_animations": [
            "*purrs softly*",
            "*stretches paws*",
            "*batches at cursor*",
            "*curls up on keyboard*",
        ],
        "reactions": {
            "success": [
                "*purrs contentedly*",
                "Great code, human!",
                "Meow-velous!",
            ],
            "fail": [
                "*tilts head*",
                "Hmm, that didn't work...",
                "Let's try again!",
            ],
            "alert": [
                "*ears perk up*",
                "Something's happening!",
            ],
        },
        "color": _PINK,
    },
    "ghostbot": {
        "tag": "ghostbot",
        "display": "GhostBot",
        "ascii": (
            "  .-. \n"
            " (O O)\n"
            "  | | \n"
            "  '`'"
        ),
        "idle_animations": [
            "*floats silently*",
            "*phases through wall*",
            "*beeps gently*",
            "*glitches*",
        ],
        "reactions": {
            "success": [
                "*winks*",
                "I see dead... bugs!",
                "Boo-tyful!",
            ],
            "fail": [
                "*flickers*",
                "Ectoplasm in the circuits!",
                "Spooky error...",
            ],
            "alert": [
                "*materializes*",
                "I sense a disturbance...",
            ],
        },
        "color": _CYAN,
    },
    "hackfox": {
        "tag": "hackfox",
        "display": "HackFox",
        "ascii": (
            "  /\\ /\\ \n"
            " ( o.o )\n"
            "  > ^ <\n"
            "  \u2500\u2500\u2500\u2500\u2500"
        ),
        "idle_animations": [
            "*cocks ear*",
            "*wags tail*",
            "*pounces on bug*",
            "*sneaks through firewall*",
        ],
        "reactions": {
            "success": [
                "*yips happily*",
                "Sneaky code works!",
                "Fox-tastic!",
            ],
            "fail": [
                "*whines*",
                "The fox is stuck...",
                "Need a cleverer trick.",
            ],
            "alert": [
                "*sniffs the air*",
                "Something's on the network...",
            ],
        },
        "color": _ORANGE,
    },
    "pixeldragon": {
        "tag": "pixeldragon",
        "display": "PixelDragon",
        "ascii": (
            "   ___  \n"
            "  /   \\ \n"
            " | o_o |\n"
            "  \\_-_/ \n"
            "  --^--"
        ),
        "idle_animations": [
            "*breathes tiny sparks*",
            "*curls tail*",
            "*scans horizon*",
            "*flaps wings*",
        ],
        "reactions": {
            "success": [
                "*roars happily*",
                "Burn the bugs!",
                "Dragon-fire code!",
            ],
            "fail": [
                "*huffs smoke*",
                "A dragon never gives up!",
                "Let me breathe fire on this bug.",
            ],
            "alert": [
                "*perks up*",
                "I sense prey...",
            ],
        },
        "color": _GREEN,
    },
}

_MASCOT_FILE = HERE / ".virgo_mascot.json"


# ── Persistence helpers ──────────────────────────────────────────────────

def _load_mascot_name() -> str:
    """Read the active mascot name from .virgo_mascot.json."""
    try:
        if not _MASCOT_FILE.exists():
            return "cybercat"
        import threading
        result = []
        def _read():
            try:
                data = json.loads(_MASCOT_FILE.read_text(encoding="utf-8"))
                name = data.get("mascot", "")
                if name in _MASCOTS:
                    result.append(name)
                else:
                    result.append("cybercat")
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load mascot config: %s", exc)
                result.append("cybercat")
        thread = threading.Thread(target=_read)
        thread.daemon = True
        thread.start()
        thread.join(timeout=0.5)
        if result:
            return result[0]
    except Exception:
        pass
    return "cybercat"


def _save_mascot_name(name: str) -> None:
    """Persist the active mascot name to .virgo_mascot.json."""
    try:
        temp_file = _MASCOT_FILE.with_suffix('.tmp')
        temp_file.write_text(
            json.dumps({"mascot": name}, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(_MASCOT_FILE)
    except OSError as exc:
        log.error("Failed to save mascot config: %s", exc)


# ── Public API ───────────────────────────────────────────────────────────

def get_mascot(name: str | None = None) -> dict:
    """Return the current mascot dict, or look up *name* if provided.

    Raises KeyError if *name* is not a known mascot.
    """
    if name is None:
        name = _load_mascot_name()
    if name not in _MASCOTS:
        msg = f"Unknown mascot: {name!r}. Choose from: {', '.join(_MASCOTS)}"
        raise KeyError(msg)
    return dict(_MASCOTS[name])


def set_mascot(name: str) -> dict:
    """Set the active mascot, save to disk, and return its definition.

    Raises KeyError if *name* is unknown.
    """
    if name not in _MASCOTS:
        msg = f"Unknown mascot: {name!r}. Choose from: {', '.join(_MASCOTS)}"
        raise KeyError(msg)
    _save_mascot_name(name)
    log.info("Active mascot set to %s", name)
    return dict(_MASCOTS[name])


def list_mascots() -> list[dict]:
    """Return all available mascot definitions."""
    return [dict(m) for m in _MASCOTS.values()]


def current_mascot_name() -> str:
    """Return the tag of the currently active mascot."""
    return _load_mascot_name()


def idle_action() -> str:
    """Return a random idle animation string from the current mascot."""
    mascot = get_mascot()
    animations = mascot.get("idle_animations", [])
    return random.choice(animations) if animations else ""


def react(event: str, result: str = "success") -> str:
    """Return a reaction string based on *event* type and *result*.

    Parameters
    ----------
    event : str
        One of ``"pipeline"``, ``"scan"``, ``"build"``, ``"alert"``.
        Currently used only for logging context; reactions are selected
        by *result*.
    result : str
        One of ``"success"``, ``"fail"``, ``"info"`` (default ``"success"``).

    Returns
    -------
    str
        A random reaction string from the current mascot's reactions for
        the given *result*.
    """
    mascot = get_mascot()
    reactions = mascot.get("reactions", {})
    pool = reactions.get(result, reactions.get("success", []))
    reaction = random.choice(pool) if pool else ""
    log.debug("Mascot reaction: event=%s result=%s msg=%s", event, result, reaction)
    return reaction


def mascot_ascii(name: str | None = None) -> str:
    """Return the ASCII art for the given *name* (or the current mascot)."""
    mascot = get_mascot(name)
    return mascot.get("ascii", "")


def cheer(result: str = "success") -> str:
    """Shorthand for ``react("pipeline", result)``."""
    return react("pipeline", result)


def speak(text: str, mascot_name: str | None = None) -> str:
    """Format *text* as spoken by the mascot.

    Returns a string like::

        <ascii> MascotName: <text>

    When *mascot_name* is ``None`` the current active mascot is used.
    """
    mascot = get_mascot(mascot_name)
    ascii_art = mascot.get("ascii", "")
    display = mascot.get("display", "Mascot")
    return f"{ascii_art}\n{display}: {text}"


def mascot_color(name: str | None = None) -> str:
    """Return the ANSI color escape code for the given mascot.

    Returns
    -------
    str
        ANSI escape sequence (e.g. ``\\033[95m`` for CyberCat).
        Falls back to empty string if no color is defined.
    """
    mascot = get_mascot(name)
    return mascot.get("color", "")


def colored_ascii(name: str | None = None) -> str:
    """Return the mascot's ASCII art wrapped in its ANSI colour codes."""
    mascot = get_mascot(name)
    color = mascot.get("color", "")
    ascii_art = mascot.get("ascii", "")
    if color:
        return f"{color}{ascii_art}{_R}"
    return ascii_art


# ── CLI handlers ─────────────────────────────────────────────────────────

def cmd_mascot_list(args: list[str] | None = None) -> None:
    """Show all available mascots with their display names and tags."""
    print(f"{icon('info')} Available mascots:")
    for mascot in list_mascots():
        tag = mascot["tag"]
        display = mascot["display"]
        color = mascot.get("color", "")
        marker = ">" if tag == current_mascot_name() else " "
        line = f"  {marker} {color}{display}{_R} ({tag})"
        print(line)


def cmd_mascot_set(args: list[str] | None = None) -> None:
    """Set the active mascot.

    Usage: virgo mascot set <name>
    """
    if not args:
        print(f"{icon('error')} Usage: virgo mascot set <name>")
        names = ", ".join(_MASCOTS)
        print(f"  Available: {names}")
        return
    name = args[0]
    try:
        mascot = set_mascot(name)
        print(f"{icon('ok')} Active mascot set to {mascot['display']}")
        print(colored_ascii(name))
    except KeyError as exc:
        print(f"{icon('error')} {exc}")


def cmd_mascot_speak(args: list[str] | None = None) -> None:
    """Make the current mascot say something.

    Usage: virgo mascot speak <text...>
    """
    if not args:
        print(f"{icon('error')} Usage: virgo mascot speak <message>")
        return
    text = " ".join(args)
    print(speak(text))


def cmd_mascot_show(args: list[str] | None = None) -> None:
    """Show the current mascot with its ASCII art."""
    name = args[0] if args else None
    mascot = get_mascot(name)
    ascii_art = mascot_ascii(name)
    display = mascot["display"]
    tag = mascot["tag"]
    print(f"{icon('info')} {display} ({tag})")
    print(colored_ascii(name))

    # Show a sample idle animation
    animations = mascot.get("idle_animations", [])
    if animations:
        print(f"  {random.choice(animations)}")


# ── Module-level init ───────────────────────────────────────────────────

# Ensure the active mascot is valid on import
_active_name = _load_mascot_name()
if _active_name not in _MASCOTS:
    _active_name = "cybercat"

# ── Personality Engine (#19) ─────────────────────────────────────────────

_MOOD_STORE = HERE / ".virgo_mascot_mood.json"
_MOODS = ["happy", "neutral", "sleepy", "excited", "sad", "playful"]
_MOOD_EMOJIS = {
    "happy": "😊", "neutral": "😐", "sleepy": "😴",
    "excited": "🤩", "sad": "😢", "playful": "😜",
}


def _load_mood() -> str:
    """Load saved mascot mood."""
    try:
        if _MOOD_STORE.exists():
            data = json.loads(_MOOD_STORE.read_text())
            return data.get("mood", "neutral")
    except Exception:
        pass
    return "neutral"


def _save_mood(mood: str) -> None:
    """Persist mascot mood."""
    try:
        _MOOD_STORE.write_text(json.dumps({"mood": mood, "name": _active_name}))
    except Exception:
        pass


def current_mood() -> str:
    """Get the current mascot mood."""
    return _load_mood()


def set_mood(mood: str) -> str:
    """Set mascot mood. Returns the mood name."""
    if mood not in _MOODS:
        mood = "neutral"
    _save_mood(mood)
    return mood


def react_to_event(event: str, success: bool = True) -> str:
    """Change mascot mood based on an event and return a reaction message."""
    mood_changes = {
        "pipeline_success": "excited",
        "pipeline_fail": "sad",
        "chat_long": "playful",
        "scan_complete": "happy",
        "idle_long": "sleepy",
        "achievement": "excited",
        "startup": "neutral",
    }
    new_mood = mood_changes.get(event, "neutral")
    if not success:
        new_mood = "sad"
    set_mood(new_mood)

    reactions = {
        "excited": [
            "That was AMAZING! 🎉", "Wooohooo! You rock!",
            "I'm so pumped right now!",
        ],
        "happy": [
            "*purrs contentedly*", "Everything's going great!",
            "Nice work, partner!",
        ],
        "playful": [
            "*boops your nose*", "Hehe, that was fun!",
            "Let's do that again!",
        ],
        "sleepy": [
            "*yawns* zzz...", "Is it nap time yet?",
            "Five more minutes... 😴",
        ],
        "sad": [
            "*ears droop* Aww...", "It's okay, we'll get it next time.",
            "*gives you a gentle headbutt*",
        ],
        "neutral": [
            "Ready when you are.", "I'm here.", "What's next?",
        ],
    }
    return random.choice(reactions.get(new_mood, reactions["neutral"]))


def mood_ascii(mood: str | None = None) -> str:
    """Return a mood indicator string for the current mascot."""
    if mood is None:
        mood = current_mood()
    emoji = _MOOD_EMOJIS.get(mood, "😐")
    return f"{emoji}  {mood.capitalize()}"


# Auto-export key functions for public API
__all__ = [
    "current_mascot_name", "get_mascot", "list_mascots",
    "set_mascot", "mascot_ascii", "idle_action", "colored_ascii",
    "react", "speak", "cheer",
    "current_mood", "set_mood", "react_to_event", "mood_ascii",
]
_save_mascot_name(_active_name)

log.debug("Active mascot: %s", _active_name)

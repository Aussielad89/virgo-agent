"""
virgo_chaos — Chaos Mode for Virgo Agent Framework.

A toggle-able system that injects controlled randomness, humor, and easter
eggs into Virgo's output.  When enabled, it adds random emojis, occasional
jokes, surprise ASCII art, and fun variations to commands and pipeline output.

State is persisted in ``.virgo_chaos.json`` in the project root.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── ANSI color helpers ───────────────────────────────────────────────────
_R = "\033[0m"  # Reset
_B = "\033[1m"  # Bold
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_PINK = "\033[95m"
_RED = "\033[91m"
_ORANGE = "\033[33m"

# ── Persistence file ────────────────────────────────────────────────────
_CHAOS_FILE = HERE / ".virgo_chaos.json"

# ── Default state ────────────────────────────────────────────────────────
_DEFAULT_STATE: dict[str, Any] = {
    "enabled": False,
    "intensity": 3,  # 1 (mild) … 5 (maximum chaos)
}

# ── Programming dad jokes (at least 10) ──────────────────────────────────
_JOKES: list[str] = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "How many programmers does it take to change a light bulb? None, that's a hardware problem.",
    "I don't test my code. But when I do, I do it in production.",
    "There are only 10 kinds of people: those who understand binary and those who don't.",
    "Why did the developer go broke? Because he used up all his cache.",
    "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?'",
    "Why do Java developers wear glasses? Because they can't C#.",
    "How do you tell an extroverted programmer from an introverted one? "
    "The extroverted one stares at YOUR shoes while talking.",
    "What's a programmer's favorite hangout place? The Foo Bar.",
    "Why did the programmer quit his job? Because he didn't get arrays.",
    "A programmer's wife tells him: 'Go to the store and get a carton of milk. "
    "If they have eggs, get a dozen.' He comes back with 12 cartons of milk.",
    "I would tell you a UDP joke, but you might not get it.",
    "There is no place like 127.0.0.1.",
    "What do you call a programmer from Finland? Nerdic.",
    "Why was the JavaScript developer sad? Because he didn't know how to 'null' his feelings.",
]

# ── Interjections (at least 20) ──────────────────────────────────────────
_INTERJECTIONS: dict[int, list[str]] = {
    1: [
        "Just saying…",
        "Heads up!",
        "By the way…",
        "Friendly reminder:",
    ],
    2: [
        "Buckle up!",
        "Plot twist:",
        "Wait for it…",
        "Drumroll, please!",
    ],
    3: [
        "Here be dragons!",
        "Chaos reigns!",
        "Breaking all the rules!",
        "Mayhem mode: ON",
    ],
    4: [
        "Unleash the kraken!",
        "Absolute pandemonium!",
        "The chaos goblins are loose!",
        "Abandon all reason!",
    ],
    5: [
        "MAXIMUM OVERCHAOS!",
        "The universe is unraveling!",
        "REALITY: OFFLINE",
        "Let there be CHAOS!",
    ],
}

# ── Easter egg commands ──────────────────────────────────────────────────
_EASTER_EGGS: dict[str, str] = {
    "make me a sandwich": "sudo make me a sandwich",
    "uptime": "up 42 minutes (since last coffee)",
    "why": (
        "42 — because some questions are too deep for mere code. "
        "Also, the meaning of life, the universe, and everything."
    ),
    "42": "The answer to life, the universe, and everything.",
    "/hack": "HACKING THE MAINFRAME… ████████ 100%\nAccess granted. Nothing to see here.",
}

# ── Silly typos for inject_typo ──────────────────────────────────────────
_TYPOS: dict[str, list[str]] = {
    "the": ["teh", "hte", "te"],
    "and": ["adn", "nad", "an"],
    "file": ["fiel", "flie", "filr"],
    "code": ["cdoe", "coed", "codr"],
    "test": ["tets", "tst", "teest"],
    "error": ["eror", "errror", "erorr"],
    "build": ["buidl", "buld", "buiid"],
    "deploy": ["deply", "deplo", "depoy"],
    "config": ["conifg", "cofnig", "conig"],
}

# ── Emoji pools per intensity for maybe_embellish ────────────────────────
_EMOJIS: dict[int, list[str]] = {
    1: ["✨", "👉"],
    2: ["✨", "👉", "🚀", "💡"],
    3: ["✨", "👉", "🚀", "💡", "🔥", "🎯", "⚡", "💥"],
    4: ["✨", "👉", "🚀", "💡", "🔥", "🎯", "⚡", "💥", "🎉", "🤯", "👾", "🤖"],
    5: [
        "✨", "👉", "🚀", "💡", "🔥", "🎯", "⚡", "💥", "🎉", "🤯",
        "👾", "🤖", "🛸", "👻", "💀", "🎪", "🌈", "🌀", "⚡", "💫",
    ],
}

# ── Embellishment decorators per intensity ───────────────────────────────
_DECORATORS: dict[int, list[str]] = {
    1: ["", "", "", ""],  # Mostly nothing at mild
    2: ["", "", " ― ", " "],
    3: ["", " → ", " ― ", " « "],
    4: [" → ", " « ", " » ", " ✦ "],
    5: [" → ", " « ", " » ", " ✦ ", " ═══ "],
}

# ── Format-output context embellishments ─────────────────────────────────
_CONTEXT_EMOJIS: dict[str, str] = {
    "success": "✅",
    "fail": "❌",
    "info": "ℹ️",
    "error": "🚨",
    "progress": "⏳",
    "generic": "",
}

_CONTEXT_PREFIXES: dict[str, list[str]] = {
    "success": ["Great success!", "Nailed it!", "All good!", "Like a charm!", "Boom!"],
    "fail": ["Oof.", "Well, that didn't work.", "Yikes.", "Not today, Satan."],
    "info": ["PSST:", "FYI:", "Heads up:", "For the record:"],
    "error": ["🔥 FIRE! 🔥", "💀 CRITICAL 💀", "🚨 PANIC 🚨", "ABORT MISSION!"],
    "progress": ["Working on it…", "Almost there…", "Processing…", "Hold my beer…"],
    "generic": [],
}

# ── ASCII art snippets (surprise) ────────────────────────────────────────
_ASCII_ART: dict[int, list[str]] = {
    1: [],
    2: ["(¬_¬)", "(•_•)", "(⌐■_■)"],
    3: [
        "  ╱▔▔╲\n ╱◠‿◠╲\n╱       ╲",
        "  _   _\n (.)_(.)\n  (   )",
    ],
    4: [
        "  ╱▔▔╲\n ╱◠‿◠╲\n╱       ╲",
        "  _   _\n (.)_(.)\n  (   )",
        "    ___\n   /   \\\n  | ^_^ |\n   \\___/",
    ],
    5: [
        "  ╱▔▔╲\n ╱◠‿◠╲\n╱       ╲",
        "  _   _\n (.)_(.)\n  (   )",
        "    ___\n   /   \\\n  | ^_^ |\n   \\___/",
        "   .--.\n  /    \\\n  |    |\n  \\__/",
    ],
}


# ── State helpers ────────────────────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    """Read chaos state from ``.virgo_chaos.json``."""
    try:
        if _CHAOS_FILE.exists():
            data = json.loads(_CHAOS_FILE.read_text(encoding="utf-8"))
            if "enabled" in data and "intensity" in data:
                return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load chaos config: %s", exc)
    return dict(_DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    """Persist chaos state to ``.virgo_chaos.json``."""
    try:
        _CHAOS_FILE.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.error("Failed to save chaos config: %s", exc)


# Current in-memory state (synced on import)
_state = _load_state()


# ── Public API ───────────────────────────────────────────────────────────

def is_chaos_enabled() -> bool:
    """Check if chaos mode is currently enabled."""
    return bool(_state.get("enabled", False))


def set_chaos(enabled: bool) -> dict:
    """Enable or disable chaos mode and persist the setting.

    Parameters
    ----------
    enabled : bool
        ``True`` to enable, ``False`` to disable.

    Returns
    -------
    dict
        The current full state dictionary (``enabled`` + ``intensity``).
    """
    _state["enabled"] = enabled
    _save_state(_state)
    status = "enabled" if enabled else "disabled"
    log.info("Chaos mode %s (intensity=%d)", status, _state["intensity"])
    return dict(_state)


def toggle_chaos() -> dict:
    """Toggle chaos mode and return the new state.

    Returns
    -------
    dict
        The full state dictionary after toggling.
    """
    current = is_chaos_enabled()
    return set_chaos(not current)


def chaos_intensity() -> int:
    """Return the current intensity level (1–5). Default: 3."""
    return int(_state.get("intensity", 3))


def set_intensity(level: int) -> dict:
    """Set chaos intensity level.

    Parameters
    ----------
    level : int
        Intensity level 1 (mild) to 5 (maximum chaos).
        Clamped to valid range automatically.

    Returns
    -------
    dict
        The full state dictionary after update.
    """
    level = max(1, min(5, level))
    _state["intensity"] = level
    _save_state(_state)
    log.info("Chaos intensity set to %d", level)
    return dict(_state)


def maybe_embellish(text: str) -> str:
    """With probability based on intensity, add emoji/decoration to *text*.

    Higher intensity = higher chance of embellishment and more lavish
    decorations.
    """
    if not is_chaos_enabled():
        return text

    intensity = chaos_intensity()
    # Probability per intensity: 1→0.1, 2→0.25, 3→0.40, 4→0.60, 5→0.85
    prob = {1: 0.1, 2: 0.25, 3: 0.40, 4: 0.60, 5: 0.85}.get(intensity, 0.4)
    if random.random() > prob:
        return text

    # Pick a random emoji and decorator
    emoji_pool = _EMOJIS.get(intensity, _EMOJIS[3])
    decorator_pool = _DECORATORS.get(intensity, _DECORATORS[3])
    emoji = random.choice(emoji_pool)
    decorator = random.choice(decorator_pool)

    # 40% chance → prefix emoji, 40% → suffix, 20% → both
    roll = random.random()
    if roll < 0.4:
        return f"{emoji} {text}"
    elif roll < 0.8:
        return f"{text} {emoji}"
    else:
        return f"{emoji} {decorator}{text}{decorator} {emoji}"


def random_interjection() -> str:
    """Return a random chaos interjection based on current intensity.

    Returns
    -------
    str
        An interjection appropriate for the current intensity level.
        If chaos is disabled, returns an empty string.
    """
    if not is_chaos_enabled():
        return ""
    intensity = chaos_intensity()
    # Pick from all levels ≤ current intensity
    pool: list[str] = []
    for level in range(1, intensity + 1):
        pool.extend(_INTERJECTIONS.get(level, []))
    if not pool:
        return ""
    return random.choice(pool)


def random_joke() -> str:
    """Return a random programming dad joke."""
    return random.choice(_JOKES)


def easter_egg(command: str) -> str | None:
    """Return a special response for easter-egg *command*, or ``None``.

    Parameters
    ----------
    command : str
        The command string to check (case-insensitive, stripped).

    Returns
    -------
    str or None
        The easter-egg response if found, otherwise ``None``.
    """
    key = command.strip().lower()
    return _EASTER_EGGS.get(key)


def inject_typo(probability: float = 0.0) -> str | None:
    """Small chance to return a silly typo'd version of common words.

    Parameters
    ----------
    probability : float
        Override probability (0.0–1.0). If not set (0.0), uses the
        default based on current chaos intensity.

    Returns
    -------
    str or None
        A typo string, or ``None`` if no typo was rolled.
    """
    if not is_chaos_enabled():
        return None

    if probability <= 0.0:
        # Default prob based on intensity
        prob = {1: 0.02, 2: 0.05, 3: 0.10, 4: 0.18, 5: 0.30}.get(
            chaos_intensity(), 0.10
        )
    else:
        prob = probability

    if random.random() > prob:
        return None

    word = random.choice(list(_TYPOS.keys()))
    typo = random.choice(_TYPOS[word])
    return typo


def format_output(text: str, context: str = "generic") -> str:
    """Apply chaos formatting to *text* based on *context* type.

    Parameters
    ----------
    text : str
        The original output text.
    context : str
        One of ``"success"``, ``"fail"``, ``"info"``, ``"error"``,
        ``"progress"``, ``"generic"``.

    Returns
    -------
    str
        Formatted text with optional prefixes, emojis, and interjections.
    """
    if not is_chaos_enabled():
        return text

    intensity = chaos_intensity()
    result = text

    # Prepend a random interjection (approx 50% chance at low intensity,
    # 80% at max)
    interject_prob = {1: 0.2, 2: 0.35, 3: 0.5, 4: 0.65, 5: 0.8}.get(intensity, 0.5)
    if random.random() < interject_prob:
        prefixes = _CONTEXT_PREFIXES.get(context, _CONTEXT_PREFIXES["generic"])
        if prefixes:
            prefix = random.choice(prefixes)
            result = f"{prefix} {result}"

    # Add emoji suffix for the context
    emoji = _CONTEXT_EMOJIS.get(context, "")
    if emoji and random.random() < prob_for_intensity(intensity):
        result = f"{result} {emoji}"

    # Surprise ASCII art at high intensity (5% chance per level past 3)
    if intensity >= 3 and random.random() < 0.05 * (intensity - 2):
        art_pool = _ASCII_ART.get(intensity, [])
        if art_pool:
            art = random.choice(art_pool)
            result = f"{result}\n{art}"

    return result


def prob_for_intensity(intensity: int) -> float:
    """Return the default probability associated with an intensity level."""
    return {1: 0.1, 2: 0.25, 3: 0.40, 4: 0.60, 5: 0.85}.get(intensity, 0.4)


# ── CLI handler ──────────────────────────────────────────────────────────

def cmd_chaos(args: list[str] | None = None) -> None:
    """CLI handler for chaos mode.

    Usage::

        virgo chaos --on
        virgo chaos --off
        virgo chaos --toggle
        virgo chaos --intensity N

    Shows current state and a random joke.
    """
    if args is None:
        args = []

    # Parse arguments
    if "--on" in args:
        state = set_chaos(True)
        print(f"{icon('ok')} Chaos mode enabled (intensity={state['intensity']})")
    elif "--off" in args:
        state = set_chaos(False)
        print(f"{icon('ok')} Chaos mode disabled")
    elif "--toggle" in args:
        was = is_chaos_enabled()
        state = toggle_chaos()
        now = state["enabled"]
        print(
            f"{icon('ok')} Chaos mode {'enabled' if now else 'disabled'}"
            f" (was {'on' if was else 'off'})"
        )
    elif "--intensity" in args:
        idx = args.index("--intensity")
        if idx + 1 < len(args):
            try:
                level = int(args[idx + 1])
                state = set_intensity(level)
                print(
                    f"{icon('ok')} Chaos intensity set to {state['intensity']}"
                )
            except ValueError:
                print(f"{icon('error')} Intensity must be a number 1–5")
                return
        else:
            print(
                f"{icon('error')} Usage: virgo chaos --intensity N  (1–5)"
            )
            return
    else:
        # Show current state
        enabled = is_chaos_enabled()
        intensity = chaos_intensity()
        status = f"{_GREEN}ENABLED{_R}" if enabled else f"{_RED}DISABLED{_R}"
        print(f"{icon('info')} Chaos mode: {status}")
        print(f"{icon('info')} Intensity:   {intensity}/5")

    # Finish with a random joke
    print(f"\n{_CYAN}Dad Joke of the Moment:{_R} {random_joke()}")


# ── Module-level init ────────────────────────────────────────────────────

# Ensure state is valid
_state["intensity"] = max(1, min(5, _state.get("intensity", 3)))
_state["enabled"] = bool(_state.get("enabled", False))
_save_state(_state)

log.debug(
    "Chaos mode %s (intensity=%d)",
    "enabled" if _state["enabled"] else "disabled",
    _state["intensity"],
)

"""Virgo Persona System — communication style profiles for Virgo Agent.

Each persona defines a distinct personality with:
- Name and display name
- ASCII banner art
- Theme colors (ANSI named colors)
- Catchphrases for random selection
- Message prefix
- Response style descriptor
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from _log import log

if TYPE_CHECKING:
    pass  # Placeholder for future type-only imports

# ── Paths ────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
PERSONA_FILE = HERE / ".virgo_persona.json"

# ── ANSI Color Map ────────────────────────────────────────────────────────────
_ANSI_CODES: dict[str, str] = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "bright_black": "90",
    "bright_red": "91",
    "bright_green": "92",
    "bright_yellow": "93",
    "bright_blue": "94",
    "bright_magenta": "95",
    "bright_cyan": "96",
    "bright_white": "97",
    # Common aliases
    "lime": "92",
    "dark_green": "32",
    "gold": "93",
    "pink": "95",
    "dark_bg": "40",
    "dark_red": "31",
    "dark_blue": "34",
    "dark_cyan": "36",
    "dark_magenta": "35",
    "dark_yellow": "33",
}


def _colors_supported() -> bool:
    """Return True if the terminal likely supports ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if not sys.stdout.isatty():
        return False
    return True


COLORS_ENABLED: bool = _colors_supported()


# ── Built-in Persona Definitions ──────────────────────────────────────────────

_PERSONAS: dict[str, dict] = {
    "hacker": {
        "name": "hacker",
        "display_name": "Hacker",
        "banner_ascii": (
            "  ╔═══╗╔═╗╔═╗╔═══╗╔═══╗╔═══╗╔═══╗\n"
            "  ║╔══╝║ ║║ ║║║╔═╗║║╔══╝║╔══╝║╔═╗║\n"
            "  ║╚══╗║╔╝╚╗║║║ ║║║╚══╗║╚══╗║╚═╝║\n"
            "  ║╔══╝║╚╗╔╝║║╚═╝║║╔══╝║╔══╝║╔╗╔╝\n"
            "  ║║   ║ ║║ ║║╔═╗║║╚══╗║╚══╗║║║╚╗\n"
            "  ╚╝   ╚═╝╚═╝╚╝ ╚╝╚═══╝╚═══╝╚╝╚═╝"
        ),
        "theme_colors": {
            "primary": "green",
            "secondary": "bright_green",
            "accent": "lime",
            "highlight": "bright_green",
            "dim": "dark_green",
        },
        "catchphrases": [
            "Breaching firewalls...",
            "Permission granted.",
            "root access acquired.",
            "System compromised.",
            "Decrypting payload...",
            "Shell opened.",
        ],
        "message_prefix": "[⌘]",
        "response_style": "technical",
    },
    "poet": {
        "name": "poet",
        "display_name": "Poet",
        "banner_ascii": (
            "  ╔═══╗╔═══╗╔═══╗╔════╗\n"
            "  ║╔══╝║╔══╝║╔═╗║╚═╗╔═╝\n"
            "  ║╚══╗║╚══╗║╚═╝║  ║║\n"
            "  ║╔══╝║╔══╝║╔╗╔╝  ║║\n"
            "  ║║   ║║   ║║║╚╗  ║║\n"
            "  ╚╝   ╚╝   ╚╝╚═╝  ╚╝"
        ),
        "theme_colors": {
            "primary": "magenta",
            "secondary": "cyan",
            "accent": "bright_cyan",
            "highlight": "bright_magenta",
            "dim": "dark_magenta",
        },
        "catchphrases": [
            "Words take flight...",
            "A stanza unfolds.",
            "In the garden of code...",
            "Verses cascade like water.",
            "The ink flows freely.",
            "Metaphors awaken.",
        ],
        "message_prefix": "[✧]",
        "response_style": "eloquent",
    },
    "pirate": {
        "name": "pirate",
        "display_name": "Pirate",
        "banner_ascii": (
            "  ╔═══╗╔═╗╔═╗╔═══╗╔════╗╔═══╗\n"
            "  ║╔═╗║║ ║║ ║║║╔═╗║╚═╗╔═╝║╔══╝\n"
            "  ║╚═╝║║║ ║║║║║ ║║  ║║  ║╚══╗\n"
            "  ║╔╗╔╝║╚═╝║║║║ ║║  ║║  ║╔══╝\n"
            "  ║║║╚╗║╔═╗║║║╚═╝║  ║║  ║║\n"
            "  ╚╝╚═╝╚╝ ╚╝╚╚═══╝  ╚╝  ╚╝"
        ),
        "theme_colors": {
            "primary": "bright_yellow",
            "secondary": "red",
            "accent": "gold",
            "highlight": "bright_yellow",
            "dim": "dark_yellow",
        },
        "catchphrases": [
            "Ahoy, matey!",
            "Batten down the hatches!",
            "Shiver me timbers!",
            "Dead men tell no tales.",
            "Treasure awaits!",
            "Hoist the sails!",
        ],
        "message_prefix": "[☠]",
        "response_style": "playful",
    },
    "cybercat": {
        "name": "cybercat",
        "display_name": "Cyber Cat",
        "banner_ascii": (
            "   ╔═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╔═╗\n"
            "   ║ ║║ ║║║║║╔╝║╔╝║╔╝║╔╝\n"
            "   ║═╣║║║║╚╝║╚╗║╚╗║╚╗║╚╗\n"
            "   ╚═╝╚╩╝╚══╝╚═╝╚═╝╚═╝╚═╝"
        ),
        "theme_colors": {
            "primary": "bright_magenta",
            "secondary": "magenta",
            "accent": "bright_cyan",
            "highlight": "bright_magenta",
            "dim": "dark_magenta",
        },
        "catchphrases": [
            "*purrs*",
            "Nine lives of code!",
            "Paws for effect.",
            "Curiosity killed the bug.",
            "Napping on the keyboard...",
            "pspspsps wake up",
        ],
        "message_prefix": "[🐱]",
        "response_style": "playful",
    },
    "sage": {
        "name": "sage",
        "display_name": "Sage",
        "banner_ascii": (
            "  ╔═══╗╔═╗╔═╗╔═══╗╔═══╗\n"
            "  ║╔══╝║ ║║ ║║║╔═╗║║╔══╝\n"
            "  ║╚══╗║ ║║ ║║║╚═╝║║╚══╗\n"
            "  ║╔══╝║ ║║ ║║║╔╗╔╝║╔══╝\n"
            "  ║║   ║ ╚╝ ║║║║╚╗║║\n"
            "  ╚╝   ╚═══╝ ╚╝╚═╝╚╝"
        ),
        "theme_colors": {
            "primary": "blue",
            "secondary": "white",
            "accent": "bright_cyan",
            "highlight": "bright_white",
            "dim": "dark_blue",
        },
        "catchphrases": [
            "Consider this...",
            "Wisdom speaks.",
            "The answer reveals itself.",
            "Patience brings clarity.",
            "Reflect on the path.",
            "Knowledge is the root.",
        ],
        "message_prefix": "[✦]",
        "response_style": "eloquent",
    },
}

# ── Active persona (lazy-loaded from disk) ────────────────────────────────────

_current_persona: dict | None = None
_current_persona_name: str = "hacker"


def _load_persona_state() -> str:
    """Load saved persona name from ``.virgo_persona.json``.

    Returns the name of the saved persona, or ``\"hacker\"`` if no file
    exists or the file is corrupt.
    """
    global _current_persona, _current_persona_name
    if not PERSONA_FILE.exists():
        name = "hacker"
    else:
        try:
            data = json.loads(PERSONA_FILE.read_text(encoding="utf-8"))
            name = data.get("name", "hacker")
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt persona file, falling back to hacker")
            name = "hacker"
    if name not in _PERSONAS:
        name = "hacker"
    _current_persona_name = name
    _current_persona = _PERSONAS[name]
    return name


def _save_persona_state(name: str) -> None:
    """Persist persona name to ``.virgo_persona.json``."""
    try:
        PERSONA_FILE.write_text(
            json.dumps({"name": name}, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Could not save persona state: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────


def get_persona(name: str | None = None) -> dict:
    """Return the persona dict for *name*, or the current persona if ``None``.

    Raises :exc:`KeyError` when *name* is not a known persona.
    """
    if name is None:
        if _current_persona is None:
            _load_persona_state()
        assert _current_persona is not None
        return dict(_current_persona)
    if name not in _PERSONAS:
        msg = f"Unknown persona: {name!r}. Available: {', '.join(sorted(_PERSONAS))}"
        raise KeyError(msg)
    return dict(_PERSONAS[name])


def set_persona(name: str) -> dict:
    """Set the active persona, persist to disk, and return it.

    Raises :exc:`KeyError` when *name* is unknown.
    """
    global _current_persona, _current_persona_name
    if name not in _PERSONAS:
        msg = f"Unknown persona: {name!r}. Available: {', '.join(sorted(_PERSONAS))}"
        raise KeyError(msg)
    _current_persona_name = name
    _current_persona = _PERSONAS[name]
    _save_persona_state(name)
    log.info("Persona set to %r", name)
    return dict(_current_persona)


def list_personas() -> list[dict]:
    """Return a list of every available persona definition."""
    return [dict(p) for p in _PERSONAS.values()]


def current_persona_name() -> str:
    """Return the name of the currently active persona."""
    if _current_persona is None:
        _load_persona_state()
    return _current_persona_name


def catchphrase() -> str:
    """Return a random catchphrase from the current persona."""
    if _current_persona is None:
        _load_persona_state()
    assert _current_persona is not None
    return random.choice(_current_persona["catchphrases"])  # nosec


def color(text: str, key: str = "primary") -> str:
    """Wrap *text* in ANSI color escape codes from the current persona's theme.

    *key* must be one of ``\"primary\"``, ``\"secondary\"``, ``\"accent\"``,
    ``\"highlight\"``, or ``\"dim\"``.

    Returns the text unchanged when :data:`COLORS_ENABLED` is ``False`` or
    the color name is unknown.
    """
    if not COLORS_ENABLED:
        return text
    if _current_persona is None:
        _load_persona_state()
    assert _current_persona is not None
    color_name = _current_persona["theme_colors"].get(key, "white")
    code = _ANSI_CODES.get(color_name)
    if code is None:
        return text
    return f"\033[{code}m{text}\033[0m"


def apply_style(text: str, persona_name: str | None = None) -> str:
    """Format *text* with the persona's message prefix.

    If *persona_name* is given, use that persona's prefix; otherwise use
    the current active persona.
    """
    p = get_persona(persona_name)
    prefix = p["message_prefix"]
    return f"{prefix} {text}"


def persona_banner(persona_name: str | None = None) -> str:
    """Return the ASCII banner art for a persona (default: current)."""
    p = get_persona(persona_name)
    return p["banner_ascii"]


# ── CLI Handler Functions ─────────────────────────────────────────────────────
# These are called from cli.py after registration.


def cmd_persona_list(args: object = None) -> None:
    """Print all available personas to stdout."""
    for p in list_personas():
        banner = p["banner_ascii"].splitlines()[0] if p["banner_ascii"] else ""
        print(f"  {color(p['name'], 'highlight'):12s}  {color(p['display_name'], 'primary'):20s}  {p['response_style']:12s}  {banner}")
    print(f"\n  Active: {color(current_persona_name(), 'accent')}")


def cmd_persona_set(args: argparse.Namespace) -> None:
    """Switch to a different persona."""
    try:
        p = set_persona(args.persona)
    except KeyError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  Persona set to {color(p['display_name'], 'accent')}.")
    print(p["banner_ascii"])


def cmd_persona_show(args: argparse.Namespace) -> None:
    """Display the current (or specified) persona details."""
    name = getattr(args, "persona", None) or current_persona_name()
    try:
        p = get_persona(name)
    except KeyError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(color(p["banner_ascii"], "accent"))
    print(f"  Name:    {color(p['display_name'], 'primary')} ({p['name']})")
    print(f"  Style:   {p['response_style']}")
    print(f"  Prefix:  {p['message_prefix']}")
    print(f"  Colors:  {p['theme_colors']}")
    print(f"  Catchphrases:")
    for cp in p["catchphrases"]:
        print(f"    • {cp}")


# ── Bootstrap ──────────────────────────────────────────────────────────────────

_load_persona_state()

"""
virgo_celebrate — celebration/defeat animation engine.

Provides ASCII art animations and decorations for success, failure,
achievements, and milestones within the Virgo Agent Framework.

Usage::

    from virgo_celebrate import banner, cheer_text, firework

    print(firework("success"))
    print(banner("All tests passed!"))
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── ANSI helpers ─────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"

# ANSI 256-color rainbow sequence (FG)
_RAINBOW_COLORS: list[str] = [
    "\033[91m",  # Red
    "\033[93m",  # Yellow
    "\033[92m",  # Green
    "\033[96m",  # Cyan
    "\033[94m",  # Blue
    "\033[95m",  # Magenta
]

# Style colors
_STYLE_COLORS: dict[str, str] = {
    "success": "\033[92m",      # Green
    "fail": "\033[91m",         # Red
    "achievement": "\033[95m",  # Magenta
    "levelup": "\033[93m",      # Yellow
}

# ── Firework ASCII burst patterns ────────────────────────────────────

_FIREWORK_PATTERNS: dict[str, list[str]] = {
    "burst_a": [
        "        *        ",
        "       ***       ",
        "      *****      ",
        "     *******     ",
        "      *****      ",
        "       ***       ",
        "        *        ",
    ],
    "burst_b": [
        "    .     .    ",
        "   ***   ***   ",
        "  ***** *****  ",
        " ************* ",
        "  ***** *****  ",
        "   ***   ***   ",
        "    .     .    ",
    ],
    "burst_c": [
        "      ✦      ",
        "     ✧ ✧     ",
        "    ✦ * ✦    ",
        "     ✧ ✧     ",
        "      ✦      ",
    ],
    "burst_d": [
        "    *  .  *    ",
        "   *** ✧ ***   ",
        "  *****✦*****  ",
        "   *** ✧ ***   ",
        "    *  .  *    ",
    ],
}

# ── Cheer messages ───────────────────────────────────────────────────

_CHEERS: dict[str, list[str]] = {
    "success": [
        "Amazing!",
        "Nailed it!",
        "Brilliant!",
        "You rock!",
        "Ship it!",
        "Outstanding!",
        "Clean sweep!",
        "Perfect!",
    ],
    "fail": [
        "Almost!",
        "Next time!",
        "Keep going!",
        "You got this!",
        "Try again!",
        "Close!",
    ],
    "achievement": [
        "Achievement unlocked!",
        "New record!",
        "Bonus XP!",
        "Legendary!",
    ],
    "levelup": [
        "LEVEL UP!",
        "You've grown!",
        "Power surged!",
        "Ascended!",
    ],
}

# ── Confetti / sparkle characters ────────────────────────────────────
_CONFETTI_CHARS = ["✦", "✧", "*", "•", "★", "☆", "✨", "+", ".", "-"]


# ═════════════════════════════════════════════════════════════════════
#  Public API
# ═════════════════════════════════════════════════════════════════════


def _random_confetti_char() -> str:
    """Return a single random confetti character."""
    return random.choice(_CONFETTI_CHARS)


def firework(style: str = "success") -> str:
    """Return an ASCII firework/confetti art piece for the given *style*.

    Args:
        style: One of ``"success"``, ``"fail"``, ``"achievement"``,
               ``"levelup"``.

    Returns:
        A multi-line ASCII art string.
    """
    valid_styles = {"success", "fail", "achievement", "levelup"}
    if style not in valid_styles:
        log.warning("Unknown firework style %r, falling back to 'success'", style)
        style = "success"

    color = _STYLE_COLORS.get(style, _STYLE_COLORS["success"])
    pattern = random.choice(list(_FIREWORK_PATTERNS.values()))
    colored = "\n".join(f"{color}{line}{_RESET}" for line in pattern)
    return colored


def sparkle_line(text: str) -> str:
    """Wrap *text* in sparkle decorations.

    Returns a string like::

        ✦ text ✦
    """
    char = _random_confetti_char()
    return f"{char} {text} {char}"


def rainbow(text: str) -> str:
    """Apply a rainbow ANSI colour cycle to *text*.

    Each character is coloured with the next colour in the cycle.
    Returns the text with ANSI escape codes — safe to print to any
    terminal, and degrades gracefully under ``errors="replace"``.
    """
    if not text:
        return ""
    result_parts: list[str] = []
    for i, ch in enumerate(text):
        color = _RAINBOW_COLORS[i % len(_RAINBOW_COLORS)]
        result_parts.append(f"{color}{ch}{_RESET}")
    return "".join(result_parts)


def confetti(width: int = 40) -> str:
    """Generate a single random confetti line of the given *width*.

    Each position is either a confetti character or a space.
    """
    if width < 1:
        return ""
    chars: list[str] = []
    for _ in range(width):
        if random.random() < 0.3:  # ~30% fill rate for readability
            chars.append(_random_confetti_char())
        else:
            chars.append(" ")
    return "".join(chars)


def banner(text: str, style: str = "success") -> str:
    """Generate a full celebration banner with border, text, and animations.

    Args:
        text:  The message to display.
        style: One of ``"success"``, ``"fail"``, ``"achievement"``,
               ``"levelup"``.

    Returns:
        A multi-line banner string with ASCII art, border, confetti,
        and a random cheer message.
    """
    valid_styles = {"success", "fail", "achievement", "levelup"}
    if style not in valid_styles:
        log.warning("Unknown banner style %r, falling back to 'success'", style)
        style = "success"

    color = _STYLE_COLORS.get(style, _STYLE_COLORS["success"])
    cheer = cheer_text(style)
    fw = firework(style)
    conf = confetti(len(text) + 12)
    border = "═" * (len(text) + 12)

    lines = [
        f"{color}{conf}{_RESET}",
        f"{color}╔{border}╗{_RESET}",
        f"{color}║     {cheer}     ║{_RESET}",
        f"{color}║   {_BOLD}{text}{_RESET}{color}   ║{_RESET}",
        f"{color}╚{border}╝{_RESET}",
        fw,
    ]
    return "\n".join(lines)


def fireworks_animation(lines: int = 8, width: int = 40) -> str:
    """Generate a multi-line ASCII firework burst pattern.

    Args:
        lines: Number of vertical lines.
        width: Horizontal width of the pattern.

    Returns:
        A string with multiple firework bursts scattered across the area.
    """
    if lines < 1 or width < 1:
        return ""

    result: list[str] = []
    for _ in range(lines):
        row: list[str] = []
        for _ in range(width):
            if random.random() < 0.15:  # ~15% fill
                row.append(random.choice(["*", "✦", "✧", ".", "+", "*"]))
            else:
                row.append(" ")
        result.append("".join(row))
    return "\n".join(result)


def cheer_text(result: str = "success") -> str:
    """Return a random cheer message for the given *result* style.

    Args:
        result: One of ``"success"``, ``"fail"``, ``"achievement"``,
                ``"levelup"``.

    Returns:
        A single cheer message string.
    """
    valid = {"success", "fail", "achievement", "levelup"}
    if result not in valid:
        log.warning("Unknown cheer style %r, falling back to 'success'", result)
        result = "success"

    messages = _CHEERS.get(result, _CHEERS["success"])
    return random.choice(messages)


# ═════════════════════════════════════════════════════════════════════
#  CLI Handler — wired by cli.py
# ═════════════════════════════════════════════════════════════════════


def cmd_celebrate(args: list[str] | None = None) -> None:
    """Show a celebration animation.

    Args:
        args: Optional list of CLI-style arguments::

            --type success|fail|achievement|levelup
            --message "Custom text"
    """
    import argparse

    parser = argparse.ArgumentParser(description="Virgo Celebration Engine")
    parser.add_argument(
        "--type",
        choices=["success", "fail", "achievement", "levelup"],
        default="success",
        help="Celebration type (default: success)",
    )
    parser.add_argument(
        "--message",
        type=str,
        default=None,
        help="Custom banner message (overrides the default cheer)",
    )

    parsed = parser.parse_args(args)

    style = parsed.type
    msg = parsed.message or cheer_text(style)

    log.info("Celebration: style=%s message=%r", style, msg)

    # ── Render ──
    print(banner(msg, style=style))
    print()
    print(fireworks_animation(lines=6, width=50))
    print()
    print(f"{icon('done')} {rainbow(msg)}")

    input("\n[PRESS ENTER TO RETURN]")


# ═════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd_celebrate(sys.argv[1:] if len(sys.argv) > 1 else None)

"""
Virgo Dynamic Theme Engine — auto-switches themes based on time-of-day,
day-of-week, and holiday schedules.

Integrates with the built-in THEMES dict from virgo_desktop.py (mocha,
latte, nord, gruvbox) and allows registering custom schedules with
theme overrides.

Usage:
    from virgo_themes import get_suggested_theme

    theme = get_suggested_theme()   # "mocha", "latte", etc.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, TypedDict

from _console import icon
from _log import log

HERE = Path(__file__).resolve().parent

# ── Built-in theme colour palettes ────────────────────────────────────────────
# Mirrors the THEMES dict from virgo_desktop.py so this module is self-contained.

BUILTIN_THEMES: dict[str, dict[str, str]] = {
    "mocha": {
        "name": "Catppuccin Mocha",
        "base": "#1e1e2e",
        "bg": "#1e1e2e",
        "surface": "#181825",
        "crust": "#11111b",
        "border": "#313244",
        "border2": "#45475a",
        "text": "#cdd6f4",
        "subtext": "#a6adc8",
        "disabled": "#6c7086",
        "accent": "#89b4fa",
        "accent2": "#a6e3a1",
        "red": "#f38ba8",
        "yellow": "#f9e2af",
        "green": "#a6e3a1",
        "sidebar_active": "#45475a",
    },
    "latte": {
        "name": "Catppuccin Latte",
        "base": "#ffffff",
        "bg": "#eff1f5",
        "surface": "#e6e9ef",
        "crust": "#dce0e8",
        "border": "#ccd0da",
        "border2": "#bcc0cc",
        "text": "#4c4f69",
        "subtext": "#5c5f77",
        "disabled": "#9ca0b0",
        "accent": "#1e66f5",
        "accent2": "#40a02b",
        "red": "#d20f39",
        "yellow": "#df8e1d",
        "green": "#40a02b",
        "sidebar_active": "#ccd0da",
    },
    "nord": {
        "name": "Nord",
        "base": "#eceff4",
        "bg": "#2e3440",
        "surface": "#3b4252",
        "crust": "#434c5e",
        "border": "#4c566a",
        "border2": "#5e6a83",
        "text": "#eceff4",
        "subtext": "#d8dee9",
        "disabled": "#6c7086",
        "accent": "#88c0d0",
        "accent2": "#a3be8c",
        "red": "#bf616a",
        "yellow": "#ebcb8b",
        "green": "#a3be8c",
        "sidebar_active": "#4c566a",
    },
    "gruvbox": {
        "name": "Gruvbox Dark",
        "base": "#fbf1c7",
        "bg": "#282828",
        "surface": "#3c3836",
        "crust": "#504945",
        "border": "#665c54",
        "border2": "#7c6f64",
        "text": "#ebdbb2",
        "subtext": "#a89984",
        "disabled": "#6c7086",
        "accent": "#d79921",
        "accent2": "#689d6a",
        "red": "#cc241d",
        "yellow": "#d79921",
        "green": "#98971a",
        "sidebar_active": "#665c54",
    },
}

# ── Custom holiday theme colour palettes ─────────────────────────────────────

WINTER_THEME: dict[str, str] = {
    "name": "Winter Wonderland",
    "base": "#e8f0fe",
    "bg": "#0a192f",
    "surface": "#112240",
    "crust": "#1a3a5c",
    "border": "#2a5a8c",
    "border2": "#4a8cc7",
    "text": "#e8f0fe",
    "subtext": "#a8c8e8",
    "disabled": "#5a7a9a",
    "accent": "#64b5f6",
    "accent2": "#e0e0e0",
    "red": "#e57373",
    "yellow": "#ffd54f",
    "green": "#81c784",
    "sidebar_active": "#2a5a8c",
}

SPOOKY_THEME: dict[str, str] = {
    "name": "Spooky Night",
    "base": "#1a1a2e",
    "bg": "#0d0d1a",
    "surface": "#16213e",
    "crust": "#1a1a2e",
    "border": "#2d2d44",
    "border2": "#4a0e4e",
    "text": "#e0e0e0",
    "subtext": "#a0a0b0",
    "disabled": "#5a5a6a",
    "accent": "#ff6b35",
    "accent2": "#7b2d8e",
    "red": "#e63946",
    "yellow": "#f4a261",
    "green": "#2a9d8f",
    "sidebar_active": "#4a0e4e",
}

CELEBRATION_THEME: dict[str, str] = {
    "name": "New Year Celebration",
    "base": "#1c1c1c",
    "bg": "#0d0d0d",
    "surface": "#1a1a1a",
    "crust": "#2a2a2a",
    "border": "#3a3a3a",
    "border2": "#d4af37",
    "text": "#ffd700",
    "subtext": "#c0a030",
    "disabled": "#6a6a6a",
    "accent": "#ffd700",
    "accent2": "#f0e68c",
    "red": "#ff6b6b",
    "yellow": "#ffd700",
    "green": "#a3be8c",
    "sidebar_active": "#d4af37",
}

# ── Persona-to-theme mapping ──────────────────────────────────────────────────

PERSONA_THEME_MAP: dict[str, str] = {
    "hacker": "gruvbox",
    "poet": "latte",
    "pirate": "nord",
    "cybercat": "mocha",
    "sage": "latte",
}

# ── Type definitions ─────────────────────────────────────────────────────────


class ScheduleDict(TypedDict, total=False):
    """A single schedule entry for the dynamic theme engine."""

    name: str
    description: str
    condition: Callable[[datetime], bool]
    theme_name: str
    theme_overrides: dict  # custom colour dict when theme_name doesn't exist
    is_holiday: bool


# ── Condition helpers ────────────────────────────────────────────────────────


def _night_condition(dt: datetime) -> bool:
    """Active between 18:00 and 06:00."""
    t = dt.time()
    return t >= time(18, 0) or t < time(6, 0)


def _day_condition(dt: datetime) -> bool:
    """Active between 06:00 and 18:00."""
    t = dt.time()
    return time(6, 0) <= t < time(18, 0)


def _work_hours_condition(dt: datetime) -> bool:
    """Active Mon-Fri 09:00-17:00."""
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = dt.time()
    return time(9, 0) <= t < time(17, 0)


def _weekend_condition(dt: datetime) -> bool:
    """Active Saturday or Sunday."""
    return dt.weekday() >= 5


def _christmas_condition(dt: datetime) -> bool:
    """Active Dec 24 - Dec 26."""
    return (dt.month == 12) and (24 <= dt.day <= 26)


def _halloween_condition(dt: datetime) -> bool:
    """Active Oct 31."""
    return (dt.month == 10) and (dt.day == 31)


def _new_year_condition(dt: datetime) -> bool:
    """Active Dec 31 - Jan 1."""
    return (dt.month == 12 and dt.day == 31) or (dt.month == 1 and dt.day == 1)


# ── Built-in schedules ───────────────────────────────────────────────────────

_BUILTIN_SCHEDULES: list[ScheduleDict] = [
    {
        "name": "Night Mode",
        "description": "18:00–06:00 → mocha theme",
        "condition": _night_condition,
        "theme_name": "mocha",
        "is_holiday": False,
    },
    {
        "name": "Day Mode",
        "description": "06:00–18:00 → latte theme",
        "condition": _day_condition,
        "theme_name": "latte",
        "is_holiday": False,
    },
    {
        "name": "Work Hours",
        "description": "Mon–Fri 09:00–17:00 → nord theme",
        "condition": _work_hours_condition,
        "theme_name": "nord",
        "is_holiday": False,
    },
    {
        "name": "Weekend",
        "description": "Saturday–Sunday → gruvbox theme",
        "condition": _weekend_condition,
        "theme_name": "gruvbox",
        "is_holiday": False,
    },
    {
        "name": "Christmas",
        "description": "Dec 24–26 → custom winter theme",
        "condition": _christmas_condition,
        "theme_name": "winter",
        "theme_overrides": WINTER_THEME,
        "is_holiday": True,
    },
    {
        "name": "Halloween",
        "description": "Oct 31 → custom spooky theme",
        "condition": _halloween_condition,
        "theme_name": "spooky",
        "theme_overrides": SPOOKY_THEME,
        "is_holiday": True,
    },
    {
        "name": "New Year",
        "description": "Dec 31 – Jan 1 → custom celebration theme",
        "condition": _new_year_condition,
        "theme_name": "celebration",
        "theme_overrides": CELEBRATION_THEME,
        "is_holiday": True,
    },
]

# Active schedule registry: built-in + any user-registered
_schedules: list[ScheduleDict] = list(_BUILTIN_SCHEDULES)


# ── Public API ───────────────────────────────────────────────────────────────


def get_active_schedule(dt: datetime | None = None) -> dict | None:
    """Return the currently active schedule entry, or *None* if no match.

    Holiday schedules are checked first (higher priority), then regular
    schedules in definition order. The first matching schedule wins.
    """
    if dt is None:
        dt = datetime.now()

    # Holiday schedules take priority
    for sched in _schedules:
        if sched.get("is_holiday") and sched["condition"](dt):
            log.info("%s %s active", icon("sparkle"), sched["name"])
            return sched

    # Regular schedules
    for sched in _schedules:
        if not sched.get("is_holiday") and sched["condition"](dt):
            log.info("%s %s active", icon("refresh"), sched["name"])
            return sched

    return None


def get_suggested_theme(dt: datetime | None = None) -> str:
    """Return the theme name that should be active for the given time.

    Falls back to ``"mocha"`` (night mode default) if no schedule matches.
    """
    sched = get_active_schedule(dt)
    if sched is None:
        log.info("%s No schedule active, falling back to mocha", icon("moon"))
        return "mocha"
    return sched["theme_name"]


def list_schedules() -> list[dict]:
    """Return all defined schedules with their metadata (no condition callable)."""
    result: list[dict] = []
    for sched in _schedules:
        entry = {
            "name": sched["name"],
            "description": sched["description"],
            "theme_name": sched["theme_name"],
            "is_holiday": sched.get("is_holiday", False),
        }
        if "theme_overrides" in sched:
            entry["theme_overrides"] = sched["theme_overrides"]
        result.append(entry)
    return result


def is_holiday_season(dt: datetime | None = None) -> str | None:
    """Return the holiday name if *dt* falls within a holiday period, else *None*."""
    if dt is None:
        dt = datetime.now()

    for sched in _schedules:
        if sched.get("is_holiday") and sched["condition"](dt):
            return sched["name"]

    return None


def register_schedule(schedule: dict) -> None:
    """Register a custom schedule entry.

    The dict must have at minimum the keys: ``name``, ``description``,
    ``condition`` (callable), and ``theme_name``.
    """
    required = {"name", "description", "condition", "theme_name"}
    missing = required - set(schedule.keys())
    if missing:
        raise ValueError(f"Schedule dict missing required keys: {missing}")

    if not callable(schedule["condition"]):
        raise TypeError("'condition' must be a callable(datetime) -> bool")

    _schedules.append(schedule)
    log.info("%s Registered schedule: %s", icon("save"), schedule["name"])


def get_theme_for_persona(persona_name: str) -> dict | None:
    """Map a persona name to a suggested visual theme dict.

    Returns the built-in theme colour dict, custom holiday theme, or *None*
    if the persona is unknown.
    """
    theme_key = PERSONA_THEME_MAP.get(persona_name)
    if theme_key is None:
        return None
    return BUILTIN_THEMES.get(theme_key)


# ── CLI handlers ─────────────────────────────────────────────────────────────


def cmd_themes_list(args: argparse.Namespace) -> None:
    """List all schedules, marking the currently active one."""
    now = datetime.now()
    active = get_active_schedule(now)

    log.info("%s Dynamic Theme Engine — Schedules", icon("virgo"))
    print(f"{'':-^60}".format(""))
    print(f"{'Name':<20} {'Theme':<16} {'Holiday':<8} {'Active':<6}")
    print(f"{'':-^60}".format(""))

    for sched in list_schedules():
        is_active = active is not None and sched["name"] == active["name"]
        marker = icon("ok") if is_active else ""
        print(
            f"{sched['name']:<20} "
            f"{sched['theme_name']:<16} "
            f"{'Yes' if sched['is_holiday'] else 'No':<8} "
            f"{marker:<6}"
        )


def cmd_themes_now(args: argparse.Namespace) -> None:
    """Show what theme is suggested right now."""
    now = datetime.now()
    theme = get_suggested_theme(now)
    sched = get_active_schedule(now)

    print(f"{icon('virgo')} Current time: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{icon('bolt')} Suggested theme: {theme}")

    if sched:
        print(f"{icon('arrow')} Active schedule: {sched['name']} — {sched['description']}")
        if sched.get("is_holiday"):
            print(f"{icon('sparkle')} Holiday season: {sched['name']}")
    else:
        print(f"{icon('info')} No schedule active (fallback theme)")

"""
virgo_heatmap — Terminal-based activity heatmap for Virgo.

Shows a visual representation of your Virgo activity over time
(hours of the day × days). Uses data from the achievement system
or a simple JSON log.

Usage:
    virgo heatmap                  # Show today's heatmap (hourly)
    virgo heatmap --days 7         # Last 7 days
    virgo heatmap --days 30        # Last 30 days
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import OUTDIR, log

# ── ANSI helpers ──────────────────────────────────────────────────────────

_R = "\033[0m"
_B = "\033[1m"
_D = "\033[2m"
_GR = "\033[32m"
_YL = "\033[33m"
_RE = "\033[31m"
_CY = "\033[36m"
_WH = "\033[37m"

# Heatmap colours (light to intense)
_LEVELS = [
    _D,
    _GR,
    _YL,
    _RE,
    _WH,
]

_CHARS = ["░", "▒", "▓", "█", "█"]

# ── Activity Log ──────────────────────────────────────────────────────────


ACTIVITY_LOG = OUTDIR / "virgo_activity_log.json"


def _load_activity_log() -> list[dict]:
    """Load activity log from JSON file."""
    if not ACTIVITY_LOG.exists():
        return []
    try:
        return json.loads(ACTIVITY_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_activity_log(entries: list[dict]) -> None:
    """Save activity log to JSON file."""
    try:
        # Keep last 100 entries
        trimmed = entries[-100:]
        ACTIVITY_LOG.write_text(
            json.dumps(trimmed, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("Failed to save activity log: %s", exc)


def log_activity(event_type: str, detail: str = "") -> None:
    """Log an activity event with timestamp."""
    entries = _load_activity_log()
    entries.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event_type,
        "detail": detail,
    })
    _save_activity_log(entries)


def _get_hour_label(hour: int) -> str:
    """Return abbreviated hour label."""
    if hour == 0:
        return "12a"
    elif hour < 12:
        return f"{hour}a"
    elif hour == 12:
        return "12p"
    else:
        return f"{hour - 12}p"


def _get_day_label(days_ago: int) -> str:
    """Return day label for relative days ago."""
    if days_ago == 0:
        return "Today"
    elif days_ago == 1:
        return "Yest"
    date = datetime.now(UTC) - timedelta(days=days_ago)
    return date.strftime("%a")


# ── Heatmap Generation ────────────────────────────────────────────────────


def generate_heatmap(days: int = 1, activity_data: list[dict] | None = None) -> str:
    """Generate an ASCII heatmap string.

    Args:
        days: Number of days to show (1-30)
        activity_data: Optional pre-loaded activity data. If None, loads from log.

    Returns:
        Multi-line string of the heatmap.
    """
    if activity_data is None:
        activity_data = _load_activity_log()

    if not activity_data:
        return f"  {_D}No activity data yet. Run some pipelines!{_R}\n"

    # Parse timestamps and count activities per hour per day
    # Grid: hour (0-23) x day (days ago)
    now = datetime.now(UTC)
    grid: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    data_points = 0
    for entry in activity_data:
        try:
            ts_str = entry.get("timestamp", "")
            if not ts_str:
                continue
            # Handle both with and without timezone
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1]
            dt = datetime.fromisoformat(ts_str)
            # Calculate days ago
            delta = now - dt
            days_ago = delta.days
            if 0 <= days_ago < days:
                grid[days_ago][dt.hour] += 1
                data_points += 1
        except (ValueError, KeyError):
            continue

    if data_points == 0:
        return f"  {_D}No activity data in the requested range.{_R}\n"

    # Find max for normalization
    max_count = max(
        (grid[day][hour] for day in range(days) for hour in range(24)),
        default=1,
    )

    lines: list[str] = []
    header = f"  {_B}Activity Heatmap{_R}  {_D}({days} day(s), {data_points} events){_R}"
    lines.append(header)
    lines.append("")

    # Day labels
    day_labels = "       "  # indent for hour column
    for day in range(days):
        label = _get_day_label(day)
        day_labels += f" {label:5s}"
    lines.append(day_labels)

    # Hour rows
    for hour in range(24):
        hour_label = _get_hour_label(hour)
        row = f"  {hour_label:5s} "
        for day in range(days):
            count = grid[day][hour]
            if count == 0:
                row += f" {_D}·{_R}    "
            else:
                # Normalize to 0-4
                level = min(4, int((count / max_count) * 5))
                level = max(0, level)
                char = _CHARS[level]
                color = _LEVELS[level]
                row += f" {color}{char}{_R} {count:3d} "
        lines.append(row)

    # Legend
    lines.append("")
    legend = "  Legend: "
    for i in range(5):
        legend += f"{_LEVELS[i]}{_CHARS[i] * 2}{_R} = {'none' if i == 0 else 'light' if i == 1 else 'medium' if i == 2 else 'heavy' if i == 3 else 'max'}  "
    lines.append(legend)
    lines.append("")

    return "\n".join(lines)


def cmd_heatmap(args: Any) -> None:
    """CLI handler for heatmap."""
    days = getattr(args, "days", 1)
    days = max(1, min(30, days))
    print()
    print(generate_heatmap(days=days))
    print()


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virgo Activity Heatmap")
    parser.add_argument("--days", "-d", type=int, default=1, help="Days to show (1-30)")
    args = parser.parse_args()
    print(generate_heatmap(days=args.days))

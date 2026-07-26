"""
virgo_leaderboard — Session-based XP leaderboard for Virgo.

Tracks session activity, streaks, and XP accumulation over time.
Builds on the achievement system's data.

Usage:
    virgo leaderboard                    # Show overall rankings
    virgo leaderboard --streak           # Show current streak
    virgo leaderboard --history          # Show XP history
    virgo leaderboard --reset            # Reset leaderboard data
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
_CY = "\033[36m"
_WH = "\033[37m"
_RE = "\033[31m"
_MA = "\033[35m"

# ── Data file ─────────────────────────────────────────────────────────────

LEADERBOARD_FILE = OUTDIR / "virgo_leaderboard.json"


def _load() -> dict[str, Any]:
    """Load leaderboard data."""
    try:
        if not LEADERBOARD_FILE.exists():
            return {
                "sessions": [],
                "total_xp": 0,
                "current_streak": 0,
                "longest_streak": 0,
                "last_active": "",
                "daily_xp": {},
                "history": [],
            }
        # Use timeout for file reading to prevent hanging
        import threading
        result = []
        def _read():
            try:
                data = json.loads(LEADERBOARD_FILE.read_text(encoding="utf-8"))
                result.append(data)
            except Exception:
                result.append({
                    "sessions": [],
                    "total_xp": 0,
                    "current_streak": 0,
                    "longest_streak": 0,
                    "last_active": "",
                    "daily_xp": {},
                    "history": [],
                })
        thread = threading.Thread(target=_read)
        thread.daemon = True
        thread.start()
        thread.join(timeout=0.5)
        if result:
            return result[0]
    except Exception:
        pass
    return {
        "sessions": [],
        "total_xp": 0,
        "current_streak": 0,
        "longest_streak": 0,
        "last_active": "",
        "daily_xp": {},
        "history": [],
    }


def _save(data: dict[str, Any]) -> None:
    """Save leaderboard data."""
    try:
        OUTDIR.mkdir(exist_ok=True)
        # Use atomic write pattern
        temp_file = LEADERBOARD_FILE.with_suffix('.tmp')
        temp_file.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        temp_file.replace(LEADERBOARD_FILE)
    except Exception as exc:
        log.warning("Failed to save leaderboard: %s", exc)


def record_session(goal: str, xp_earned: int, passed: bool) -> dict[str, Any]:
    """Record a pipeline session and update stats.

    Args:
        goal: The pipeline goal
        xp_earned: XP earned this session
        passed: Whether the pipeline passed

    Returns:
        Updated leaderboard stats.
    """
    data = _load()
    now = datetime.now(UTC)
    today_key = now.strftime("%Y-%m-%d")

    session = {
        "timestamp": now.isoformat(),
        "goal": goal[:80],
        "xp": xp_earned,
        "passed": passed,
    }
    data["sessions"].append(session)
    data["total_xp"] = data.get("total_xp", 0) + xp_earned

    # Update daily XP
    daily = data.get("daily_xp", {})
    daily[today_key] = daily.get(today_key, 0) + xp_earned
    data["daily_xp"] = daily

    # Streak tracking
    last_active = data.get("last_active", "")
    if last_active:
        last_date = datetime.fromisoformat(last_active).date()
        today = now.date()
        delta = (today - last_date).days
        if delta == 1:
            # Consecutive day
            data["current_streak"] = data.get("current_streak", 0) + 1
        elif delta > 1:
            # Streak broken
            data["current_streak"] = 1
        # If delta == 0, same day, don't change streak
    else:
        data["current_streak"] = 1

    data["last_active"] = now.isoformat()

    # Track longest streak
    if data["current_streak"] > data.get("longest_streak", 0):
        data["longest_streak"] = data["current_streak"]

    # History entry
    history = data.get("history", [])
    history.append({
        "date": today_key,
        "xp": xp_earned,
        "passed": passed,
        "goal": goal[:60],
    })
    data["history"] = history[-100:]  # Keep last 100 entries

    _save(data)
    return get_stats(data=data)


def get_stats(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get current leaderboard stats."""
    if data is None:
        data = _load()

    sessions = data.get("sessions", [])
    total_xp = data.get("total_xp", 0)
    current_streak = data.get("current_streak", 0)
    longest_streak = data.get("longest_streak", 0)

    total_sessions = len(sessions)
    passed_sessions = sum(1 for s in sessions if s.get("passed"))
    fail_sessions = total_sessions - passed_sessions

    # Daily breakdown
    daily_xp = data.get("daily_xp", {})
    today_key = datetime.now(UTC).strftime("%Y-%m-%d")
    today_xp = daily_xp.get(today_key, 0)

    # Avg XP per session
    avg_xp = round(total_xp / total_sessions, 1) if total_sessions else 0

    # Best day
    best_day_xp = max(daily_xp.values()) if daily_xp else 0
    best_day = max(daily_xp, key=daily_xp.get) if daily_xp else ""

    return {
        "total_xp": total_xp,
        "total_sessions": total_sessions,
        "passed_sessions": passed_sessions,
        "fail_sessions": fail_sessions,
        "pass_rate": round(passed_sessions / total_sessions * 100, 1) if total_sessions else 0,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "today_xp": today_xp,
        "avg_xp": avg_xp,
        "best_day_xp": best_day_xp,
        "best_day": best_day,
        "history": data.get("history", []),
    }


def get_history(days: int = 7) -> list[dict[str, Any]]:
    """Get recent session history."""
    data = _load()
    history = data.get("history", [])
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return [h for h in history if h.get("date", "") >= cutoff[:10]]


def reset() -> dict[str, Any]:
    """Reset all leaderboard data."""
    empty = {
        "sessions": [],
        "total_xp": 0,
        "current_streak": 0,
        "longest_streak": 0,
        "last_active": "",
        "daily_xp": {},
        "history": [],
    }
    _save(empty)
    return get_stats(data=empty)


# ── Formatting ────────────────────────────────────────────────────────────


def format_stats(stats: dict[str, Any] | None = None) -> str:
    """Format leaderboard stats as a display string."""
    if stats is None:
        stats = get_stats()

    lines: list[str] = []
    lines.append(f"\n  {_B}{icon('brain')} LEADERBOARD{_R}")
    lines.append(f"  {'─' * 50}")

    # Main stat box
    total_xp = stats.get("total_xp", 0)
    sessions = stats.get("total_sessions", 0)
    pass_rate = stats.get("pass_rate", 0)
    streak = stats.get("current_streak", 0)
    longest = stats.get("longest_streak", 0)

    lines.append(f"  {_GR}Total XP:{_R}     {_B}{total_xp}{_R}")
    lines.append(f"  {_CY}Sessions:{_R}    {sessions}  ({pass_rate}% pass rate)")
    lines.append(f"  {_YL}Streak:{_R}      {streak} day(s)  {_D}(longest: {longest}){_R}")
    lines.append(f"  {_WH}Today:{_R}       {stats.get('today_xp', 0)} XP earned")
    lines.append(f"  {_MA}Best Day:{_R}    {stats.get('best_day', '-')} ({stats.get('best_day_xp', 0)} XP)")
    lines.append(f"  {_D}Avg/Session:{_R}  {stats.get('avg_xp', 0)} XP")

    lines.append("")
    lines.append(f"  {_B}Recent Sessions{_R}")
    lines.append(f"  {'─' * 50}")

    history = stats.get("history", [])
    if not history:
        lines.append(f"  {_D}No sessions recorded yet.{_R}")
    else:
        for h in history[-10:]:
            date = h.get("date", "?")
            xp = h.get("xp", 0)
            passed = h.get("passed", False)
            goal = h.get("goal", "")[:40]
            status = f"{_GR}✓{_R}" if passed else f"{_RE}✗{_R}"
            lines.append(f"  {status} {_D}{date}{_R}  +{xp:3d} XP  {_D}{goal}{_R}")

    lines.append("")
    return "\n".join(lines)


# ── CLI handler ───────────────────────────────────────────────────────────


def cmd_leaderboard(args: Any) -> None:
    """CLI handler for leaderboard."""
    if getattr(args, "reset", False):
        stats = reset()
        print(f"\n  {icon('history')} Leaderboard data reset.")
        return

    if getattr(args, "streak", False):
        stats = get_stats()
        print(f"\n  {_B}Streak Info{_R}")
        print(f"  Current: {stats.get('current_streak', 0)} day(s)")
        print(f"  Longest: {stats.get('longest_streak', 0)} day(s)")
        print(f"  Last active: {stats.get('last_active', 'never')}")
        return

    if getattr(args, "history", False):
        days = getattr(args, "days", 7)
        history = get_history(days=days)
        print(f"\n  {_B}History ({days} days){_R}")
        print(f"  {'─' * 50}")
        for h in history[-20:]:
            print(f"  {h.get('date', '?'):12s}  +{h.get('xp', 0):4d} XP  "
                  f"{'✓' if h.get('passed') else '✗'}  {h.get('goal', '')[:40]}")
        print()
        return

    print(format_stats())


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virgo Leaderboard")
    parser.add_argument("--streak", action="store_true", help="Show streak info")
    parser.add_argument("--history", action="store_true", help="Show history")
    parser.add_argument("--days", type=int, default=7, help="Days of history")
    parser.add_argument("--reset", action="store_true", help="Reset data")
    args = parser.parse_args()
    cmd_leaderboard(args)

"""Virgo Achievement System — gamification layer with SQLite backend.

Provides an achievement/unlock system with XP, levels, and hook-based
triggers integrated into the Virgo Agent Framework.

Usage::

    from virgo_achievements import get_achievements, hook

    system = get_achievements()
    system.hook("pipeline_complete", total_runs=1)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

from _console import icon
from _log import OUTDIR, log

# ──────────────────────────────────────────────────────────────────────
#  Hook Constants
# ──────────────────────────────────────────────────────────────────────

HOOK_PIPELINE_COMPLETE = "pipeline_complete"
HOOK_PIPELINE_ITERATION = "pipeline_iteration"
HOOK_NETWORK_SCAN = "network_scan"
HOOK_SWARM_RUN = "swarm_run"
HOOK_SEARCH = "web_search"
HOOK_FINGERPRINT = "fingerprint"
HOOK_BOT_START = "bot_start"
HOOK_SHARE = "session_share"
HOOK_PERSONA_CHANGE = "persona_change"
HOOK_FOCUS_MODE = "focus_mode"
HOOK_MASCOT_ACTIVATE = "mascot_activate"

ALL_HOOKS: list[str] = [
    HOOK_PIPELINE_COMPLETE,
    HOOK_PIPELINE_ITERATION,
    HOOK_NETWORK_SCAN,
    HOOK_SWARM_RUN,
    HOOK_SEARCH,
    HOOK_FINGERPRINT,
    HOOK_BOT_START,
    HOOK_SHARE,
    HOOK_PERSONA_CHANGE,
    HOOK_FOCUS_MODE,
    HOOK_MASCOT_ACTIVATE,
]

# ──────────────────────────────────────────────────────────────────────
#  Built-in Achievement Definitions  (17 total)
# ──────────────────────────────────────────────────────────────────────

BUILTIN_ACHIEVEMENTS: list[dict[str, Any]] = [
    # ── Pipeline ──
    {
        "id": "first_run",
        "name": "First Pipeline",
        "description": "Run your first pipeline",
        "icon": "\U0001f680",
        "xp": 10,
        "category": "pipeline",
        "condition": {"hook": HOOK_PIPELINE_COMPLETE, "one_shot": True},
    },
    {
        "id": "bug_squasher",
        "name": "Bug Squasher",
        "description": "Fix 10 test failures",
        "icon": "\U0001f41b",
        "xp": 50,
        "category": "pipeline",
        "condition": {
            "hook": HOOK_PIPELINE_ITERATION,
            "field": "test_failures_fixed",
            "threshold": 10,
        },
    },
    {
        "id": "pit_master",
        "name": "Pipeline Master",
        "description": "Run 100 pipelines",
        "icon": "\U0001f3ed",
        "xp": 200,
        "category": "pipeline",
        "condition": {
            "hook": HOOK_PIPELINE_COMPLETE,
            "field": "total_runs",
            "threshold": 100,
        },
    },
    {
        "id": "perfect_run",
        "name": "Perfect Run",
        "description": "Pass on first iteration",
        "icon": "\U0001f48e",
        "xp": 100,
        "category": "pipeline",
        "condition": {
            "hook": HOOK_PIPELINE_COMPLETE,
            "field": "first_iteration_pass",
            "threshold": 1,
        },
    },
    # ── Network ──
    {
        "id": "first_scan",
        "name": "First Contact",
        "description": "Run a network scan",
        "icon": "\U0001f4e1",
        "xp": 10,
        "category": "network",
        "condition": {"hook": HOOK_NETWORK_SCAN, "one_shot": True},
    },
    {
        "id": "net_ninja",
        "name": "Network Ninja",
        "description": "Scan 50 hosts total",
        "icon": "\U0001f977",
        "xp": 100,
        "category": "network",
        "condition": {
            "hook": HOOK_NETWORK_SCAN,
            "field": "total_hosts_scanned",
            "threshold": 50,
        },
    },
    {
        "id": "fingerprinter",
        "name": "Banner Lord",
        "description": "Run fingerprinter 10 times",
        "icon": "\U0001f3f4",
        "xp": 75,
        "category": "network",
        "condition": {
            "hook": HOOK_FINGERPRINT,
            "field": "total_runs",
            "threshold": 10,
        },
    },
    # ── Swarm ──
    {
        "id": "first_swarm",
        "name": "Swarm Commander",
        "description": "First multi-agent swarm",
        "icon": "\U0001f41d",
        "xp": 25,
        "category": "swarm",
        "condition": {"hook": HOOK_SWARM_RUN, "one_shot": True},
    },
    {
        "id": "swarm_master",
        "name": "Hive Mind",
        "description": "Run 25 swarm commands",
        "icon": "\U0001f9e0",
        "xp": 150,
        "category": "swarm",
        "condition": {
            "hook": HOOK_SWARM_RUN,
            "field": "total_runs",
            "threshold": 25,
        },
    },
    # ── Social ──
    {
        "id": "first_share",
        "name": "Social Butterfly",
        "description": "Share a session",
        "icon": "\U0001f98b",
        "xp": 10,
        "category": "social",
        "condition": {"hook": HOOK_SHARE, "one_shot": True},
    },
    {
        "id": "first_bot",
        "name": "Bot Whisperer",
        "description": "Start the Telegram bot",
        "icon": "\U0001f916",
        "xp": 25,
        "category": "social",
        "condition": {"hook": HOOK_BOT_START, "one_shot": True},
    },
    # ── Milestone ──
    {
        "id": "level_5",
        "name": "Apprentice",
        "description": "Reach level 5",
        "icon": "\u2b50",
        "xp": 0,
        "category": "milestone",
        "condition": {"type": "level", "threshold": 5},
    },
    {
        "id": "level_10",
        "name": "Expert",
        "description": "Reach level 10",
        "icon": "\U0001f31f",
        "xp": 0,
        "category": "milestone",
        "condition": {"type": "level", "threshold": 10},
    },
    {
        "id": "level_25",
        "name": "Master",
        "description": "Reach level 25",
        "icon": "\U0001f451",
        "xp": 0,
        "category": "milestone",
        "condition": {"type": "level", "threshold": 25},
    },
    # ── Special ──
    {
        "id": "persona_try",
        "name": "Masquerade",
        "description": "Try a different persona",
        "icon": "\U0001f3ad",
        "xp": 15,
        "category": "special",
        "condition": {"hook": HOOK_PERSONA_CHANGE, "one_shot": True},
    },
    {
        "id": "focus_mode",
        "name": "Deep Focus",
        "description": "Use focus mode 5 times",
        "icon": "\U0001f3a7",
        "xp": 30,
        "category": "special",
        "condition": {
            "hook": HOOK_FOCUS_MODE,
            "field": "total_uses",
            "threshold": 5,
        },
    },
    {
        "id": "first_mascot",
        "name": "New Friend",
        "description": "Unlock the mascot",
        "icon": "\U0001f43e",
        "xp": 15,
        "category": "special",
        "condition": {"hook": HOOK_MASCOT_ACTIVATE, "one_shot": True},
    },
]


# ──────────────────────────────────────────────────────────────────────
#  Default DB path
# ──────────────────────────────────────────────────────────────────────

def _default_db_path() -> Path:
    return HERE / ".virgo_memory" / "achievements.db"


# ──────────────────────────────────────────────────────────────────────
#  AchievementSystem
# ──────────────────────────────────────────────────────────────────────

class AchievementSystem:
    """Gamification backend backed by SQLite.

    Stores achievement definitions in-memory (registered via *register*)
    and persists unlock state in a local SQLite database.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or _default_db_path())
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._achievements: dict[str, dict[str, Any]] = {}
        self._load_achievements()

    # ── internal helpers ────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS achievements (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                icon        TEXT NOT NULL DEFAULT '',
                xp          INTEGER NOT NULL DEFAULT 0,
                category    TEXT NOT NULL DEFAULT 'special',
                condition   TEXT
            );
            CREATE TABLE IF NOT EXISTS unlocked (
                achievement_id TEXT PRIMARY KEY,
                unlocked_at    TEXT NOT NULL,
                context        TEXT DEFAULT ''
            );
        """)
        self._conn.commit()

    def _load_achievements(self) -> None:
        rows = self._conn.execute("SELECT * FROM achievements").fetchall()
        for row in rows:
            d = dict(row)
            if d["condition"]:
                d["condition"] = json.loads(d["condition"])
            self._achievements[d["id"]] = d

    # ── public API ──────────────────────────────────────────────────

    def register(self, achievement: dict) -> None:
        """Register an achievement definition.

        *achievement* must have at least an *id* and *name* key.
        Persisted to the SQLite DB so it survives restarts.
        """
        aid = achievement["id"]
        condition_json = json.dumps(achievement.get("condition", {}))
        self._conn.execute(
            """INSERT OR REPLACE INTO achievements
               (id, name, description, icon, xp, category, condition)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                achievement["name"],
                achievement.get("description", ""),
                achievement.get("icon", ""),
                achievement.get("xp", 0),
                achievement.get("category", "special"),
                condition_json,
            ),
        )
        self._conn.commit()
        self._achievements[aid] = dict(achievement)
        log.debug("Achievement registered: %s (%s)", aid, achievement["name"])

    def check_condition(self, achievement_id: str, hook_data: dict) -> bool:
        """Return True if *achievement_id*'s condition is satisfied by *hook_data*."""
        achievement = self._achievements.get(achievement_id)
        if not achievement:
            return False
        condition = achievement.get("condition", {})
        if not condition:
            return True

        # Level-based ── compare current level to threshold
        if condition.get("type") == "level":
            threshold: int = condition.get("threshold", 1)
            stats = self.get_stats()
            return stats["level"] >= threshold

        # One-shot ── any matching hook call satisfies
        if condition.get("one_shot"):
            return True

        # Count-based ── compare hook_data field to threshold
        field: str | None = condition.get("field")
        threshold = condition.get("threshold", 1)
        value: int = hook_data.get(field, 0) if field else 0
        return value >= threshold

    def trigger(self, achievement_id: str, context: str = "") -> dict | None:
        """Try to unlock an achievement.

        Checks the achievement's condition first.  Returns the achievement
        dict if newly unlocked, *None* if already owned or condition not met.
        """
        if achievement_id not in self._achievements:
            log.warning("Achievement not registered: %s", achievement_id)
            return None
        if not self.check_condition(achievement_id, {}):
            return None
        return self._do_unlock(achievement_id, context)

    def unlock(self, achievement_id: str) -> dict | None:
        """Force-unlock an achievement regardless of its condition.

        Returns the achievement dict if newly unlocked, *None* if already owned.
        """
        if achievement_id not in self._achievements:
            log.warning("Cannot unlock unknown achievement: %s", achievement_id)
            return None
        return self._do_unlock(achievement_id)

    def _do_unlock(self, achievement_id: str, context: str = "") -> dict | None:
        """Internal: insert an unlock record (no condition check)."""
        existing = self._conn.execute(
            "SELECT achievement_id FROM unlocked WHERE achievement_id = ?",
            (achievement_id,),
        ).fetchone()
        if existing:
            return None

        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO unlocked (achievement_id, unlocked_at, context) VALUES (?, ?, ?)",
            (achievement_id, now, context),
        )
        self._conn.commit()
        achievement = self._achievements[achievement_id]
        log.info(
            "[ACHIEVEMENT] %s %s (%s) +%d XP",
            achievement.get("icon", ""),
            achievement["name"],
            achievement_id,
            achievement.get("xp", 0),
        )
        return dict(achievement)

    def get_progress(self, achievement_id: str) -> dict:
        """Return a dict with unlock status for a single achievement."""
        achievement = self._achievements.get(achievement_id)
        unlocked = self._conn.execute(
            "SELECT * FROM unlocked WHERE achievement_id = ?",
            (achievement_id,),
        ).fetchone()
        return {
            "id": achievement_id,
            "name": achievement["name"] if achievement else "Unknown",
            "description": achievement["description"] if achievement else "",
            "icon": achievement.get("icon", "") if achievement else "",
            "xp": achievement.get("xp", 0) if achievement else 0,
            "category": achievement.get("category", "special") if achievement else "special",
            "unlocked": unlocked is not None,
            "unlocked_at": unlocked["unlocked_at"] if unlocked else None,
            "context": unlocked["context"] if unlocked else "",
        }

    def get_all_progress(self) -> list[dict]:
        """Return unlock status for every registered achievement."""
        return [self.get_progress(aid) for aid in sorted(self._achievements)]

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Return the *limit* most recently unlocked achievements."""
        rows = self._conn.execute(
            "SELECT * FROM unlocked ORDER BY unlocked_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            aid = row["achievement_id"]
            ach = self._achievements.get(aid, {})
            result.append(
                {
                    "id": aid,
                    "name": ach.get("name", "Unknown"),
                    "description": ach.get("description", ""),
                    "icon": ach.get("icon", ""),
                    "xp": ach.get("xp", 0),
                    "category": ach.get("category", "special"),
                    "unlocked_at": row["unlocked_at"],
                    "context": row["context"],
                }
            )
        return result

    def get_stats(self) -> dict:
        """Return aggregate stats: XP, level, counts."""
        total_xp = 0
        unlocked_rows = self._conn.execute(
            "SELECT achievement_id FROM unlocked"
        ).fetchall()
        unlocked_count = len(unlocked_rows)
        for row in unlocked_rows:
            ach = self._achievements.get(row["achievement_id"], {})
            total_xp += ach.get("xp", 0)

        current_level = self.get_level(total_xp)
        next_total = self.get_xp_for_next_level(current_level)
        return {
            "total_xp": total_xp,
            "unlocked_count": unlocked_count,
            "registered_count": len(self._achievements),
            "level": current_level,
            "next_level_xp": next_total,
        }

    # ── level helpers ───────────────────────────────────────────────

    @staticmethod
    def get_level(total_xp: int) -> int:
        """Calculate level from cumulative XP.

        ``level = floor(sqrt(xp / 50)) + 1``
        """
        return int((total_xp / 50) ** 0.5) + 1

    @staticmethod
    def get_xp_for_next_level(current_level: int) -> int:
        """Return the *total* XP threshold for the next level.

        Example: level 1 → 50, level 2 → 200, level 3 → 450.
        """
        return 50 * (current_level ** 2)

    # ── hook integration ────────────────────────────────────────────

    def hook(self, hook_name: str, **data: Any) -> list[dict]:
        """Process a hook event from the Virgo framework.

        Checks all registered achievements whose conditions match the
        hook and returns a list of newly-unlocked achievement dicts.
        """
        newly: list[dict[str, Any]] = []

        for aid, achievement in self._achievements.items():
            condition = achievement.get("condition", {})

            # Level achievements are checked on every hook
            if condition.get("type") == "level":
                if self.check_condition(aid, data):
                    result = self._do_unlock(aid)
                    if result is not None:
                        newly.append(result)
                continue

            # Hook-based achievements
            if condition.get("hook") != hook_name:
                continue

            if self.check_condition(aid, data):
                result = self._do_unlock(aid)
                if result is not None:
                    newly.append(result)

        if newly:
            log.info(
                "Hook %s — %d new achievement(s) unlocked",
                hook_name,
                len(newly),
            )
        return newly


# ──────────────────────────────────────────────────────────────────────
#  Singleton  factory
# ──────────────────────────────────────────────────────────────────────

_achievement_system: AchievementSystem | None = None


def get_achievements() -> AchievementSystem:
    """Return the global AchievementSystem singleton.

    Creates and initialises it on first call, registering all built-in
    achievements automatically.
    """
    global _achievement_system
    if _achievement_system is None:
        _achievement_system = AchievementSystem()
        for ach in BUILTIN_ACHIEVEMENTS:
            _achievement_system.register(ach)
    return _achievement_system


# ──────────────────────────────────────────────────────────────────────
#  CLI Handlers  (wired from cli.py)
# ──────────────────────────────────────────────────────────────────────

def cmd_achievements_list(args: Any = None) -> None:
    """Show all achievements with unlock status."""
    system = get_achievements()
    progress = system.get_all_progress()
    print(f"\n{icon('rocket')} VIRGO ACHIEVEMENTS\n")
    for p in progress:
        status = f"{icon('done')}" if p["unlocked"] else f"{icon('goal')}"
        print(f"  {status} {p['icon']} {p['name']}  ({p['id']})")
        print(f"       {p['description']}  \u2014  +{p['xp']} XP  [{p['category']}]")
        if p["unlocked_at"]:
            print(f"       Unlocked: {p['unlocked_at']}")
        print()

    stats = system.get_stats()
    print(
        f"{icon('info')}  "
        f"Level {stats['level']}  \u2022  "
        f"{stats['total_xp']} XP  \u2022  "
        f"{stats['unlocked_count']}/{stats['registered_count']} unlocked"
    )
    print(f"       {stats['next_level_xp']} total XP needed for next level\n")


def cmd_achievements_recent(args: Any = None) -> None:
    """Show recently unlocked achievements."""
    system = get_achievements()
    recent = system.get_recent()
    if not recent:
        print(f"\n{icon('info')} No achievements unlocked yet.\n")
        return
    print(f"\n{icon('history')} RECENT ACHIEVEMENTS\n")
    for r in recent:
        print(f"  {r['icon']} {r['name']}  (+{r['xp']} XP)  \u2014  {r['unlocked_at']}")
    print()


def cmd_achievements_stats(args: Any = None) -> None:
    """Show XP, level, and next-level progress."""
    system = get_achievements()
    stats = system.get_stats()
    print(f"\n{icon('info')} ACHIEVEMENT STATS\n")
    print(f"  Level:          {stats['level']}")
    print(f"  Total XP:       {stats['total_xp']}")
    print(f"  Unlocked:       {stats['unlocked_count']}/{stats['registered_count']}")
    print(f"  Next level at:  {stats['next_level_xp']} total XP\n")


# ──────────────────────────────────────────────────────────────────────
#  Main (self-test)
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("list", "recent", "stats"):
        {
            "list": cmd_achievements_list,
            "recent": cmd_achievements_recent,
            "stats": cmd_achievements_stats,
        }[sys.argv[1]](sys.argv[1:])
    else:
        cmd_achievements_list(None)

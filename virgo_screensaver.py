"""
virgo_screensaver — Terminal screensaver for Virgo.

When the dashboard sits idle, this module provides animated
screensaver modes: Matrix rain, Star Wars crawl, and system stat scroller.

Usage:
    virgo screensaver matrix          # Start Matrix rain
    virgo screensaver crawl           # Start Star Wars crawl
    virgo screensaver stats           # Start system stat scroller
    virgo screensaver stop            # Stop any running screensaver
    virgo screensaver timeout 120     # Set idle timeout in seconds
"""

from __future__ import annotations

import os
import random
import shutil
import string
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── ANSI helpers ──────────────────────────────────────────────────────────

_R = "\033[0m"
_D = "\033[2m"
_GR = "\033[32m"
_CY = "\033[36m"
_WH = "\033[37m"
_YL = "\033[33m"

# ── State ─────────────────────────────────────────────────────────────────

_active_mode: str | None = None
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None
_idle_timeout: int = 120  # seconds
_last_activity: float = time.time()
_screensaver_enabled: bool = True


def _get_size() -> tuple[int, int]:
    """Get terminal size as (cols, rows)."""
    try:
        return shutil.get_terminal_size()
    except Exception:
        return (80, 24)


def _clear() -> None:
    """Clear screen."""
    os.system("cls" if os.name == "nt" else "clear")


def _hide_cursor() -> None:
    """Hide terminal cursor."""
    print("\033[?25l", end="", flush=True)


def _show_cursor() -> None:
    """Show terminal cursor."""
    print("\033[?25h", end="", flush=True)


# ── Matrix Rain ────────────────────────────────────────────────────────────

_CYBER_CHARS = string.ascii_uppercase + string.digits + "!@#$%^&*()_+-=[]{}|;:',.<>?/"


def _matrix_rain(stop: threading.Event) -> None:
    """Matrix rain animation."""
    cols, rows = _get_size()
    # Track column positions and speeds
    drops: list[int] = [random.randint(-rows, 0) for _ in range(cols)]
    speeds: list[float] = [random.uniform(0.05, 0.3) for _ in range(cols)]

    _hide_cursor()
    _clear()

    try:
        while not stop.is_set():
            cols_now, rows_now = _get_size()

            # Resize arrays if terminal changed
            while len(drops) < cols_now:
                drops.append(random.randint(-rows_now, 0))
                speeds.append(random.uniform(0.05, 0.3))
            while len(drops) > cols_now:
                drops.pop()
                speeds.pop()

            out_lines: list[list[str]] = [[" "] * cols_now for _ in range(rows_now)]

            for col in range(cols_now):
                drop = drops[col]
                speed = speeds[col]

                if drop < 0:
                    drops[col] += 1
                    continue

                for i in range(3):  # Trail length
                    y = int(drop) - i
                    if 0 <= y < rows_now:
                        char = random.choice(_CYBER_CHARS)
                        if i == 0:
                            # Lead character is bright white
                            out_lines[y][col] = f"{_WH}{_B}{char}{_R}"
                        elif i == 1:
                            # Bright green
                            out_lines[y][col] = f"{_GR}{_B}{char}{_R}"
                        else:
                            # Dim green
                            out_lines[y][col] = f"{_GR}{_D}{char}{_R}"

                drops[col] += speed
                if drops[col] >= rows_now:
                    drops[col] = 0
                    speeds[col] = random.uniform(0.05, 0.3)

            # Title overlay
            title_y = rows_now // 3
            title_x = cols_now // 2 - 15
            if title_x > 0 and title_y < rows_now:
                title = "VIRGO"
                for i, ch in enumerate(title):
                    if title_x + i < cols_now:
                        out_lines[title_y][title_x + i] = f"{_GR}{_B}{ch}{_R}"
                subtitle = "multi-agent state machine"
                for i, ch in enumerate(subtitle):
                    if title_x + i < cols_now:
                        out_lines[title_y + 1][title_x + i] = f"{_D}{_GR}{ch}{_R}"

            # Render
            frame = "\n".join("".join(line) for line in out_lines)
            print(f"\033[{rows_now}A{frame}", end="", flush=True)

            stop.wait(0.05)

    finally:
        _show_cursor()


# ── Star Wars Crawl ──────────────────────────────────────────────────────


_CRAWL_TEXT = [
    "EPISODE VIII",
    "",
    "THE LAST COMMIT",
    "",
    "It is a period of great debugging.",
    "The virgo pipeline, running",
    "on a lone developer's machine,",
    "has detected a bug in the",
    "production deployment...",
    "",
    "Imperial forces, led by the",
    "dreaded Linter, have unleashed",
    "a wave of syntax errors across",
    "the codebase...",
    "",
    "Meanwhile, a young developer",
    "named Mikey discovers a powerful",
    "tool known as 'virgo run --chaos'",
    "that could save the repositories...",
    "",
    "PRESS ANY KEY TO EXIT",
]


def _star_wars_crawl(stop: threading.Event) -> None:
    """Star Wars style scrolling text."""
    _hide_cursor()
    _clear()

    cols, rows = _get_size()

    try:
        line_num = 0
        while not stop.is_set():
            cols_now, _ = _get_size()
            _clear()

            # Show lines scrolling upward
            for i in range(rows_now):
                idx = line_num + i - rows_now + 1
                if 0 <= idx < len(_CRAWL_TEXT):
                    line = _CRAWL_TEXT[idx]
                    # Center text
                    padding = max(0, (cols_now - len(line)) // 2)
                    if idx == 0:
                        print(f"{' ' * padding}{_YL}{_B}{line}{_R}")
                    else:
                        print(f"{' ' * padding}{_CY}{line}{_R}")
                else:
                    print()

            line_num += 1
            if line_num > len(_CRAWL_TEXT) + rows_now:
                line_num = 0
                time.sleep(1)

            stop.wait(0.15)

    finally:
        _show_cursor()


# ── System Stats Scroller ─────────────────────────────────────────────────


def _stats_scroller(stop: threading.Event) -> None:
    """Scrolling system stats display."""
    _hide_cursor()
    _clear()

    has_psutil = False
    try:
        import psutil as _ps  # noqa: PLC0415
        has_psutil = True
    except ImportError:
        pass

    col = 0
    try:
        while not stop.is_set():
            cols, rows = _get_size()
            _clear()

            # Header
            print(f"{'':^{cols}s}".join([
                f"{_GR}{_B}═══ VIRGO SYSTEM MONITOR ═══{_R}"
            ]))
            print()

            # Stat lines
            lines = [
                ("Host", os.environ.get("COMPUTERNAME", "unknown")),
                ("Time", time.strftime("%Y-%m-%d %H:%M:%S")),
                ("Uptime", f"{time.time() - _last_activity:.0f}s since last activity"),
            ]

            if has_psutil:
                try:
                    cpu = _ps.cpu_percent(interval=0.1)
                    ram = _ps.virtual_memory()
                    disk = _ps.disk_usage(os.path.sep)
                    boot = _ps.boot_time()
                    boot_time = time.strftime("%H:%M:%S", time.localtime(boot))
                    lines.extend([
                        ("CPU", f"{cpu:.0f}%"),
                        ("RAM", f"{ram.percent:.0f}% ({ram.used // 1024**3}GB/{ram.total // 1024**3}GB)"),
                        ("Disk", f"{disk.percent:.0f}% ({disk.used // 1024**3}GB/{disk.total // 1024**3}GB)"),
                        ("Boot", boot_time),
                    ])
                except Exception:
                    pass

            for key, val in lines:
                # Animated dots based on column
                dots = "." * (col % 12 // 3)
                print(f"  {_GR}{key:12s}{_R} {val} {_D}{dots}{_R}")

            # Spacer
            print()
            for _ in range(rows - len(lines) - 5):
                print()

            # Footer
            print(f"{_D}{'─' * cols}{_R}")
            print(f"{_D}  PRESS ANY KEY TO EXIT  |  Screensaver active{_R}")

            col += 1
            stop.wait(1.0)

    finally:
        _show_cursor()


# ── Public API ────────────────────────────────────────────────────────────

MODES = {
    "matrix": {"name": "Matrix Rain", "fn": _matrix_rain, "desc": "Falling green code"},
    "crawl": {"name": "Star Wars Crawl", "fn": _star_wars_crawl, "desc": "Scrolling story text"},
    "stats": {"name": "System Stats", "fn": _stats_scroller, "desc": "Live system monitoring"},
}


def start(mode: str = "matrix") -> dict:
    """Start a screensaver mode."""
    global _active_mode, _thread, _stop_event  # noqa: PLW0603

    if mode not in MODES:
        return {"error": f"Unknown mode '{mode}'. Available: {', '.join(MODES)}"}

    stop()

    _active_mode = mode
    _stop_event = threading.Event()

    _thread = threading.Thread(
        target=MODES[mode]["fn"], args=(_stop_event,), daemon=True
    )
    _thread.start()

    return {"status": "started", "mode": mode, "name": MODES[mode]["name"]}


def stop() -> dict:
    """Stop any running screensaver."""
    global _active_mode, _thread, _stop_event  # noqa: PLW0603

    if _stop_event:
        _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=2.0)
    _show_cursor()

    _active_mode = None
    _stop_event = None
    _thread = None

    return {"status": "stopped"}


def status() -> dict:
    """Return current screensaver status."""
    return {
        "active": _active_mode is not None,
        "mode": _active_mode,
        "timeout": _idle_timeout,
        "enabled": _screensaver_enabled,
    }


def set_timeout(seconds: int) -> dict:
    """Set the idle timeout before screensaver activates."""
    global _idle_timeout  # noqa: PLW0603
    _idle_timeout = max(10, seconds)
    return {"timeout": _idle_timeout}


def register_activity() -> None:
    """Call this on any user activity to reset the idle timer."""
    global _last_activity  # noqa: PLW0603
    _last_activity = time.time()


def list_modes() -> list[dict]:
    """List available screensaver modes."""
    return [
        {"id": mid, "name": cfg["name"], "description": cfg["desc"]}
        for mid, cfg in MODES.items()
    ]


# ── CLI handlers ──────────────────────────────────────────────────────────


def cmd_screensaver(args: Any) -> None:
    """Handle screensaver subcommands."""
    cmd = getattr(args, "screensaver_command", None)

    if cmd == "list" or not cmd:
        modes = list_modes()
        print(f"\n  {icon('virgo')} Screensaver Modes")
        print(f"  {'─' * 50}")
        for m in modes:
            print(f"  [{m['id']:8s}] {m['name']:20s}  {m['description']}")
        print(f"\n  Timeout: {_idle_timeout}s | Active: {_active_mode or 'none'}")
        print()

    elif cmd in MODES:
        start(cmd)
        # The screensaver takes over the terminal, so we note:
        st = status()
        print(f"  {icon('virgo')} Screensaver: {st.get('mode', '?')} started")
        print("  (close terminal tab or press Ctrl+C to exit)")

    elif cmd == "stop":
        stop()
        print(f"  {icon('history')} Screensaver stopped")

    elif cmd == "timeout":
        val = getattr(args, "timeout_val", 120)
        set_timeout(val)
        print(f"  {icon('brain')} Screensaver timeout set to {val}s")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virgo Screensaver")
    sub = parser.add_subparsers(dest="command")
    for mode_id in MODES:
        sub.add_parser(mode_id, help=f"Start {mode_id} screensaver")
    sub.add_parser("stop", help="Stop screensaver")
    sub.add_parser("list", help="List modes")
    p_timeout = sub.add_parser("timeout", help="Set idle timeout")
    p_timeout.add_argument("seconds", type=int, nargs="?", default=120)

    args = parser.parse_args()
    if args.command == "list":
        for m in list_modes():
            print(f"  {m['id']:8s}  {m['name']:20s}  {m['description']}")
    elif args.command == "stop":
        stop()
        print("Stopped")
    elif args.command == "timeout":
        set_timeout(args.seconds)
        print(f"Timeout: {_idle_timeout}s")
    elif args.command in MODES:
        r = start(args.command)
        print(f"Started: {r.get('name', args.command)}")
        try:
            while _active_mode:
                time.sleep(1)
        except KeyboardInterrupt:
            stop()
    else:
        parser.print_help()

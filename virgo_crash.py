"""
Crash reporter and last-good-state restore system for virgo_desktop.py.

Records unhandled exceptions to .virgo_crash_reports/ and exposes a small CLI.
Uses stdlib only.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path(".virgo_crash_reports")
LAST_CRASH_MARKER = Path(".virgo_last_crash")
MAX_REPORTS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_tail(log_file: str | None, max_bytes: int = 4096) -> str:
    if not log_file:
        return ""
    p = Path(log_file)
    if not p.exists():
        return ""
    try:
        data = p.read_bytes()
        tail = data[-max_bytes:]
        return tail.decode("utf-8", "replace")
    except Exception:
        return ""


def record_crash(
    exc_type,
    exc_value,
    exc_tb,
    last_active_page: str | None = None,
    log_file: str | None = None,
) -> str | None:
    """Write a crash report JSON and maintain a rolling buffer of 5 reports.

    Also writes .virgo_last_crash pointing at the newest report.
    Returns the path to the newly written report, or None on failure.
    """
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pid = os.getpid()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{pid}.json"
        report_path = REPORTS_DIR / filename

        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        report = {
            "timestamp": _utc_now(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "exception_type": exc_type.__name__ if exc_type else None,
            "exception_message": str(exc_value) if exc_value else None,
            "traceback": tb_text,
            "last_active_page": last_active_page,
            "log_tail": _log_tail(log_file),
        }

        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        _purge_old_reports()

        try:
            LAST_CRASH_MARKER.write_text(str(report_path), encoding="utf-8")
        except Exception:
            pass

        return str(report_path)
    except Exception:
        return None


def _purge_old_reports() -> None:
    try:
        files = sorted(
            REPORTS_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[MAX_REPORTS:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def list_reports() -> list[str]:
    if not REPORTS_DIR.exists():
        return []
    return sorted(str(p) for p in REPORTS_DIR.glob("*.json"))


def show_report(path: str) -> None:
    p = Path(path)
    if not p.exists():
        print(f"Report not found: {path}")
        return
    print(p.read_text(encoding="utf-8"))


def clear_reports() -> None:
    if not REPORTS_DIR.exists():
        return
    for p in REPORTS_DIR.glob("*.json"):
        try:
            p.unlink()
        except Exception:
            pass
    try:
        LAST_CRASH_MARKER.unlink()
    except Exception:
        pass


def _cli() -> None:
    if len(sys.argv) < 2:
        print("Usage: python virgo_crash.py list|show <file>|clear")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "list":
        reports = list_reports()
        if not reports:
            print("No crash reports found.")
        else:
            for r in reports:
                print(r)
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: python virgo_crash.py show <file>")
            sys.exit(1)
        show_report(sys.argv[2])
    elif cmd == "clear":
        clear_reports()
        print("Crash reports cleared.")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()

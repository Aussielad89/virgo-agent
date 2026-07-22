"""
virgo_watchdog — scheduled re-evaluation engine.

Runs the diagnostics → alerts → fixer pipeline on a configurable
interval (default: 60 seconds).  Use this instead of running each
module manually when you want continuous monitoring.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import log

DEFAULT_INTERVAL = 60  # seconds between cycles


def run_cycle() -> dict[str, object]:
    """Execute one full monitoring cycle: diag → alerts → fix.

    Returns a dict with timing and status for each step.
    """
    start = time.time()
    results: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "steps": {},
    }

    # Step 1: Diagnostics
    print(f"{icon('sat')} Watchdog cycle starting...")
    diag_start = time.time()
    try:
        subprocess.run(
            [sys.executable, os.path.join(HERE, "virgo_diagnostics.py")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        results["steps"]["diagnostics"] = "ok"
    except subprocess.TimeoutExpired:
        results["steps"]["diagnostics"] = "timeout"
        print(f"{icon('warn')} diagnostics timed out")
    except Exception as exc:
        results["steps"]["diagnostics"] = f"error: {exc}"
    results["diag_time_s"] = round(time.time() - diag_start, 2)

    # Step 2: Alerts
    alert_start = time.time()
    try:
        subprocess.run(
            [sys.executable, os.path.join(HERE, "virgo_alerts.py")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        results["steps"]["alerts"] = "ok"
    except Exception as exc:
        results["steps"]["alerts"] = f"error: {exc}"
    results["alert_time_s"] = round(time.time() - alert_start, 2)

    # Step 3: Fixer
    fix_start = time.time()
    try:
        subprocess.run(
            [sys.executable, os.path.join(HERE, "virgo_fixer.py")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        results["steps"]["fixer"] = "ok"
    except Exception as exc:
        results["steps"]["fixer"] = f"error: {exc}"
    results["fix_time_s"] = round(time.time() - fix_start, 2)

    results["total_time_s"] = round(time.time() - start, 2)
    return results


def run_watchdog(interval: int = DEFAULT_INTERVAL, cycles: int = 0) -> None:
    """Run the monitoring pipeline repeatedly.

    Args:
        interval: Seconds between cycles.
        cycles:   Number of cycles (0 = run forever until Ctrl+C).
    """
    print(f"\n{icon('shield')} Virgo Watchdog — starting ({interval}s interval)")
    if cycles:
        print(f"{icon('info')} Will run {cycles} cycle(s), then exit.")
    else:
        print(f"{icon('info')} Running indefinitely — Ctrl+C to stop.")
    print("-" * 50)

    count = 0
    try:
        while True:
            count += 1
            print(f"\n{icon('rocket')} Cycle {count} — {datetime.now(UTC).isoformat()}")
            results = run_cycle()
            log.info("Cycle %d complete: %s", count, results["steps"])
            print(f"\n{icon('done')} Cycle {count} finished in {results['total_time_s']}s")

            if cycles and count >= cycles:
                print(f"\n{icon('ok')} All {cycles} cycles complete.")
                break

            print(f"\n{icon('info')} Next cycle in {interval}s...")
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n{icon('warn')} Watchdog stopped by user after {count} cycle(s).")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Virgo watchdog — scheduled monitoring")
    p.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between cycles (default: {DEFAULT_INTERVAL})",
    )
    p.add_argument(
        "-c", "--cycles", type=int, default=0, help="Number of cycles (default: infinite)"
    )
    args = p.parse_args()
    run_watchdog(interval=args.interval, cycles=args.cycles)
    input("\n[PRESS ENTER TO RETURN]")

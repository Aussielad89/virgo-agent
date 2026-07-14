"""
virgo_webhook — alert dispatch gateway with HTTP POST support.

Reads ALERTS_TRIGGERED.txt, packs it into a JSON telemetry payload,
and either POSTs it to a configured endpoint (real mode) or prints
the payload (simulation mode).

Set the WEBHOOK_URL env var for real HTTP dispatch, or omit it to
run in simulation/print mode.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import log

ALERT_FILE = "ALERTS_TRIGGERED.txt"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_RETRIES = int(os.environ.get("WEBHOOK_RETRIES", "3"))


def build_telemetry() -> dict:
    """Read the alert file and build a JSON telemetry payload.

    Returns a dict with keys:
      - agent:  name of the reporting agent
      - status: "dispatched" or "idle"
      - alerts: list of alert strings (empty if file absent)
      - timestamp: ISO-format UTC timestamp
      - alert_count: number of alerts in the payload
    """
    payload: dict = {
        "agent": "virgo-webhook",
        "status": "idle",
        "alerts": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_count": 0,
    }

    if not os.path.exists(ALERT_FILE):
        log.info("No alert file found (%s) — nothing to dispatch.", ALERT_FILE)
        return payload

    with open(ALERT_FILE) as f:
        content = f.read().strip()

    if not content:
        log.info("Alert file is empty — nothing to dispatch.")
        return payload

    payload["alerts"] = [line.strip() for line in content.splitlines() if line.strip()]
    payload["alert_count"] = len(payload["alerts"])
    payload["status"] = "dispatched"
    return payload


def dispatch_http(payload: dict, url: str) -> bool:
    """POST the payload to *url* with retry logic.

    Returns True on success, False if all retries fail.
    """
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "virgo-webhook/1.0"}

    for attempt in range(1, WEBHOOK_RETRIES + 1):
        req = Request(url, data=data, headers=headers)
        try:
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                log.info("Webhook POST %s → %s (attempt %d/%d)", url, resp.status, attempt, WEBHOOK_RETRIES)
                print(f"{icon('ok')} HTTP {resp.status} — {body[:200]}")
                return True
        except URLError as exc:
            log.warning("Webhook attempt %d/%d failed: %s", attempt, WEBHOOK_RETRIES, exc)
            if attempt < WEBHOOK_RETRIES:
                import time as _time
                _time.sleep(1 * attempt)  # linear backoff
            else:
                print(f"{icon('error')} All {WEBHOOK_RETRIES} attempts failed: {exc}")
    return False


def dispatch_webhook(payload: dict) -> None:
    """Dispatch the telemetry payload — either via HTTP or simulation."""
    print(f"\n{icon('sat')} Virgo Webhook Gateway")
    print("-" * 40)

    if payload["status"] != "dispatched":
        print(f"{icon('info')} Dispatch status: {payload['status']} — no action taken.")
        return

    print(f"{icon('rocket')} Dispatch status: {payload['status']}")
    print(f"{icon('alert')} Alert count:     {payload['alert_count']}")
    print(f"{icon('info')} Timestamp:       {payload['timestamp']}")

    if WEBHOOK_URL:
        print(f"{icon('sat')} Endpoint: {WEBHOOK_URL}")
        success = dispatch_http(payload, WEBHOOK_URL)
        status = "dispatched" if success else "failed"
        print(f"\n{icon('done') if success else icon('error')} Dispatch {status}.")
    else:
        print(f"\n{icon('info')} Simulation mode (set WEBHOOK_URL for HTTP POST)\n")
        print(json.dumps(payload, indent=2))
        print(f"\n{icon('done')} Payload printed — dispatch simulated successfully.")

    print()


def run_webhook() -> None:
    """Build telemetry and dispatch."""
    payload = build_telemetry()
    dispatch_webhook(payload)


if __name__ == "__main__":
    run_webhook()
    input("\n[PRESS ENTER TO RETURN]")

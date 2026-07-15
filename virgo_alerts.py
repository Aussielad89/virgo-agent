"""
virgo_alerts — alert engine evaluating system logs.

Reads virgo_network_map.json and virgo_full_report.json to detect
security, hardware, and service anomalies, then writes triggered
alerts to ALERTS_TRIGGERED.txt.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import OUTDIR

NETWORK_MAP_FILE = str(OUTDIR / "virgo_network_map.json")
DIAG_REPORT_FILE = str(OUTDIR / "virgo_full_report.json")
ALERTS_FILE = str(OUTDIR / "ALERTS_TRIGGERED.txt")


def check_thresholds() -> None:
    alert_log: list[str] = []
    print(f"{icon('alert')} Virgo Alert Engine evaluating latest system logs...")

    # 1. Evaluate Network Scan Results
    if os.path.exists(NETWORK_MAP_FILE):
        with open(NETWORK_MAP_FILE) as f:
            net_data = json.load(f)
            scan_results = net_data.get("subnet_scan_results", {})

            for ip, ports in scan_results.items():
                if ip != "192.168.1.1":
                    alert_log.append(
                        f"[SECURITY] Unexpected active host discovered on subnet: {ip} (Ports: {ports})"
                    )
    else:
        alert_log.append(
            f"[SYSTEM] Warning: {NETWORK_MAP_FILE} not found. Run network scanner first."
        )

    # 2. Evaluate Full Diagnostics Report
    if os.path.exists(DIAG_REPORT_FILE):
        with open(DIAG_REPORT_FILE) as f:
            diag_data = json.load(f)

            recon = diag_data.get("1_network_recon", {})
            if recon.get("port_11434") == "CLOSED":
                alert_log.append("[CRITICAL] Ollama Service is down! Port 11434 is closed.")

            logs = diag_data.get("3_log_analysis", [])
            for error in logs:
                raw_log = error.get("raw_log", "")
                action = error.get("suggested_action", "")
                if "error 30" in raw_log.lower():
                    alert_log.append(f"[HARDWARE ALERT] {action}")
                elif "database" in raw_log.lower():
                    alert_log.append(f"[SERVICE ALERT] {action}")
    else:
        alert_log.append(
            f"[SYSTEM] Warning: {DIAG_REPORT_FILE} not found. Run diagnostics suite first."
        )

    # 3. Output Triggered Alerts
    if alert_log:
        print(f"{icon('warn')} {len(alert_log)} alerts triggered! Writing to {ALERTS_FILE}...")
        with open(ALERTS_FILE, "w") as f:
            f.write("\n".join(alert_log))
    else:
        print(f"{icon('ok')} System clear. No alerts triggered.")
        if os.path.exists(ALERTS_FILE):
            os.remove(ALERTS_FILE)


if __name__ == "__main__":
    check_thresholds()

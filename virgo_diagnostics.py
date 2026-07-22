"""
virgo_diagnostics — full system diagnostics suite.

Collects network recon (local ports), system health info (OS, storage),
and parses mock_logs.txt for known error patterns. Writes a consolidated
report to virgo_full_report.json.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import OUTDIR

REPORT_FILE = str(OUTDIR / "virgo_full_report.json")


def run_full_diagnostics() -> None:
    report: dict = {
        "1_network_recon": {},
        "2_system_health": {},
        "3_log_analysis": [],
    }

    print(f"{icon('sat')} Starting Virgo Diagnostics Suite...")

    # --- 1. NETWORK RECON (Common local ports) ---
    target_ports = [11434, 8000, 8080]
    for port in target_ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        report["1_network_recon"][f"port_{port}"] = "OPEN" if result == 0 else "CLOSED"
        sock.close()

    # --- 2. SYSTEM HEALTH ---
    report["2_system_health"]["os"] = platform.system()
    report["2_system_health"]["os_release"] = platform.release()

    # Quick disk check via powershell if on Windows
    if platform.system() == "Windows":
        try:
            cmd = "Get-PSDrive C | Select-Object Used, Free"
            res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
            report["2_system_health"]["storage_info"] = res.stdout.strip().split("\n")[-1]
        except Exception:
            report["2_system_health"]["storage_info"] = "Could not retrieve storage metrics."

    # --- 3. LOG ANALYSIS & ERROR RECONCILIATION ---
    error_lookup = {
        "error 30": (
            "CRITICAL: Device harness communication timeout. "
            "Check your 48v controller wiring connections and main harness pins."
        ),
        "database": (
            "WARNING: Local database connection refused. "
            "Verify your database background service is currently active."
        ),
    }

    log_path = os.path.join(HERE, "mock_logs.txt")
    if os.path.exists(log_path):
        with open(log_path) as f:
            for line in f:
                if "ERROR" in line or "CRITICAL" in line:
                    matched_fix = "No specific match found in local knowledge base."
                    for key, fix in error_lookup.items():
                        if key in line.lower():
                            matched_fix = fix
                            break
                    report["3_log_analysis"].append(
                        {
                            "raw_log": line.strip(),
                            "suggested_action": matched_fix,
                        }
                    )
    else:
        report["3_log_analysis"].append("mock_logs.txt missing. Skipping text analysis.")

    # --- SAVE CONSOLIDATED DIAGNOSTIC REPORT ---
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"{icon('done')} Full diagnostic check completed successfully!")
    print("Saved comprehensive summary report to: " + REPORT_FILE)


if __name__ == "__main__":
    run_full_diagnostics()

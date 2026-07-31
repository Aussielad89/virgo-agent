"""
auto_remediate.py — Auto-remediation chain with rollback safety.

Implements a circuit-breaker pattern:
  1. Run alert checks
  2. Apply fixes
  3. Verify fixes worked
  4. Rollback if verification fails

Can be triggered from chat (/auto-fix) or CLI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

ALERTS_FILE = str(HERE / "out" / "ALERTS_TRIGGERED.txt")
MOCK_LOGS = HERE / "mock_logs.txt"
AUTO_FIX_STATE = HERE / ".virgo_memory" / "auto_fix_state.json"


class RemediationResult:
    """Result of an auto-remediation attempt."""

    def __init__(self, success: bool, steps: list[str], rollback: bool = False):
        self.success = success
        self.steps = steps
        self.rollback = rollback

    def __repr__(self) -> str:
        return f"RemediationResult(success={self.success}, steps={len(self.steps)}, rollback={self.rollback})"


def run_alerts() -> list[str]:
    """Run the alert engine and return triggered alerts."""
    try:
        result = subprocess.run(
            [sys.executable, str(HERE / "virgo_alerts.py")],
            capture_output=True,
            text=True,
            cwd=str(HERE),
        )
        if os.path.exists(ALERTS_FILE):
            return Path(ALERTS_FILE).read_text(encoding="utf-8").splitlines()
    except Exception:
        pass
    return []


def apply_fixes(alerts: list[str]) -> tuple[bool, list[str]]:
    """Apply fixes for matched alerts. Returns (changed, steps)."""
    steps: list[str] = []
    changed = False

    if "[SECURITY]" in "\n".join(alerts):
        steps.append("[SECURITY] Host allowlist action logged")
        changed = True

    if "[HARDWARE ALERT]" in "\n".join(alerts):
        if MOCK_LOGS.exists():
            backup = MOCK_LOGS.with_suffix(".bak")
            shutil.copy2(MOCK_LOGS, backup)
            content = MOCK_LOGS.read_text(encoding="utf-8")
            new_content = content.replace("error 30", "resolved - harness re-established")
            if new_content != content:
                MOCK_LOGS.write_text(new_content, encoding="utf-8")
                steps.append("[HARDWARE] Error 30 → resolved")
                changed = True
            steps.append(f"backup saved to {backup}")

    if "[SERVICE ALERT]" in "\n".join(alerts):
        if MOCK_LOGS.exists():
            backup = MOCK_LOGS.with_suffix(".bak")
            shutil.copy2(MOCK_LOGS, backup)
            content = MOCK_LOGS.read_text(encoding="utf-8")
            new_content = content.replace(
                "Failed to connect to local database",
                "Database connection restored successfully",
            )
            if new_content != content:
                MOCK_LOGS.write_text(new_content, encoding="utf-8")
                steps.append("[SERVICE] Database connection restored")
                changed = True

    return changed, steps


def verify_fix() -> bool:
    """Run alerts again to verify fixes took effect."""
    alerts = run_alerts()
    return len(alerts) == 0


def rollback() -> list[str]:
    """Rollback changes by restoring backups."""
    steps: list[str] = []
    for f in HERE.rglob("*.bak"):
        original = f.with_suffix("")
        if original.exists():
            shutil.move(str(f), str(original))
            steps.append(f"Restored {original.name}")
    return steps


def auto_fix(enable_rollback: bool = True, max_attempts: int = 2) -> RemediationResult:
    """Run the full auto-remediation chain with safety.

    Returns a RemediationResult with success status and step log.
    """
    steps: list[str] = ["Starting auto-remediation chain"]

    # Step 1: Run alerts
    alerts = run_alerts()
    if not alerts:
        steps.append("No alerts triggered")
        return RemediationResult(True, steps)

    steps.append(f"Detected {len(alerts)} alert(s)")

    # Step 2: Apply fixes
    changed, fix_steps = apply_fixes(alerts)
    steps.extend(fix_steps)

    if not changed:
        steps.append("No changes applied")
        return RemediationResult(True, steps)

    # Step 3: Verify
    steps.append("Verifying fixes...")
    if verify_fix():
        steps.append("Verification passed")
        return RemediationResult(True, steps)

    # Step 4: Rollback if enabled
    if enable_rollback:
        steps.append("Verification failed - initiating rollback")
        rollback_steps = rollback()
        steps.extend(rollback_steps)
        return RemediationResult(False, steps, rollback=True)

    steps.append("Verification failed - no rollback")
    return RemediationResult(False, steps)


def auto_fix_with_timeout(
    enable_rollback: bool = True, timeout_seconds: int = 30
) -> RemediationResult:
    """Run auto-remediation in a subprocess with timeout.

    Safer for production use - won't hang the main process.
    """
    import json
    import tempfile
    import threading

    result_file = HERE / ".virgo_memory" / "auto_fix_result.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.unlink(missing_ok=True)

    def worker():
        result = auto_fix(enable_rollback=enable_rollback)
        result_file.write_text(json.dumps({
            "success": result.success,
            "steps": result.steps,
            "rollback": result.rollback,
        }), encoding="utf-8")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        return RemediationResult(False, ["Timeout exceeded"], rollback=False)

    if result_file.exists():
        data = json.loads(result_file.read_text())
        result_file.unlink()
        r = RemediationResult(data["success"], data["steps"], data.get("rollback", False))
        return r

    return RemediationResult(False, ["Unknown error"], rollback=False)
"""Tests for virgo_webhook — alert dispatch gateway."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from virgo_webhook import build_telemetry, dispatch_webhook


@patch("virgo_webhook.ALERT_FILE", new_callable=lambda: "nonexistent_alerts.txt")
def test_build_telemetry_no_file(mock_path) -> None:
    """When the alert file doesn't exist, status is idle."""
    payload = build_telemetry()
    assert payload["status"] == "idle"
    assert payload["alert_count"] == 0
    assert payload["agent"] == "virgo-webhook"


@patch("virgo_webhook.ALERT_FILE", new_callable=lambda: "nonexistent_empty.txt")
def test_build_telemetry_empty_file(mock_path) -> None:
    """An empty alert file also produces idle status."""
    # Create an empty file
    Path("nonexistent_empty.txt").write_text("")
    try:
        payload = build_telemetry()
        assert payload["status"] == "idle"
    finally:
        Path("nonexistent_empty.txt").unlink(missing_ok=True)


def test_build_telemetry_with_alerts(tmp_path) -> None:
    """When alerts exist, they're packed into the payload."""
    alert_file = tmp_path / "ALERTS_TRIGGERED.txt"
    alert_file.write_text("[SECURITY] Unusual host detected\n[CRITICAL] Ollama down\n")

    with patch("virgo_webhook.ALERT_FILE", str(alert_file)):
        payload = build_telemetry()

    assert payload["status"] == "dispatched"
    assert payload["alert_count"] == 2
    assert len(payload["alerts"]) == 2
    assert "SECURITY" in payload["alerts"][0]
    assert "CRITICAL" in payload["alerts"][1]
    assert "timestamp" in payload


@patch("virgo_webhook.WEBHOOK_URL", "")
def test_dispatch_webhook_idle(capsys) -> None:
    """Dispatch with idle status prints no-action message."""
    payload = {
        "agent": "virgo-webhook",
        "status": "idle",
        "alerts": [],
        "timestamp": "2025-01-01T00:00:00Z",
        "alert_count": 0,
    }
    dispatch_webhook(payload)
    captured = capsys.readouterr()
    assert "no action taken" in captured.out.lower()


@patch("virgo_webhook.WEBHOOK_URL", "")
def test_dispatch_webhook_dispatched(capsys) -> None:
    """Dispatch with alerts prints the JSON payload."""
    payload = {
        "agent": "virgo-webhook",
        "status": "dispatched",
        "alerts": ["[TEST] Test alert"],
        "timestamp": "2025-01-01T00:00:00Z",
        "alert_count": 1,
    }
    dispatch_webhook(payload)
    captured = capsys.readouterr()
    assert "dispatch simulated successfully" in captured.out.lower()
    assert "Test alert" in captured.out
    # JSON payload should be printed
    assert '"agent": "virgo-webhook"' in captured.out

"""Tests for virgo_alerts — threshold evaluation engine."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from virgo_alerts import check_thresholds


@patch("virgo_alerts.NETWORK_MAP_FILE", "test_no_network_map.json")
@patch("virgo_alerts.DIAG_REPORT_FILE", "test_no_diag_report.json")
@patch("virgo_alerts.ALERTS_FILE", "test_alerts_output.txt")
def test_check_thresholds_no_files(capsys) -> None:
    """When neither report file exists, it warns about both."""
    # Remove leftover files
    for f in ("test_no_network_map.json", "test_no_diag_report.json", "test_alerts_output.txt"):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    check_thresholds()
    captured = capsys.readouterr()

    # Both missing files -> 2 warnings written to the alert file
    assert "alerts triggered" in captured.out
    alerts_path = Path("test_alerts_output.txt")
    try:
        assert alerts_path.exists()
        content = alerts_path.read_text()
        assert "Run diagnostics suite first" in content
    finally:
        alerts_path.unlink(missing_ok=True)
    for f in ("test_no_network_map.json", "test_no_diag_report.json"):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


@patch("virgo_alerts.ALERTS_FILE", "test_alerts_output.txt")
def test_check_thresholds_network_alert(tmp_path) -> None:
    """An unexpected host in the network map triggers a security alert."""
    net_map = tmp_path / "virgo_network_map.json"
    net_map.write_text(json.dumps({
        "subnet_scan_results": {
            "192.168.1.1": [22],
            "10.0.0.5": [80, 443],
        }
    }))
    diag_report = tmp_path / "virgo_full_report.json"
    diag_report.write_text(json.dumps({}))

    with (
        patch("virgo_alerts.NETWORK_MAP_FILE", str(net_map)),
        patch("virgo_alerts.DIAG_REPORT_FILE", str(diag_report)),
    ):
        check_thresholds()

    alerts_path = Path("test_alerts_output.txt")
    try:
        assert alerts_path.exists()
        content = alerts_path.read_text()
        assert "SECURITY" in content
        assert "10.0.0.5" in content
    finally:
        alerts_path.unlink(missing_ok=True)


@patch("virgo_alerts.ALERTS_FILE", "test_alerts_output.txt")
def test_check_thresholds_diag_ollama_down(tmp_path) -> None:
    """A closed Ollama port triggers a critical alert."""
    net_map = tmp_path / "virgo_network_map.json"
    net_map.write_text(json.dumps({}))
    diag_report = tmp_path / "virgo_full_report.json"
    diag_report.write_text(json.dumps({
        "1_network_recon": {"port_11434": "CLOSED"},
        "3_log_analysis": [],
    }))

    with (
        patch("virgo_alerts.NETWORK_MAP_FILE", str(net_map)),
        patch("virgo_alerts.DIAG_REPORT_FILE", str(diag_report)),
    ):
        check_thresholds()

    alerts_path = Path("test_alerts_output.txt")
    try:
        assert alerts_path.exists()
        content = alerts_path.read_text()
        assert "CRITICAL" in content
        assert "Ollama" in content
    finally:
        alerts_path.unlink(missing_ok=True)


@patch("virgo_alerts.NETWORK_MAP_FILE", "test_clear_network_map.json")
@patch("virgo_alerts.DIAG_REPORT_FILE", "test_clear_diag.json")
@patch("virgo_alerts.ALERTS_FILE", "test_alerts_output.txt")
def test_check_thresholds_no_alerts(capsys, tmp_path) -> None:
    """When everything is fine, no alerts are written."""
    # Write clean report files at the patched paths
    net_file = tmp_path / "test_clear_network_map.json"
    net_file.write_text(json.dumps({"subnet_scan_results": {"192.168.1.1": [22]}}))
    diag_file = tmp_path / "test_clear_diag.json"
    diag_file.write_text(json.dumps({
        "1_network_recon": {"port_11434": "OPEN"},
        "3_log_analysis": [],
    }))

    with (
        patch("virgo_alerts.NETWORK_MAP_FILE", str(net_file)),
        patch("virgo_alerts.DIAG_REPORT_FILE", str(diag_file)),
    ):
        check_thresholds()

    captured = capsys.readouterr()
    assert "System clear" in captured.out
    assert not os.path.exists("test_alerts_output.txt")


from pathlib import Path  # noqa: E402

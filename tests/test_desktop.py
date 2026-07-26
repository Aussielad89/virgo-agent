"""Import-level smoke tests for the Virgo Desktop GUI.

These run headless (no QApplication needed) and verify the desktop modules
import cleanly and expose the expected pages — catching syntax/import
regressions without requiring a display.
"""

import importlib

import pytest

pytest.importorskip("PyQt6")


def test_pages_module_imports():
    mod = importlib.import_module("virgo_desktop_pages")
    for name in (
        "ChatPage",
        "PipelinePage",
        "NetworkPage",
        "DiagnosticsPage",
        "AlertsPage",
        "ScaffoldPage",
        "SessionPage",
        "SwarmPage",
        "LogsPage",
        "SettingsPage",
        "AboutPage",
        "MascotChatPage",
        "ActivityFeedPage",
        "LeaderboardPage",
        "ProcessMonitorPage",
        "BenchmarkPage",
        "PluginsPage",
        "FilesPage",
        "DashboardPage",
        "_StopStream",
    ):
        assert hasattr(mod, name), f"missing {name}"


def test_desktop_module_imports():
    mod = importlib.import_module("virgo_desktop")
    assert hasattr(mod, "VirgoDesktopWindow")
    assert hasattr(mod, "DESKTOP_ICONS")
    assert "pipeline" in mod.DESKTOP_ICONS
    assert "settings" in mod.DESKTOP_ICONS

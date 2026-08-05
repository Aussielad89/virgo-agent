"""Tests for virgo_notifications (store + scanning) and the desktop wiring.

The store is pure stdlib and runs headless. Page-level tests run offscreen
(QT_QPA_PLATFORM=offscreen) so they work on machines without a display.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def store(tmp_path):
    from virgo_notifications import NotificationStore

    return NotificationStore(tmp_path / "feed.json")


# ── store logic (headless) ─────────────────────────────────────────────


def test_emit_and_dedupe(store):
    first = store.emit("t", "Title", "msg", severity="warning")
    dup = store.emit("t", "Title", "msg", severity="warning")
    other = store.emit("t", "Title", "different")
    assert first is not None and dup is None
    assert other is not None
    assert len(store.all()) == 2


def test_unread_and_mark_read(store):
    a = store.emit("t", "A", "one")
    store.emit("t", "B", "two")
    assert len(store.unread()) == 2
    store.mark_read(a["id"])
    assert len(store.unread()) == 1
    store.mark_all_read()
    assert store.unread() == []


def test_persistence_roundtrip(tmp_path):
    from virgo_notifications import NotificationStore

    path = tmp_path / "feed.json"
    s1 = NotificationStore(path)
    item = s1.emit("t", "Title", "persisted", severity="critical")
    s1.mark_read(item["id"])
    s2 = NotificationStore(path)
    assert len(s2.all()) == 1
    assert s2.all()[0]["read"] is True
    # Re-emitting the same content on the fresh store must not duplicate.
    assert s2.emit("t", "Title", "persisted") is None


def test_clear(store):
    store.emit("t", "A", "one")
    store.clear()
    assert store.all() == []
    assert store.unread() == []


def test_severity_guess():
    from virgo_notifications import _severity

    assert _severity("CRITICAL: device timeout") == "critical"
    assert _severity("warning: high cpu") == "warning"
    assert _severity("all good") == "info"


def test_scan_sources_dedupe(store):
    """Scanning the real output dir twice must not duplicate items."""
    new1 = store.scan_all()
    new2 = store.scan_all()
    assert new2 == []  # everything was already recorded
    # All new items are genuinely new entries in the feed.
    assert all(n in store.all() for n in new1)


def test_emit_ignores_unknown_severity(store):
    item = store.emit("t", "T", "m", severity="loud")
    assert item is not None
    assert item["severity"] == "info"


# ── desktop page wiring (offscreen) ────────────────────────────────────


def test_notifications_page_constructs_and_renders(qapp):
    from virgo_notifications import NotificationStore
    from virgo_desktop_pages import NotificationsPage

    page = NotificationsPage()
    page._store = NotificationStore(tempfile.mkdtemp() + "/feed.json")
    page._store.emit("alerts", "Alert", "something warned", severity="warning")
    page._store.emit("network", "Scan", "3 hosts", severity="info")
    page._render(page._store.all())
    assert page.list.count() == 2
    page._mark_all_read()
    assert page._store.unread() == []


def test_chat_memory_injection(qapp, tmp_path, monkeypatch):
    """_build_system must inject recalled past experience into the prompt."""
    from experience import ExperienceMemory
    from virgo_desktop_pages import ChatPage

    mem_path = tmp_path / "exp.jsonl"
    mem = ExperienceMemory(str(mem_path))
    mem.add(
        goal="fix the flaky parser test",
        approach="chat",
        tools_used=["chat"],
        outcome="mocked the clock and the test passed",
        success=True,
        lesson="freeze time in tests",
    )
    monkeypatch.setattr("experience.get_memory", lambda path=None: mem)

    page = ChatPage()
    system = page._build_system("how do I fix a flaky parser test?")
    # Experience context should be present (it references the stored goal).
    assert "PAST EXPERIENCE" in system or "flaky parser test" in system


def test_chat_search_renders_cards(qapp):
    from virgo_desktop_pages import ChatPage

    page = ChatPage()
    payload = json.dumps(
        {
            "status": "success",
            "results": [
                {
                    "title": "Virgo Agent",
                    "url": "https://example.com/virgo",
                    "snippet": "A multi-agent state machine.",
                }
            ],
        }
    )
    page._render_search("virgo agent", payload)
    assert page._search_context  # context retained for follow-ups
    assert "example.com" in page._search_context


def test_chat_search_error_path(qapp):
    from virgo_desktop_pages import ChatPage

    page = ChatPage()
    page._render_search("q", json.dumps({"status": "error", "message": "blocked"}))
    assert page._search_context == ""


def test_chat_remember_writes_experience(qapp, tmp_path, monkeypatch):
    from experience import ExperienceMemory
    from virgo_desktop_pages import ChatPage

    mem_path = tmp_path / "exp.jsonl"
    mem = ExperienceMemory(str(mem_path))
    monkeypatch.setattr("experience.get_memory", lambda path=None: mem)

    page = ChatPage()
    page._last_user = "create a notes app"
    page._last_reply = "done, scaffolded notes app"
    page._remember_last_exchange()
    assert mem.stats()["count"] == 1
    assert mem.recall("create a notes app", k=1)[0]["goal"] == "create a notes app"

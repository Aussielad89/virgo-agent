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
        "NotificationsPage",
        "_StopStream",
    ):
        assert hasattr(mod, name), f"missing {name}"


def test_desktop_module_imports():
    mod = importlib.import_module("virgo_desktop")
    assert hasattr(mod, "VirgoDesktopWindow")
    assert hasattr(mod, "DESKTOP_ICONS")
    assert "pipeline" in mod.DESKTOP_ICONS
    assert "settings" in mod.DESKTOP_ICONS


# ── Prompt library helpers (pure, no Qt needed) ──────────────────────────


def _pages():
    return importlib.import_module("virgo_desktop_pages")


def test_prompt_slug_is_safe_and_consistent():
    mod = _pages()
    assert mod._prompt_slug("Tech Time Machine") == "tech_time_machine"
    assert mod._prompt_slug("A/B? Test!") == "a_b_test"
    assert mod._prompt_slug("   ") == "prompt"
    assert mod._prompt_slug("Roast Me?") == "roast_me"


def test_prompt_variable_extraction_and_filling():
    mod = _pages()
    text = "Explain {{topic}} to a 5-year-old, tone {{ tone }}."
    assert mod._find_prompt_vars(text) == ["topic", "tone"]
    filled = mod._fill_prompt_vars(text, {"topic": "black holes", "tone": "silly"})
    assert filled == "Explain black holes to a 5-year-old, tone silly."
    # Unknown placeholders are left untouched.
    assert mod._fill_prompt_vars("{{missing}}", {}) == "{{missing}}"


def test_prompt_file_round_trip(tmp_path):
    mod = _pages()
    dest = mod._write_prompt_file(tmp_path, "Haiku Everything", "5-7-5 it.", "General")
    assert dest.name == "haiku_everything.json"
    data = mod._load_prompt_file(dest)
    assert data["name"] == "Haiku Everything"
    assert data["text"] == "5-7-5 it."
    assert data["category"] == "General"
    assert data["_path"] == str(dest)


def test_load_prompt_file_handles_bad_json(tmp_path):
    mod = _pages()
    bad = tmp_path / "broken.json"
    bad.write_text("not json {", encoding="utf-8")
    assert mod._load_prompt_file(bad) is None


def test_chat_session_round_trip(tmp_path, monkeypatch):
    mod = _pages()
    monkeypatch.setattr(mod, "_CHAT_HISTORY_DIR", tmp_path)
    assert mod._load_recent_chat() is None
    path = mod._chat_session_path()
    assert path.parent == tmp_path
    assert path.name.startswith("chat_")
    payload = {
        "session_id": "abc123",
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    }
    import json

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    msgs, model, sid = mod._load_recent_chat()
    assert msgs == payload["messages"]
    assert model == "test-model"
    assert sid == "abc123"


def test_prompt_contract_matches_library_reader(tmp_path):
    """A prompt written the same way the panel saves it loads correctly."""
    import json as _json

    mod = _pages()
    name = "Stack Trace Oracle"
    dest = mod._write_prompt_file(tmp_path, name, "diagnose it", "Debug")
    raw = _json.loads(dest.read_text(encoding="utf-8"))
    assert set(raw) == {"name", "text", "category"}
    assert raw["category"] == "Debug"

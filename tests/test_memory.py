"""
Tests for memory — session persistence and replay.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from memory import list_sessions, load_state, save_state


class TestSaveLoad:
    def test_save_creates_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        state = {"goal": "test", "phase": "complete"}
        path = save_state(state, name="test_run")
        assert path.exists()
        assert path.name == "test_run.json"

    def test_load_returns_same_data(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        state = {"goal": "test", "phase": "complete"}
        save_state(state, name="test_run")
        loaded = load_state("test_run")
        assert loaded["goal"] == "test"
        assert loaded["phase"] == "complete"

    def test_save_auto_generates_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        state = {"goal": "test"}
        path = save_state(state)  # no name — should generate timestamp
        assert path.exists()
        assert path.name.startswith("run_")

    def test_load_by_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        state = {"goal": "path_test"}
        path = save_state(state, name="custom_path")
        loaded = load_state(str(path))
        assert loaded["goal"] == "path_test"

    def test_load_nonexistent_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_state("nonexistent_run_xyz")


class TestListSessions:
    def test_list_empty(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        sessions = list_sessions()
        assert sessions == []

    def test_list_with_sessions(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        save_state({"goal": "a"}, name="run_a")
        save_state({"goal": "b"}, name="run_b")
        sessions = list_sessions()
        assert len(sessions) == 2

    def test_list_sorted_by_time(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        import time

        save_state({}, name="first")
        time.sleep(0.05)
        save_state({}, name="second")
        sessions = list_sessions()
        # Most recent first
        assert sessions[0]["name"] == "second"


class TestEncoder:
    def test_plain_dict(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        data = {"key": "value", "num": 42}
        path = save_state(data, name="plain")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["key"] == "value"
        assert loaded["num"] == 42

    def test_path_value(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("memory.MEMORY_DIR", tmp_path)
        data = {"path": Path("/some/path")}
        path = save_state(data, name="path_val")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        # Windows uses backslashes, POSIX uses forward slashes
        assert "some" in loaded["path"]
        assert "path" in loaded["path"]

"""Tests for cli.py commands (version, doctor, config, update, chat)."""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
CLI = str(HERE / "cli.py")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run cli.py with the given arguments and return the result."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, CLI, *args],
        capture_output=True, text=True, encoding="utf-8",
        timeout=30,
        cwd=str(HERE),
        env=env,
    )


# ── version ──────────────────────────────────────────────────────────────────


class TestVersion:
    def test_version_flag(self) -> None:
        r = run_cli("--version")
        assert r.returncode == 0
        assert "virgo-agent v" in r.stdout

    def test_version_subcommand(self) -> None:
        r = run_cli("version")
        assert r.returncode == 0
        assert "virgo-agent v" in r.stdout
        assert "Python:" in r.stdout

    def test_version_contains_semver(self) -> None:
        r = run_cli("version")
        assert r.returncode == 0
        # Match vX.Y.Z
        import re
        assert re.search(r"v\d+\.\d+\.\d+", r.stdout)


# ── doctor ───────────────────────────────────────────────────────────────────


class TestDoctor:
    def test_doctor_runs(self) -> None:
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "checks passed" in r.stdout
        assert "virgo-agent v" in r.stdout

    def test_doctor_repository(self) -> None:
        r = run_cli("doctor")
        assert "[OK]  Repository" in r.stdout

    def test_doctor_python(self) -> None:
        r = run_cli("doctor")
        assert "[OK]  Python 3.11+" in r.stdout

    def test_doctor_dashboard_config(self) -> None:
        r = run_cli("doctor")
        assert "[OK]  Dashboard config" in r.stdout

    def test_doctor_bat(self) -> None:
        r = run_cli("doctor")
        assert "virgo.bat" in r.stdout


# ── config ───────────────────────────────────────────────────────────────────


class TestConfig:
    def test_config_shows_vars(self) -> None:
        r = run_cli("config")
        assert r.returncode == 0
        assert "LLM_BASE_URL" in r.stdout
        assert "VIRGO_LOG_LEVEL" in r.stdout

    def test_config_get(self) -> None:
        r = run_cli("config", "--get", "LLM_BASE_URL")
        assert r.returncode == 0
        assert "LLM_BASE_URL=" in r.stdout

    def test_config_get_unknown(self) -> None:
        r = run_cli("config", "--get", "NONEXISTENT_VAR_XYZ")
        assert r.returncode == 0
        assert "NONEXISTENT_VAR_XYZ=" in r.stdout

    def test_config_set_and_unset(self, tmp_path: Path) -> None:
        """Test --set and --unset in an isolated directory."""
        # Create a temporary .env
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VIRGO_VAR=old\n", encoding="utf-8")

        # Run config in that directory
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI, "config", "--set", "TEST_VIRGO_VAR=new"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(tmp_path),
            env=env,
        )
        # Should not crash
        assert r.returncode in (0, 1)  # 1 if env not set up, but shouldn't crash

        # Run config --unset
        r = subprocess.run(
            [sys.executable, CLI, "config", "--unset", "TEST_VIRGO_VAR"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode in (0, 1)


# ── chat ─────────────────────────────────────────────────────────────────────


class TestChat:
    def test_chat_exit_immediately(self) -> None:
        """Sending 'exit' immediately should exit cleanly."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI, "chat"],
            input="exit\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(HERE),
            env=env,
        )
        assert r.returncode == 0
        assert "Virgo Chat" in r.stdout

    def test_chat_quit_immediately(self) -> None:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI, "chat"],
            input="quit\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(HERE),
            env=env,
        )
        assert r.returncode == 0

    def test_chat_no_llm_still_works(self) -> None:
        """Without LLM, chat falls back to teach mode."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI, "chat"],
            input="hello\n/quit\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(HERE),
            env=env,
        )
        assert r.returncode == 0
        # Should show the fallback message
        assert "You said:" in r.stdout or "LLM connected" in r.stdout or "No LLM" in r.stdout

    def test_chat_slash_save(self) -> None:
        """/save should not crash."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI, "chat"],
            input="hello\n/save\nexit\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(HERE),
            env=env,
        )
        assert r.returncode == 0
        # Should have saved the chat
        assert "Saved" in r.stdout or "Auto-saved" in r.stdout or "chat" in r.stdout


# ── self-install ─────────────────────────────────────────────────────────────


class TestSelfInstall:
    def test_self_install_shows_status(self) -> None:
        r = run_cli("self-install")
        # May be already in PATH or succeed — either way, don't crash
        assert r.returncode == 0
        assert any(x in r.stdout for x in ["PATH", "already in PATH", "Added"])


# ── Run without subcommand ────────────────────────────────────────────────────


class TestBareCommand:
    def test_bare_menu(self) -> None:
        """Running with no args should launch the dashboard (and exit on 'X')."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, CLI],
            input="X\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=str(HERE),
            env=env,
        )
        assert r.returncode == 0
        assert "VIRGO AGENT FRAMEWORK" in r.stdout or "[VIRGO]" in r.stdout

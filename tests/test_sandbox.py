"""Tests for virgo_sandbox — safe command runtime bridge (allowlist mode)."""

from __future__ import annotations

import pytest

from virgo_sandbox import ALLOWED_COMMANDS, is_command_safe, run_sandboxed


class TestIsCommandSafe:
    def test_safe_ipconfig(self) -> None:
        safe, reason = is_command_safe(["ipconfig", "/all"])
        assert safe is True
        assert reason == ""

    def test_safe_systeminfo(self) -> None:
        safe, reason = is_command_safe(["systeminfo"])
        assert safe is True

    def test_safe_ping(self) -> None:
        safe, reason = is_command_safe(["ping", "-n", "4", "127.0.0.1"])
        assert safe is True

    def test_forbidden_rmdir(self) -> None:
        """rmdir is not on the allowlist."""
        safe, reason = is_command_safe(["rmdir", "/s", "/q", "C:\\Windows"])
        assert safe is False
        assert "not on the allowlist" in reason

    def test_forbidden_del(self) -> None:
        """del is not on the allowlist."""
        safe, reason = is_command_safe(["del", "/f", "test.txt"])
        assert safe is False

    def test_forbidden_shutdown(self) -> None:
        """shutdown is not on the allowlist."""
        safe, reason = is_command_safe(["shutdown", "/s"])
        assert safe is False

    def test_forbidden_flag_on_allowed_command(self) -> None:
        """Check that /s flag is forbidden for ipconfig (not in allowed flags)."""
        safe, reason = is_command_safe(["ipconfig", "/s"])
        assert safe is False
        assert "/s" in reason

    def test_forbidden_flag_rf(self) -> None:
        """echo does not permit -rf flag."""
        safe, reason = is_command_safe(["echo", "-rf", "/etc"])
        assert safe is False

    def test_empty_command(self) -> None:
        safe, reason = is_command_safe([])
        assert safe is False

    def test_all_allowed_commands_pass_basic(self) -> None:
        """Every entry in ALLOWED_COMMANDS is allowed for a trivial invocation."""
        for cmd in sorted(ALLOWED_COMMANDS):
            safe, _ = is_command_safe([cmd, "dummy"])
            assert safe is True, f"{cmd} should be allowed"


class TestRunSandboxed:
    def test_run_safe_command(self) -> None:
        """Run a trivial safe command and check stdout."""
        stdout = run_sandboxed(["python", "--version"])
        assert "Python" in stdout

    def test_forbidden_command_raises(self) -> None:
        """Forbidden commands raise ValueError."""
        with pytest.raises(ValueError, match="Blocked by sandbox"):
            run_sandboxed(["rmdir", "/s"])

    def test_failing_command_raises(self) -> None:
        """Non-existent command raises CalledProcessError or FileNotFoundError."""
        with pytest.raises(Exception):
            run_sandboxed(["nonexistent_command_xyz123"])

    def test_custom_safe_command(self) -> None:
        """Users can run arbitrary safe commands."""
        stdout = run_sandboxed(["python", "-c", "print('hello sandbox')"])
        assert "hello sandbox" in stdout

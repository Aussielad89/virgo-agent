"""Tests for virgo_run — core agent pipeline runner."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

from virgo_run import execute_pipeline_step


@patch("virgo_run.subprocess.run")
def test_execute_pipeline_step_success(mock_run) -> None:
    """A successful subprocess returns True."""
    mock_run.return_value.returncode = 0
    result = execute_pipeline_step("test_script.py", "Test step")
    assert result is True


@patch("virgo_run.subprocess.run")
def test_execute_pipeline_step_failure(mock_run) -> None:
    """A failed subprocess (non-zero exit) returns False."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "test_script.py")
    result = execute_pipeline_step("test_script.py", "Test step")
    assert result is False


@patch("virgo_run.subprocess.run")
def test_execute_pipeline_step_exception(mock_run) -> None:
    """An exception in subprocess returns False gracefully."""
    mock_run.side_effect = FileNotFoundError("No such file")
    result = execute_pipeline_step("nonexistent.py", "Missing step")
    assert result is False


@patch("virgo_run.subprocess.run")
def test_execute_pipeline_step_calls_correct_python(mock_run) -> None:
    """The subprocess is invoked with sys.executable and the script name."""
    mock_run.return_value.returncode = 0
    execute_pipeline_step("myscript.py", "Test")
    mock_run.assert_called_once_with([sys.executable, "myscript.py"], check=True)

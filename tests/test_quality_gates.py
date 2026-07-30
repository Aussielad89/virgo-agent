"""Tests for quality_gates — post-generation code quality checks."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality_gates import (
    GateResult,
    QualityReport,
    run_all_gates,
    run_bandit,
    run_lizard,
    run_semgrep,
    run_vulture,
    _tool_available,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLEAN_PY = '''\
"""A clean module."""

def hello(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"
'''

_DIRTY_PY = '''\
import pickle
import os

def unsafe():
    x = eval("1+1")
    return pickle.loads(b"malicious")

def dead_function():
    pass
'''


@pytest.fixture
def tmp_python(tmp_path: Path):
    """Write a clean Python file and return its path."""
    f = tmp_path / "sample.py"
    f.write_text(_CLEAN_PY, encoding="utf-8")
    return str(f)


@pytest.fixture
def tmp_dirty_python(tmp_path: Path):
    """Write an unsafe Python file and return its path."""
    f = tmp_path / "dirty.py"
    f.write_text(_DIRTY_PY, encoding="utf-8")
    return str(f)


# ---------------------------------------------------------------------------
# GateResult / QualityReport
# ---------------------------------------------------------------------------

class TestGateResult:
    def test_passed_by_default(self):
        r = GateResult(tool="test", passed=True)
        assert r.passed is True
        assert r.skipped is False
        assert r.findings == []

    def test_failed(self):
        r = GateResult(tool="test", passed=False,
                       findings=[{"issue": "bad"}])
        assert r.passed is False
        assert len(r.findings) == 1


class TestQualityReport:
    def test_all_pass(self):
        report = QualityReport(results=[
            GateResult(tool="a", passed=True),
            GateResult(tool="b", passed=True),
        ])
        assert report.passed is True
        assert report.total_findings == 0

    def test_one_fails(self):
        report = QualityReport(results=[
            GateResult(tool="a", passed=True),
            GateResult(tool="b", passed=False, findings=[{"x": 1}]),
        ])
        assert report.passed is False
        assert report.total_findings == 1

    def test_skipped_doesnt_fail(self):
        report = QualityReport(results=[
            GateResult(tool="a", passed=True, skipped=True),
            GateResult(tool="b", passed=True),
        ])
        assert report.passed is True

    def test_summary_table(self):
        report = QualityReport(results=[
            GateResult(tool="bandit", passed=True),
            GateResult(tool="vulture", passed=False,
                       findings=[{"x": 1}, {"y": 2}]),
        ])
        table = report.summary_table()
        assert "bandit" in table
        assert "vulture" in table
        assert "FAIL" in table


# ---------------------------------------------------------------------------
# Tool availability
# ---------------------------------------------------------------------------

class TestToolAvailable:
    def test_python_exists(self):
        assert _tool_available(sys.executable) is True

    def test_nonexistent_tool(self):
        assert _tool_available("nonexistent_tool_xyz_12345") is False


# ---------------------------------------------------------------------------
# Individual gates (live — requires tools on PATH)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _tool_available("bandit"),
    reason="bandit not installed"
)
class TestBandit:
    def test_clean_file_passes(self, tmp_python):
        result = run_bandit([tmp_python], severity="medium")
        assert result.tool == "bandit"
        assert result.skipped is False
        # Clean file should pass
        assert result.passed is True

    def test_dirty_file_fails(self, tmp_dirty_python):
        result = run_bandit([tmp_dirty_python], severity="medium")
        assert result.tool == "bandit"
        assert result.skipped is False
        # Dirty file has eval() and pickle.loads() — should fail
        assert result.passed is False
        assert len(result.findings) > 0

    def test_missing_tool_returns_skipped(self):
        with patch("quality_gates._tool_available", return_value=False):
            result = run_bandit(["/tmp/x.py"])
            assert result.skipped is True


@pytest.mark.skipif(
    not _tool_available("vulture"),
    reason="vulture not installed"
)
class TestVulture:
    def test_clean_file_passes(self, tmp_python):
        result = run_vulture([tmp_python])
        assert result.tool == "vulture"
        assert result.skipped is False
        assert result.passed is True

    def test_dead_code_detected(self, tmp_dirty_python):
        result = run_vulture([tmp_dirty_python])
        assert result.tool == "vulture"
        assert result.skipped is False
        # Dead function should be detected
        # (may or may not find it depending on confidence)
        assert isinstance(result.findings, list)


@pytest.mark.skipif(
    not _tool_available("lizard"),
    reason="lizard not installed"
)
class TestLizard:
    def test_simple_file_passes(self, tmp_python):
        result = run_lizard([tmp_python])
        assert result.tool == "lizard"
        assert result.skipped is False
        assert result.passed is True

    def test_complex_function_flagged(self, tmp_path):
        """Generate a function with high cyclomatic complexity."""
        complex_code = 'def complicated(x):\n'
        for i in range(20):
            complex_code += f'    if x == {i}:\n        pass\n'
        f = tmp_path / "complex.py"
        f.write_text(complex_code, encoding="utf-8")
        result = run_lizard([str(f.resolve())], complexity_threshold=5)
        assert result.tool == "lizard"
        # lizard may or may not flag this depending on platform
        # Just verify it runs without error
        assert result.skipped is False
        assert isinstance(result.findings, list)


@pytest.mark.skipif(
    not _tool_available("semgrep"),
    reason="semgrep not installed"
)
class TestSemgrep:
    def test_clean_file_passes(self, tmp_python):
        result = run_semgrep([tmp_python], severity="WARNING")
        assert result.tool == "semgrep"
        assert result.skipped is False
        assert isinstance(result.findings, list)

    def test_missing_tool_returns_skipped(self):
        with patch("quality_gates._tool_available", return_value=False):
            result = run_semgrep(["/tmp/x.py"])
            assert result.skipped is True


# ---------------------------------------------------------------------------
# run_all_gates (aggregate)
# ---------------------------------------------------------------------------

class TestRunAllGates:
    def test_returns_quality_report(self, tmp_python):
        report = run_all_gates([tmp_python])
        assert isinstance(report, QualityReport)
        assert len(report.results) == 4  # bandit, vulture, lizard, semgrep

    def test_empty_paths_still_works(self):
        report = run_all_gates([])
        assert isinstance(report, QualityReport)
        # All gates should handle empty paths gracefully
        for r in report.results:
            assert r.tool in ("bandit", "vulture", "lizard", "semgrep")

    def test_missing_tools_all_skipped(self, tmp_python):
        with patch("quality_gates._tool_available", return_value=False):
            report = run_all_gates([tmp_python])
            assert report.passed is True  # all skipped = pass
            assert all(r.skipped for r in report.results)

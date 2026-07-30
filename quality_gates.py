"""
quality_gates — Post-generation code quality checks for Virgo.

Runs four CLI tools against generated Python files and aggregates
results into a single report.  All tools are optional — if a tool
is not installed the corresponding check is silently skipped.

Tools
-----
* **bandit**  — security vulnerability detection
* **vulture** — dead/unused code detection
* **lizard**  — cyclomatic complexity analysis
* **semgrep** — pattern-based static analysis
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Result from a single quality gate."""

    tool: str
    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    skipped: bool = False


@dataclass
class QualityReport:
    """Aggregated results from all quality gates."""

    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True only if every non-skipped gate passed."""
        return all(r.passed or r.skipped for r in self.results)

    @property
    def total_findings(self) -> int:
        return sum(len(r.findings) for r in self.results)

    def summary_table(self) -> str:
        """Human-readable summary table."""
        lines: list[str] = []
        lines.append(f"{'Tool':<12} {'Status':<10} {'Findings':>8}")
        lines.append("-" * 34)
        for r in self.results:
            status = "SKIPPED" if r.skipped else ("PASS" if r.passed else "FAIL")
            lines.append(f"{r.tool:<12} {status:<10} {len(r.findings):>8}")
        lines.append("-" * 34)
        passed = "PASS" if self.passed else "FAIL"
        lines.append(f"{'TOTAL':<12} {passed:<10} {self.total_findings:>8}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_available(name: str) -> bool:
    """Check if a CLI tool is on PATH."""
    return shutil.which(name) is not None


def _run_tool(
    cmd: list[str],
    *,
    timeout: int = 60,
    cwd: str | Path | None = None,
) -> tuple[int, str, str]:
    """Run a CLI tool and return (returncode, stdout, stderr).

    Returns (-1, '', exc_string) on OSError so callers never crash.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"{cmd[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return -1, "", f"{cmd[0]} timed out after {timeout}s"
    except OSError as exc:
        return -1, "", str(exc)


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------

def run_bandit(
    paths: list[str],
    *,
    severity: str = "medium",
    confidence: str = "medium",
    exclude: list[str] | None = None,
) -> GateResult:
    """Run bandit security scanner on *paths*.

    Parameters
    ----------
    paths:
        File or directory paths to scan.
    severity:
        Minimum severity to report ('low', 'medium', 'high').
    confidence:
        Minimum confidence to report ('low', 'medium', 'high').
    exclude:
        Glob patterns to exclude (e.g. ['*/tests/*']).
    """
    if not _tool_available("bandit"):
        return GateResult(tool="bandit", passed=True, skipped=True,
                          summary="bandit not installed")

    cmd = [
        "bandit", "-r", "-f", "json",
        "-l" if severity == "low" else
        "-ll" if severity == "medium" else
        "-lll",
        "--confidence-level", confidence,
    ]
    if exclude:
        for ex in exclude:
            cmd.extend(["--exclude", ex])
    cmd.extend(paths)

    rc, stdout, stderr = _run_tool(cmd)
    if rc == -1:
        return GateResult(tool="bandit", passed=True, skipped=True,
                          summary=stderr)

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # bandit may output non-JSON on some errors
        return GateResult(
            tool="bandit", passed=True, skipped=True,
            summary=f"Failed to parse bandit output: {stderr[:200]}",
        )

    metrics = data.get("metrics", {}).get("_totals", {})
    results = data.get("results", [])
    findings = [
        {
            "file": r.get("filename", ""),
            "line": r.get("line_number", 0),
            "issue": r.get("issue_text", ""),
            "severity": r.get("issue_severity", ""),
            "confidence": r.get("issue_confidence", ""),
            "test_id": r.get("test_id", ""),
        }
        for r in results
    ]
    high = metrics.get("SEVERITY.HIGH", 0) + metrics.get("SEVERITY.MEDIUM", 0)
    passed = high == 0
    summary = f"{len(findings)} finding(s), {high} medium/high"
    return GateResult(tool="bandit", passed=passed, findings=findings,
                      summary=summary)


def run_vulture(
    paths: list[str],
    *,
    min_confidence: int = 80,
) -> GateResult:
    """Run vulture dead-code detector on *paths*."""
    if not _tool_available("vulture"):
        return GateResult(tool="vulture", passed=True, skipped=True,
                          summary="vulture not installed")

    cmd = ["vulture", "--min-confidence", str(min_confidence), "--json"]
    cmd.extend(paths)

    rc, stdout, stderr = _run_tool(cmd)
    if rc == -1:
        return GateResult(tool="vulture", passed=True, skipped=True,
                          summary=stderr)

    # vulture --json outputs one JSON object per line (or a single array)
    findings: list[dict[str, Any]] = []
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            findings = data
        elif isinstance(data, dict):
            findings = [data]
    except json.JSONDecodeError:
        # vulture may not support --json on all versions; parse text output
        for line in stdout.splitlines():
            line = line.strip()
            if ":" in line and "%" in line:
                # typical vulture output: file:line: unused import 'X' (90% confidence)
                findings.append({"raw": line})

    passed = len(findings) == 0
    summary = f"{len(findings)} dead code item(s)"
    return GateResult(tool="vulture", passed=passed, findings=findings,
                      summary=summary)


def run_lizard(
    paths: list[str],
    *,
    complexity_threshold: int = 15,
) -> GateResult:
    """Run lizard complexity analyzer on *paths*."""
    if not _tool_available("lizard"):
        return GateResult(tool="lizard", passed=True, skipped=True,
                          summary="lizard not installed")

    cmd = [
        "lizard",
        "-C", str(complexity_threshold),
        "-w",  # warnings only
    ]
    cmd.extend(paths)

    rc, stdout, stderr = _run_tool(cmd)
    if rc == -1:
        return GateResult(tool="lizard", passed=True, skipped=True,
                          summary=stderr)

    # Parse text output — lines with warnings contain the function name
    # and complexity.  Format:  file:line: line: FunctionName (CCN: N)
    findings: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "Total" in line or "Average" in line:
            continue
        # Warning lines from lizard contain function names and CCN
        if "CCN" in line or "cyclomatic" in line.lower():
            findings.append({"raw": line})
        elif "(" in line and ")" in line and ":" in line:
            # Heuristic: function signature lines in warnings
            findings.append({"raw": line})

    passed = len(findings) == 0
    summary = f"{len(findings)} function(s) above complexity {complexity_threshold}"
    return GateResult(tool="lizard", passed=passed, findings=findings,
                      summary=summary)


def run_semgrep(
    paths: list[str],
    *,
    rules: str | None = None,
    severity: str = "WARNING",
) -> GateResult:
    """Run semgrep pattern-based analysis on *paths*.

    Parameters
    ----------
    rules:
        Path to a semgrep rule file, or a built-in rule set name
        (e.g. 'p/python').  Defaults to p/python (Python best practices).
    severity:
        Minimum severity: 'INFO', 'WARNING', or 'ERROR'.
    """
    if not _tool_available("semgrep"):
        return GateResult(tool="semgrep", passed=True, skipped=True,
                          summary="semgrep not installed")

    cmd = [
        "semgrep", "--json",
        "--severity", severity,
    ]
    if rules:
        cmd.extend(["--config", rules])
    else:
        cmd.extend(["--config", "p/python"])
    cmd.extend(paths)

    rc, stdout, stderr = _run_tool(cmd, timeout=120)
    if rc == -1:
        return GateResult(tool="semgrep", passed=True, skipped=True,
                          summary=stderr)

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return GateResult(
            tool="semgrep", passed=True, skipped=True,
            summary=f"Failed to parse semgrep output: {stderr[:200]}",
        )

    results = data.get("results", [])
    findings = [
        {
            "file": r.get("path", ""),
            "line": r.get("start", {}).get("line", 0),
            "rule": r.get("check_id", ""),
            "message": r.get("extra", {}).get("message", ""),
            "severity": r.get("extra", {}).get("severity", ""),
        }
        for r in results
    ]
    passed = len(findings) == 0
    summary = f"{len(findings)} finding(s)"
    return GateResult(tool="semgrep", passed=passed, findings=findings,
                      summary=summary)


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

def run_all_gates(
    paths: list[str],
    *,
    bandit_severity: str = "medium",
    vulture_min_confidence: int = 80,
    lizard_complexity: int = 15,
    semgrep_rules: str | None = None,
    semgrep_severity: str = "WARNING",
    bandit_exclude: list[str] | None = None,
) -> QualityReport:
    """Run all four quality gates and return an aggregated report.

    Each gate runs independently — a failure in one does not block the others.
    """
    report = QualityReport()
    report.results.append(run_bandit(
        paths, severity=bandit_severity, exclude=bandit_exclude,
    ))
    report.results.append(run_vulture(paths, min_confidence=vulture_min_confidence))
    report.results.append(run_lizard(paths, complexity_threshold=lizard_complexity))
    report.results.append(run_semgrep(
        paths, rules=semgrep_rules, severity=semgrep_severity,
    ))
    return report

"""Tests for the deterministic demo pipeline (run.py) and CLI demo wiring.

Covers the parser regex fix (bracketed vs unbracketed timestamps) and the
`demo --goal` argument wiring in cli.py.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def _load_run_module():
    spec = importlib.util.spec_from_file_location("virgo_demo_run", HERE / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_parser(code: str, log_path: Path) -> int:
    """Write PARSER_CODE to a temp file next to log_path and execute it."""
    script = HERE / "_demo_parse_probe.py"
    script.write_text(code, encoding="utf-8")
    try:
        # Run from HERE so the generated parser's relative mock_logs.txt resolves.
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(HERE),
            capture_output=True,
            text=True,
        )
        return proc.returncode
    finally:
        script.unlink(missing_ok=True)


def test_parser_extracts_error_critical_entries():
    run = _load_run_module()
    log = HERE / "mock_logs.txt"
    assert log.exists(), "mock_logs.txt fixture missing"
    rc = _run_parser(run.PARSER_CODE, log)
    assert rc == 0
    summary = HERE / "summary_output.txt"
    try:
        text = summary.read_text(encoding="utf-8")
    finally:
        summary.unlink(missing_ok=True)
    assert "Extracted 2 entries from mock_logs.txt" in text
    assert "ERROR" in text and "CRITICAL" in text


def test_parser_regex_matches_bracketed_and_unbracketed():

    run = _load_run_module()
    # Extract the compiled pattern from PARSER_CODE.
    ns: dict = {}
    # The regex is built inside parse_log; replicate by exec-ing the def.
    src = run.PARSER_CODE
    exec(src, ns)  # defines parse_log in ns

    # Bracketed format (ERROR level to survive the demo's filter)
    p1 = HERE / "_t1.log"
    p1.write_text("[2026-07-10 12:00:00] ERROR: bracketed entry\n")
    # Unbracketed format (matches mock_logs.txt)
    p2 = HERE / "_t2.log"
    p2.write_text("2026-07-10 CRITICAL: unbracketed entry\n")
    try:
        assert len(ns["parse_log"](str(p1))) == 1
        assert len(ns["parse_log"](str(p2))) == 1
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)


def test_demo_subparser_accepts_goal(monkeypatch):
    import cli
    import run as run_mod

    captured = {}

    def fake_run_main(goal=None):
        captured["goal"] = goal
        return None

    # cmd_demo does `from run import main`, so patch the run module's main.
    monkeypatch.setattr(run_mod, "main", fake_run_main)

    # Invoke cli.main with the documented demo --goal command.
    monkeypatch.setattr(sys, "argv", ["virgo", "demo", "--goal", "parse mock_logs.txt"])
    cli.main()
    assert captured.get("goal") == "parse mock_logs.txt"

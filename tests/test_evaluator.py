"""Tests for evaluator.py — deterministic + LLM evaluation modes."""

from __future__ import annotations

import evaluator
from evaluator import Evaluation, evaluate


# ── Fake client for LLM mode ────────────────────────────────────────────────

class FakeClient:
    """Tiny stand-in for main.LLMClient.chat(messages, role='evaluator')."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.called_with_role: str | None = None

    def chat(self, messages, role: str = "evaluator") -> str:
        self.called_with_role = role
        return self.response


# A transcript that satisfies every deterministic check.
GOOD_GOAL = "Build a web scraper that collects product prices"
GOOD_TRANSCRIPT = (
    "Tool: web_fetch url=https://example.com\n"
    "The agent collected product prices from the page.\n"
    "Tool: file_writer wrote results.json\n"
    "Done. The scraper gathered all requested product prices successfully."
)


def test_deterministic_all_pass() -> None:
    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT)
    assert isinstance(ev, Evaluation)
    assert ev.passed is True
    assert ev.score == 1.0
    assert len(ev.checks) == 4
    assert all("FAILED" not in c for c in ev.checks)


def test_deterministic_fail_on_tool_error() -> None:
    transcript = (
        "Tool: web_fetch url=https://example.com\n"
        "ERROR: connection refused while fetching the page\n"
        "The agent tried to collect product prices but failed.\n"
    )
    ev = evaluate(GOOD_GOAL, transcript)
    assert ev.passed is False
    assert ev.score < 1.0
    assert any(c.startswith("no_tool_errors") and "FAILED" in c for c in ev.checks)


def test_deterministic_fail_on_empty() -> None:
    ev = evaluate(GOOD_GOAL, "short")
    assert ev.passed is False
    assert ev.score < 1.0
    assert any(c.startswith("not_empty") and "FAILED" in c for c in ev.checks)


def test_deterministic_fail_on_no_action() -> None:
    # No tool call marker, but long enough and contains a keyword.
    transcript = (
        "The agent thought about product prices for a while and then "
        "stopped without doing anything measurable at all."
    )
    ev = evaluate(GOOD_GOAL, transcript)
    assert ev.passed is False
    assert any(c.startswith("has_action") and "FAILED" in c for c in ev.checks)


def test_deterministic_goal_term_check() -> None:
    # Long, has a tool call, but missing the salient goal keyword.
    transcript = (
        "Tool: file_writer wrote report.txt\n"
        "The agent produced a report about the weather and saved it to disk "
        "without referencing the original objective in any meaningful way.\n"
    )
    ev = evaluate(GOOD_GOAL, transcript)
    assert ev.passed is False
    assert any(c.startswith("goal_terms") and "FAILED" in c for c in ev.checks)


def test_llm_mode_parse_happy_path() -> None:
    client = FakeClient(
        '{"passed": true, "score": 0.92, "rationale": "Goal achieved."}'
    )
    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT, client=client)
    assert client.called_with_role == "evaluator"
    assert ev.passed is True
    assert ev.score == 0.92
    assert "Goal achieved" in ev.rationale
    # checks are still populated from the deterministic layer
    assert len(ev.checks) == 4


def test_llm_mode_parse_failure_falls_back() -> None:
    # Returns garbage JSON -> must fall back to deterministic (all-pass).
    client = FakeClient("I cannot produce JSON, sorry.")
    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT, client=client)
    assert ev.passed is True
    assert ev.score == 1.0
    assert "parse failed" in ev.rationale.lower()


def test_llm_mode_call_failure_falls_back() -> None:
    class BrokenClient:
        def chat(self, messages, role: str = "evaluator") -> str:
            raise RuntimeError("model unavailable")

    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT, client=BrokenClient())
    assert ev.passed is True
    assert "call failed" in ev.rationale.lower()


def test_llm_mode_json_with_surrounding_text() -> None:
    # LLM wraps JSON in prose; regex extraction should still work.
    client = FakeClient(
        "Here is my verdict:\n"
        '{"passed": false, "score": 0.25, "rationale": "Partial work only."}\n'
        "Hope that helps!"
    )
    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT, client=client)
    assert ev.passed is False
    assert ev.score == 0.25
    assert "Partial work only." in ev.rationale


def test_llm_mode_malformed_verdict_falls_back() -> None:
    # Valid JSON but missing required keys / wrong types.
    client = FakeClient('{"foo": "bar"}')
    ev = evaluate(GOOD_GOAL, GOOD_TRANSCRIPT, client=client)
    # Falls back to deterministic all-pass on the good transcript.
    assert ev.passed is True
    assert "malformed" in ev.rationale.lower()


def test_evaluate_never_raises_on_crazy_input() -> None:
    # Ensure the hard safety net returns a usable Evaluation, not an exception.
    client = object()  # has no .chat attribute of the right shape
    ev = evaluate("", "", client=client)
    assert isinstance(ev, Evaluation)
    assert ev.passed is False
    assert 0.0 <= ev.score <= 1.0

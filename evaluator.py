"""evaluator — quality gate for autonomous agent runs.

This module decides whether an autonomous agent actually *succeeded* at a
goal, rather than merely "did not crash". It exposes:

  * :class:`Evaluation` — a dataclass describing the verdict.
  * :func:`evaluate` — the public entry point, with two modes:

      - deterministic (no LLM client, or client call fails): a set of
        cheap, transparent heuristic checks over the transcript.
      - LLM-assisted (a client with a ``chat`` method is supplied): a
        rubric prompt asks the model for a structured verdict, parsed
        defensively, falling back to the deterministic path on any failure.

The function is wrapped so that it never raises — a failure always yields a
deterministic ``Evaluation`` rather than an exception.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from _console import icon
from _log import log


@dataclass
class Evaluation:
    """Outcome of evaluating an agent run against a goal."""

    passed: bool
    score: float
    rationale: str
    checks: list[str] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────

def _salient_keywords(goal: str) -> list[str]:
    """Return lowercase tokens of length >= 4 from the goal.

    Stopword filtering keeps the keyword set focused on meaningful terms.
    """
    stopwords = {
        "the", "and", "that", "this", "with", "from", "your", "have", "will",
        "they", "their", "what", "when", "where", "which", "while", "about",
        "would", "could", "should", "into", "than", "then", "them", "there",
        "here", "been", "being", "were", "does", "done", "make", "made",
        "some", "such", "only", "also", "after", "before", "over", "under",
    }
    tokens = re.findall(r"[a-zA-Z0-9_]+", goal.lower())
    out: list[str] = []
    for tok in tokens:
        if len(tok) >= 4 and tok not in stopwords and tok not in out:
            out.append(tok)
    return out


def _has_tool_call(transcript: str) -> bool:
    """True if the transcript records at least one tool invocation."""
    return ("Tool:" in transcript) or ('{"tool"' in transcript)


def _has_tool_error(transcript: str) -> bool:
    """True if the transcript records an ERROR: tool result."""
    return "ERROR:" in transcript


def _deterministic_checks(goal: str, transcript: str) -> tuple[list[str], list[str]]:
    """Compute the deterministic check list.

    Returns ``(checks, failed)`` where ``checks`` is the human-readable list
    of every check performed and ``failed`` is the subset that failed.
    """
    checks: list[str] = []

    no_error = not _has_tool_error(transcript)
    checks.append(
        "no_tool_errors: transcript contains no 'ERROR:' tool result"
        + ("" if no_error else " — FAILED")
    )

    has_action = _has_tool_call(transcript)
    checks.append(
        "has_action: transcript shows at least one tool call"
        + ("" if has_action else " — FAILED")
    )

    keywords = _salient_keywords(goal)
    goal_hit = False
    if keywords:
        goal_hit = any(kw in transcript.lower() for kw in keywords)
    else:
        # No salient keywords to match against; treat as not-checkable -> fail.
        goal_hit = False
    checks.append(
        "goal_terms: a salient goal keyword appears in the transcript"
        + ("" if goal_hit else " — FAILED")
    )

    not_empty = len(transcript) > 50
    checks.append(
        "not_empty: transcript length > 50"
        + ("" if not_empty else " — FAILED")
    )

    failed = [
        c for c in checks if c.endswith("— FAILED")
    ]
    return checks, failed


def _deterministic_evaluation(goal: str, transcript: str, reason: str = "") -> Evaluation:
    """Build an :class:`Evaluation` from the deterministic checks."""
    checks, failed = _deterministic_checks(goal, transcript)
    passed = len(failed) == 0
    score = 0.0 if not checks else (len(checks) - len(failed)) / len(checks)
    if failed:
        rationale = (
            f"Deterministic checks failed: {', '.join(c.split(' — ')[0] for c in failed)}."
        )
    else:
        rationale = "All deterministic checks passed."
    if reason:
        rationale = f"{rationale} ({reason})"
    return Evaluation(passed=passed, score=score, rationale=rationale, checks=checks)


# ── LLM mode ─────────────────────────────────────────────────────────────────

def _build_rubric_messages(goal: str, transcript: str, rubric: str) -> list[dict[str, str]]:
    """Construct the messages sent to the LLM evaluator."""
    rubric_block = f"\nAdditional rubric guidance:\n{rubric}\n" if rubric else ""
    system = (
        "You are a strict, impartial evaluator of autonomous agent runs. "
        "Given a goal and the full run transcript, decide whether the agent "
        "actually achieved the goal (not merely that it did not crash). "
        "Respond with ONLY a single JSON object of the form:\n"
        '{"passed": <true|false>, "score": <float 0.0-1.0>, '
        '"rationale": "<short explanation>"}\n'
        "Do not include any text outside the JSON object."
    )
    user = (
        f"GOAL:\n{goal}\n\n"
        f"TRANSCRIPT:\n{transcript}\n"
        f"{rubric_block}"
        "Return the JSON verdict now."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from *text* defensively.

    Raises ``ValueError`` if no valid JSON object is found.
    """
    # Find the first balanced-ish JSON object via a tolerant brace scan.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(match.group(0))


def _llm_evaluation(
    goal: str, transcript: str, client: object, rubric: str
) -> Evaluation:
    """Attempt an LLM-based evaluation, falling back to deterministic."""
    messages = _build_rubric_messages(goal, transcript, rubric)
    try:
        raw = client.chat(messages, role="evaluator")  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — never raise from evaluate()
        log.warning("%s LLM client call failed: %s", icon("warn"), exc)
        return _deterministic_evaluation(goal, transcript, reason="LLM call failed")

    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("%s Failed to parse LLM verdict: %s", icon("warn"), exc)
        return _deterministic_evaluation(goal, transcript, reason="LLM parse failed")

    try:
        passed = bool(data["passed"])
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        rationale = str(data.get("rationale", "LLM provided no rationale."))
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("%s Malformed LLM verdict: %s", icon("warn"), exc)
        return _deterministic_evaluation(goal, transcript, reason="LLM verdict malformed")

    checks, _failed = _deterministic_checks(goal, transcript)
    return Evaluation(passed=passed, score=score, rationale=rationale, checks=checks)


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate(
    goal: str,
    transcript: str,
    client: object = None,
    rubric: str = "",
) -> Evaluation:
    """Evaluate an agent run against *goal* using *transcript*.

    Parameters
    ----------
    goal:
        The objective the agent was meant to achieve.
    transcript:
        The full agent run log text.
    client:
        Optional LLM client exposing ``chat(messages, role='evaluator')``
        (e.g. ``main.LLMClient``). When ``None`` or when the call fails,
        deterministic checks are used.
    rubric:
        Optional extra natural-language evaluation guidance.

    Returns
    -------
    Evaluation
        Never raises; on any unexpected error a deterministic evaluation is
        returned so callers always get a usable verdict.
    """
    try:
        if client is not None and hasattr(client, "chat"):
            return _llm_evaluation(goal, transcript, client, rubric)
        return _deterministic_evaluation(goal, transcript)
    except Exception as exc:  # noqa: BLE001 — hard safety net
        log.error("%s evaluate() unexpectedly failed: %s", icon("error"), exc)
        return _deterministic_evaluation(goal, transcript, reason="evaluator error")

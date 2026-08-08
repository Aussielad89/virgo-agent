"""
ci_agent — run Virgo's autonomous agent inside CI.

Reads a goal from ``VIRGO_CI_GOAL`` (or the first CLI argument), runs the
ReAct runtime, appends a summary to ``$GITHUB_STEP_SUMMARY`` when present,
and exits non-zero when the goal was not satisfied — so CI fails loudly
instead of merging an "agent said it tried".

Usage:
    python ci_agent.py "write a README for this repo"
    VIRGO_CI_GOAL="run the test suite" python ci_agent.py

Set ``VIRGO_CI_LLM=1`` to enable LLM-backed reasoning (needs a reachable
endpoint configured via LLM_BASE_URL); otherwise the deterministic loop
runs, which is fully offline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _step_summary_path() -> Path | None:
    raw = os.getenv("GITHUB_STEP_SUMMARY")
    return Path(raw) if raw else None


def main() -> int:
    goal = os.getenv("VIRGO_CI_GOAL") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not goal:
        print("ERROR: no goal. Set VIRGO_CI_GOAL or pass it as an argument.")
        return 2

    from agent_runtime import AgentConfig, build_runtime

    client = None
    if os.getenv("VIRGO_CI_LLM", "").lower() in ("1", "true", "yes"):
        try:
            import main as _main

            client = _main.get_client_for("agent")
        except Exception as exc:  # pragma: no cover
            print(f"[ci_agent] LLM unavailable ({exc}); running deterministic loop")

    config = AgentConfig(max_steps=int(os.getenv("VIRGO_CI_STEPS", "12")),
                         max_retries=int(os.getenv("VIRGO_CI_RETRIES", "2")),
                         save_session=True)
    runtime = build_runtime(client=client, config=config, include_mcp=False)
    print(f"[ci_agent] goal: {goal}")
    result = runtime.run(goal)

    ev = result.evaluation
    score = f"{ev.score:.2f}" if ev is not None else "n/a"
    summary = (
        f"## Virgo agent run\n\n"
        f"- **Goal:** `{goal}`\n"
        f"- **Result:** {'✅ PASS' if result.passed else '❌ FAIL'}\n"
        f"- **Score:** {score}\n"
        f"- **Steps:** {result.steps}\n"
        f"- **Tools:** {', '.join(result.tools_used) or 'none'}\n"
        f"- **Session:** `{result.session_id or 'n/a'}`\n"
    )
    print(summary)

    path = _step_summary_path()
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(summary + "\n")
        except OSError as exc:  # pragma: no cover
            print(f"[ci_agent] cannot write step summary: {exc}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

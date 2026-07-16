"""
End-to-end demo: discover mock_logs.txt, generate a parser, test & fix.

Policies are deterministic (no LLM) — they inspect WorkspaceState
samples and produce hard-coded but adaptive Python code.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from environment import AgentEnvironment
from tools import ToolRegistry
from logo import print_logo
from orchestrator import Orchestrator, TestLog, WorkspaceState


# ===========================================================================
# Policy: planner
# ===========================================================================

def planner(goal: str, state: WorkspaceState) -> str:
    """Examine discovered files and produce a plan."""
    lines = [f"Plan for: {goal}"]

    for df in state.discovered_files:
        if df.sample:
            fmt = df.sample.get("format", "?")
            preview = df.sample.get("preview", [])
            if preview:
                lines.append(f"  - {df.path}  [{fmt}]  sample: {preview[0][:80]}")
        else:
            lines.append(f"  - {df.path}")

    lines.append("")
    lines.append("Steps:")
    lines.append("  1. Parse mock_logs.txt with regex to extract timestamp, level, message")
    lines.append("  2. Filter lines where level is ERROR or CRITICAL")
    lines.append("  3. Write structured results to summary_output.txt")
    lines.append("  4. Exit with code 0 on success")

    return "\n".join(lines)


# ===========================================================================
# Policy: code_generator
# ===========================================================================

PARSER_CODE = r'''"""
Auto-generated parser for mock_logs.txt.

Extracts ERROR and CRITICAL entries and writes them to
summary_output.txt.
"""

import re
import sys
from pathlib import Path


def parse_log(file_path: str) -> list[dict]:
    """Parse a log file, returning structured entries.

    Accepts either ``[YYYY-MM-DD HH:MM:SS] LEVEL: msg`` or the
    unbracketed ``YYYY-MM-DD LEVEL: msg`` format used by mock_logs.txt.
    """
    pattern = re.compile(
        r"(?:\[)?(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)(?:\])?\s+"
        r"(\w+):\s+(.+)"
    )
    entries: list[dict] = []

    with open(file_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n\r")
            m = pattern.match(line)
            if m is None:
                continue  # skip lines that don't match the format
            timestamp, level, message = m.groups()
            if level in ("ERROR", "CRITICAL"):
                entries.append({
                    "timestamp": timestamp,
                    "level": level,
                    "message": message,
                })

    return entries


def main() -> int:
    log_path = Path("mock_logs.txt")
    if not log_path.exists():
        print(f"Error: {log_path} not found", file=sys.stderr)
        return 1

    entries = parse_log(str(log_path))

    out_path = Path("summary_output.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"Extracted {len(entries)} entries from {log_path}\n")
        fh.write("=" * 50 + "\n")
        for entry in entries:
            fh.write(
                f"[{entry['timestamp']}] "
                f"{entry['level']}: "
                f"{entry['message']}\n"
            )

    print(f"==> Summary written to {out_path} with {len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def code_generator(
    plan: str,
    state: WorkspaceState,
    registry: ToolRegistry,
    env: AgentEnvironment,
) -> list[tuple[str, str]]:
    """Produce the parser script based on the plan and discovered files."""
    return [("parse_logs.py", PARSER_CODE)]


# ===========================================================================
# Policy: fixer
# ===========================================================================

def fixer(
    log: "TestLog",
    state: WorkspaceState,
    registry: ToolRegistry,
    env: AgentEnvironment,
) -> list[tuple[str, str, str]] | None:
    """Analyse a test failure and return patches to apply.

    Returns list of (file_path, old_string, new_string) or None
    if no automatic fix is available.
    """
    err = (log.stderr or "") + (log.stdout or "")

    # -- UnicodeEncodeError (emoji on cp1252) → strip non-ASCII ---------
    if "UnicodeEncodeError" in err:
        return [(
            "parse_logs.py",
            'print(f"==> Summary written to {out_path} with {len(entries)} entries")',
            'print("==> Summary written to {} with {} entries".format(out_path, len(entries)))',
        )]

    # -- FileNotFoundError → prepend full path resolution ---------------
    if "FileNotFoundError" in err or "No such file" in err:
        return [(
            "parse_logs.py",
            'log_path = Path("mock_logs.txt")',
            'log_path = Path(__file__).parent / "mock_logs.txt"',
        )]

    # -- ImportError → try installing the missing package ---------------
    m_import = re.search(r"ModuleNotFoundError: No module named '(\w+)'", err)
    if m_import:
        pkg = m_import.group(1)
        try:
            env.install(pkg, quiet=True)
        except RuntimeError:
            pass  # might still fail, but we tried
        return []  # no source patch needed — rely on re-run

    # -- SyntaxError → report and give up (shouldn't happen with syntax
    #    validation, but just in case)
    if "SyntaxError" in err:
        print("  [FIXER] Syntax error — cannot auto-fix, skipping")
        return None

    # -- Generic: print the error so the operator sees it ---------------
    print(f"  [FIXER] No auto-fix for:\n{err[:400]}")
    return None


# ===========================================================================
# Main
# ===========================================================================

def main(goal: str | None = None) -> None:
    print_logo()

    # -- Bootstrap infrastructure ---------------------------------------
    print("  [BOOT] Setting up agent environment …")
    env = AgentEnvironment(base_path=str(HERE))
    if env.is_ready:
        env.teardown()
    env.setup()
    print(f"  [BOOT] agent_env ready at {env.python}")

    registry = ToolRegistry()
    registry.register_defaults(env)

    orch = Orchestrator(
        env, registry, base_path=str(HERE),
        workspace_excludes=["agent_env", ".crush", ".git", "__pycache__"],
    )

    # -- Run the pipeline -----------------------------------------------
    print()
    pipeline_goal = (
        goal
        if goal
        else "Find mock_logs.txt, extract its data structure, "
        "and write a separate script that parses it and extracts "
        "only the lines with specific markers into a clean summary file."
    )
    state = orch.run(
        goal=pipeline_goal,
        planner=planner,
        code_gen=code_generator,
        fixer=fixer,
        max_iterations=3,
        auto_approve=True,
    )

    # -- Report results -------------------------------------------------
    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Goal:           {state.goal[:70]}…")
    print(f"  Phase:          {state.phase}")
    print(f"  Files generated: {len(state.generated_files)}")
    for gf in state.generated_files:
        passed = "PASS" if gf.passed else "FAIL"
        print(f"    {gf.path:30s}  [{passed}]  (iteration {gf.iteration})")
    print(f"  WTF iterations: {state.iteration}")
    print(f"  Loop passed:    {state.loop_passed}")
    print(f"  Test logs:      {len(state.test_logs)}")

    # -- Show the summary if it was produced ----------------------------
    summary = HERE / "summary_output.txt"
    if summary.exists():
        print()
        print("  --- summary_output.txt ---")
        print(f"  {summary.read_text().strip()}")
        summary.unlink()  # clean up

    # -- Cleanup --------------------------------------------------------
    for f in ["parse_logs.py", "parse_logs.py.bak"]:
        (HERE / f).unlink(missing_ok=True)
    env.teardown()

    print()
    if state.loop_passed:
        print("  [PASS] END-TO-END TEST PASSED")
    else:
        print("  [FAIL] END-TO-END TEST FAILED (WTF loop did not resolve)")
        sys.exit(1)


if __name__ == "__main__":
    main()

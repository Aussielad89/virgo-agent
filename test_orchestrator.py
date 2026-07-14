"""Smoke-tests for orchestrator.py — discovery, state tracking, WTF loop."""
import os, sys, json
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from environment import AgentEnvironment
from tools import ToolRegistry
from orchestrator import Orchestrator, WorkspaceState, GeneratedFile, TestLog

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
env = AgentEnvironment(base_path=str(HERE))
if env.is_ready:
    env.teardown()
env.setup()
env.install("tomli", quiet=True)

reg = ToolRegistry()
reg.register_defaults(env)

orch = Orchestrator(env, reg, base_path=str(HERE),
    workspace_excludes=["agent_env", ".crush", ".git", "__pycache__"])

print("=== 1. Discovery ===")

# Create sample files for discovery
(HERE / "_test_data.csv").write_text("city,pop,country\nTokyo,37400,Japan\nDelhi,32200,India\n")
(HERE / "_test_data.json").write_text(json.dumps([{"a": 1, "b": 2}, {"a": 3, "b": 4}]))
(HERE / "_test_note.txt").write_text("hello\nworld\n")

state = orch.run(goal="Test discovery", max_iterations=1, auto_approve=True)
assert len(state.discovered_files) >= 3, f"Expected >=3 files, got {len(state.discovered_files)}"
names = [f.path for f in state.discovered_files]
print(f"  Found {len(state.discovered_files)} files: {names}")

# Check CSV got schema
csv_files = [f for f in state.discovered_files if f.path.endswith("_test_data.csv")]
if csv_files:
    s = csv_files[0].sample
    assert s and "columns" in s, f"CSV sample missing columns: {s}"
    print(f"  CSV columns: {s['columns']}, schema: {s['schema']}")
else:
    print("  (no csv file in discovered set — check include patterns)")

print()

# Clean sample files
for f in ["_test_data.csv", "_test_data.json", "_test_note.txt"]:
    (HERE / f).unlink(missing_ok=True)

print("=== 2. WTF Loop — all green ===")

state = orch.run(
    goal="Write a script that prints OK and exits 0",
    planner=lambda g, s: "Write a trivial hello script",
    code_gen=lambda plan, s, r, e: [
        ("_test_hello.py", "print('OK')\n"),
    ],
    max_iterations=2,
    auto_approve=True,
)
assert state.loop_passed, f"Expected pass, got {state.test_logs}"
assert len(state.generated_files) == 1
assert state.test_logs[-1].passed
print(f"  Iterations used: {state.iteration}")
print(f"  Test passed: {state.loop_passed}")
print()

print("=== 3. WTF Loop — fix on second attempt ===")

fix_calls: list[int] = []

state = orch.run(
    goal="Script that prints OK after fix",
    planner=lambda g, s: "write a script, fix bug",
    code_gen=lambda plan, s, r, e: [
        ("_test_buggy.py", "print('OK')\nimport sys; sys.exit(1)\n"),  # intentionally fails
    ],
    fixer=lambda log, s, r, e: [
        ("_test_buggy.py", "import sys; sys.exit(1)", "# fixed\n"),
    ] if log.returncode != 0 else None,
    max_iterations=3,
    auto_approve=True,
)
print(f"  Iterations used: {state.iteration}")
print(f"  Final passed: {state.loop_passed}")
# Should have passed because the fixer patches the exit(1) line
assert state.loop_passed, f"Expected fixer to resolve, logs: {[l.passed for l in state.test_logs]}"
print()

print("=== 4. WTF Loop — max iterations exceeded ===")

state = orch.run(
    goal="Always-failing script",
    planner=lambda g, s: "",
    code_gen=lambda plan, s, r, e: [
        ("_test_always_fail.py", "import sys; sys.exit(1)\n"),
    ],
    fixer=None,
    max_iterations=2,
    auto_approve=True,
)
assert not state.loop_passed
assert state.iteration == 2
print(f"  Iterations: {state.iteration}, passed: {state.loop_passed} (expected)")
print()

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
for f in ["_test_hello.py", "_test_buggy.py", "_test_always_fail.py"]:
    (HERE / f).unlink(missing_ok=True)
    bak = HERE / (f + ".bak")
    bak.unlink(missing_ok=True)

env.teardown()

print("All orchestrator smoke-tests passed.")

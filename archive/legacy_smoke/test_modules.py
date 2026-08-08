"""Quick smoke-test for environment.py and tools.py."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from environment import AgentEnvironment
from tools import ToolRegistry

# ---------------------------------------------------------------------------
# 1. AgentEnvironment — setup / teardown
# ---------------------------------------------------------------------------
print("=== AgentEnvironment ===")

env = AgentEnvironment(base_path=str(HERE))
if env.is_ready:
    env.teardown()
assert not env.is_ready, "should not be ready before setup"

env.setup()
assert env.is_ready, "should be ready after setup"
assert env.python.exists(), f"python not found at {env.python}"
print(f"  Python: {env.python}")

# run a simple script
proc = env.run("print('hello from agent_env')")
assert proc.returncode == 0
assert "hello from agent_env" in proc.stdout
print(f"  Script execution: OK (stdout={proc.stdout.strip()!r})")

# install a small pure-Python package
env.install("tomli", quiet=True)
proc = env.run("import tomli; print(tomli.__version__)")
assert proc.returncode == 0, f"tomli install failed: {proc.stderr}"
print(f"  Dynamic install: OK (tomli {proc.stdout.strip()})")

# ensure (idempotent)
out = env.ensure("tomli", quiet=True)
assert out == "", f"ensure should be noop when installed, got: {out}"

# run_file
script = HERE / "_test_script.py"
try:
    script.write_text("print('run_file works')")
    proc = env.run_file(str(script))
    assert proc.returncode == 0
    assert "run_file works" in proc.stdout
    print("  run_file: OK")
finally:
    script.unlink(missing_ok=True)

env.teardown()
assert not env.is_ready
print("  Teardown: OK")
print()

# ---------------------------------------------------------------------------
# 2. ToolRegistry + built-in tools
# ---------------------------------------------------------------------------
print("=== ToolRegistry ===")

reg = ToolRegistry()
reg.register_defaults(env)  # env still None from teardown, but we pass it
# re-create env for code_patcher syntax checks
env.setup()

# list
names = [t["name"] for t in reg.list()]
assert "file_sampler" in names
assert "code_patcher" in names
print(f"  Registered: {names}")

# -- file_sampler: text -------------------------------------------------
text_file = HERE / "_test_sample.txt"
try:
    text_file.write_text("line1\nline2\nline3\n" * 1000)
    result = reg.execute("file_sampler", file_path=str(text_file), sample_size=100)
    assert result["format"] == "txt"
    assert result["sampled_lines"] > 0
    assert result["preview"][0] == "line1"
    print(f"  file_sampler (text): OK ({result['sampled_lines']} lines sampled)")
finally:
    text_file.unlink(missing_ok=True)

# -- file_sampler: CSV --------------------------------------------------
csv_file = HERE / "_test_sample.csv"
try:
    csv_file.write_text("name,age,active\nAlice,30,true\nBob,25,false\nCharlie,35,true\n")
    result = reg.execute("file_sampler", file_path=str(csv_file), sample_size=10000)
    assert result["format"] == "csv"
    assert result["columns"] == ["name", "age", "active"]
    assert len(result["rows"]) == 3
    print(f"  file_sampler (csv): OK (cols={result['columns']}, rows={len(result['rows'])})")
finally:
    csv_file.unlink(missing_ok=True)

# -- file_sampler: JSON -------------------------------------------------
json_file = HERE / "_test_sample.json"
try:
    json_file.write_text(
        json.dumps(
            [
                {"id": 1, "value": "a"},
                {"id": 2, "value": "b"},
            ]
        )
    )
    result = reg.execute("file_sampler", file_path=str(json_file))
    assert result["format"] == "json"
    assert result["type"] == "array"
    assert result["length"] == 2
    print(f"  file_sampler (json): OK (length={result['length']})")
finally:
    json_file.unlink(missing_ok=True)

# -- code_patcher: write ------------------------------------------------
target = HERE / "_test_output.py"
try:
    result = reg.execute(
        "code_patcher",
        file_path=str(target),
        content="x = 42\n",
        mode="write",
        env=env,
    )
    assert result["action"] in ("created", "overwritten")
    assert target.read_text() == "x = 42\n"
    assert result.get("syntax_check") == "passed"
    print(f"  code_patcher (write): OK (syntax={result.get('syntax_check')})")

    # -- code_patcher: patch --------------------------------------------
    result2 = reg.execute(
        "code_patcher",
        file_path=str(target),
        content="y = 99",
        mode="patch",
        old_string="x = 42",
        env=env,
    )
    assert result2["action"] == "patched"
    assert "y = 99" in target.read_text()
    print(f"  code_patcher (patch): OK (syntax={result2.get('syntax_check')})")
finally:
    target.unlink(missing_ok=True)
    (HERE / "_test_output.py.bak").unlink(missing_ok=True)

# -- code_patcher: syntax failure detection -----------------------------
bad_file = HERE / "_test_bad.py"
try:
    result = reg.execute(
        "code_patcher",
        file_path=str(bad_file),
        content="def foo(:\n    pass\n",
        mode="write",
        env=env,
    )
    # Syntax check should fail or be skipped depending on env
    print(
        f"  code_patcher (bad syntax): check={result.get('syntax_check')!r}"
        f"  error={result.get('syntax_error', '')!r}"
    )
finally:
    bad_file.unlink(missing_ok=True)
    (HERE / "_test_bad.py.bak").unlink(missing_ok=True)

# -- python_runner tool -------------------------------------------------
proc_result = reg.execute("python_runner", script="print('runner works')")
assert proc_result["returncode"] == 0
assert "runner works" in proc_result["stdout"]
print("  python_runner: OK")

print()
print("All smoke-tests passed.")

# Cleanup
env.teardown()
print("agent_env torn down.")

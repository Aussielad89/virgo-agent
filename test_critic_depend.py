"""
Integration test: critic + auto-depend pipeline path.

Runs the orchestrator with run_critic=True and auto_depend=True using
a code_gen that produces a file with a known third-party import
and missing __name__ guard.
"""

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from environment import AgentEnvironment
from orchestrator import Orchestrator
from tools import ToolRegistry

print("=== Critic + Auto-Depend Integration ===")

# Setup env
env = AgentEnvironment(base_path=str(HERE))
if env.is_ready:
    env.teardown()
env.setup()

registry = ToolRegistry()
registry.register_defaults(env)

orch = Orchestrator(
    env,
    registry,
    base_path=str(HERE),
    workspace_excludes=[
        "agent_env",
        ".crush",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".virgo_memory",
    ],
)


# code_gen produces a file with:
#   - missing __name__ guard (critic warning)
#   - import pandas (auto-depend should install)
def code_gen(plan, state, reg, env):
    return [
        (
            "_test_critic_dep.py",
            "import pandas\nimport sys\n\n"
            "df = pandas.DataFrame({'a': [1,2,3]})\n"
            "print(df.mean())\n",
        )
    ]


state = orch.run(
    goal="test critic + auto-depend",
    code_gen=code_gen,
    max_iterations=1,
    run_critic=True,
    auto_depend=True,
    auto_approve=True,
)

print()
print(f"  Phase:       {state.phase}")
print(f"  Files gen:   {len(state.generated_files)}")
print(f"  Loop result: {'PASS' if state.loop_passed else 'FAIL'}")

# Check critic ran (should have produced warnings about missing __name__)
# We can't easily capture the printed output, but we know it ran if phase
# passed through 'reviewing' and 'dependencies' states.
print(f"  Phase history: init -> ... -> {state.phase}")
print()

# Check that pandas is now installed in the agent env
proc = env.run("import pandas; print(pandas.__version__)")
if proc.returncode == 0:
    print(f"  pandas installed: {proc.stdout.strip()}")
else:
    print(f"  pandas NOT installed: {proc.stderr}")

# Cleanup test file
test_file = HERE / "_test_critic_dep.py"
if test_file.exists():
    test_file.unlink()
    (HERE / "_test_critic_dep.py.bak").unlink(missing_ok=True)

env.teardown()
print()
print("=== Done ===")

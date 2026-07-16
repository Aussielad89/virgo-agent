"""
Tests for orchestrator — 4-phase state machine.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Modules under test import via sys.path.insert, so we add the project root
import sys
HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from orchestrator import (
    Orchestrator, WorkspaceState, DiscoveredFile, GeneratedFile, TestLog,
    _step,
)
from _console import _supports_emoji
from tools import ToolRegistry
from environment import AgentEnvironment


# ===========================================================================
# Helper fixtures
# ===========================================================================


@pytest.fixture
def tmp_workspace() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d).resolve()


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register_defaults()
    return r


@pytest.fixture
def env(tmp_workspace: Path) -> AgentEnvironment:
    e = AgentEnvironment(str(tmp_workspace))
    # Don't call .setup() — we test env separately
    return e


# ===========================================================================
# WorkspaceState
# ===========================================================================


class TestWorkspaceState:
    def test_default_state(self) -> None:
        state = WorkspaceState(goal="test")
        assert state.goal == "test"
        assert state.base_path == "."
        assert state.phase == "init"
        assert state.discovered_files == []
        assert state.generated_files == []
        assert state.test_logs == []
        assert state.iteration == 0
        assert state.max_iterations == 5
        assert state.loop_passed is False

    def test_custom_max_iterations(self) -> None:
        state = WorkspaceState(goal="test", max_iterations=10)
        assert state.max_iterations == 10

    def test_custom_base_path(self) -> None:
        state = WorkspaceState(goal="test", base_path="/tmp")
        assert state.base_path == "/tmp"

    def test_context_storage(self) -> None:
        state = WorkspaceState(goal="test")
        state.context["key"] = "value"
        assert state.context["key"] == "value"


# ===========================================================================
# DiscoveredFile
# ===========================================================================


class TestDiscoveredFile:
    def test_minimal(self) -> None:
        f = DiscoveredFile(path="test.txt", extension=".txt", size=100)
        assert f.path == "test.txt"
        assert f.extension == ".txt"
        assert f.size == 100
        assert f.sample is None

    def test_with_sample(self) -> None:
        f = DiscoveredFile(path="data.csv", extension=".csv", size=200,
                           sample={"columns": ["a", "b"]})
        assert f.sample == {"columns": ["a", "b"]}


# ===========================================================================
# GeneratedFile
# ===========================================================================


class TestGeneratedFile:
    def test_defaults(self) -> None:
        f = GeneratedFile(path="test.py", content="print('hello')")
        assert f.path == "test.py"
        assert f.content == "print('hello')"
        assert f.iteration == 0
        assert f.passed is None

    def test_with_results(self) -> None:
        f = GeneratedFile(path="test.py", content="", iteration=3, passed=True)
        assert f.iteration == 3
        assert f.passed is True


# ===========================================================================
# TestLog
# ===========================================================================


class TestTestLog:
    def test_passed_property(self) -> None:
        log = TestLog(file="test.py", iteration=1, returncode=0,
                       stdout="ok", stderr="")
        assert log.passed is True

    def test_failed_property(self) -> None:
        log = TestLog(file="test.py", iteration=1, returncode=1,
                       stdout="", stderr="error")
        assert log.passed is False


# ===========================================================================
# _supports_emoji / _step (smoke tests)
# ===========================================================================


class TestStepPrinter:
    def test_supports_emoji_returns_bool(self) -> None:
        result = _supports_emoji()
        assert isinstance(result, bool)

    def test_step_does_not_crash(self, capsys: pytest.CaptureFixture) -> None:
        _step("goal", "test goal")
        captured = capsys.readouterr()
        assert "test goal" in captured.out


# ===========================================================================
# Orchestrator — construction
# ===========================================================================


class TestOrchestratorConstruction:
    def test_requires_env_and_registry(self, env: AgentEnvironment, registry: ToolRegistry) -> None:
        orch = Orchestrator(env, registry)
        assert orch.env is env
        assert orch.registry is registry
        assert orch.state is None

    def test_default_excludes(self, env: AgentEnvironment, registry: ToolRegistry) -> None:
        orch = Orchestrator(env, registry)
        assert "agent_env" in orch.excludes
        assert ".git" in orch.excludes
        assert "__pycache__" in orch.excludes

    def test_custom_includes(self, env: AgentEnvironment, registry: ToolRegistry) -> None:
        orch = Orchestrator(env, registry, workspace_includes=["*.py"])
        assert orch.includes == ["*.py"]

    def test_base_path_resolved(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        assert orch.base_path == tmp_workspace.resolve()


# ===========================================================================
# Orchestrator — _is_excluded
# ===========================================================================


class TestIsExcluded:
    def test_excluded_suffix(self, env: AgentEnvironment, registry: ToolRegistry) -> None:
        orch = Orchestrator(env, registry)
        assert orch._is_excluded(Path("test.bak"))
        assert orch._is_excluded(Path("test.pyc"))

    def test_not_excluded(self, env: AgentEnvironment, registry: ToolRegistry) -> None:
        orch = Orchestrator(env, registry)
        assert not orch._is_excluded(Path("test.py"))
        assert not orch._is_excluded(Path("data.csv"))

    def test_excluded_directory(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        (tmp_workspace / ".git").mkdir()
        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        assert orch._is_excluded(tmp_workspace / ".git")


# ===========================================================================
# Orchestrator — _discover (requires a workspace with files)
# ===========================================================================


class TestDiscover:
    def test_discover_finds_files(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        (tmp_workspace / "test.py").write_text("print('x')")
        (tmp_workspace / "data.csv").write_text("a,b\n1,2\n")
        (tmp_workspace / "agent_env").mkdir()  # should be excluded

        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = WorkspaceState(goal="test", base_path=str(tmp_workspace))
        orch._discover(state)

        found = [f.path for f in state.discovered_files]
        assert "test.py" in found
        assert "data.csv" in found
        assert not any("agent_env" in f for f in found)

    def test_discover_empty_workspace(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = WorkspaceState(goal="test", base_path=str(tmp_workspace))
        orch._discover(state)
        assert state.discovered_files == []

    def test_discover_file_metadata(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        (tmp_workspace / "data.json").write_text('{"x": 1}')
        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = WorkspaceState(goal="test", base_path=str(tmp_workspace))
        orch._discover(state)
        assert len(state.discovered_files) == 1
        f = state.discovered_files[0]
        assert f.extension == ".json"
        assert f.size > 0


# ===========================================================================
# Orchestrator — smoke test .run() with a no-op pipeline
# ===========================================================================


class TestRun:
    def test_run_without_policies_no_crash(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        """Calling .run() without policies should not crash.
        It will discover files, enter plan loop, but won't generate anything."""
        (tmp_workspace / "dummy.txt").write_text("hello")

        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = orch.run(
            goal="test",
            auto_approve=True,
            max_iterations=1,
        )
        assert state is not None
        assert state.goal == "test"

    def test_run_with_plan_only(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        """Providing only a planner should generate a plan."""
        (tmp_workspace / "dummy.txt").write_text("hello")

        def my_planner(goal: str, state: WorkspaceState) -> str:
            return f"Plan: process {len(state.discovered_files)} files"

        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = orch.run(goal="test", planner=my_planner, auto_approve=True, max_iterations=1)
        assert "Plan:" in state.plan
        assert "1 files" in state.plan

    def test_run_with_critic_flag(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        """Setting run_critic=True should not crash even with generated files."""
        (tmp_workspace / "mod.py").write_text("x = 1")

        def my_gen(plan, state, reg, env):
            return [("out.py", "x = 1")]

        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = orch.run(goal="test", code_gen=my_gen, auto_approve=True, max_iterations=1, run_critic=True)
        assert state.phase in ("complete", "testing")

    def test_run_auto_approve_works(self, env: AgentEnvironment, registry: ToolRegistry, tmp_workspace: Path) -> None:
        """With auto_approve=True, the pipeline should not prompt."""
        orch = Orchestrator(env, registry, base_path=str(tmp_workspace))
        state = orch.run(goal="test", auto_approve=True, max_iterations=1)
        assert state.phase == "complete"

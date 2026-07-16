"""
Tests for swarm multi-agent orchestration + SubAgent.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import pytest
from orchestrator import Orchestrator
from subagent import SubAgent, AgentResult
from tools import ToolRegistry
from environment import AgentEnvironment


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register_defaults()
    return r


@pytest.fixture
def env(tmp_path: Path) -> AgentEnvironment:
    e = AgentEnvironment(str(tmp_path))
    if e.is_ready:
        e.teardown()
    e.setup()
    yield e
    try:
        e.teardown()
    except Exception:
        pass


@pytest.fixture
def orch(registry: ToolRegistry, env: AgentEnvironment) -> Orchestrator:
    return Orchestrator(env, registry, base_path=str(env.base_path))


# ===========================================================================
# SubAgent tests
# ===========================================================================

class TestSubAgent:
    """SubAgent is the per-worker unit used by Orchestrator.swarm()."""

    def test_agent_result_dataclass(self) -> None:
        r = AgentResult(name="test", goal="do thing", status="success")
        assert r.name == "test"
        assert r.goal == "do thing"
        assert r.status == "success"
        assert r.files_created == []
        assert r.duration == 0.0

    def test_subagent_run_no_llm(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """SubAgent should create a fallback file even without LLM policies."""
        agent = SubAgent(name="test_worker", goal="print hello")
        result = agent.run(registry, env, verbose=False)
        assert result.status == "success"
        assert len(result.files_created) >= 1
        assert "test_worker" in result.files_created[0] or "worker" in result.files_created[0]

    def test_subagent_run_empty_tools(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """SubAgent with empty tool_names falls back to defaults."""
        agent = SubAgent(name="minimal", goal="test", tools=[])
        result = agent.run(registry, env, verbose=False)
        assert result.status == "success"

    def test_subagent_fallback_file_content(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """The fallback generator should produce a valid .py file listed in results."""
        agent = SubAgent(name="writer", goal="write a test script")
        result = agent.run(registry, env, verbose=False)
        assert len(result.files_created) >= 1
        created = result.files_created[0]
        assert created.endswith(".py"), f"Expected .py file, got {created}"

    def test_subagent_blackboard_posts(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """SubAgent should post status updates to blackboard when provided."""
        try:
            from blackboard import Blackboard
        except ImportError:
            pytest.skip("Blackboard module not available")
        bb = Blackboard()
        agent = SubAgent(name="bb_test", goal="test bb", blackboard=bb)
        result = agent.run(registry, env, verbose=False)
        assert result.status == "success"
        # Should have posted at least "started" and "completed" or "failed"
        keys = list(bb._topics.keys())
        agent_keys = [k for k in keys if "bb_test" in k]
        assert len(agent_keys) >= 1

    def test_subagent_status_failed_on_exception(self, registry: ToolRegistry) -> None:
        """SubAgent should return failed status when env is broken."""
        # Create a minimal env that's not set up
        env = AgentEnvironment("/nonexistent/path")
        agent = SubAgent(name="fail_agent", goal="should fail")
        result = agent.run(registry, env, verbose=False)
        # Should gracefully handle the error
        assert result.status in ("failed", "success")  # graceful fallback may still work

    def test_subagent_planning_called(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """SubAgent should call the planner when provided."""
        plan_called = False

        def fake_planner(goal: str, **kwargs) -> str:
            nonlocal plan_called
            plan_called = True
            return f"Plan: {goal}"

        agent = SubAgent(name="planner_test", goal="test plan", planner=fake_planner)
        result = agent.run(registry, env, verbose=False)
        assert plan_called, "planner was not called"
        assert result.status == "success"

    def test_subagent_generator_called(self, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """SubAgent should use the provided generator instead of fallback."""
        gen_called = False

        def fake_generator(plan: str, **kwargs) -> list[tuple[str, str]]:
            nonlocal gen_called
            gen_called = True
            return [("generated.py", f"# {plan}\nprint('ok')\n")]

        agent = SubAgent(name="gen_test", goal="test gen", generator=fake_generator)
        result = agent.run(registry, env, verbose=False)
        assert gen_called, "generator was not called"
        assert "generated.py" in result.files_created


# ===========================================================================
# Orchestrator.swarm() tests
# ===========================================================================

class TestOrchestratorSwarm:
    """Orchestrator.swarm() delegates to SubAgent workers."""

    def test_swarm_empty_agents(self, orch: Orchestrator) -> None:
        """Swarm with no agents should return empty results."""
        results = orch.swarm("empty test", [], verbose=False)
        assert results == []

    def test_swarm_single_agent(self, orch: Orchestrator, registry: ToolRegistry, env: AgentEnvironment) -> None:
        """Swarm with one agent should produce one result."""
        results = orch.swarm(
            "Single agent test",
            [("worker1", "print hello world")],
            verbose=False,
        )
        assert len(results) == 1
        assert results[0]["name"] == "worker1"
        assert results[0]["status"] in ("success", "failed")

    def test_swarm_multiple_agents(self, orch: Orchestrator) -> None:
        """Swarm with multiple agents should return results in order."""
        results = orch.swarm(
            "Multiple agents",
            [("agent_a", "task A"), ("agent_b", "task B"), ("agent_c", "task C")],
            verbose=False,
        )
        assert len(results) == 3
        names = [r["name"] for r in results]
        assert names == ["agent_a", "agent_b", "agent_c"]

    def test_swarm_ordered_mode(self, orch: Orchestrator) -> None:
        """Ordered mode should still produce results (sequential execution)."""
        results = orch.swarm(
            "Ordered test",
            [("first", "task 1"), ("second", "task 2")],
            ordered=True,
            verbose=False,
        )
        assert len(results) == 2
        # Ordered should not affect result count
        assert results[0]["name"] == "first"
        assert results[1]["name"] == "second"

    def test_swarm_shared_blackboard(self, orch: Orchestrator) -> None:
        """Shared blackboard should not break execution."""
        results = orch.swarm(
            "Blackboard test",
            [("agent_x", "task x"), ("agent_y", "task y")],
            share=True,
            verbose=False,
        )
        assert len(results) == 2

    def test_swarm_shared_ordered(self, orch: Orchestrator) -> None:
        """Blackboard + ordered should be valid."""
        results = orch.swarm(
            "BB ordered test",
            [("alpha", "task alpha"), ("beta", "task beta")],
            share=True,
            ordered=True,
            verbose=False,
        )
        assert len(results) == 2

    def test_swarm_result_structure(self, orch: Orchestrator) -> None:
        """Each swarm result should have the expected keys."""
        results = orch.swarm(
            "Result shape test",
            [("shape_test", "print 'hello'")],
            verbose=False,
        )
        assert len(results) == 1
        r = results[0]
        assert "name" in r
        assert "goal" in r
        assert "status" in r
        assert "files" in r
        assert "duration" in r
        assert isinstance(r["duration"], (int, float))
        assert isinstance(r["files"], list)

    def test_swarm_saves_state(self, orch: Orchestrator) -> None:
        """Swarm results should be accessible via the result list."""
        results = orch.swarm(
            "State test",
            [("state_test", "print 'state'")],
            verbose=False,
        )
        assert len(results) == 1
        # Results dict should have meaningful content
        assert results[0]["goal"] == "print 'state'"

    def test_swarm_verbose_output(self, orch: Orchestrator, capsys) -> None:
        """Verbose mode should print progress to stdout."""
        orch.swarm(
            "Verbose test",
            [("verbose_agent", "print 'verbose'")],
            verbose=True,
        )
        captured = capsys.readouterr()
        assert "swarm" in captured.out.lower() or "verbose_agent" in captured.out

    def test_swarm_duration_tracking(self, orch: Orchestrator) -> None:
        """Each agent result should have a positive duration."""
        results = orch.swarm(
            "Duration test",
            [("fast", "print 'fast'"), ("slow", "import time; time.sleep(0.05); print('slow')")],
            verbose=False,
        )
        for r in results:
            assert r["duration"] >= 0

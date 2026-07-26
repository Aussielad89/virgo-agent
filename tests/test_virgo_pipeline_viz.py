"""Tests for virgo_pipeline_viz — Pipeline Visualizer."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from virgo_pipeline_viz import PipelineViz, get_viz, viz_start, viz_phase, viz_stop  # noqa: E402


class TestPipelineViz:
    """Tests for PipelineViz class."""

    def test_create(self):
        """PipelineViz can be instantiated."""
        viz = PipelineViz(width=60)
        assert viz is not None
        assert viz.active_phase == "idle"

    def test_start_sets_goal(self):
        """start() sets goal and max_iterations."""
        viz = PipelineViz(width=60)
        viz.start(goal="test goal", max_iterations=5)
        assert viz.goal == "test goal"
        assert viz.max_iterations == 5

    def test_set_phase_changes_active(self):
        """set_phase updates active_phase."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.set_phase("discover")
        assert viz.active_phase == "discover"
        viz.set_phase("plan")
        assert viz.active_phase == "plan"

    def test_set_phase_unknown_does_nothing(self):
        """set_phase ignores unknown phase."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.set_phase("discover")
        viz.set_phase("nonexistent")
        assert viz.active_phase == "discover"

    def test_set_iteration(self):
        """set_iteration updates iteration."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.set_iteration(3)
        assert viz.iteration == 3

    def test_add_phase_result(self):
        """add_phase_result adds to phases list."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.add_phase_result("discover", "pass", "found files")
        assert len(viz.phases) == 1
        assert viz.phases[0]["phase"] == "discover"
        assert viz.phases[0]["detail"] == "found files"

    def test_stop_sets_done(self):
        """stop() sets active_phase to done."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.stop()
        assert viz.active_phase == "done"

    def test_stop_preserves_pass_fail(self):
        """stop() doesn't override pass/fail status."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.set_phase("pass")
        viz.stop()
        assert viz.active_phase == "pass"

    def test_disable_suppresses_output(self):
        """disable() prevents rendering."""
        viz = PipelineViz(width=60)
        viz.disable()
        assert viz._enabled is False

    def test_enable_restores_output(self):
        """enable() allows rendering again."""
        viz = PipelineViz(width=60)
        viz.disable()
        viz.enable()
        assert viz._enabled is True

    def test_phase_timing_recorded(self):
        """Phase times are recorded on set_phase."""
        viz = PipelineViz(width=60)
        viz.start()
        viz.set_phase("discover")
        time.sleep(0.02)
        viz.set_phase("plan")
        assert "discover" in viz.phase_times
        assert viz.phase_times["discover"] > 0.0

    def test_get_viz_singleton(self):
        """get_viz returns same instance."""
        v1 = get_viz()
        v2 = get_viz()
        assert v1 is v2

    def test_viz_start_global(self):
        """viz_start() convenience works."""
        viz_stop()  # ensure clean
        viz_start("global test", 3)
        viz = get_viz()
        assert viz.goal == "global test"
        viz_stop()

    def test_viz_phase_global(self):
        """viz_phase() convenience works."""
        viz_start("test", 3)
        viz_phase("test")
        viz = get_viz()
        assert viz.active_phase == "test"
        viz_stop()

    def test_make_iteration_bar(self):
        """_make_iteration_bar returns string."""
        viz = PipelineViz(width=60)
        viz.start(max_iterations=5)
        viz.set_iteration(2)
        bar = viz._make_iteration_bar()
        assert isinstance(bar, str)
        assert "2/5" in bar

    def test_full_pipeline_flow(self):
        """Simulate a full pipeline run without errors."""
        viz = PipelineViz(width=60)
        viz.disable()
        viz.start(goal="full test", max_iterations=2)

        for phase in ["discover", "plan", "generate", "test", "pass"]:
            viz.set_phase(phase)
            viz.add_phase_result(phase, "pass")

        viz.stop(elapsed=1.5)
        assert len(viz.phases) == 5

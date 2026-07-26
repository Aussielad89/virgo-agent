"""
virgo_pipeline_viz — Live animated pipeline visualizer for Virgo.

Renders an ASCII flowchart of the pipeline phases as they execute:
  discover → plan → generate → test → fix → pass/fail

Each phase lights up with color when active, shows elapsed time,
and the overall progress bar tracks iterations.

Usage (integrated into orchestrator):
    from virgo_pipeline_viz import PipelineViz
    viz = PipelineViz()
    viz.start()
    viz.set_phase("discover")
    ...
    viz.set_phase("pass")
    viz.stop(elapsed=12.5)
"""

from __future__ import annotations

import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log

# ── ANSI helpers ──────────────────────────────────────────────────────────

_R = "\033[0m"
_B = "\033[1m"
_D = "\033[2m"
_I = "\033[3m"

_CY = "\033[36m"
_GR = "\033[32m"
_YL = "\033[33m"
_RE = "\033[31m"
_MA = "\033[35m"
_BL = "\033[34m"
_WH = "\033[37m"

# Phase colours
_PHASE_COLORS = {
    "idle": _D,
    "discover": _CY,
    "plan": _BL,
    "generate": _YL,
    "test": _MA,
    "fix": _RE,
    "pass": _GR,
    "fail": _RE,
    "done": _GR,
}

_PHASE_LABELS = {
    "idle": "⏳ IDLE",
    "discover": "🔍 DISCOVER",
    "plan": "🧠 PLAN",
    "generate": "⚡ GENERATE",
    "test": "🧪 TEST",
    "fix": "🔧 FIX",
    "pass": "✅ PASS",
    "fail": "❌ FAIL",
    "done": "✦ DONE",
}

_PHASE_ICONS = {
    "idle": "○",
    "discover": "◉",
    "plan": "◆",
    "generate": "▶",
    "test": "●",
    "fix": "▲",
    "pass": "★",
    "fail": "✖",
    "done": "✦",
}

# Pipeline flow order for the visualizer
_PIPELINE_FLOW = ["discover", "plan", "generate", "test", "fix", "pass"]

# ── Pipeline Visualizer ────────────────────────────────────────────────────


class PipelineViz:
    """Live ASCII pipeline visualizer with animated phases."""

    def __init__(self, width: int | None = None) -> None:
        self.width = width or self._get_width()
        self.phases: list[dict[str, Any]] = []
        self.active_phase: str = "idle"
        self.iteration: int = 1
        self.max_iterations: int = 3
        self.goal: str = ""
        self.start_time: float = 0.0
        self.phase_times: dict[str, float] = {}
        self._phase_start: float = 0.0
        self._lines_output: int = 0
        self._enabled: bool = True

    def _get_width(self) -> int:
        try:
            return min(shutil.get_terminal_size().columns - 2, 80)
        except Exception:
            return 70

    def start(self, goal: str = "", max_iterations: int = 3) -> None:
        """Start the visualizer for a new pipeline run."""
        self.goal = goal
        self.max_iterations = max_iterations
        self.iteration = 1
        self.active_phase = "idle"
        self.start_time = time.time()
        self.phase_times = {}
        self.phases = []

        if not self._enabled:
            return

        self._draw_header()
        self._render()

    def set_phase(self, phase: str) -> None:
        """Update the active phase (discover, plan, generate, test, fix, pass, fail)."""
        if phase in _PHASE_COLORS:
            # Record time for previous phase if there was one
            if self.active_phase != "idle" and self.active_phase != phase:
                elapsed = time.time() - self._phase_start
                self.phase_times[self.active_phase] = elapsed

            self.active_phase = phase
            self._phase_start = time.time()

            if phase == "fail" or phase == "pass":
                self.phase_times[phase] = time.time() - self._phase_start

            if self._enabled:
                self._render()
        else:
            log.warning("Unknown phase: %s", phase)

    def set_iteration(self, iteration: int) -> None:
        """Update current iteration number."""
        self.iteration = iteration
        if self._enabled:
            self._render()

    def add_phase_result(self, phase: str, status: str, detail: str = "") -> None:
        """Add a completed phase result to history."""
        self.phases.append({
            "phase": phase,
            "status": status,
            "detail": detail,
            "time": self.phase_times.get(phase, 0.0),
        })
        if self._enabled:
            self._render()

    def stop(self, elapsed: float = 0.0) -> None:
        """Finish the visualizer and show summary."""
        if self.active_phase in ("pass", "fail", "done"):
            pass
        else:
            self.active_phase = "done"

        if elapsed == 0.0 and self.start_time:
            elapsed = time.time() - self.start_time

        if self._enabled:
            self._draw_summary(elapsed)

    def disable(self) -> None:
        """Disable the visualizer output."""
        self._enabled = False

    def enable(self) -> None:
        """Enable the visualizer output."""
        self._enabled = True

    # ── Rendering ───────────────────────────────────────────────────────

    def _draw_header(self) -> None:
        """Draw the pipeline visualizer header."""
        w = self.width
        goal_trunc = self.goal[:w - 20] if self.goal else ""
        
        print()
        print(f"  {_CY}╔{'═' * (w - 2)}╗{_R}")
        if goal_trunc:
            print(f"  {_CY}║{_R}  {_B}Pipeline:{_R} {goal_trunc:{w - 14}s}  {_CY}║{_R}")
        
        # Phase flow diagram placeholder (updated each render)
        self._flow_line_y = 0  # Track where flow line renders for redraw

    def _render(self) -> None:
        """Render/update the pipeline flow visualization."""
        if not self._enabled:
            return

        w = self.width
        
        # Build the phase flow line
        # ── [🔍 DISCOVER] ──→ [🧠 PLAN] ──→ [⚡ GENERATE] ──→ ...
        flow_parts = []
        for phase in _PIPELINE_FLOW:
            is_active = (phase == self.active_phase)
            is_done = phase in [p["phase"] for p in self.phases if p["status"] == "pass"]
            
            label = _PHASE_LABELS.get(phase, phase.upper())
            color = _PHASE_COLORS.get(phase, _D)
            
            if is_active:
                # Active phase — bright, with pulsing icon
                icon_c = _PHASE_ICONS.get(phase, ">")
                parts = f"{_B}{color}{icon_c} {label}{_R}"
            elif is_done:
                # Completed phase — dim
                parts = f"{_D}{_PHASE_ICONS.get(phase, '✓')} {label}{_R}"
            else:
                # Future phase — very dim
                parts = f"{_D}{_PHASE_ICONS.get(phase, '○')} {_D}{label}{_R}"
            
            flow_parts.append(parts)
        
        # Connect phases with arrows
        flow_line = f"  {_D}──{_R}  ".join(flow_parts)
        
        # Truncate if too long
        if len(flow_line) > w:
            flow_line = flow_line[:w - 3] + "…"
        
        # Iteration bar
        iter_bar = self._make_iteration_bar()
        
        # Phase timer
        timer = ""
        if self.active_phase != "idle" and self._phase_start:
            elapsed = time.time() - self._phase_start
            timer = f"  {_D}[{elapsed:.1f}s]{_R}"
        
        # ── Move cursor up and re-draw flow section ──
        # Clear previous flow lines (3 lines: flow, iter bar, spacer)
        if hasattr(self, '_prev_flow_lines') and self._prev_flow_lines > 0:
            print(f"\033[{self._prev_flow_lines}A", end="", flush=True)
            # Clear those lines
            for _ in range(self._prev_flow_lines):
                print(" " * (w + 4))
            print(f"\033[{self._prev_flow_lines}A", end="", flush=True)
        
        # Print flow
        print(f"  {_CY}║{_R}  {flow_line}{' ' * max(0, w - len(flow_line) - 4)}  {_CY}║{_R}")
        print(f"  {_CY}║{_R}  {iter_bar}{timer}{' ' * max(0, w - len(iter_bar) - len(timer) - 4)}  {_CY}║{_R}")
        print()
        
        self._prev_flow_lines = 3

    def _make_iteration_bar(self) -> str:
        """Create ASCII iteration progress bar."""
        total = self.max_iterations or 3
        current = min(self.iteration, total)
        
        bar = ""
        for i in range(total):
            if i < current - 1:
                # Done
                bar += f"{_GR}█{_R}"
            elif i == current - 1:
                # Current (active phase)
                if self.active_phase in ("pass", "fail", "done"):
                    bar += f"{_GR}█{_R}"
                else:
                    bar += f"{_YL}▓{_R}"
            else:
                # Future
                bar += f"{_D}░{_R}"
        
        label = f"{_B}WTF {current}/{total}{_R}"
        return f"{_D}Iterations:{_R} {bar}  {label}"

    def _draw_summary(self, elapsed: float) -> None:
        """Draw the final summary after pipeline completes."""
        w = self.width
        status = "PASS" if self.active_phase == "pass" else "FAIL" if self.active_phase == "fail" else "DONE"
        status_color = _GR if status == "PASS" else _RE if status == "FAIL" else _CY
        
        # Phase timing breakdown
        phases_summary = ""
        for phase in _PIPELINE_FLOW:
            t = self.phase_times.get(phase, 0.0)
            if t > 0:
                color = _PHASE_COLORS.get(phase, _D)
                label = _PHASE_LABELS.get(phase, phase.upper())[:6]
                phases_summary += f"  {color}{label}{_R} {t:.1f}s"
        
        print(f"  {_CY}╠{'═' * (w - 2)}╣{_R}")
        print(f"  {_CY}║{_R}  {_B}Result:{_R} {status_color}{status}{_R}  "
              f"  {_D}Total:{_R} {elapsed:.1f}s"
              f"  {' ' * max(0, w - 35)}  {_CY}║{_R}")
        if phases_summary:
            print(f"  {_CY}║{_R}  {phases_summary}{' ' * max(0, w - len(phases_summary) - 4)}  {_CY}║{_R}")
        print(f"  {_CY}╚{'═' * (w - 2)}╝{_R}")
        print()


# ── Single-function convenience API ────────────────────────────────────────

_viz_instance: PipelineViz | None = None


def get_viz() -> PipelineViz:
    """Get or create the global PipelineViz instance."""
    global _viz_instance
    if _viz_instance is None:
        _viz_instance = PipelineViz()
    return _viz_instance


def viz_start(goal: str = "", max_iterations: int = 3) -> None:
    """Start the pipeline visualizer."""
    get_viz().start(goal, max_iterations)


def viz_phase(phase: str) -> None:
    """Update the current phase."""
    get_viz().set_phase(phase)


def viz_iteration(iteration: int) -> None:
    """Update the current iteration."""
    get_viz().set_iteration(iteration)


def viz_stop(elapsed: float = 0.0) -> None:
    """Stop the visualizer."""
    get_viz().stop(elapsed)


# ── CLI handler (wired from cli.py) ──────────────────────────────────────


def cmd_viz_demo(_args: Any = None) -> None:
    """Run a demo of the pipeline visualizer."""
    import time as _time

    viz = get_viz()
    viz.start("demo pipeline", max_iterations=3)

    phases = ["discover", "plan", "generate", "test", "fix", "pass"]
    for phase in phases:
        viz.set_phase(phase)
        _time.sleep(0.5)
        viz.add_phase_result(phase, "pass", f"{phase} completed")

    viz.stop(elapsed=3.2)

    # Celebration
    try:
        from virgo_celebrate import banner
        print(banner("PIPELINE PASSED!", "success"))
    except ImportError:
        print(f"\n  {_GR}{_B}✦ PIPELINE PASSED ✦{_R}\n")


# ── Main (standalone demo) ────────────────────────────────────────────────


if __name__ == "__main__":
    cmd_viz_demo()

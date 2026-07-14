"""
virgo — multi-agent state machine core.

Drives a four-phase pipeline for every user goal:

  1. 🔍  Discover  — scan workspace, sample files, infer schemas
  2. 🧠  Plan      — decide what to build (delegated to a policy)
  3. 💻  Generate  — write code files using the tool registry
  4. 🔄  WTF Loop  — Write → Test → Fix, repeating until green or
                     max_iterations exhausted

The ``Orchestrator.run()`` method accepts three policy callbacks so
callers (including LLM-based agents) can plug in arbitrary planning,
code-generation, and error-fixing logic without touching the loop
infrastructure.
"""

from __future__ import annotations

import os
import sys
import time
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from environment import AgentEnvironment
    from tools import ToolRegistry


# ===========================================================================
# Step printer — coloured / emoji terminal output
# ===========================================================================

_ICONS = {
    "goal":     "goal",
    "discover": "discover",
    "plan":     "plan",
    "generate": "generate",
    "test":     "test",
    "fix":      "fix",
    "pass":     "pass",
    "fail":     "fail",
    "info":     "info",
    "syntax":   "syntax",
}


def _supports_emoji() -> bool:
    """Return True if the terminal is likely to handle Unicode emoji."""
    enc = (sys.stdout.encoding or "").lower()
    return "utf" in enc or enc in ("", "unknown")


def _step(label: str, *parts: str) -> None:
    msg = "  ".join(p for p in parts if p)
    if _supports_emoji():
        # Full Unicode mode
        _EMOJI = {
            "goal":     "\U0001F3AF",  # 🎯
            "discover": "\U0001F50D",  # 🔍
            "plan":     "\U0001F9E0",  # 🧠
            "generate": "\U0001F4BB",  # 💻
            "test":     "\U0001F6E0",  # 🛠
            "fix":      "\U0001F527",  # 🔧
            "pass":     "\u2705",      # ✅
            "fail":     "\u274C",      # ❌
            "info":     "\u2139",      # ℹ
            "syntax":   "\U0001F52C",  # 🔬
        }
        icon = _EMOJI.get(label, "\u27A1")
        print(f"  {icon}  {msg}" if label in _EMOJI else f"  \u27A1  {msg}")
    else:
        # ASCII-safe fallback
        _TEXT = {
            "goal":     "[GOAL]",
            "discover": "[SCAN]",
            "plan":     "[PLAN]",
            "generate": "[CODE]",
            "test":     "[TEST]",
            "fix":      "[FIX]",
            "pass":     "[PASS]",
            "fail":     "[FAIL]",
            "info":     "[INFO]",
            "syntax":   "[SYNTAX]",
        }
        tag = _TEXT.get(label, ">>>")
        print(f"  {tag}  {msg}")


# ===========================================================================
# Data types — flow through the pipeline
# ===========================================================================

@dataclass
class DiscoveredFile:
    """Metadata for one file found during workspace discovery."""
    path: str
    extension: str
    size: int
    sample: dict[str, Any] | None = None


@dataclass
class GeneratedFile:
    """A file produced in the generate phase."""
    path: str
    content: str
    iteration: int = 0          # last WTF iteration it was tested in
    passed: bool | None = None   # latest test result


@dataclass
class TestLog:
    """Result from executing a generated file in the agent env."""
    file: str
    iteration: int
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass
class WorkspaceState:
    """Mutable state bag that the pipeline reads and writes.

    External policy callbacks receive this so they can inspect what
    was discovered, what has been generated, and what errors occurred.
    """
    goal: str
    base_path: str = "."

    # -- discovery ----------------------------------------------------------
    discovered_files: list[DiscoveredFile] = field(default_factory=list)

    # -- planning -----------------------------------------------------------
    plan: str = ""

    # -- generation ---------------------------------------------------------
    generated_files: list[GeneratedFile] = field(default_factory=list)

    # -- WTF loop -----------------------------------------------------------
    test_logs: list[TestLog] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 5
    loop_passed: bool = False

    # -- lifecycle ----------------------------------------------------------
    phase: str = "init"          # init | discovered | planned | generated |
                                 # testing | fixing | complete
    context: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Policy type aliases (for documentation / type-checking)
# ===========================================================================

# planner(goal, state) -> plan_string
Planner = Callable[[str, WorkspaceState], str]

# code_gen(plan, state, registry, env) -> list[(file_path, content)]
CodeGenerator = Callable[
    [str, WorkspaceState, Any, Any],
    list[tuple[str, str]],
]

# fixer(error_log, state, registry, env) -> list[(file, old, new)] | None
Fixer = Callable[
    [TestLog, WorkspaceState, Any, Any],
    Optional[list[tuple[str, str, str]]],
]


# ===========================================================================
# Orchestrator
# ===========================================================================

class Orchestrator:
    """Four-phase state machine for autonomous code generation.

    Usage
    -----
    Most callers will only ever need ``.run()``::

        orch = Orchestrator(env, registry)
        state = orch.run(
            goal="Extract summary stats from logs.csv and write a report",
            planner=my_planner,
            code_gen=my_generator,
            fixer=my_fixer,
        )

    When called without policies the pipeline still runs — it will
    discover files and enter the WTF loop but will skip generation
    (useful for inspection or incremental usage).
    """

    def __init__(
        self,
        env: AgentEnvironment,
        registry: ToolRegistry,
        base_path: Optional[str] = None,
        *,
        workspace_includes: Optional[list[str]] = None,
        workspace_excludes: Optional[list[str]] = None,
    ) -> None:
        self.env = env
        self.registry = registry
        self.base_path = Path(base_path or os.getcwd()).resolve()

        # File-discovery patterns
        self.includes = workspace_includes or ["**/*"]
        self.excludes = workspace_excludes or [
            "agent_env",
            ".crush",
            ".git",
            "__pycache__",
            ".venv",
            ".mypy_cache",
            ".pytest_cache",
        ]
        self.suffix_excludes = [".bak", ".pyc", ".pyo"]

        # Populated by .run()
        self.state: Optional[WorkspaceState] = None

    # ======================================================================
    # Public entry point
    # ======================================================================

    def run(
        self,
        goal: str,
        *,
        planner: Optional[Planner] = None,
        code_gen: Optional[CodeGenerator] = None,
        fixer: Optional[Fixer] = None,
        max_iterations: int = 5,
        max_plan_cycles: int = 5,
        run_critic: bool = False,
        auto_depend: bool = False,
        auto_approve: bool = False,
    ) -> WorkspaceState:
        """Run the full discovery → plan → generate → test-fix pipeline.

        Parameters
        ----------
        goal:
            The user's objective (free-text string).
        planner:
            Callable(goal, state) -> plan_string.  If omitted the goal
            itself is used as the plan.
        code_gen:
            Callable(plan, state, registry, env) -> list[(path, content)].
            Each tuple is written via the ``code_patcher`` tool.
        fixer:
            Callable(test_log, state, registry, env)
            -> list[(file_path, old_string, new_string)] | None.
            Each tuple is applied as a ``code_patcher`` patch.
        max_iterations:
            Hard cap on WTF cycles (default 5).
        run_critic:
            Run static analysis on generated files before testing.
        auto_depend:
            Scan generated files for imports and auto-install missing
            third-party packages in the agent environment.
        auto_approve:
            Skip the interactive plan-approval prompt (default False).
            Set to True for automated / non-interactive runs.
        """
        self.state = WorkspaceState(
            goal=goal,
            base_path=str(self.base_path),
            max_iterations=max_iterations,
        )
        state = self.state

        # Display pipeline overview graph
        try:
            from workflow import render_graph as _render_graph
            print(_render_graph("discover"))
        except Exception:
            pass

        # ---- Phase 1: Discover -------------------------------------------
        state.phase = "discovering"
        _step("goal", goal)
        self._discover(state)

        # ---- Phase 2-3: Plan → Human approval → (revise or generate) ----
        state.phase = "planning"
        plan_cycles = 0
        approved = False

        while not approved and plan_cycles < max_plan_cycles:
            plan_cycles += 1
            try:
                plan = planner(goal, state) if planner else goal
            except Exception as exc:
                _step("fail", f"Planner crashed: {exc}")
                print("  [!] Planner encountered an unexpected error — using goal as plan")
                plan = goal
            state.plan = plan
            _step("plan", f"Cycle {plan_cycles}/{max_plan_cycles}")
            print(f"\n{'=' * 60}")
            print(f"  PLAN")
            print(f"{'=' * 60}")
            print(textwrap.indent(plan.strip(), "  "))
            print(f"{'=' * 60}")
            if auto_approve:
                approved = True
                _step("pass", "Plan auto-approved")
            else:
                answer = input("  >>> Do you approve this plan? (y/n): ").strip().lower()

                if answer in ("", "y", "yes"):
                    approved = True
                    _step("pass", "Plan approved")
                else:
                    feedback = input("  >>> Your feedback (or press Enter to abort): ").strip()
                    if not feedback:
                        _step("fail", "Plan rejected — aborting")
                        state.phase = "aborted"
                        return state
                    # Incorporate feedback into the goal for the next cycle
                    goal = goal + "\n[REVISION] " + feedback
                    _step("fix", f"Feedback applied — re-planning")

        if not approved:
            _step("fail", f"Plan not approved after {max_plan_cycles} cycles — aborting")
            state.phase = "aborted"
            return state

        # ---- Phase 4: Generate (was Phase 3) -----------------------------
        state.phase = "generating"
        if code_gen:
            try:
                files = code_gen(plan, state, self.registry, self.env)
            except Exception as exc:
                _step("fail", f"Generator crashed: {exc}")
                print("  [!] Generator encountered an unexpected error — skipping generation")
                files = []
            _step("generate", f"Writing {len(files)} file(s) …")
            for fpath, content in files:
                result = self.registry.execute(
                    "code_patcher",
                    file_path=fpath,
                    content=content,
                    mode="write",
                )
                state.generated_files.append(
                    GeneratedFile(path=fpath, content=content)
                )
                syntax = result.get("syntax_check", "")
                extra = f"syntax:{syntax}" if syntax else ""
                _step("generate", fpath, extra)

        # ---- Phase 4a: Critic (optional) -----------------------------------
        if run_critic and state.generated_files:
            state.phase = "reviewing"
            _step("syntax", "Running code critic …")
            paths = [str(self.base_path / gf.path) for gf in state.generated_files]
            try:
                from critic import review_files
                report = review_files(paths)
                print(f"\n{report}")
                if not report.passed:
                    _step("fail", f"Critic found {len(report.errors)} error(s)")
                else:
                    _step("pass", "Critic passed")
            except Exception as exc:
                _step("info", f"Critic skipped: {exc}")

        # ---- Phase 4b: Auto-dependency install (optional) -------------------
        if auto_depend and state.generated_files:
            state.phase = "dependencies"
            _step("syntax", "Checking dependencies …")
            for gf in state.generated_files:
                try:
                    from autodepend import auto_install
                    installed = auto_install(gf.content, self.env)
                    if installed:
                        _step("info", f"  Installed: {', '.join(installed)}")
                except Exception as exc:
                    _step("info", f"  Dep check skipped: {exc}")

        # ---- Phase 5: Write-Test-Fix loop --------------------------------
        state.phase = "testing"
        self._wtf_loop(fixer, max_iterations)

        state.phase = "complete"
        return state

    # ======================================================================
    # Multi-agent swarm
    # ======================================================================

    def swarm(
        self,
        goal: str,
        agents: list[tuple[str, str]],
        *,
        max_iterations: int = 3,
        verbose: bool = True,
        use_llm: bool = False,
        share: bool = False,       # enable agent-to-agent blackboard
        ordered: bool = False,     # run agents in sequence, not parallel
    ) -> list[dict[str, Any]]:
        """Delegate sub-goals to parallel agents and collect results.

        Parameters
        ----------
        goal:
            The overarching goal (for context).
        agents:
            List of (name, sub_goal) tuples.  Each becomes a SubAgent.
        max_iterations:
            Per-agent WTF iteration cap.
        verbose:
            Print agent progress to stdout.
        use_llm:
            If True, load LLM-backed policies from ``main`` as the
            default planner / generator / fixer for each agent.

        Returns
        -------
        List of result dicts, one per agent (in the same order).
        """
        from subagent import SubAgent

        # Optionally load LLM policies
        planner = generator = fixer = None
        if use_llm:
            try:
                import main
                # Create a minimal state so adapters have something to pass
                from orchestrator import WorkspaceState as _WS
                _swarm_state = _WS(goal=goal, base_path=str(self.base_path))

                # Discover the workspace so planners have context
                self._discover(_swarm_state)

                def _planner(goal: str, **kwargs: Any) -> str:
                    return main.my_planner(goal, _swarm_state)

                def _generator(plan: str, **kwargs: Any) -> list[tuple[str, str]]:
                    return main.my_generator(plan, _swarm_state,
                                              self.registry, self.env)

                def _fixer(file: str, error: str, **kwargs: Any) -> list[tuple[str, str, str]] | None:
                    from orchestrator import TestLog
                    log = TestLog(
                        file=file, iteration=1, returncode=1,
                        stdout="", stderr=error,
                    )
                    return main.my_fixer(log, _swarm_state,
                                          self.registry, self.env)

                planner = _planner
                generator = _generator
                fixer = _fixer
            except Exception as exc:
                import traceback
                print(f"  [swarm] LLM load failed: {exc}")
                traceback.print_exc()

        print(f"\n  {'=' * 58}")
        print(f"  SWARM: {goal}")
        if share:
            print(f"  Blackboard: ON  |  Ordered: {'yes' if ordered else 'no'}")
        print(f"  {'=' * 58}")

        # ── Shared blackboard ────────────────────────────────────────
        bb = None
        if share:
            from blackboard import Blackboard
            bb = Blackboard()
            bb.post("swarm/goal", goal, source="orchestrator", phase="init")

        results: list[dict[str, Any]] = []
        t0 = time.time()

        for idx, (name, sub_goal) in enumerate(agents, 1):
            # Ordered mode: wait for previous agent's completed status
            if ordered and idx > 1 and bb is not None:
                prev = agents[idx - 2][0]
                if verbose:
                    print(f"  [swarm] waiting for {prev} to complete …")
                bb.wait_for(f"agent/{prev}/status", timeout=600)

            agent = SubAgent(
                name=name,
                goal=sub_goal,
                planner=planner,
                generator=generator,
                fixer=fixer,
                max_iterations=max_iterations,
                blackboard=bb,
            )
            result = agent.run(self.registry, self.env, verbose=verbose)
            results.append({
                "name": result.name,
                "goal": result.goal,
                "status": result.status,
                "files": result.files_created,
                "output": result.output,
                "error": result.error,
                "duration": round(result.duration, 2),
            })

            status_icon = "✅" if result.status == "success" else "❌"
            print(f"  {status_icon}  [{idx}/{len(agents)}] {name} — "
                  f"{result.status} ({result.duration:.1f}s) "
                  f"→ {len(result.files_created)} file(s)")

        total = time.time() - t0
        passed = sum(1 for r in results if r["status"] == "success")
        print(f"  {'=' * 58}")
        print(f"  Swarm done: {passed}/{len(results)} agents passed "
              f"in {total:.1f}s")
        if bb is not None:
            print(f"  {'─' * 58}")
            print(f"  Blackboard summary:")
            print(bb.summary())
        return results

    def _is_excluded(self, p: Path) -> bool:
        """Return True if *p*'s suffix or relative path should be excluded."""
        if p.suffix in self.suffix_excludes:
            return True
        try:
            # Resolve both sides so Windows 8.3 short-name / casing mismatches
            # (e.g. RUNNER~1 vs runneradmin) don't break the comparison.
            rel = p.resolve().relative_to(self.base_path).as_posix()
        except ValueError:
            return False
        for ex in self.excludes:
            ex_norm = ex.rstrip("/")
            if rel == ex_norm or rel.startswith(ex_norm + "/"):
                return True
        return False

    # ======================================================================
    # Phase 1 — Workspace discovery
    # ======================================================================

    def _discover(self, state: WorkspaceState) -> None:
        _step("discover", f"Scanning {self.base_path}")

        seen: set[Path] = set()
        for pattern in self.includes:
            for p in sorted(self.base_path.glob(pattern)):
                if not p.is_file() or p in seen:
                    continue
                seen.add(p)
                if self._is_excluded(p):
                    continue

                try:
                    sample = self.registry.execute(
                        "file_sampler", file_path=str(p)
                    )
                except Exception:
                    sample = None

                df = DiscoveredFile(
                    path=str(p.relative_to(self.base_path)),
                    extension=p.suffix.lower(),
                    size=p.stat().st_size,
                    sample=sample,
                )
                state.discovered_files.append(df)

                if sample:
                    fmt = sample.get("format") or p.suffix.lower().lstrip(".")
                    _step("discover", f"  {df.path}", f"[{fmt}] {df.size:,} B")
                else:
                    _step("discover", f"  {df.path}", f"{df.size:,} B")

    # ======================================================================
    # Phase 4 — Write-Test-Fix loop
    # ======================================================================

    def _wtf_loop(
        self,
        fixer: Optional[Fixer],
        max_iterations: int,
    ) -> None:
        state = self.state
        if state is None:
            return

        # ── Optional progress bar ──────────────────────────────────────
        _pb = None
        if state.generated_files:
            try:
                from workflow import ProgressBar as _ProgressBar
                _pb = _ProgressBar(total=len(state.generated_files) * max_iterations,
                                   prefix="  WTF")
            except Exception:
                pass

        _wtf_start = time.time()

        while state.iteration < max_iterations and not state.loop_passed:
            state.iteration += 1
            elapsed = time.time() - _wtf_start
            elapsed_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
            _step("test", f"Cycle {state.iteration}/{max_iterations}  [{elapsed_str}]")

            all_passed = True

            for gf in state.generated_files:
                log = self._test_file(gf, state)
                state.test_logs.append(log)

                if log.passed:
                    gf.passed = True
                    gf.iteration = state.iteration
                else:
                    all_passed = False
                    gf.passed = False
                    gf.iteration = state.iteration
                    _step(
                        "fix",
                        gf.path,
                        f"exit {log.returncode}",
                    )

                    # Give the fixer a chance to patch
                    if fixer:
                        try:
                            patches = fixer(log, state, self.registry, self.env)
                        except Exception as exc:
                            _step("fix", f"Fixer crashed: {exc}")
                            print("  [!] Fixer encountered an unexpected error — skipping patch")
                            patches = None
                        if patches:
                            for fpath, old, new in patches:
                                try:
                                    self.registry.execute(
                                        "code_patcher",
                                        file_path=fpath,
                                        content=new,
                                        mode="patch",
                                        old_string=old,
                                    )
                                    _step("fix", f"  patched {fpath}")
                                except (ValueError, FileNotFoundError) as exc:
                                    _step("fix", f"  patch failed: {exc}")
                                    # Fall back to overwrite
                                    self.registry.execute(
                                        "code_patcher",
                                        file_path=fpath,
                                        content=new,
                                        mode="write",
                                    )
                                    _step("fix", f"  re-wrote {fpath}")
                            # Update content in state
                            for fpath, _, new in patches:
                                for g in state.generated_files:
                                    if g.path == fpath:
                                        g.content = new
                    else:
                        _step("fix", "  no fixer — skipping patch")

            # Update progress bar
            if _pb:
                _passed = sum(1 for gf in state.generated_files if gf.passed)
                _failed = sum(1 for gf in state.generated_files if gf.passed is False)
                _pb.update(state.iteration, _passed, _failed)

            if all_passed:
                state.loop_passed = True
                _step("pass", "All generated files passed")
            elif state.iteration >= max_iterations:
                _step("fail", f"Max cycles ({max_iterations}) reached")

        # ── WTF summary ────────────────────────────────────────────
        passed_count = sum(1 for gf in state.generated_files if gf.passed)
        total_count = len(state.generated_files)
        if total_count > 0:
            wtf_elapsed = time.time() - _wtf_start
            wtf_elapsed_str = f"{wtf_elapsed:.1f}s" if wtf_elapsed < 60 else f"{wtf_elapsed/60:.1f}m"
            _step("info", f"WTF summary: {passed_count}/{total_count} passed, "
                          f"{state.iteration} cycle(s), {wtf_elapsed_str}")

        if _pb:
            _passed = sum(1 for gf in state.generated_files if gf.passed)
            _failed = sum(1 for gf in state.generated_files if gf.passed is False)
            _pb.done(_passed, _failed)

    # ======================================================================
    # Test a single file
    # ======================================================================

    def _test_file(
        self,
        gf: GeneratedFile,
        state: WorkspaceState,
    ) -> TestLog:
        """Run *gf* in the agent environment and return a TestLog."""
        try:
            # Resolve relative paths against the workspace base
            abs_path = gf.path
            if not os.path.isabs(gf.path):
                abs_path = str(self.base_path / gf.path)
            proc = self.env.run_file(abs_path)
            rc = proc.returncode
            out = proc.stdout or ""
            err = proc.stderr or ""
        except Exception as exc:
            rc = -1
            out = ""
            err = str(exc)

        log = TestLog(
            file=gf.path,
            iteration=state.iteration,
            returncode=rc,
            stdout=out,
            stderr=err,
        )

        if log.passed:
            _step("pass", f"  {gf.path}  passed")
        else:
            _step("fail", f"  {gf.path}  failed  exit={rc}")
            if err:
                # Show a compact excerpt of the error
                excerpt = err.strip().splitlines()
                for line in excerpt[:8]:
                    _step("info", f"    {line}")

        return log

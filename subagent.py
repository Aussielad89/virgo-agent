"""
subagent — a semi-autonomous agent that executes a goal with its own
tool subset and LLM client, then reports results back.

Designed to be spawned from Orchestrator.swarm() for parallel delegation.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ── Result type ─────────────────────────────────────────────────────


@dataclass
class AgentResult:
    """What a SubAgent produced."""

    name: str
    goal: str
    status: str  # success | failed | skipped
    plan: str = ""
    files_created: list[str] = field(default_factory=list)
    output: str = ""
    error: str = ""
    duration: float = 0.0


# ── SubAgent ────────────────────────────────────────────────────────


class SubAgent:
    """A focused worker with its own LLM client and tool subset.

    Usage::

        agent = SubAgent(name="scanner", goal="Build a port scanner")
        result = agent.run(registry, env)
    """

    def __init__(
        self,
        name: str,
        goal: str,
        *,
        tools: list[str] | None = None,
        planner: Callable | None = None,
        generator: Callable | None = None,
        fixer: Callable | None = None,
        max_iterations: int = 3,
        blackboard: Any = None,  # shared Blackboard
    ) -> None:
        self.name = name
        self.goal = goal
        self.tool_names = tools or [
            "file_sampler",
            "code_patcher",
            "python_runner",
        ]
        self.planner = planner
        self.generator = generator
        self.fixer = fixer
        self.max_iterations = max_iterations
        self.blackboard = blackboard

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self,
        registry: Any,  # ToolRegistry
        env: Any,  # AgentEnvironment
        *,
        verbose: bool = True,
    ) -> AgentResult:
        """Execute the agent's goal and return its result.

        Steps:
            1. LLM-based planning (if a planner is set)
            2. Code generation (if a generator is set)
            3. Write → Test → Fix loop (if a fixer is set)
        """
        t0 = time.time()
        result = AgentResult(name=self.name, goal=self.goal, status="success")
        bb = self.blackboard

        self._log(verbose, f"[{self.name}] Starting — {self.goal}")
        if bb is not None:
            bb.post(f"agent/{self.name}/status", "started", source=self.name, phase="init")

        try:
            # ── Phase 1: Plan ───────────────────────────────────────
            plan = self.goal
            if self.planner:
                self._log(verbose, f"[{self.name}] Planning …")
                plan = self.planner(self.goal, registry=registry)
                result.plan = plan
                self._log(verbose, f"[{self.name}] Plan ready")
                if bb is not None:
                    bb.post(f"agent/{self.name}/plan", plan, source=self.name, phase="plan")

            # ── Phase 2: Generate ───────────────────────────────────
            if self.generator:
                self._log(verbose, f"[{self.name}] Generating …")
                files = self.generator(plan, registry=registry, env=env)
            else:
                self._log(verbose, f"[{self.name}] Generating (fallback) …")
                slug = re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")
                fname = f"{slug}.py"
                content = (
                    f"#!/usr/bin/env python3\n"
                    f"# {self.name} — {self.goal}\n\n"
                    f"def main():\n"
                    f'    print("{self.goal}")\n\n'
                    f"if __name__ == '__main__':\n"
                    f"    main()\n"
                )
                files = [(fname, content)]

            for fpath, content in files:
                if not fpath.endswith(".py"):
                    slug = re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")
                    fpath = f"{slug}.py"
                try:
                    registry.execute(
                        "code_patcher",
                        file_path=fpath,
                        content=content,
                        mode="write",
                    )
                    result.files_created.append(fpath)
                    self._log(verbose, f"[{self.name}]   wrote {fpath}")
                except Exception as exc:
                    self._log(verbose, f"[{self.name}]   write failed {fpath}: {exc}")

            if bb is not None and result.files_created:
                bb.post(
                    f"agent/{self.name}/files",
                    result.files_created,
                    source=self.name,
                    phase="generate",
                )

            # ── Phase 3: WTF loop ───────────────────────────────────
            if result.files_created and self.fixer:
                for iteration in range(1, self.max_iterations + 1):
                    all_passed = True
                    for fpath in result.files_created:
                        ok, out_text, err_text = self._test_file(fpath, env)
                        if not ok:
                            all_passed = False
                            result.output = out_text
                            result.error = err_text
                            self._log(verbose, f"[{self.name}]   {fpath} failed (iter {iteration})")
                            patches = self.fixer(
                                file=fpath,
                                error=err_text,
                                registry=registry,
                                env=env,
                            )
                            if patches:
                                for fp, old, new in patches:
                                    try:
                                        registry.execute(
                                            "code_patcher",
                                            file_path=fp,
                                            content=new,
                                            mode="patch",
                                            old_string=old,
                                        )
                                    except (ValueError, FileNotFoundError):
                                        registry.execute(
                                            "code_patcher",
                                            file_path=fp,
                                            content=new,
                                            mode="write",
                                        )
                            break  # one file at a time
                    if all_passed:
                        self._log(verbose, f"[{self.name}] All files passed")
                        break

        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            self._log(verbose, f"[{self.name}] FAILED: {exc}")
            if bb is not None:
                bb.post(f"agent/{self.name}/status", "failed", source=self.name, phase="done")

        result.duration = time.time() - t0
        self._log(verbose, f"[{self.name}] Done ({result.duration:.1f}s)")
        if bb is not None and result.status == "success":
            bb.post(f"agent/{self.name}/status", "completed", source=self.name, phase="done")
        return result

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _test_file(fpath: str, env: Any) -> tuple[bool, str, str]:
        """Run *fpath* in the env and return (ok, stdout, stderr)."""
        try:
            abs_path = fpath
            if not os.path.isabs(fpath):
                base = getattr(env, "base_path", os.getcwd())
                abs_path = os.path.join(base, fpath)
            proc = env.run_file(abs_path)
            ok = proc.returncode == 0
            return ok, proc.stdout or "", proc.stderr or ""
        except Exception as exc:
            return False, "", str(exc)

    @staticmethod
    def _log(verbose: bool, msg: str) -> None:
        if verbose:
            print(f"  {msg}", flush=True)

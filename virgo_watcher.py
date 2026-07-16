"""
virgo_watcher — file-watch mode that re-triggers the pipeline on changes.

Usage::

    python virgo_watcher.py --dir ./src --goal "keep tests passing"
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon


# ── Change detection ─────────────────────────────────────────────────

class FileWatcher:
    """Polling-based file watcher with debounce.

    Scans *base_path* every *interval* seconds, compares stat mtime/size
    against the previous snapshot, and calls *on_change* when files are
    created or modified (after a quiet *debounce* period).
    """

    def __init__(
        self,
        base_path: str | Path = ".",
        *,
        interval: float = 2.0,
        debounce: float = 1.0,
        exclude: Optional[list[str]] = None,
    ) -> None:
        self.base_path = Path(base_path).resolve()
        self.interval = interval
        self.debounce = debounce
        self.exclude = exclude or ["__pycache__", ".git", ".venv",
                                   "agent_env", ".virgo_memory", ".coverage"]

        self._snapshot: dict[str, tuple[float, int]] = {}  # path → (mtime, size)

    # ── Public API ──────────────────────────────────────────────────

    def start(self, on_change: Callable[[list[str]], None]) -> None:
        """Begin the watch loop.  Calls *on_change(changed_paths)* when
        the filesystem settles after modifications."""
        print(f"{icon('watch')} Watching {self.base_path} "
              f"(poll {self.interval}s, debounce {self.debounce}s)")
        print(f"  Excludes: {', '.join(self.exclude)}")
        print(f"  {'─' * 50}")

        self._snapshot = self._take_snapshot()
        while True:
            try:
                time.sleep(self.interval)
                fresh = self._take_snapshot()
                changes = self._diff(self._snapshot, fresh)

                if changes:
                    # Wait for quiet period (no more changes)
                    quiet_start = time.time()
                    while time.time() - quiet_start < self.debounce:
                        time.sleep(0.2)
                        settled = self._take_snapshot()
                        settled_changes = self._diff(fresh, settled)
                        if settled_changes:
                            changes.update(settled_changes)
                            fresh = settled
                            quiet_start = time.time()

                    self._snapshot = fresh
                    on_change(sorted(changes))
            except KeyboardInterrupt:
                print(f"\n{icon('ok')} Watcher stopped.")
                break

    # ── Internal ────────────────────────────────────────────────────

    def _walk(self) -> list[Path]:
        """Yield all non-excluded file paths under base_path."""
        results: list[Path] = []
        for root_str, dirs, files in os.walk(str(self.base_path)):
            root = Path(root_str)
            # Prune excluded dirs in-place so os.walk skips them
            dirs[:] = [d for d in dirs
                       if d not in self.exclude
                       and not any(p in d for p in self.exclude)]
            for fname in files:
                fpath = root / fname
                if not any(p in str(fpath) for p in self.exclude):
                    results.append(fpath)
        return results

    def _take_snapshot(self) -> dict[str, tuple[float, int]]:
        """Map relative path → (mtime, size)."""
        snap: dict[str, tuple[float, int]] = {}
        for abspath in self._walk():
            try:
                st = abspath.stat()
                rel = str(abspath.relative_to(self.base_path))
                snap[rel] = (st.st_mtime, st.st_size)
            except OSError:
                pass
        return snap

    @staticmethod
    def _diff(
        old: dict[str, tuple[float, int]],
        new: dict[str, tuple[float, int]],
    ) -> dict[str, str]:
        """Return {path: "new"|"modified"} for every changed entry."""
        changes: dict[str, str] = {}
        for path, meta in new.items():
            if path not in old:
                changes[path] = "new"
            elif old[path] != meta:
                changes[path] = "modified"
        return changes


# ── Pipeline trigger ─────────────────────────────────────────────────

def run_pipeline(
    goal: str,
    dir_path: str,
    *,
    use_llm: bool = False,
    max_iterations: int = 3,
    router: Optional[str] = None,
    use_crush: bool = False,
    stream: bool = False,
    auto_approve: bool = True,
) -> None:
    """Execute a single pipeline run on *dir_path*."""
    from tools import ToolRegistry
    from environment import AgentEnvironment
    from orchestrator import Orchestrator

    env = AgentEnvironment(base_path=dir_path)
    registry = ToolRegistry()
    orch = Orchestrator(
        env, registry, base_path=dir_path,
        workspace_excludes=["__pycache__", ".git", ".venv",
                            "agent_env", ".virgo_memory", ".coverage",
                            "dist", "virgo_agent.egg-info"],
    )

    planner = code_gen = fixer = None
    if use_llm or router or use_crush:
        try:
            import main
            if router:
                main.ROUTER_CONFIG = main.router_from_file(router)
            if use_crush and not main.ROUTER_CONFIG:
                main.USE_CRUSH = True
            if stream:
                main.STREAM_OUTPUT = True
            planner = main.my_planner
            code_gen = main.my_generator
            fixer = main.my_fixer
        except Exception as exc:
            print(f"  [watcher] LLM load failed: {exc}")

    state = orch.run(
        goal=goal,
        planner=planner,
        code_gen=code_gen,
        fixer=fixer,
        max_iterations=max_iterations,
        auto_approve=auto_approve,
        run_critic=False,
        auto_depend=False,
    )

    files = [gf.path for gf in state.generated_files]
    print(f"  {icon('done')} Pipeline done — {len(files)} file(s) "
          f"in {state.phase or '?'} phase")


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(
        description="virgo_watcher — file-watch mode",
    )
    p.add_argument("--dir", "-d", default=".",
                   help="Directory to watch (default: .)")
    p.add_argument("--goal", "-g", default="auto-fix broken code",
                   help="Pipeline goal (default: auto-fix broken code)")
    p.add_argument("--interval", "-i", type=float, default=2.0,
                   help="Poll interval in seconds (default: 2.0)")
    p.add_argument("--debounce", type=float, default=1.0,
                   help="Quiet period s after last change (default: 1.0)")
    p.add_argument("--exclude", "-x", action="append", default=[],
                   help="Additional exclude pattern")
    p.add_argument("--iterations", type=int, default=3,
                   help="Max WTF iterations (default: 3)")
    p.add_argument("--llm", action="store_true",
                   help="Use LLM-backed policies")
    p.add_argument("--crush", action="store_true",
                   help="Use Crush CLI backend")
    p.add_argument("--router", default=None,
                   help="Path to router JSON config")
    p.add_argument("--stream", action="store_true",
                   help="Stream LLM output")
    args = p.parse_args()

    exclude_base = ["__pycache__", ".git", ".venv",
                    "agent_env", ".virgo_memory", ".coverage"]
    exclude_base.extend(args.exclude)

    watcher = FileWatcher(
        args.dir,
        interval=args.interval,
        debounce=args.debounce,
        exclude=exclude_base,
    )

    def on_change(changed: list[str]) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n{icon('zap')} [{ts}] Change detected — "
              f"{len(changed)} file(s)")
        for path in changed[:8]:
            status = "🆕" if path.endswith(tuple(".py .txt .json .yaml .md .csv .html .css .js .ts .tsx .jsx".split())) else "📄"
            print(f"    {status} {path}")
        if len(changed) > 8:
            print(f"    ... and {len(changed) - 8} more")
        print()
        run_pipeline(
            args.goal,
            dir_path=str(Path(args.dir).resolve()),
            use_llm=args.llm,
            max_iterations=args.iterations,
            router=args.router,
            use_crush=args.crush,
            stream=args.stream,
        )

    watcher.start(on_change)


if __name__ == "__main__":
    main()

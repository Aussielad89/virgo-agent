"""
virgo_checkpoint — Pipeline checkpoint and resume system.

Saves the full pipeline state after each WTF iteration so crashed
runs can be resumed from the last checkpoint instead of starting over.

Usage (CLI):
    virgo run --goal "build scraper"         # auto-checkpoints
    virgo resume <session>                   # resume from last checkpoint
    virgo checkpoints                        # list all checkpoints
    virgo checkpoint show <session>          # show checkpoint details

Usage (Programmatic):
    from virgo_checkpoint import CheckpointManager
    mgr = CheckpointManager()
    mgr.save(state, "my_run")
    state = mgr.load("my_run")
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).resolve().parent
CHECKPOINT_DIR = HERE / ".virgo_checkpoints"


# ═══════════════════════════════════════════════════════════════════════
# Checkpoint data
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Checkpoint:
    """A serialisable snapshot of pipeline state."""
    session: str
    goal: str
    phase: str
    iteration: int
    max_iterations: int
    loop_passed: bool
    plan: str
    generated_files: list[dict[str, Any]]
    test_logs: list[dict[str, Any]]
    discovered_files: list[dict[str, Any]]
    timestamp: float = 0.0
    elapsed: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        n_files = len(self.generated_files)
        n_passed = sum(1 for f in self.generated_files if f.get("passed"))
        status = "✅ PASSED" if self.loop_passed else "🔄 IN PROGRESS"
        return (
            f"Session:  {self.session}\n"
            f"Goal:     {self.goal[:80]}\n"
            f"Phase:    {self.phase}\n"
            f"Iteration: {self.iteration}/{self.max_iterations}\n"
            f"Files:    {n_files} generated, {n_passed} passed\n"
            f"Status:   {status}\n"
            f"Time:     {self._fmt_elapsed()}\n"
            f"Saved:    {self._fmt_timestamp()}"
        )

    def _fmt_elapsed(self) -> str:
        if self.elapsed < 60:
            return f"{self.elapsed:.1f}s"
        return f"{self.elapsed / 60:.1f}m"

    def _fmt_timestamp(self) -> str:
        if self.timestamp:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))
        return "unknown"


# ═══════════════════════════════════════════════════════════════════════
# Checkpoint manager
# ═══════════════════════════════════════════════════════════════════════

class CheckpointManager:
    """Manages pipeline checkpoints on disk."""

    def __init__(self, checkpoint_dir: Path | str | None = None) -> None:
        self.dir = Path(checkpoint_dir) if checkpoint_dir else CHECKPOINT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session: str) -> Path:
        return self.dir / session

    def _checkpoint_path(self, session: str, iteration: int) -> Path:
        return self._session_dir(session) / f"iter_{iteration:03d}.json"

    def _latest_path(self, session: str) -> Path:
        return self._session_dir(session) / "latest.json"

    # ── Save ────────────────────────────────────────────────────────

    def save(self, state: Any, session: str, elapsed: float = 0.0) -> Path:
        """Save a checkpoint from a WorkspaceState object.

        Parameters
        ----------
        state:
            The orchestrator's WorkspaceState (or any object with matching attrs).
        session:
            Session/run name.
        elapsed:
            Total elapsed time in seconds.

        Returns
        -------
        Path to the saved checkpoint file.
        """
        cp = self._state_to_checkpoint(state, session, elapsed)

        # Save iteration-specific file
        iter_path = self._checkpoint_path(session, cp.iteration)
        iter_path.parent.mkdir(parents=True, exist_ok=True)
        iter_path.write_text(json.dumps(asdict(cp), indent=2, default=str), encoding="utf-8")

        # Update latest symlink (copy)
        latest = self._latest_path(session)
        latest.write_text(json.dumps(asdict(cp), indent=2, default=str), encoding="utf-8")

        log.info("checkpoint: saved iteration %d → %s", cp.iteration, iter_path)
        return iter_path

    def _state_to_checkpoint(self, state: Any, session: str, elapsed: float) -> Checkpoint:
        """Convert a WorkspaceState (or dict) to a Checkpoint."""
        # Check if it's a WorkspaceState dataclass (has GeneratedFile objects, not dicts)
        if hasattr(state, "generated_files") and state.generated_files:
            first_gf = state.generated_files[0]
            if hasattr(first_gf, "path"):  # dataclass objects
                return self._convert_dataclass_state(state, session, elapsed)

        # Otherwise treat as dict-like
        return self._convert_dict_state(state, session, elapsed)

    def _convert_dataclass_state(self, state: Any, session: str, elapsed: float) -> Checkpoint:
        """Convert a WorkspaceState dataclass to a Checkpoint."""
        gen_files = []
        for gf in state.generated_files:
            gen_files.append({
                "path": gf.path,
                "content": gf.content,
                "passed": gf.passed,
                "iteration": gf.iteration,
            })

        test_logs = []
        for tl in state.test_logs:
            test_logs.append({
                "file_path": tl.file_path,
                "passed": tl.passed,
                "returncode": tl.returncode,
                "stdout": tl.stdout[:2000],
                "stderr": tl.stderr[:2000],
            })

        disc_files = []
        for df in state.discovered_files:
            disc_files.append({
                "path": df.path,
                "size": df.size,
                "language": df.language,
            })

        context_clean = {}
        for k, v in (state.context or {}).items():
            try:
                json.dumps(v)
                context_clean[k] = v
            except (TypeError, ValueError):
                context_clean[k] = str(v)

        return Checkpoint(
            session=session,
            goal=state.goal,
            phase=state.phase,
            iteration=state.iteration,
            max_iterations=state.max_iterations,
            loop_passed=state.loop_passed,
            plan=state.plan[:5000],
            generated_files=gen_files,
            test_logs=test_logs,
            discovered_files=disc_files,
            timestamp=time.time(),
            elapsed=elapsed,
            context=context_clean,
        )

    def _convert_dict_state(self, state: Any, session: str, elapsed: float) -> Checkpoint:
        """Convert a dict-based state to a Checkpoint."""
        # If it's already a Checkpoint, just return it with updated elapsed
        if isinstance(state, Checkpoint):
            state.elapsed = elapsed
            state.timestamp = time.time()
            return state

        # Otherwise assume it's a dict
        context_clean = {}
        for k, v in (state.get("context", {}) or {}).items():
            try:
                json.dumps(v)
                context_clean[k] = v
            except (TypeError, ValueError):
                context_clean[k] = str(v)

        return Checkpoint(
            session=session,
            goal=str(state.get("goal", "")),
            phase=str(state.get("phase", "unknown")),
            iteration=int(state.get("iteration", 0)),
            max_iterations=int(state.get("max_iterations", 5)),
            loop_passed=bool(state.get("loop_passed", False)),
            plan=str(state.get("plan", "")),
            generated_files=state.get("generated_files", []),
            test_logs=state.get("test_logs", []),
            discovered_files=state.get("discovered_files", []),
            timestamp=time.time(),
            elapsed=elapsed,
            context=context_clean,
        )

    # ── Load ────────────────────────────────────────────────────────

    def load(self, session: str) -> Checkpoint | None:
        """Load the latest checkpoint for a session."""
        latest = self._latest_path(session)
        if not latest.exists():
            log.warning("checkpoint: no checkpoint found for session '%s'", session)
            return None

        data = json.loads(latest.read_text(encoding="utf-8"))
        return Checkpoint(**data)

    def load_iteration(self, session: str, iteration: int) -> Checkpoint | None:
        """Load a specific iteration's checkpoint."""
        path = self._checkpoint_path(session, iteration)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Checkpoint(**data)

    # ── List ────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all checkpointed sessions."""
        sessions = []
        if not self.dir.exists():
            return sessions

        for session_dir in sorted(self.dir.iterdir()):
            if not session_dir.is_dir():
                continue
            latest = session_dir / "latest.json"
            if not latest.exists():
                continue

            data = json.loads(latest.read_text(encoding="utf-8"))
            cp = Checkpoint(**data)

            # Count iterations
            iter_files = list(session_dir.glob("iter_*.json"))

            sessions.append({
                "session": cp.session,
                "goal": cp.goal[:80],
                "phase": cp.phase,
                "iteration": cp.iteration,
                "max_iterations": cp.max_iterations,
                "loop_passed": cp.loop_passed,
                "n_files": len(cp.generated_files),
                "n_iterations": len(iter_files),
                "elapsed": cp._fmt_elapsed(),
                "saved": cp._fmt_timestamp(),
            })

        return sessions

    # ── Delete ──────────────────────────────────────────────────────

    def delete(self, session: str) -> bool:
        """Delete all checkpoints for a session."""
        session_dir = self._session_dir(session)
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
            log.info("checkpoint: deleted session '%s'", session)
            return True
        return False

    # ── Restore generated files ─────────────────────────────────────

    def restore_files(self, checkpoint: Checkpoint, base_path: Path | str = ".") -> int:
        """Write the generated files from a checkpoint back to disk.

        Returns the number of files restored.
        """
        base = Path(base_path)
        count = 0
        for gf in checkpoint.generated_files:
            fpath = base / gf["path"]
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(gf["content"], encoding="utf-8")
            count += 1
            log.info("checkpoint: restored %s", gf["path"])
        return count


# ═══════════════════════════════════════════════════════════════════════
# Convenience functions
# ═══════════════════════════════════════════════════════════════════════

_default_mgr: CheckpointManager | None = None


def _get_mgr() -> CheckpointManager:
    global _default_mgr
    if _default_mgr is None:
        _default_mgr = CheckpointManager()
    return _default_mgr


def save_checkpoint(state: Any, session: str, elapsed: float = 0.0) -> Path:
    """Save a checkpoint (module-level convenience)."""
    return _get_mgr().save(state, session, elapsed)


def load_checkpoint(session: str) -> Checkpoint | None:
    """Load the latest checkpoint for a session."""
    return _get_mgr().load(session)


def list_checkpoints() -> list[dict[str, Any]]:
    """List all checkpointed sessions."""
    return _get_mgr().list_sessions()

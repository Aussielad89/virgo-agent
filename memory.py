"""
memory — persistence, replay, and feedback memory for virgo.

Saves WorkspaceState to JSON so pipelines can be inspected,
replayed, or continued after a crash.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
MEMORY_DIR = HERE / ".virgo_memory"

# ---------------------------------------------------------------------------
# JSON encoder that handles dataclasses + Path
# ---------------------------------------------------------------------------

class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return {k: v for k, v in asdict(o).items() if v is not None}
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_state(state: Any, name: Optional[str] = None) -> Path:
    """Serialize a WorkspaceState (or any dataclass) to JSON.

    Writes to ``.virgo_memory/<name>.json`` and returns the path.
    If *name* is omitted a timestamp-based name is generated.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not name:
        name = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    path = MEMORY_DIR / f"{name}.json"
    data = json.dumps(state, cls=_Encoder, indent=2, ensure_ascii=False)
    path.write_text(data, encoding="utf-8")
    return path


def load_state(name_or_path: str) -> dict[str, Any]:
    """Load a saved state by run name or full path."""
    path = Path(name_or_path)
    if not path.exists():
        path = MEMORY_DIR / f"{name_or_path}.json"
    if not path.exists():
        raise FileNotFoundError(f"No saved state at {name_or_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions() -> list[dict[str, Any]]:
    """Return metadata for all saved sessions, newest first."""
    if not MEMORY_DIR.exists():
        return []
    sessions = []
    for p in sorted(MEMORY_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sessions.append({
                "name": p.stem,
                "path": str(p),
                "goal": data.get("goal", "")[:100],
                "phase": data.get("phase", ""),
                "loop_passed": data.get("loop_passed"),
                "iteration": data.get("iteration", 0),
                "generated": len(data.get("generated_files", [])),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            })
        except Exception:
            sessions.append({"name": p.stem, "path": str(p), "error": "corrupt"})
    return sessions


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay(
    name_or_path: str,
    orch: Any,  # Orchestrator instance
    env: Any,   # AgentEnvironment
    registry: Any,  # ToolRegistry
    *,
    planner: Any = None,
    code_gen: Any = None,
    fixer: Any = None,
    max_iterations: Optional[int] = None,
) -> Any:
    """Re-run a saved pipeline from its persisted state.

    Loads the saved goal and discovered files, then re-executes
    generation and the WTF loop.  Useful for iterating on code_gen
    or fixer policies without re-discovering files.
    """
    data = load_state(name_or_path)

    # Restore goal
    goal = data.get("goal", "")

    # Build a partial WorkspaceState with discovered files pre-loaded
    from orchestrator import WorkspaceState, DiscoveredFile, GeneratedFile
    state = WorkspaceState(goal=goal, base_path=data.get("base_path", "."))

    for df_dict in data.get("discovered_files", []):
        state.discovered_files.append(DiscoveredFile(**df_dict))

    for gf_dict in data.get("generated_files", []):
        state.generated_files.append(GeneratedFile(**gf_dict))

    # Patch the orchestrator's state so discovery is skipped
    orch.state = state
    state.phase = "planning"

    # Re-run from planning onward
    plan = planner(goal, state) if planner else goal
    state.plan = plan

    if code_gen:
        state.phase = "generating"
        files = code_gen(plan, state, registry, env)
        for fpath, content in files:
            registry.execute("code_patcher", file_path=fpath, content=content, mode="write")
            state.generated_files.append(GeneratedFile(path=fpath, content=content))

    state.phase = "testing"
    # Run WTF loop directly
    orch._wtf_loop(fixer, max_iterations or state.max_iterations)
    state.phase = "complete"

    save_state(state, name=f"{Path(name_or_path).stem}_replay")
    return state


# ---------------------------------------------------------------------------
# Feedback memory — learn from successful fixes
# ---------------------------------------------------------------------------

class FeedbackMemory:
    """Store and retrieve (error_pattern → fix) pairs."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or MEMORY_DIR / "feedback.json"
        self._data: list[dict[str, str]] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data[-200:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def record(self, error_snippet: str, patch_old: str, patch_new: str, success: bool = True) -> None:
        """Store a fix that resolved an error."""
        if not success:
            return
        self._data.append({
            "error": error_snippet[:500],
            "old": patch_old[:500],
            "new": patch_new[:500],
            "count": 1,
        })
        self.save()

    def lookup(self, error_snippet: str) -> Optional[dict[str, str]]:
        """Return a matching fix if one exists."""
        for entry in reversed(self._data):
            if entry["error"] in error_snippet or error_snippet in entry["error"]:
                return entry
        return None

    def __len__(self) -> int:
        return len(self._data)

"""
approval — human-in-the-loop gate for risky agent tool calls.

The sandbox allowlist is the *static* safety net; this is the *dynamic*
one. When an agent wants to run a tool at or above a risk threshold, the
gate asks a human before the tool executes. The gate is hook-based so the
desktop GUI can install a dialog-based hook while the CLI uses a simple
y/n prompt — both go through the same :class:`ApprovalGate` API.

Usage::

    from approval import ApprovalGate, InteractiveApproval
    registry.approval_gate = ApprovalGate(hook=InteractiveApproval())
    registry.approval_threshold = RISK_MEDIUM   # from tools_core

The agent then sees::

    ERROR: tool 'shell' requires approval and was denied

whenever a human says no, and the ReAct loop reacts to that observation.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

# ── Risk levels mirror tools_core so this module stands alone ─────────
RISK_UNKNOWN = 0
RISK_SAFE = 1
RISK_LOW = 2
RISK_MEDIUM = 3
RISK_HIGH = 4
RISK_CRITICAL = 5

_RISK_LABELS = {
    RISK_UNKNOWN: "unknown",
    RISK_SAFE: "safe",
    RISK_LOW: "low",
    RISK_MEDIUM: "medium",
    RISK_HIGH: "high",
    RISK_CRITICAL: "critical",
}

ApprovalHook = Callable[[str, str, int], bool]  # (tool, args, risk) -> allowed


class ApprovalGate:
    """Decides whether a tool call may proceed, via a pluggable hook.

    With no hook installed the gate is a no-op that allows everything,
    so enabling it is always safe in environments without a human.
    """

    def __init__(self, hook: ApprovalHook | None = None) -> None:
        self._hook = hook

    def install(self, hook: ApprovalHook) -> None:
        """Replace the decision hook."""
        self._hook = hook

    def approve(self, tool: str, args: str, risk: int) -> bool:
        """Return True when *tool* may run, False when a human denied it."""
        hook = self._hook or get_global_hook()
        if hook is None:
            return True
        try:
            return bool(hook(tool, args, int(risk)))
        except Exception:  # pragma: no cover - a broken hook must fail closed
            return False

    def __call__(self, tool: str, args: str, risk: int) -> bool:
        return self.approve(tool, args, risk)


# ── Global hook (the desktop registers a dialog here) ─────────────────

_GLOBAL_HOOK: ApprovalHook | None = None


def set_global_hook(hook: ApprovalHook | None) -> None:
    """Install the process-wide approval hook (e.g. a desktop dialog)."""
    global _GLOBAL_HOOK
    _GLOBAL_HOOK = hook


def get_global_hook() -> ApprovalHook | None:
    """Return the process-wide approval hook, if any."""
    return _GLOBAL_HOOK


# ── Terminal interactive approval ──────────────────────────────────────


class InteractiveApproval:
    """Terminal y/n prompt with per-tool 'always/never' memory.

    Answers are remembered for the lifetime of the object; use
    ``remember=False`` to re-ask every time.
    """

    def __init__(self, remember: bool = True) -> None:
        self.remember = remember
        self._decisions: dict[str, bool] = {}

    def __call__(self, tool: str, args: str, risk: int) -> bool:
        if tool in self._decisions:
            return self._decisions[tool]
        label = _RISK_LABELS.get(risk, str(risk))
        snippet = (args or "").strip().replace("\n", " ")[:90]
        prompt = f"[approval] {tool} ({label}){' - ' + snippet if snippet else ''} [y/N/a/never] "
        try:
            ans = (input(prompt) or "n").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if ans in ("y", "yes"):
            return True
        if ans in ("a", "always"):
            self._decisions[tool] = True
            return True
        if ans in ("n", "never"):
            self._decisions[tool] = False
            return False
        return False


# ── Auto-approval (headless / CI / tests) ──────────────────────────────


class AutoApproval:
    """Always allows (optionally only up to a risk cap). Useful for CI."""

    def __init__(self, max_risk: int = RISK_SAFE) -> None:
        self.max_risk = max_risk

    def __call__(self, tool: str, args: str, risk: int) -> bool:
        return risk <= self.max_risk


# ── ToolRegistry integration helper ────────────────────────────────────


def attach_to_registry(registry: Any, gate: ApprovalHook | ApprovalGate | None,
                       threshold: int = RISK_MEDIUM) -> Any:
    """Attach *gate* to a ToolRegistry so ``call()`` enforces approval.

    Accepts either an ApprovalGate, a plain callable, or None (detaches).
    """
    if gate is None:
        registry.approval_gate = None
        registry.approval_threshold = threshold
        return registry
    if not isinstance(gate, ApprovalGate):
        gate = ApprovalGate(hook=gate)
    registry.approval_gate = gate
    registry.approval_threshold = threshold
    return registry


def risk_of_tool(registry: Any, tool: str) -> int:
    """Best-effort risk lookup for *tool* (0 = unknown)."""
    for attr in ("risk_of",):
        fn = getattr(registry, attr, None)
        if callable(fn):
            try:
                return int(fn(tool))
            except Exception:  # pragma: no cover
                return RISK_UNKNOWN
    return RISK_UNKNOWN

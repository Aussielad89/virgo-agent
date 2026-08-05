"""
budget — per-run and per-day cost tracking with overrun alerts.

Tracks estimated token usage and cost for agent runs so long-running
autonomy never silently burns budget. Estimates tokens as ``chars / 4``
(a common heuristic) and cost per model from an optional price table;
local models (Ollama/ornith) cost nothing by default.

Alerts: when spend crosses the budget limit (env ``VIRGO_BUDGET_LIMIT``
or the constructor arg), a warning is logged, the alert hook fires, and
``check()`` starts returning ``over=True``.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from _log import log

DEFAULT_RECORDS = Path(".virgo_memory") / "budget.jsonl"
DEFAULT_LIMIT = float(os.getenv("VIRGO_BUDGET_LIMIT", "0") or 0)  # 0 = unlimited

# Optional $/1M tokens for known cloud models; anything not listed and
# not local defaults to a conservative 0 (local inference).
_COST_PER_MT: dict[str, float] = {
    "gpt-4": 30.0,
    "gpt-4o": 5.0,
    "gpt-4o-mini": 0.5,
    "gpt-3.5": 1.5,
    "claude-3.5": 3.0,
    "claude-3.7": 3.0,
    "claude-sonnet": 3.0,
    "claude-opus": 15.0,
    "deepseek": 0.3,
    "gemini": 2.5,
    "llama-3": 0.6,
    "mistral": 0.4,
}

_LOCAL_MARKERS = ("ollama", "ornith", "qwen", "llama", "phi", "gemma", "mistral", "local")


def _is_local(model: str) -> bool:
    low = (model or "").lower()
    return any(m in low for m in _LOCAL_MARKERS)


def _estimate_cost(model: str, chars: int) -> float:
    """Dollar cost for *chars* of text through *model* (0 for local)."""
    if _is_local(model):
        return 0.0
    low = (model or "").lower()
    per_mt = next((c for k, c in _COST_PER_MT.items() if k in low), 0.0)
    tokens = max(0, chars) / 4.0
    return tokens / 1_000_000 * per_mt


class BudgetTracker:
    """Append-only spend ledger with a configurable daily limit."""

    def __init__(
        self,
        records_path: str | Path | None = None,
        limit: float | None = None,
        alert_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.records_path = Path(records_path) if records_path else DEFAULT_RECORDS
        self.limit = float(limit) if limit is not None else DEFAULT_LIMIT
        self.alert_hook = alert_hook
        self._records: list[dict[str, Any]] = []
        self._over_alerted = False
        self._load()

    # ── persistence ──────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.records_path.exists():
            return
        try:
            for line in self.records_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    self._records.append(rec)
        except OSError as exc:  # pragma: no cover
            log.warning("budget: cannot read %s: %s", self.records_path, exc)

    def _persist(self, rec: dict[str, Any]) -> None:
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── spending ─────────────────────────────────────────────────────
    def spend(
        self,
        model: str,
        text: str = "",
        chars: int | None = None,
        goal: str = "",
    ) -> dict[str, Any]:
        """Record estimated usage for *text* (or explicit *chars*).

        Returns the ledger entry; call :meth:`check` to see the verdict.
        """
        n_chars = chars if chars is not None else len(text or "")
        cost = _estimate_cost(model, n_chars)
        today = datetime.now(UTC).date().isoformat()
        rec = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "day": today,
            "model": model,
            "chars": n_chars,
            "estimated_tokens": int(n_chars / 4),
            "cost": round(cost, 6),
            "goal": (goal or "")[:120],
        }
        self._records.append(rec)
        self._persist(rec)
        self._maybe_alert()
        return rec

    # ── status ───────────────────────────────────────────────────────
    def _today(self) -> str:
        return datetime.now(UTC).date().isoformat()

    def day_spend(self, day: str | None = None) -> tuple[float, int]:
        """Return (cost, estimated_tokens) for a day (default: today)."""
        day = day or self._today()
        cost = sum(r.get("cost", 0.0) for r in self._records if r.get("day") == day)
        tokens = sum(r.get("estimated_tokens", 0) for r in self._records if r.get("day") == day)
        return cost, tokens

    def check(self) -> dict[str, Any]:
        """Verdict: {cost, tokens, limit, remaining, over, pct}."""
        cost, tokens = self.day_spend()
        over = bool(self.limit and cost >= self.limit)
        return {
            "cost": round(cost, 4),
            "tokens": tokens,
            "limit": self.limit,
            "remaining": round(max(0.0, self.limit - cost), 4) if self.limit else None,
            "over": over,
            "pct": round(100.0 * cost / self.limit, 1) if self.limit else 0.0,
            "day": self._today(),
        }

    def set_limit(self, limit: float) -> None:
        """Update the daily budget limit."""
        self.limit = float(limit)
        self._over_alerted = False

    def status_text(self) -> str:
        """One-line human summary."""
        v = self.check()
        limit = f" / ${v['limit']:.2f}" if v["limit"] else " (unlimited)"
        state = "OVER BUDGET!" if v["over"] else "ok"
        return (
            f"budget {state}: ${v['cost']:.4f}{limit} "
            f"({v['tokens']} est. tokens, {v['pct']:.0f}%)"
        )

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Newest spend entries first."""
        return list(reversed(self._records[-limit:]))

    def _maybe_alert(self) -> None:
        v = self.check()
        if v["over"] and not self._over_alerted:
            self._over_alerted = True
            msg = f"budget alert: ${v['cost']:.4f} spent, limit ${v['limit']:.2f}"
            log.warning("budget: %s", msg)
            if self.alert_hook is not None:
                try:
                    self.alert_hook(msg)
                except Exception:  # pragma: no cover
                    pass


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: BudgetTracker | None = None


def get_budget(
    records_path: str | Path | None = None,
    limit: float | None = None,
) -> BudgetTracker:
    """Lazy process-wide BudgetTracker singleton."""
    global _INSTANCE
    if records_path is not None or limit is not None:
        _INSTANCE = BudgetTracker(records_path, limit)
    elif _INSTANCE is None:
        _INSTANCE = BudgetTracker()
    return _INSTANCE

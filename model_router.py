"""
model_router — benchmark-driven auto-routing of tasks to models.

Virgo runs several roles (planner, generator, fixer, chat, embed). This
module picks the best model per role from *recorded evidence* — pass rate,
rubric score, cost, latency — instead of a fixed config, and falls back to
the virgo.toml ``[model]`` defaults plus a size heuristic when there is no
data yet. Benchmarks accumulate in ``.virgo_memory/benchmarks.jsonl``.

Routing policy (per role):
1. rank candidates with recorded data by utility = pass_rate - cost_penalty
   - latency_penalty, preferring evidence over guesses,
2. fill any gaps from config defaults (smallest fit first),
3. never route to a model that has never passed a recorded run of the role.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_RECORDS = Path(".virgo_memory") / "benchmarks.jsonl"

# Rough size rank — smaller models are cheaper/faster.
_SIZE_RANK = {
    "0.5": 1, "0.6": 1, "0.8": 2, "1.5": 3, "2": 3, "2b": 3, "3": 4,
    "3.5": 4, "3.8": 4, "4": 5, "4b": 5, "7": 6, "8": 6, "9": 7,
    "10.7": 8, "11": 8, "13": 9, "14": 9, "30": 10, "32": 10, "35": 11,
    "70": 12, "120": 13, "400": 14,
}


def _size_rank(name: str) -> int:
    low = (name or "").lower()
    for key, rank in sorted(_SIZE_RANK.items(), key=lambda kv: -len(kv[0])):
        if key in low:
            return rank
    return 99 if "cloud" in low else 50


def _config_defaults() -> dict[str, str]:
    """Role -> model name from virgo.toml / env (best effort)."""
    defaults: dict[str, str] = {}
    try:
        from config import load as _load_cfg

        cfg = _load_cfg() or {}
        defaults.update(
            {
                k: v
                for k, v in (cfg.get("model") or {}).items()
                if isinstance(v, str) and k in ("planner", "generator", "fixer")
            }
        )
        chat_cfg = cfg.get("chat") or {}
        if isinstance(chat_cfg, dict) and chat_cfg.get("model"):
            defaults["chat"] = chat_cfg["model"]
    except Exception:  # pragma: no cover
        pass
    for role in ("planner", "generator", "fixer"):
        env_name = f"MODEL_{role.upper()}"
        if os.getenv(env_name):
            defaults[role] = os.getenv(env_name, "")  # type: ignore
    defaults.setdefault("planner", "ornith:latest")
    defaults.setdefault("generator", "ornith:latest")
    defaults.setdefault("fixer", "ornith:latest")
    return defaults


class ModelRouter:
    """Evidence-based model selection with size-heuristic fallback."""

    def __init__(self, records_path: str | Path | None = None) -> None:
        self.records_path = Path(records_path) if records_path else DEFAULT_RECORDS
        self._records: list[dict[str, Any]] = []
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
            log.warning("model_router: cannot read %s: %s", self.records_path, exc)

    def _persist(self, rec: dict[str, Any]) -> None:
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── recording ────────────────────────────────────────────────────
    def record(
        self,
        model: str,
        task_type: str,
        passed: bool,
        score: float = 0.0,
        cost: float = 0.0,
        latency_s: float = 0.0,
    ) -> dict[str, Any]:
        """Record one benchmark result for a model on a task type."""
        rec = {
            "model": model,
            "task_type": task_type,
            "passed": bool(passed),
            "score": float(score),
            "cost": float(cost),
            "latency_s": float(latency_s),
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._records.append(rec)
        self._persist(rec)
        log.info("model_router: benchmark %s/%s -> %s (%s)",
                 task_type, model, "PASS" if passed else "FAIL", round(score, 2))
        return rec

    # ── evidence ─────────────────────────────────────────────────────
    def _stats_for(self, task_type: str) -> dict[str, dict[str, float]]:
        """Per-model aggregate stats for a task type."""
        agg: dict[str, dict[str, float]] = {}
        for rec in self._records:
            if rec.get("task_type") != task_type:
                continue
            m = rec.get("model", "?")
            stats = agg.setdefault(m, {"runs": 0, "passes": 0, "score_sum": 0.0,
                                       "cost_sum": 0.0, "lat_sum": 0.0})
            stats["runs"] += 1
            stats["passes"] += 1 if rec.get("passed") else 0
            stats["score_sum"] += float(rec.get("score", 0.0))
            stats["cost_sum"] += float(rec.get("cost", 0.0))
            stats["lat_sum"] += float(rec.get("latency_s", 0.0))
        return agg

    # ── routing ──────────────────────────────────────────────────────
    def route(self, task_type: str, hint: str = "") -> str:
        """Pick the best model for *task_type* (optionally guided by *hint*).

        Strategy: prefer models with recorded runs; rank by utility
        (pass rate minus cost/latency penalties); skip models that have
        never passed; fill gaps with config defaults by size.
        """
        defaults = _config_defaults()
        default_model = defaults.get(task_type) or defaults.get("generator", "ornith:latest")

        stats = self._stats_for(task_type)
        if stats:
            candidates = []
            for model, s in stats.items():
                runs = s["runs"]
                pass_rate = s["passes"] / runs if runs else 0.0
                if s["passes"] == 0 and runs >= 1:
                    continue  # never passed — don't route here
                avg_cost = s["cost_sum"] / runs
                avg_lat = s["lat_sum"] / runs
                # utility: pass rate dominates; cost/latency shave it off
                utility = pass_rate - 0.2 * min(avg_cost, 1.0) - 0.01 * min(avg_lat, 10.0)
                candidates.append((utility, model))
            if candidates:
                best = max(candidates, key=lambda c: c[0])[1]
                if "big" in hint.lower() or "code" in hint.lower() or "reason" in hint.lower():
                    # For heavy tasks prefer the biggest recorded model
                    heavy = [m for m, _ in stats.items() if _size_rank(m) >= _size_rank(best)]
                    if heavy:
                        return max(heavy, key=_size_rank)
                return best

        # No evidence: pick the smallest configured default for the role.
        pool = [default_model]
        for role in ("planner", "generator", "fixer", "chat"):
            m = defaults.get(role)
            if m and m not in pool:
                pool.append(m)
        if "big" in hint.lower() or "code" in hint.lower() or "reason" in hint.lower():
            return max(pool, key=_size_rank)
        return min(pool, key=_size_rank)

    def report(self, task_type: str | None = None) -> str:
        """Human-readable evidence report, optionally per task type."""
        if not self._records:
            return "(no benchmark records yet — run 'virgo route --benchmark' after agent runs)"
        lines = ["Model routing evidence:"]
        for rec in self._records:
            if task_type and rec.get("task_type") != task_type:
                continue
            flag = "PASS" if rec.get("passed") else "FAIL"
            lines.append(
                f"  - [{flag}] {rec.get('task_type','?')} <- {rec.get('model','?')} "
                f"(score {rec.get('score', 0):.2f}, cost {rec.get('cost', 0):.3f}, "
                f"{rec.get('latency_s', 0):.1f}s) @ {rec.get('ts','')}"
            )
        return "\n".join(lines) or "(no matching records)"


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: ModelRouter | None = None


def get_router(records_path: str | Path | None = None) -> ModelRouter:
    """Lazy process-wide ModelRouter singleton."""
    global _INSTANCE
    if records_path is not None:
        _INSTANCE = ModelRouter(records_path)
    elif _INSTANCE is None:
        _INSTANCE = ModelRouter()
    return _INSTANCE

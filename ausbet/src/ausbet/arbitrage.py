"""Arbitrage, dutching and hedging maths.

Arbitrage ("surebet") exists when the best odds available for every outcome
of a market imply probabilities that sum to less than 100% — i.e. the market
has negative overround. Splitting stakes across bookmakers then locks a
guaranteed profit regardless of result.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def overround(odds: list[float]) -> float:
    """Sum of implied probabilities across outcomes (e.g. 1.03 = 103%)."""
    if not odds:
        raise ValueError("need at least one odds value")
    return sum(1.0 / o for o in odds)


def is_arbitrage(odds: list[float], tolerance: float = 1e-9) -> bool:
    """True when the outcome set has a guaranteed-profit structure."""
    return overround(odds) < 1.0 - tolerance


@dataclass
class StakingPlan:
    """Equal-return stake split across a set of outcomes."""

    odds: list[float]
    stakes: list[float] = field(default_factory=list)
    total: float = 0.0
    guaranteed_return: float = 0.0
    profit: float = 0.0
    roi_pct: float = 0.0
    overround: float = 0.0
    is_arb: bool = False

    def __post_init__(self) -> None:
        if not self.stakes:
            raise ValueError("stakes not computed")


def _split(odds: list[float], total: float) -> StakingPlan:
    """Split `total` across outcomes so every outcome returns the same amount."""
    if not odds:
        raise ValueError("need at least one odds value")
    if any(o < 1.0 for o in odds):
        raise ValueError("all odds must be >= 1.0")
    if total <= 0:
        raise ValueError(f"total must be > 0, got {total}")
    s = sum(1.0 / o for o in odds)
    return_stake = total / s
    stakes = [round(return_stake / o, 2) for o in odds]
    # Re-derive the return from the rounded stakes for honest accounting.
    guaranteed = min(stakes[i] * odds[i] for i in range(len(odds)))
    return StakingPlan(
        odds=list(odds),
        stakes=stakes,
        total=round(total, 2),
        guaranteed_return=round(guaranteed, 2),
        profit=round(guaranteed - total, 2),
        roi_pct=round((guaranteed - total) / total * 100.0, 2),
        overround=s,
        is_arb=s < 1.0,
    )


def arbitrage_stakes(odds: list[float], total: float = 100.0) -> StakingPlan:
    """Stake split for a 2+ way arbitrage. Raises if no arbitrage exists."""
    plan = _split(odds, total)
    if not plan.is_arb:
        raise ValueError(
            f"no arbitrage: implied probabilities sum to {plan.overround * 100:.2f}% "
            f"(need < 100%)"
        )
    return plan


def dutch_stakes(odds: list[float], total: float = 100.0) -> StakingPlan:
    """Equal-profit dutch across any set of outcomes (no arbitrage required)."""
    return _split(odds, total)


def hedge_stake(back_odds: float, back_stake: float, lay_odds: float) -> tuple[float, float]:
    """Equal-profit hedge: lay stake + locked profit.

    Back selection at `back_odds` with `back_stake`; lay at `lay_odds`.
    Returns (lay_stake, guaranteed_profit).
    """
    if back_odds <= 1.0 or lay_odds <= 1.0:
        raise ValueError("back and lay odds must be > 1.0")
    if back_stake <= 0:
        raise ValueError(f"back_stake must be > 0, got {back_stake}")
    back_profit = back_stake * (back_odds - 1.0)
    lay_stake = back_profit / (lay_odds - 1.0)
    guaranteed = back_profit - lay_stake
    return round(lay_stake, 2), round(guaranteed, 2)

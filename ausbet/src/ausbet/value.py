"""Value betting maths: expected value, edge and fair odds."""

from __future__ import annotations

from dataclasses import dataclass

from ausbet.bankroll import kelly_fraction
from ausbet.odds import parse


def expected_value(decimal: float, prob_est: float) -> float:
    """Expected profit per $1 staked. Positive = value bet.

    EV = odds * p - 1
    """
    d = float(decimal)
    p = float(prob_est)
    if not 0.0 < p < 1.0:
        raise ValueError(f"prob_est must be in (0, 1), got {p}")
    return round(d * p - 1.0, 6)


def edge_pct(decimal: float, prob_est: float) -> float:
    """Edge as a percentage of stake."""
    return expected_value(decimal, prob_est) * 100.0


def fair_odds(prob_est: float) -> float:
    """Break-even (fair) decimal odds for a probability."""
    p = float(prob_est)
    if not 0.0 < p < 1.0:
        raise ValueError(f"prob_est must be in (0, 1), got {p}")
    return round(1.0 / p, 4)


def is_value(decimal: float, prob_est: float) -> bool:
    """True when the bet has positive expected value."""
    return expected_value(decimal, prob_est) > 0.0


@dataclass
class ValuePick:
    """One value-betting candidate from a market scan."""

    selection: str
    odds: float
    prob_est: float
    ev_per_unit: float
    edge_pct: float
    kelly_fraction: float

    @property
    def is_value(self) -> bool:
        return self.ev_per_unit > 0.0


def scan_market(
    selections: list[tuple[str, str | float]], probs: dict[str, float]
) -> list[ValuePick]:
    """Scan a market's selections [(name, odds), ...] against estimated
    probabilities {name: p}. Returns a ValuePick per selection, sorted by EV."""
    picks: list[ValuePick] = []
    for name, odds in selections:
        d = parse(odds)
        p = probs.get(name)
        if p is None:
            continue
        ev = expected_value(d, p)
        picks.append(
            ValuePick(
                selection=name,
                odds=d,
                prob_est=p,
                ev_per_unit=ev,
                edge_pct=ev * 100.0,
                kelly_fraction=kelly_fraction(d, p),
            )
        )
    return sorted(picks, key=lambda x: x.ev_per_unit, reverse=True)

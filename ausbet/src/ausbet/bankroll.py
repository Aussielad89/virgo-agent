"""Bankroll management and staking strategies.

Strategies:
    kelly      Full / fractional Kelly criterion — optimal long-run growth,
               requires an edge. Returns 0 when there is no edge.
    flat       Fixed dollar amount per bet.
    percent    Fixed percentage of the current bankroll.
"""

from __future__ import annotations

from ausbet.odds import parse

STRATEGIES = ("kelly", "flat", "percent")


def kelly_fraction(decimal: float, prob_est: float) -> float:
    """Full-Kelly fraction of bankroll to stake (0..1, clamped at 0).

    f* = (b*p - q) / b  where b = decimal-1, q = 1-p.
    Returns 0.0 when the bet has no positive expected value.
    """
    d = float(decimal)
    p = float(prob_est)
    if not 0.0 < p < 1.0:
        raise ValueError(f"prob_est must be in (0, 1), got {p}")
    b = d - 1.0
    if b <= 0.0:
        return 0.0
    f = (b * p - (1.0 - p)) / b
    return max(0.0, f)


def kelly_stake(
    decimal: float,
    prob_est: float,
    bankroll: float,
    fraction: float = 0.25,
) -> float:
    """(Default quarter-Kelly) stake in dollars, 2dp. 0.0 when no edge."""
    f = kelly_fraction(decimal, prob_est)
    if f <= 0.0:
        return 0.0
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    if bankroll < 0:
        raise ValueError(f"bankroll must be >= 0, got {bankroll}")
    return round(bankroll * f * fraction, 2)


def flat_stake(amount: float) -> float:
    """Flat staking: same dollar amount every bet."""
    if amount <= 0:
        raise ValueError(f"stake must be > 0, got {amount}")
    return round(float(amount), 2)


def percent_stake(bankroll: float, pct: float) -> float:
    """Percentage staking: pct% of the current bankroll."""
    if bankroll < 0:
        raise ValueError(f"bankroll must be >= 0, got {bankroll}")
    if not 0.0 < pct <= 100.0:
        raise ValueError(f"pct must be in (0, 100], got {pct}")
    return round(bankroll * pct / 100.0, 2)


def suggest_stake(
    strategy: str,
    bankroll: float,
    decimal: float | None = None,
    prob_est: float | None = None,
    amount: float | None = None,
    pct: float | None = None,
    kelly_fraction: float = 0.25,
) -> float:
    """Dispatch to a staking strategy by name."""
    strategy = strategy.lower()
    if strategy == "kelly":
        if decimal is None or prob_est is None:
            raise ValueError("kelly strategy requires --odds and --prob")
        return kelly_stake(parse(decimal), prob_est, bankroll, kelly_fraction)
    if strategy == "flat":
        if amount is None:
            raise ValueError("flat strategy requires --amount")
        return flat_stake(amount)
    if strategy == "percent":
        if pct is None:
            raise ValueError("percent strategy requires --pct")
        return percent_stake(bankroll, pct)
    raise ValueError(f"unknown strategy {strategy!r}; one of {', '.join(STRATEGIES)}")

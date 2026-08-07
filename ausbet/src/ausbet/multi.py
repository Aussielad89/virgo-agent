"""Multi / parlay / racing-special fairness: stacked-margin analysis.

Bookmakers build multis by multiplying the odds of each leg — and each leg
carries its own margin (overround), so the *combined* margin stacks. The
practical question for a punter is simpler: is the multi price they're
offering better or worse than placing the same legs as singles at the best
available price? This module answers that, and — when you supply your own
probabilities — whether the multi has positive expected value at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ausbet.odds import parse


@dataclass
class MultiLeg:
    """One leg of a multi, priced at the best single odds you can get."""

    name: str
    odds: float  # decimal


@dataclass
class MultiAnalysis:
    """Fair-price and value analysis for one multi."""

    legs: list[MultiLeg]
    singles_price: float    # product of single odds — break-even vs placing the legs yourself
    combined_implied: float  # product of 1/odds — the bookie-margin implied prob of the multi
    offer: float | None     # the bookie's multi price, when given
    stake: float
    diff_pct: float | None  # (offer - singles) / singles * 100; negative = stacked-margin tax
    probs: dict[str, float] | None = None
    model_fair: float | None = None  # 1 / product(p_i) — true no-margin fair price
    model_ev: float | None = None    # offer * product(p_i) - 1 — EV per $ staked

    @property
    def verdict(self) -> str:
        if self.offer is None:
            return (
                f"no offer given — the fair price of this multi as singles is "
                f"{self.singles_price:.2f} (take the best single price per leg)"
            )
        if self.diff_pct is not None and self.diff_pct < 0:
            line = (
                f"the multi pays {abs(self.diff_pct):.1f}% LESS than placing the "
                f"singles at best price — stacked bookie margin; the singles are the better bet"
            )
        else:
            line = (
                f"the multi pays {self.diff_pct:+.1f}% vs the singles — a genuine "
                f"boost, take the multi"
            )
        if self.model_ev is not None:
            tag = "VALUE" if self.model_ev > 0 else "no value"
            line += f" | vs your model: EV {self.model_ev:+.3f}/$ ({tag}, fair {self.model_fair:.2f})"
        return line


def analyze_multi(
    legs: list[tuple[str, str | float]],
    offer: float | None = None,
    stake: float = 10.0,
    probs: dict[str, float] | None = None,
) -> MultiAnalysis:
    """Analyse a multi vs its singles.

    ``legs`` is [(name, best single decimal odds), ...] — at least two legs.
    ``offer`` is the bookie's multi price; ``probs`` optionally maps leg names
    to your own win probabilities (0..1) for a true EV read.
    """
    if len(legs) < 2:
        raise ValueError("a multi needs at least 2 legs")
    parsed: list[MultiLeg] = []
    for name, o in legs:
        d = parse(o)
        parsed.append(MultiLeg(name=name.strip(), odds=d))
    singles = 1.0
    implied = 1.0
    for leg in parsed:
        singles *= leg.odds
        implied *= 1.0 / leg.odds
    singles = round(singles, 4)
    implied = round(implied, 6)

    diff: float | None = None
    if offer is not None:
        if offer < 1.0:
            raise ValueError(f"offer must be >= 1.0, got {offer}")
        diff = round((offer - singles) / singles * 100.0, 2)

    model_fair: float | None = None
    model_ev: float | None = None
    if probs is not None:
        missing = [leg.name for leg in parsed if leg.name not in probs]
        if missing:
            raise ValueError(f"no probability given for leg(s): {', '.join(missing)}")
        p_product = 1.0
        for leg in parsed:
            p = probs[leg.name]
            if not 0.0 < p < 1.0:
                raise ValueError(f"prob for {leg.name!r} must be in (0, 1), got {p}")
            p_product *= p
        model_fair = round(1.0 / p_product, 4)
        if offer is not None:
            model_ev = round(offer * p_product - 1.0, 6)

    return MultiAnalysis(
        legs=parsed,
        singles_price=singles,
        combined_implied=implied,
        offer=round(offer, 2) if offer is not None else None,
        stake=stake,
        diff_pct=diff,
        probs=probs,
        model_fair=model_fair,
        model_ev=model_ev,
    )

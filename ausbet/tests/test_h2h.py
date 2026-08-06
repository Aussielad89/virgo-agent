"""Bookie-vs-bookie head-to-head scan tests (no network)."""

from __future__ import annotations

import pytest

from ausbet.compare import MarketOdds, Outcome, head_to_head


def _market_outcomes(sport: str, event: str, bookie_prices: dict[str, dict[str, float]]) -> MarketOdds:
    """bookie_prices: {outcome: {bookie: odds}}."""
    outcomes = [
        Outcome(name=name, bookmaker=bk, odds=od)
        for name, prices in bookie_prices.items()
        for bk, od in prices.items()
    ]
    return MarketOdds(sport=sport, event=event, market="h2h", outcomes=outcomes)


def test_gap_computation():
    m = _market_outcomes("AFL", "Cats v Pies", {
        "Geelong": {"Sportsbet": 1.85, "Neds": 1.80},
        "Collingwood": {"Sportsbet": 2.00, "Neds": 1.95},
    })
    rows = head_to_head([m])
    by_outcome = {r.outcome: r for r in rows}
    assert len(rows) == 2
    assert by_outcome["Geelong"].better == "sportsbet"
    assert by_outcome["Geelong"].better_odds == 1.85
    assert by_outcome["Geelong"].gap_pct == pytest.approx(2.78, abs=0.01)  # (1.85-1.80)/1.80
    assert by_outcome["Collingwood"].better == "sportsbet"
    assert by_outcome["Collingwood"].gap_pct == pytest.approx(2.56, abs=0.01)  # (2.00-1.95)/1.95


def test_case_insensitive_substring_bookie_match():
    m = _market_outcomes("NRL", "Storm v Broncos", {
        "Melbourne": {"sportsbet": 2.10, "NEDS": 2.00},
        "Brisbane": {"SportsBet": 1.80, "Neds": 1.90},
    })
    rows = head_to_head([m])
    assert len(rows) == 2
    prices = {r.outcome: r.prices for r in rows}
    assert prices["Melbourne"]["neds"] == 2.00
    assert prices["Brisbane"]["sportsbet"] == 1.80
    assert prices["Melbourne"]["sportsbet"] == 2.10
    assert prices["Brisbane"]["neds"] == 1.90


def test_ignores_non_h2h_markets():
    spread = MarketOdds(
        sport="AFL", event="Cats v Pies", market="spreads",
        outcomes=[Outcome(name="Geelong", bookmaker="Sportsbet", odds=1.85),
                  Outcome(name="Geelong", bookmaker="Neds", odds=1.80)],
    )
    assert head_to_head([spread]) == []


def test_sport_filter():
    afl = _market_outcomes("AFL", "A v B", {"A": {"Sportsbet": 1.5, "Neds": 1.4}, "B": {"Sportsbet": 2.5, "Neds": 2.6}})
    nrl = _market_outcomes("NRL", "C v D", {"C": {"Sportsbet": 1.9, "Neds": 1.8}, "D": {"Sportsbet": 1.9, "Neds": 2.0}})
    rows = head_to_head([afl, nrl], sport_filter="nrl")
    assert len(rows) == 2
    assert all(r.sport == "NRL" for r in rows)


def test_outcome_with_single_bookie_excluded():
    m = _market_outcomes("AFL", "A v B", {
        "A": {"Sportsbet": 1.5, "Neds": 1.4},
        "B": {"Sportsbet": 2.5},  # no Neds price -> not comparable
    })
    rows = head_to_head([m])
    assert [r.outcome for r in rows] == ["A"]


def test_sorted_by_gap_desc_within_event():
    m = _market_outcomes("AFL", "A v B", {
        "A": {"Sportsbet": 1.5, "Neds": 1.4},     # gap 7.14%
        "B": {"Sportsbet": 2.5, "Neds": 2.45},   # gap 2.04%
    })
    rows = head_to_head([m])
    assert [r.outcome for r in rows] == ["A", "B"]


def test_sample_data_has_both_user_bookies():
    from pathlib import Path

    import ausbet
    from ausbet.compare import StaticSource

    sample = Path(ausbet.__file__).resolve().parent / "data" / "sample_market.json"
    rows = head_to_head(StaticSource(sample).fetch())
    assert len(rows) == 4  # 2 outcomes per market x 2 markets, all priced at neds + sportsbet
    assert all(set(r.prices) == {"neds", "sportsbet"} for r in rows)

"""Arbitrage / dutching / hedging tests."""

from __future__ import annotations

import pytest

from ausbet.arbitrage import (
    arbitrage_stakes,
    dutch_stakes,
    hedge_stake,
    is_arbitrage,
    overround,
)


def test_overround():
    assert overround([2.0, 2.0]) == pytest.approx(1.0)
    assert overround([2.10, 2.05]) == pytest.approx(0.963995, abs=1e-4)


def test_is_arbitrage():
    assert is_arbitrage([2.10, 2.05])          # 96.4% -> arb
    assert not is_arbitrage([1.95, 1.95])      # 102.6% -> no arb
    assert not is_arbitrage([2.0, 2.0])        # fair -> no arb


def test_arbitrage_stakes_two_way():
    plan = arbitrage_stakes([2.10, 2.05], total=100.0)
    assert plan.is_arb
    assert sum(plan.stakes) == pytest.approx(100.0, abs=0.02)
    assert plan.profit == pytest.approx(3.73, abs=0.02)
    assert plan.roi_pct == pytest.approx(3.73, abs=0.02)
    assert plan.guaranteed_return == pytest.approx(103.73, abs=0.02)


def test_arbitrage_stakes_three_way():
    # 3.0 / 4.0 / 6.0: implied = 0.3333+0.25+0.1667 = 0.75 -> 33% arb
    plan = arbitrage_stakes([3.0, 4.0, 6.0], total=100.0)
    assert plan.profit == pytest.approx(33.33, abs=0.1)
    assert plan.is_arb


def test_arbitrage_rejected_without_arb():
    with pytest.raises(ValueError, match="no arbitrage"):
        arbitrage_stakes([1.95, 1.95])


def test_dutch_fair_market_returns_total():
    # 2.0/3.0/6.0 -> exactly 100% implied -> dutch breaks even
    plan = dutch_stakes([2.0, 3.0, 6.0], total=100.0)
    assert plan.guaranteed_return == pytest.approx(100.0, abs=0.02)
    assert plan.profit == pytest.approx(0.0, abs=0.02)


def test_dutch_stakes_sum_to_total():
    plan = dutch_stakes([2.5, 3.1, 4.2], total=200.0)
    assert sum(plan.stakes) == pytest.approx(200.0, abs=0.1)
    r = [plan.stakes[i] * plan.odds[i] for i in range(3)]
    assert r[0] == pytest.approx(r[1], abs=0.05)
    assert r[1] == pytest.approx(r[2], abs=0.05)


def test_hedge_equal_profit():
    lay_stake, profit = hedge_stake(back_odds=2.5, back_stake=50.0, lay_odds=2.6)
    assert lay_stake == pytest.approx(46.88, abs=0.01)
    assert profit == pytest.approx(28.12, abs=0.01)


def test_hedge_validation():
    with pytest.raises(ValueError):
        hedge_stake(1.0, 50.0, 2.6)
    with pytest.raises(ValueError):
        hedge_stake(2.5, 0.0, 2.6)

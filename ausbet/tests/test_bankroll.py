"""Bankroll / staking strategy tests."""

from __future__ import annotations

import pytest

from ausbet.bankroll import (
    flat_stake,
    kelly_fraction,
    kelly_stake,
    percent_stake,
    suggest_stake,
)


def test_kelly_fair_odds_no_edge():
    # 2.00 at 50% is fair: full Kelly = 0
    assert kelly_fraction(2.0, 0.5) == pytest.approx(0.0)


def test_kelly_positive_edge():
    # 2.50 at 50% -> f* = (1.5*0.5 - 0.5)/1.5 = 1/6
    assert kelly_fraction(2.5, 0.5) == pytest.approx(0.166666, abs=1e-5)


def test_kelly_negative_edge_clamped_to_zero():
    assert kelly_fraction(1.85, 0.5) == 0.0


def test_kelly_stake_default_quarter():
    # $1000 bankroll, f=1/6, quarter kelly -> 1000 * 1/6 * 0.25 = 41.67
    assert kelly_stake(2.5, 0.5, 1000.0) == pytest.approx(41.67, abs=0.01)


def test_kelly_stake_no_edge_is_zero():
    assert kelly_stake(2.0, 0.5, 1000.0) == 0.0


def test_kelly_stake_full_fraction():
    assert kelly_stake(2.5, 0.5, 600.0, fraction=1.0) == pytest.approx(100.0, abs=0.01)


def test_kelly_prob_out_of_range():
    with pytest.raises(ValueError):
        kelly_fraction(2.0, 0.0)
    with pytest.raises(ValueError):
        kelly_fraction(2.0, 1.0)


def test_flat_stake():
    assert flat_stake(50) == 50.0
    with pytest.raises(ValueError):
        flat_stake(0)


def test_percent_stake():
    assert percent_stake(1000.0, 2.0) == 20.0
    with pytest.raises(ValueError):
        percent_stake(1000.0, 0.0)


def test_suggest_stake_dispatch():
    assert suggest_stake("flat", 1000.0, amount=25) == 25.0
    assert suggest_stake("percent", 1000.0, pct=1.5) == 15.0
    assert suggest_stake("kelly", 1000.0, decimal=2.5, prob_est=0.5) == pytest.approx(41.67, abs=0.01)


def test_suggest_stake_missing_args():
    with pytest.raises(ValueError):
        suggest_stake("kelly", 1000.0)
    with pytest.raises(ValueError):
        suggest_stake("flat", 1000.0)
    with pytest.raises(ValueError):
        suggest_stake("quantum", 1000.0)

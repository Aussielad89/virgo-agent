"""Value betting maths tests."""

from __future__ import annotations

import pytest

from ausbet.value import (
    edge_pct,
    expected_value,
    fair_odds,
    is_value,
    scan_market,
)


def test_expected_value():
    assert expected_value(2.5, 0.5) == pytest.approx(0.25)
    assert expected_value(2.0, 0.5) == pytest.approx(0.0)
    assert expected_value(1.85, 0.5) == pytest.approx(-0.075)


def test_edge_pct():
    assert edge_pct(2.5, 0.5) == pytest.approx(25.0)


def test_fair_odds():
    assert fair_odds(0.5) == pytest.approx(2.0)
    assert fair_odds(0.25) == pytest.approx(4.0)


def test_is_value():
    assert is_value(2.5, 0.5)
    assert not is_value(1.85, 0.5)
    assert not is_value(2.0, 0.5)


def test_bad_prob_rejected():
    with pytest.raises(ValueError):
        expected_value(2.0, 0.0)
    with pytest.raises(ValueError):
        fair_odds(1.5)


def test_scan_market_sorts_by_ev():
    picks = scan_market(
        [("A", 2.5), ("B", 1.85), ("C", 3.0)],
        {"A": 0.5, "B": 0.5, "C": 0.25},
    )
    # EV: A +0.25, B -0.075, C -0.25
    assert [p.selection for p in picks] == ["A", "B", "C"]
    a = picks[0]
    assert a.is_value and a.ev_per_unit == pytest.approx(0.25)
    assert a.kelly_fraction == pytest.approx(1 / 6, abs=1e-5)
    assert not picks[-1].is_value


def test_scan_market_skips_missing_prob():
    picks = scan_market([("A", 2.0)], {"A": 0.5, "B": 0.5})
    assert len(picks) == 1

"""Multi / racing-special fairness tests (no network)."""

from __future__ import annotations

import pytest

from ausbet.multi import analyze_multi


def test_singles_price_is_product():
    a = analyze_multi([("A", 1.85), ("B", 2.00)])
    assert a.singles_price == pytest.approx(3.70, abs=0.001)
    assert a.combined_implied == pytest.approx((1.0 / 1.85) * (1.0 / 2.00), abs=1e-6)


def test_offer_below_singles_is_tax():
    a = analyze_multi([("A", 1.85), ("B", 2.00)], offer=3.50)
    assert a.diff_pct == pytest.approx(-5.41, abs=0.01)  # (3.50-3.70)/3.70
    assert "LESS" in a.verdict


def test_offer_above_singles_is_boost():
    a = analyze_multi([("A", 1.85), ("B", 2.00)], offer=3.90)
    assert a.diff_pct == pytest.approx(5.41, abs=0.01)
    assert "boost" in a.verdict.lower()


def test_ev_with_probs():
    # P(A)=0.55, P(B)=0.50 -> true multi prob 0.275; offer 3.70 -> EV = 3.70*0.275-1 = +0.0175
    a = analyze_multi([("A", 1.85), ("B", 2.00)], offer=3.70, probs={"A": 0.55, "B": 0.50})
    assert a.model_fair == pytest.approx(1.0 / 0.275, abs=0.01)
    assert a.model_ev == pytest.approx(3.70 * 0.275 - 1.0, abs=1e-3)
    assert "VALUE" in a.verdict


def test_no_offer_verdict():
    a = analyze_multi([("A", 1.85), ("B", 2.00)])
    assert a.offer is None
    assert a.diff_pct is None
    assert "fair price" in a.verdict


def test_requires_two_legs():
    with pytest.raises(ValueError, match="at least 2 legs"):
        analyze_multi([("A", 1.85)])


def test_bad_odds_rejected():
    with pytest.raises(ValueError):
        analyze_multi([("A", 0.5), ("B", 2.0)])


def test_missing_prob_rejected():
    with pytest.raises(ValueError, match="no probability"):
        analyze_multi([("A", 1.85), ("B", 2.00)], offer=3.5, probs={"A": 0.5})


def test_odds_as_strings_parsed():
    a = analyze_multi([("A", "5/2"), ("B", "+200")])
    assert a.singles_price == pytest.approx(3.5 * 3.0, abs=0.01)

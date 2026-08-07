"""Arb watcher tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import ausbet
from ausbet.compare import StaticSource
from ausbet.watch import ArbAlert, scan_for_arbs, watch_once

SAMPLE = Path(ausbet.__file__).resolve().parent / "data" / "sample_market.json"


@pytest.fixture()
def sample_markets():
    return StaticSource(SAMPLE).fetch()


def test_scan_finds_nrl_arb(sample_markets):
    alerts = scan_for_arbs(sample_markets)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.event == "Melbourne v Brisbane"
    assert a.overround_pct == pytest.approx(96.40, abs=0.01)
    assert a.profit == pytest.approx(3.73, abs=0.02)
    assert a.roi_pct == pytest.approx(3.73, abs=0.02)
    assert a.selections == ["Melbourne", "Brisbane"]


def test_min_roi_filters_out_small_arb(sample_markets):
    assert scan_for_arbs(sample_markets, min_roi=5.0) == []  # 3.73% < 5%
    assert len(scan_for_arbs(sample_markets, min_roi=3.0)) == 1


def test_no_arb_market_returns_empty():
    from ausbet.compare import MarketOdds, Outcome

    fair = [MarketOdds(sport="S", event="E", market="h2h", outcomes=[
        Outcome("A", "B1", 1.95), Outcome("B", "B2", 1.95)])]
    assert scan_for_arbs(fair) == []


def test_alert_summary_contains_event(sample_markets):
    a = scan_for_arbs(sample_markets)[0]
    assert "Melbourne v Brisbane" in a.summary()
    assert "ARB" in a.summary()
    assert "$+3.73" in a.summary()


def test_watch_once(sample_markets):
    alerts = watch_once(StaticSource(SAMPLE))
    assert len(alerts) == 1


def test_alert_is_dataclass(sample_markets):
    a = scan_for_arbs(sample_markets)[0]
    assert isinstance(a, ArbAlert)
    assert a.detected_at  # timestamp populated

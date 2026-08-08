"""Odds source + comparison tests (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

import ausbet
from ausbet.compare import (
    MarketComparison,
    StaticSource,
    TheOddsAPISource,
    compare,
)

SAMPLE = Path(ausbet.__file__).resolve().parent / "data" / "sample_market.json"


def test_static_source_loads_sample():
    markets = StaticSource(SAMPLE).fetch()
    assert len(markets) == 2
    afl = markets[0]
    assert afl.sport == "AFL"
    assert afl.event == "Geelong v Collingwood"
    assert len(afl.outcomes) == 8  # Sportsbet, Ladbrokes, TAB, Neds x 2 selections


def test_compare_afl_best_prices():
    comps = compare(StaticSource(SAMPLE).fetch())
    afl = next(c for c in comps if c.sport == "AFL")
    assert afl.best["Geelong"] == ("Ladbrokes", 1.90)
    assert afl.best["Collingwood"] == ("Sportsbet", 2.00)
    assert afl.overrounds["TAB"] == pytest.approx(103.70, abs=0.01)
    assert afl.best_overround_pct == pytest.approx(102.63, abs=0.01)


def test_compare_nrl_contains_arb():
    comps = compare(StaticSource(SAMPLE).fetch())
    nrl = next(c for c in comps if c.sport == "NRL")
    assert nrl.best["Melbourne"] == ("Sportsbet", 2.10)
    assert nrl.best["Brisbane"] == ("Ladbrokes", 2.05)
    assert nrl.best_overround_pct < 100.0  # arbitrage spot


def test_compare_render_smoke():
    comps = compare(StaticSource(SAMPLE).fetch())
    text = comps[0].render()
    assert "BEST" in text
    assert "MARGIN" in text


def test_static_csv_source(tmp_path):
    csv_file = tmp_path / "odds.csv"
    csv_file.write_text(
        "sport,event,selection,bookmaker,odds\n"
        "NRL,Cows v Dogs,Cowboys,TAB,1.75\n"
        "NRL,Cows v Dogs,Dogs,TAB,2.10\n",
        encoding="utf-8",
    )
    markets = StaticSource(csv_file).fetch()
    assert len(markets) == 2
    assert markets[0].outcomes[0].odds == 1.75


def test_oddsapi_source_requires_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    src = TheOddsAPISource()
    assert src.available_sports() == []
    with pytest.raises(RuntimeError, match="ODDS_API_KEY"):
        src.fetch()


def test_market_key_grouping():
    m1 = StaticSource(SAMPLE).fetch()[0]
    assert m1.key == ("AFL", "Geelong v Collingwood", "h2h")

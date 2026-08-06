"""Betfair adapter tests — fixture-based, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ausbet
from ausbet.betfair import BetfairError, BetfairExchangeSource

FIXTURE = Path(ausbet.__file__).resolve().parent / "data" / "sample_betfair.json"


def test_fixture_parse_back_and_lay():
    src = BetfairExchangeSource(fixture=FIXTURE)
    markets = src.fetch()
    assert len(markets) == 1
    m = markets[0]
    assert m.event == "Geelong v Collingwood"
    assert m.market == "Match Odds"
    assert m.market_id == "1.234567890"
    assert len(m.outcomes) == 2
    geelong = next(o for o in m.outcomes if o.name == "Geelong")
    assert geelong.bookmaker == "Betfair"
    assert geelong.odds == pytest.approx(1.88)
    assert geelong.lay == pytest.approx(1.89)
    collingwood = next(o for o in m.outcomes if o.name == "Collingwood")
    assert collingwood.odds == pytest.approx(1.99)
    assert collingwood.lay == pytest.approx(2.02)


def test_parse_without_lay_keeps_back():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for runner in payload["book"][0]["runners"]:
        runner["ex"]["availableToLay"] = []
    markets = BetfairExchangeSource._parse(payload)
    assert len(markets) == 1
    for o in markets[0].outcomes:
        assert o.lay is None
        assert o.odds > 1.0


def test_parse_skips_runner_without_back_price():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["book"][0]["runners"][0]["ex"]["availableToBack"] = []
    markets = BetfairExchangeSource._parse(payload)
    assert [o.name for o in markets[0].outcomes] == ["Collingwood"]


def test_parse_empty_catalogue():
    assert BetfairExchangeSource._parse({"catalogue": [], "book": []}) == []


def test_fetch_requires_credentials(monkeypatch):
    for var in ("BETFAIR_APP_KEY", "BETFAIR_USERNAME", "BETFAIR_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    src = BetfairExchangeSource()
    with pytest.raises(RuntimeError, match="BETFAIR_APP_KEY"):
        src.fetch()


def test_login_raises_clean_error_when_creds_missing():
    src = BetfairExchangeSource()
    with pytest.raises(RuntimeError, match="credentials missing"):
        src.login()


def test_betfair_error_type():
    assert issubclass(BetfairError, RuntimeError)

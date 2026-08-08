"""Bet store + stats tests (SQLite, tmp path)."""

from __future__ import annotations

import pytest

from ausbet.tracker import Bet, BetStore


@pytest.fixture()
def store(tmp_path):
    s = BetStore(tmp_path / "bets.db")
    yield s
    s.close()


def test_add_and_get(store):
    bet = Bet(bookmaker="Sportsbet", sport="AFL", selection="Geelong", odds=1.85, stake=50.0)
    bid = store.add(bet)
    loaded = store.get(bid)
    assert loaded is not None
    assert loaded.selection == "Geelong"
    assert loaded.odds == 1.85
    assert loaded.result is None


def test_bet_validation():
    with pytest.raises(ValueError):
        Bet(bookmaker="x", sport="x", selection="x", odds=0.5, stake=10)
    with pytest.raises(ValueError):
        Bet(bookmaker="x", sport="x", selection="x", odds=2.0, stake=0)
    with pytest.raises(ValueError):
        Bet(bookmaker="x", sport="x", selection="x", odds=2.0, stake=10, result="maybe")


def test_settle_won_defaults_to_odds_times_stake(store):
    bid = store.add(Bet(bookmaker="B", sport="S", selection="Sel", odds=2.5, stake=40.0))
    settled = store.settle(bid, "won")
    assert settled.payout == pytest.approx(100.0)


def test_settle_lost_and_void(store):
    bid = store.add(Bet(bookmaker="B", sport="S", selection="Sel", odds=2.5, stake=40.0))
    assert store.settle(bid, "lost").payout == 0.0
    bid2 = store.add(Bet(bookmaker="B", sport="S", selection="Sel2", odds=4.5, stake=10.0))
    assert store.settle(bid2, "void").payout == 10.0


def test_settle_missing_bet_raises(store):
    with pytest.raises(KeyError):
        store.settle(999, "won")


def test_delete(store):
    bid = store.add(Bet(bookmaker="B", sport="S", selection="Sel", odds=2.0, stake=10.0))
    store.delete(bid)
    assert store.get(bid) is None
    with pytest.raises(KeyError):
        store.delete(bid)


def test_pending_filter(store):
    store.add(Bet(bookmaker="B", sport="S", selection="A", odds=2.0, stake=10.0))
    bid2 = store.add(Bet(bookmaker="B", sport="S", selection="B", odds=2.0, stake=10.0, result="won"))
    pending = store.list(pending_only=True)
    assert [b.id for b in pending] == [bid2 - 1]


def test_stats_math(store):
    store.add(Bet(bookmaker="Sportsbet", sport="AFL", selection="Geelong", odds=1.85, stake=50.0, result="won"))
    store.add(Bet(bookmaker="Ladbrokes", sport="AFL", selection="Pies", odds=2.0, stake=25.0, result="lost"))
    store.add(Bet(bookmaker="Betfair", sport="NRL", selection="Melb", odds=1.90, stake=40.0, result="won"))
    store.add(Bet(bookmaker="TAB", sport="Cricket", selection="Smith", odds=4.5, stake=10.0, result="void"))
    store.add(Bet(bookmaker="PointsBet", sport="AFL", selection="Geelong 40+", odds=5.0, stake=20.0))
    s = store.stats()
    assert s.total_bets == 5
    assert s.settled == 4
    assert s.pending == 1
    assert s.staked == pytest.approx(125.0)          # 50+25+40+10 (pending excluded)
    assert s.returned == pytest.approx(178.5)        # 92.5 + 0 + 76 + 10
    assert s.profit == pytest.approx(53.5)
    assert s.roi_pct == pytest.approx(42.8, abs=0.1)
    assert s.strike_rate_pct == pytest.approx(66.67, abs=0.01)  # 2 of 3 decided (void excluded)
    assert s.by_sport["AFL"]["bets"] == 2
    assert s.by_bookmaker["Sportsbet"]["profit"] == pytest.approx(42.5)


def test_export_csv(store, tmp_path):
    store.add(Bet(bookmaker="B", sport="S", selection="Sel", odds=2.0, stake=10.0, result="won"))
    out = tmp_path / "bets.csv"
    path = store.export_csv(out)
    text = path.read_text(encoding="utf-8")
    assert "bookmaker,sport,selection,odds,stake" in text
    assert "won" in text

"""Auto-settle tests (no network)."""

from __future__ import annotations

import pytest

from ausbet.results import GameResult, auto_settle, games_from_scores_api, sport_matches, team_side
from ausbet.tracker import Bet, BetStore


# ---------------------------------------------------------------- matching

def test_team_side_exact_and_substring():
    assert team_side("Melbourne", "Melbourne", "Brisbane") == "home"
    assert team_side("Brisbane", "Melbourne", "Brisbane") == "away"
    assert team_side("Melbourne Demons", "Melbourne", "Brisbane") == "home"  # reverse substring
    assert team_side("Sydney", "Sydney Swans", "GWS Giants") == "home"       # forward substring
    assert team_side("Sydney", "Sydney Swans", "Sydney Roosters") == "ambiguous"
    assert team_side("Niners", "Sydney Swans", "GWS Giants") is None


def test_sport_matches():
    assert sport_matches("AFL", "Aussie Rules")
    assert sport_matches("NRL", "Rugby League")
    assert not sport_matches("AFL", "Rugby League")
    assert not sport_matches("Racing", "Aussie Rules")


# ---------------------------------------------------------------- settling

def _store_with_bets(tmp_path, bets: list[Bet]) -> BetStore:
    store = BetStore(tmp_path / "t.db")
    for b in bets:
        store.add(b)
    return store


def test_auto_settle_wins_and_losses(tmp_path):
    store = _store_with_bets(tmp_path, [
        Bet(bookmaker="Neds", sport="AFL", selection="Geelong", odds=1.85, stake=10.0, market="h2h"),
        Bet(bookmaker="Sportsbet", sport="AFL", selection="Collingwood", odds=2.0, stake=10.0, market="h2h"),
    ])
    try:
        games = [GameResult(home="Geelong", away="Collingwood", home_score=102, away_score=88,
                            sport="Aussie Rules")]
        report = auto_settle(store, games)
        assert len(report.settled) == 2
        results = {b.selection: b.result for b in report.settled}
        assert results["Geelong"] == "won"
        assert results["Collingwood"] == "lost"
        geelong = next(b for b in report.settled if b.selection == "Geelong")
        assert geelong.payout == pytest.approx(18.50, abs=0.01)  # 1.85 * 10
    finally:
        store.close()


def test_auto_settle_draw_left_pending(tmp_path):
    store = _store_with_bets(tmp_path, [
        Bet(bookmaker="Neds", sport="AFL", selection="Geelong", odds=1.85, stake=10.0, market="h2h"),
    ])
    try:
        games = [GameResult(home="Geelong", away="Collingwood", home_score=90, away_score=90,
                            sport="Aussie Rules")]
        report = auto_settle(store, games)
        assert report.settled == []
        assert len(report.draws) == 1
        assert store.list()[0].result is None
    finally:
        store.close()


def test_auto_settle_ambiguous_and_unmatched(tmp_path):
    store = _store_with_bets(tmp_path, [
        Bet(bookmaker="Neds", sport="NRL", selection="Sydney", odds=2.0, stake=10.0, market="h2h"),
        Bet(bookmaker="Neds", sport="NRL", selection="North Queensland", odds=2.0, stake=10.0, market="h2h"),
        Bet(bookmaker="Neds", sport="NRL", selection="Penrith", odds=2.0, stake=10.0, market="h2h"),
    ])
    try:
        games = [GameResult(home="Sydney Roosters", away="Sydney Swans", home_score=20, away_score=10,
                            sport="Rugby League")]
        report = auto_settle(store, games)
        assert len(report.ambiguous) == 1   # "Sydney" matches both teams
        assert len(report.unmatched) == 2   # Cowboys + Panthers have no game
        assert report.settled == []
    finally:
        store.close()


def test_multis_left_pending(tmp_path):
    store = _store_with_bets(tmp_path, [
        Bet(bookmaker="Neds", sport="AFL", selection="Geelong", odds=3.5, stake=10.0, market="multi"),
    ])
    try:
        games = [GameResult(home="Geelong", away="Collingwood", home_score=102, away_score=88,
                            sport="Aussie Rules")]
        report = auto_settle(store, games)
        assert report.settled == []
        assert report.unmatched == []
        assert store.list()[0].result is None
    finally:
        store.close()


def test_sport_mismatch_unmatched(tmp_path):
    store = _store_with_bets(tmp_path, [
        Bet(bookmaker="Neds", sport="NRL", selection="Geelong", odds=1.85, stake=10.0, market="h2h"),
    ])
    try:
        games = [GameResult(home="Geelong", away="Collingwood", home_score=102, away_score=88,
                            sport="Aussie Rules")]
        report = auto_settle(store, games)
        assert len(report.unmatched) == 1
    finally:
        store.close()


# ---------------------------------------------------------------- parsing

def test_games_from_scores_api_oddsapi_shape():
    raw = [{
        "sport_title": "Aussie Rules",
        "home_team": "Geelong", "away_team": "Collingwood",
        "completed": True,
        "scores": [{"name": "Geelong", "score": "102"}, {"name": "Collingwood", "score": "88"}],
    }]
    games = games_from_scores_api(raw)
    assert games[0].home_score == 102
    assert games[0].away_score == 88
    assert games[0].sport == "Aussie Rules"
    assert games[0].completed


def test_games_from_scores_api_file_shape():
    raw = [{"home": "Melbourne", "away": "Brisbane", "home_score": 24, "away_score": 10, "sport": "NRL"}]
    games = games_from_scores_api(raw)
    assert games[0].home_score == 24
    assert games[0].away_score == 10
    assert games[0].sport == "NRL"
    assert games[0].completed

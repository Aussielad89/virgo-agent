"""TheOddsAPISource live-feed behaviour tests (mocked network)."""

from __future__ import annotations

import json

import pytest

from ausbet.compare import TheOddsAPISource

# NOTE: the real /sports response has NO per-sport "regions" field —
# only active/description/group/has_outrights/key/title. The default
# sport selection must rely on title matching alone (regression for the
# "au in s.get('regions', [])" bug that silently returned zero markets).

SPORTS = [
    {"key": "americanfootball_nfl", "title": "NFL", "active": True},
    {"key": "aussierules_afl", "title": "AFL", "active": True},
    {"key": "aussierules_aflw", "title": "AFL Women's", "active": True},
    {"key": "rugbyleague_nrl", "title": "NRL", "active": True},
    {"key": "soccer_epl", "title": "EPL", "active": True},
]


def _odds_payload(sport_key: str, title: str) -> list[dict]:
    home, away = ("Geelong", "Collingwood") if sport_key == "aussierules_afl" else ("Melbourne", "Brisbane")
    return [{
        "id": f"game-{sport_key}",
        "sport_key": sport_key,
        "sport_title": title,
        "commence_time": "2026-08-09T05:00:00Z",
        "home_team": home,
        "away_team": away,
        "bookmakers": [{
            "key": "sportsbet",
            "title": "Sportsbet",
            "markets": [{
                "key": "h2h",
                "outcomes": [{"name": home, "price": 1.85}, {"name": away, "price": 2.00}],
            }],
        }],
    }]


class _FakeSource(TheOddsAPISource):
    def __init__(self, sports: list[dict]) -> None:
        super().__init__(api_key="test-key")
        self._sports = sports
        self.fetched_keys: list[str] = []

    def available_sports(self) -> list[dict]:
        return self._sports

    def _get(self, url: str) -> dict:
        for sport in self._sports:
            key = sport["key"]
            if f"/sports/{key}/odds/" in url:
                self.fetched_keys.append(key)
                return _odds_payload(key, sport["title"])  # type: ignore[return-value]
        return {}


def test_default_fetches_only_au_football_codes():
    src = _FakeSource(SPORTS)
    markets = src.fetch()
    assert src.fetched_keys == ["aussierules_afl", "aussierules_aflw", "rugbyleague_nrl"]
    assert sorted({m.sport for m in markets}) == ["AFL", "AFL Women's", "NRL"]


def test_explicit_sport_keys_limit_the_fetch():
    src = _FakeSource(SPORTS)
    markets = src.fetch(sport_keys=["aussierules_afl"])
    assert src.fetched_keys == ["aussierules_afl"]
    assert {m.sport for m in markets} == {"AFL"}


def test_missing_sport_key_raises():
    src = _FakeSource(SPORTS)
    with pytest.raises(RuntimeError, match="not available"):
        src.fetch(sport_keys=["aussierules_afl", "nope_nope"])


def test_fetch_scores_filters_to_au_football():
    src = _FakeSource(SPORTS)
    src._get = lambda url: [{"id": "g1", "home_team": "Geelong", "away_team": "Collingwood",
                             "completed": True,
                             "scores": [{"name": "Geelong", "score": "102"},
                                        {"name": "Collingwood", "score": "88"}]}]
    games = src.fetch_scores(days=1)
    assert len(games) == 3  # AFL + AFLW + NRL games
    assert {g["sport_title"] for g in games} == {"AFL", "AFL Women's", "NRL"}


def test_cache_round_trip_preserves_markets(tmp_path):
    """A cache written by fetch() must read back as the same markets."""
    cache = tmp_path / "odds_cache.json"
    src = _FakeSource(SPORTS)
    live = src.fetch(sport_keys=["aussierules_afl"])
    cache.write_text(
        json.dumps([src._serialize(m) for m in live], indent=2), encoding="utf-8"
    )
    cached = TheOddsAPISource(api_key="x", cache_path=cache).fetch()
    assert len(cached) == len(live)
    assert cached[0].sport == "AFL"
    assert cached[0].event == live[0].event
    assert {o.bookmaker for o in cached[0].outcomes} == {"sportsbet"}

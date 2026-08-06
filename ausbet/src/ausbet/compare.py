"""Odds comparison: pluggable sources, best-odds pivots and overround analysis.

Sources:
    StaticSource       JSON/CSV file with odds already collected (offline demo)
    TheOddsAPISource   https://the-odds-api.com — free tier covers AU
                       bookmakers (Sportsbet, Ladbrokes, Bet365, TAB, Neds,
                       Betfair, PointsBet, ...). Requires ODDS_API_KEY env var.
"""

from __future__ import annotations

import csv
import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

API_BASE = "https://api.the-odds-api.com/v4"
DEFAULT_REGIONS = "au"
DEFAULT_MARKETS = "h2h,spreads,totals"


def _is_au_football(title: str) -> bool:
    """True when a the-odds-api sport title is AFL or NRL (auto-settle scope)."""
    t = title.lower()
    return any(k in t for k in ("afl", "aussie", "australian rules", "rugby league", "nrl"))


@dataclass
class Outcome:
    """One selection's price at one bookmaker, in decimal odds."""

    name: str
    bookmaker: str
    odds: float
    lay: float | None = None  # exchange lay price (Betfair), when available


@dataclass
class MarketOdds:
    """One market (e.g. AFL h2h for a single match) with prices per bookie."""

    sport: str
    event: str
    market: str
    outcomes: list[Outcome]
    start_time: str | None = None
    market_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.sport, self.event, self.market)


@dataclass
class MarketComparison:
    """Best-price analysis for a single market."""

    sport: str
    event: str
    market: str
    bookmakers: set[str] = field(default_factory=set)
    # outcome name -> {bookmaker: decimal odds}
    prices: dict[str, dict[str, float]] = field(default_factory=dict)
    # outcome name -> (best bookmaker, best odds)
    best: dict[str, tuple[str, float]] = field(default_factory=dict)
    # outcome name -> best lay price (exchange), when present
    lays: dict[str, float] = field(default_factory=dict)
    # bookmaker -> overround % (sum of implied probabilities)
    overrounds: dict[str, float] = field(default_factory=dict)
    best_overround_pct: float = 0.0

    def render(self, top: int | None = None) -> str:
        lines = [f"{self.sport} — {self.event} [{self.market}]"]
        for name in sorted(self.best):
            bb, bo = self.best[name]
            row = f"  BEST  {name:<28} {bo:>6.2f}  @ {bb}"
            if name in self.lays:
                row += f"   (lay {self.lays[name]:.2f})"
            lines.append(row)
        if self.overrounds:
            order = sorted(self.overrounds.items(), key=lambda kv: kv[1])
            margin_line = "  MARGIN  " + "  |  ".join(
                f"{bk}: {ov:.1f}%" for bk, ov in order[: top or len(order)]
            )
            lines.append(margin_line)
        lines.append("")
        return "\n".join(lines)


class OddsSource(Protocol):
    """Anything that yields markets with decimal odds."""

    name: str

    def fetch(self) -> list[MarketOdds]: ...


class StaticSource:
    """Loads odds from a JSON file.

    JSON shape:
        {
          "source": "manual",
          "markets": [
            {"sport": "AFL", "event": "Cats v Pies", "market": "h2h",
             "outcomes": [{"name": "Geelong", "bookmaker": "Sportsbet", "odds": 1.85}, ...]}
          ]
        }
    """

    name = "static"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self) -> list[MarketOdds]:
        if self.path.suffix.lower() == ".csv":
            return self._fetch_csv()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        markets = []
        for m in data.get("markets", []):
            outcomes = [
                Outcome(name=o["name"], bookmaker=o["bookmaker"], odds=float(o["odds"]))
                for o in m.get("outcomes", [])
            ]
            markets.append(
                MarketOdds(
                    sport=m.get("sport", ""),
                    event=m.get("event", ""),
                    market=m.get("market", "h2h"),
                    outcomes=outcomes,
                    start_time=m.get("start_time"),
                )
            )
        return markets

    def _fetch_csv(self) -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        with open(self.path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                markets.append(
                    MarketOdds(
                        sport=row["sport"],
                        event=row["event"],
                        market=row.get("market", "h2h"),
                        outcomes=[
                            Outcome(
                                name=row["selection"],
                                bookmaker=row["bookmaker"],
                                odds=float(row["odds"]),
                            )
                        ],
                    )
                )
        return markets


class TheOddsAPISource:
    """Live odds via the-odds-api.com. Set ODDS_API_KEY to use.

    Regions default to Australia; markets h2h/spreads/totals. Free tier is
    limited (500 requests/month) — cache results to disk with `cache_path`.
    """

    name = "the-odds-api"

    def __init__(
        self,
        api_key: str | None = None,
        regions: str = DEFAULT_REGIONS,
        markets: str = DEFAULT_MARKETS,
        cache_path: str | Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        self.regions = regions
        self.markets = markets
        self.cache_path = Path(cache_path) if cache_path else None
        self.timeout = timeout

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def available_sports(self) -> list[dict]:
        if not self.api_key:
            return []
        url = f"{API_BASE}/sports/?apiKey={self.api_key}"
        return self._get(url)

    def fetch(self) -> list[MarketOdds]:
        if not self.api_key:
            raise RuntimeError(
                "ODDS_API_KEY not set — get a free key at https://the-odds-api.com "
                "and set it in the environment, or use --source static."
            )
        if self.cache_path and self.cache_path.exists():
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return self._parse(data)
        sports = [s for s in self.available_sports() if self.regions in s.get("regions", [])]
        if not sports:
            raise RuntimeError(f"no sports available for region {self.regions!r}")
        markets: list[MarketOdds] = []
        for sport in sports[:8]:  # stay inside free-tier limits
            url = (
                f"{API_BASE}/sports/{sport['key']}/odds/?apiKey={self.api_key}"
                f"&regions={self.regions}&markets={self.markets}&oddsFormat=decimal"
            )
            try:
                data = self._get(url)
            except urllib.error.URLError as exc:
                raise RuntimeError(f"odds fetch failed for {sport['key']}: {exc}") from exc
            markets.extend(self._parse(data, default_sport=sport["title"]))
        if self.cache_path:
            self.cache_path.write_text(
                json.dumps([self._serialize(m) for m in markets], indent=2), encoding="utf-8"
            )
        return markets

    def fetch_scores(self, days: int = 2, sport_keys: list[str] | None = None) -> list[dict]:
        """Final scores for completed AU games (the-odds-api /scores endpoint).

        Returns raw game dicts with an extra ``sport_title`` field:
        ``{sport_key, sport_title, home_team, away_team, completed,
        scores: [{'name': team, 'score': '12'}, ...]}``.

        By default only AU football codes are fetched (AFL + NRL — the
        sports whose titles mention aussie rules / afl / rugby league / nrl);
        pass ``sport_keys`` to override (see ``available_sports()``).
        """
        if not self.api_key:
            raise RuntimeError(
                "ODDS_API_KEY not set — get a free key at https://the-odds-api.com "
                "and set it in the environment."
            )
        available = self.available_sports()
        if not available:
            raise RuntimeError(f"no sports available for region {self.regions!r}")
        if sport_keys is None:
            sport_keys = [
                s["key"] for s in available
                if self.regions in s.get("regions", []) and _is_au_football(s.get("title", ""))
            ]
        games: list[dict] = []
        for s in available:
            if s.get("key") not in sport_keys:
                continue
            url = f"{API_BASE}/sports/{s['key']}/scores/?apiKey={self.api_key}&daysFrom={days}"
            try:
                data = self._get(url)
            except urllib.error.URLError as exc:
                raise RuntimeError(f"scores fetch failed for {s['key']}: {exc}") from exc
            for g in data:
                g["sport_title"] = s.get("title", g.get("sport_title", ""))
                games.append(g)
        return games

    @staticmethod
    def _serialize(m: MarketOdds) -> dict:
        return {
            "sport": m.sport,
            "event": m.event,
            "market": m.market,
            "start_time": m.start_time,
            "outcomes": [
                {"name": o.name, "bookmaker": o.bookmaker, "odds": o.odds}
                for o in m.outcomes
            ],
        }

    def _parse(self, data: list, default_sport: str = "") -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        for game in data:
            sport = default_sport or game.get("sport_title", "")
            event = game.get("home_team", "") or ""
            away = game.get("away_team", "")
            if away:
                event = f"{event} v {away}"
            for bm in game.get("bookmakers", []):
                for mk in bm.get("markets", []):
                    outcomes = [
                        Outcome(name=o["name"], bookmaker=bm["key"], odds=float(o["price"]))
                        for o in mk.get("outcomes", [])
                    ]
                    markets.append(
                        MarketOdds(
                            sport=sport,
                            event=event,
                            market=mk.get("key", "h2h"),
                            outcomes=outcomes,
                            start_time=game.get("commence_time"),
                        )
                    )
        return markets


def compare(markets: list[MarketOdds]) -> list[MarketComparison]:
    """Group markets and pivot best prices + overround per bookmaker."""
    groups: dict[tuple, list[MarketOdds]] = {}
    for m in markets:
        groups.setdefault(m.key, []).append(m)

    results: list[MarketComparison] = []
    for key, group in groups.items():
        sport, event, market = key
        comp = MarketComparison(sport=sport, event=event, market=market)
        for m in group:
            for o in m.outcomes:
                comp.bookmakers.add(o.bookmaker)
                comp.prices.setdefault(o.name, {})[o.bookmaker] = o.odds
                if o.lay is not None:
                    comp.lays.setdefault(o.name, o.lay)
        # Best price per outcome
        for name, prices in comp.prices.items():
            bookie = max(prices, key=prices.get)
            comp.best[name] = (bookie, prices[bookie])
        # Overround per bookmaker (only where the bookie prices every outcome)
        for bookie in sorted(comp.bookmakers):
            odds_for = []
            complete = True
            for name in comp.prices:
                if bookie not in comp.prices[name]:
                    complete = False
                    break
                odds_for.append(comp.prices[name][bookie])
            if complete and len(odds_for) > 1:
                comp.overrounds[bookie] = round(sum(1.0 / o for o in odds_for) * 100.0, 2)
        # Synthetic best-of-market overround: < 100% flags a possible arbitrage
        best_odds = [best for _, best in comp.best.values()]
        if len(best_odds) > 1:
            comp.best_overround_pct = round(sum(1.0 / o for o in best_odds) * 100.0, 2)
        results.append(comp)
    return sorted(results, key=lambda c: (c.sport, c.event, c.market))


@dataclass
class H2HRow:
    """One outcome priced by at least two requested bookies, with the gap."""

    sport: str
    event: str
    outcome: str
    prices: dict[str, float]  # requested bookie (lowercased) -> decimal odds
    better: str
    better_odds: float
    gap_pct: float  # (better - worst requested) / worst * 100


def head_to_head(
    markets: list[MarketOdds],
    bookies: list[str] = ("neds", "sportsbet"),
    sport_filter: str | None = None,
) -> list[H2HRow]:
    """Bookie-vs-bookie price scan for head-to-head markets.

    Bookie names match case-insensitively and by substring ('sportsbet'
    matches 'Sportsbet', 'neds' matches 'Neds'). Only h2h outcomes priced by
    at least two requested bookies are returned, sorted by gap descending
    within each event.
    """
    wanted = [b.lower() for b in bookies]

    def find(actual: str) -> str | None:
        a = actual.lower()
        for b in wanted:
            if b in a or a in b:
                return b
        return None

    rows: list[H2HRow] = []
    for m in markets:
        if m.market != "h2h":
            continue
        if sport_filter and sport_filter.lower() not in m.sport.lower():
            continue
        by_outcome: dict[str, dict[str, float]] = {}
        for o in m.outcomes:
            b = find(o.bookmaker)
            if b is None:
                continue
            by_outcome.setdefault(o.name, {})[b] = o.odds
        for outcome, prices in by_outcome.items():
            if len(prices) < 2:
                continue
            better = max(prices, key=prices.get)
            worse = min(prices.values())
            better_odds = prices[better]
            gap = (better_odds - worse) / worse * 100.0 if worse else 0.0
            rows.append(
                H2HRow(
                    sport=m.sport,
                    event=m.event,
                    outcome=outcome,
                    prices=dict(sorted(prices.items())),
                    better=better,
                    better_odds=round(better_odds, 2),
                    gap_pct=round(gap, 2),
                )
            )
    return sorted(rows, key=lambda r: (r.sport, r.event, -r.gap_pct))

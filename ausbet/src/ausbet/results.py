"""Auto-settle pending head-to-head bets from final scores.

The tracker only records bets; results arrive later. This module matches
pending h2h bets to completed games by team name and settles them
(won / lost / void-on-draw), leaving everything else untouched.

Matching is deliberately conservative: a selection that matches *both* teams
of a game (or games across codes) is reported as ambiguous rather than
settled on a guess. Bets on multis / racing specials can't be settled from a
single match result and are left pending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ausbet.tracker import Bet, BetStore

# Bet sports that can be settled from a match result, mapped to the-odds-api
# sport-title keywords.
_SPORT_TITLES = {
    "AFL": ("afl", "aussie", "australian rules"),
    "NRL": ("nrl", "rugby league"),
}


@dataclass
class GameResult:
    """A completed (or in-progress) match with final scores."""

    home: str
    away: str
    home_score: int
    away_score: int
    completed: bool = True
    sport: str = ""


@dataclass
class SettleReport:
    """What an auto-settle pass did and what it left alone."""

    settled: list[Bet] = field(default_factory=list)
    unmatched: list[Bet] = field(default_factory=list)
    ambiguous: list[Bet] = field(default_factory=list)
    draws: list[Bet] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sport_matches(bet_sport: str, game_sport: str) -> bool:
    """True when a bet's sport label ('AFL'/'NRL') covers a game's title."""
    bs = bet_sport.lower()
    gs = game_sport.lower()
    for keywords in _SPORT_TITLES.values():
        if any(k in bs for k in keywords):
            return any(k in gs for k in keywords)
    return False


def team_side(selection: str, home: str, away: str) -> str | None:
    """Which side of a game a selection refers to.

    Returns 'home', 'away', 'ambiguous' (matches both) or None (no match).
    Matching is exact first, then substring in either direction, all
    case/punctuation-insensitive.
    """
    sel = _norm(selection)
    h = _norm(home)
    a = _norm(away)
    if not sel:
        return None
    hits_home = sel == h or (sel in h or h in sel)
    hits_away = sel == a or (sel in a or a in sel)
    if hits_home and hits_away:
        return "ambiguous"
    if hits_home:
        return "home"
    if hits_away:
        return "away"
    return None


def auto_settle(store: BetStore, games: list[GameResult]) -> SettleReport:
    """Settle every pending h2h-style bet that a completed game decides.

    Only bets with market 'h2h' (or unset) are considered — multis, racing
    specials and other multi-leg bets stay pending by design.
    """
    report = SettleReport()
    pending = [b for b in store.list(limit=10_000) if b.result is None]
    for bet in pending:
        if bet.market not in ("h2h", ""):
            continue  # not auto-settlable from a single match result
        match: tuple[GameResult, str] | None = None
        for g in games:
            if not g.completed or not sport_matches(bet.sport, g.sport):
                continue
            side = team_side(bet.selection, g.home, g.away)
            if side in ("home", "away"):
                match = (g, side)
                break
            if side == "ambiguous" and match is None:
                match = (g, "ambiguous")
        if match is None:
            report.unmatched.append(bet)
            continue
        game, side = match
        if side == "ambiguous":
            report.ambiguous.append(bet)
            continue
        if game.home_score == game.away_score:
            report.draws.append(bet)
            continue
        won = (side == "home" and game.home_score > game.away_score) or (
            side == "away" and game.away_score > game.home_score
        )
        store.settle(bet.id, "won" if won else "lost")
        refreshed = store.get(bet.id)
        if refreshed is not None:
            report.settled.append(refreshed)
    return report


def games_from_scores_api(raw: list[dict]) -> list[GameResult]:
    """Parse game dicts into GameResult — accepts both the-odds-api /scores
    shape ({home_team, away_team, scores, completed, sport_title}) and the
    plain file shape ({home, away, home_score, away_score, completed, sport})."""
    games: list[GameResult] = []
    for g in raw:
        if "home_team" in g and "scores" in g:  # the-odds-api shape
            scores = {
                s.get("name", "").lower(): int(s.get("score") or 0)
                for s in g.get("scores", [])
            }
            home = g.get("home_team", "")
            away = g.get("away_team", "")
            games.append(
                GameResult(
                    home=home,
                    away=away,
                    home_score=scores.get(home.lower(), 0),
                    away_score=scores.get(away.lower(), 0),
                    completed=bool(g.get("completed")),
                    sport=g.get("sport_title", ""),
                )
            )
        else:  # plain file shape
            games.append(
                GameResult(
                    home=g.get("home", ""),
                    away=g.get("away", ""),
                    home_score=int(g.get("home_score") or 0),
                    away_score=int(g.get("away_score") or 0),
                    completed=bool(g.get("completed", True)),
                    sport=g.get("sport", ""),
                )
            )
    return games

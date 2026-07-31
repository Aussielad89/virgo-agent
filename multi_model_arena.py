"""
multi_model_arena.py — ELO-ranked model comparison arena.

Provides:
  - ELO rating system for comparing model responses
  - Arena mode with side-by-side comparison
  - Voting UI to rank which response is better
  - Persistent ratings in .virgo_memory/arena_ratings.json

Usage from chat:
  /arena <query>  — launch arena mode with selected models
  /arena-rankings — show current ELO rankings
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
RATINGS_FILE = HERE / ".virgo_memory" / "arena_ratings.json"

# ELO parameters
K_FACTOR = 32  # Rating change per match
DEFAULT_RATING = 1500  # Starting rating for new models


class EloRanker:
    """Manages ELO ratings for model comparison."""

    def __init__(self) -> None:
        self._ratings: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        """Load ratings from disk."""
        if RATINGS_FILE.exists():
            try:
                data = json.loads(RATINGS_FILE.read_text(encoding="utf-8"))
                self._ratings = data.get("ratings", {})
            except Exception:
                self._ratings = {}

    def _save(self) -> None:
        """Save ratings to disk."""
        RATINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RATINGS_FILE.write_text(json.dumps({"ratings": self._ratings}, indent=2), encoding="utf-8")

    def get_rating(self, model: str) -> int:
        """Get rating for a model, defaulting to 1500."""
        return self._ratings.get(model, DEFAULT_RATING)

    def record_match(self, winner: str, loser: str) -> dict[str, int]:
        """Record a match outcome. Returns updated ratings."""
        ra = self.get_rating(winner)
        rb = self.get_rating(loser)

        ea = 1 / (1 + 10 ** ((rb - ra) / 400))
        eb = 1 / (1 + 10 ** ((ra - rb) / 400))

        new_ra = int(ra + K_FACTOR * (1 - ea))
        new_rb = int(rb + K_FACTOR * (0 - eb))

        self._ratings[winner] = new_ra
        self._ratings[loser] = new_rb
        self._save()

        return {winner: new_ra, loser: new_rb}

    def get_rankings(self) -> list[tuple[str, int]]:
        """Return models sorted by rating (descending)."""
        return sorted(self._ratings.items(), key=lambda x: -x[1])

    def to_markdown(self) -> str:
        """Generate a markdown table of rankings."""
        lines = ["| Model | Rating |", "|-------|--------|"]
        for model, rating in self.get_rankings():
            lines.append(f"| {model} | {rating} |")
        return "\n".join(lines)

    def save_results(self) -> None:
        """Public method to save the current ratings to disk."""
        self._save()

# Global singleton
_ranker: EloRanker | None = None


def get_ranker() -> EloRanker:
    """Get or create the global ELO ranker."""
    global _ranker
    if _ranker is None:
        _ranker = EloRanker()
    return _ranker


def arena_match(models: list[str], responses: dict[str, str], winner: str | None = None) -> dict[str, Any]:
    """Record an arena match result.

    Args:
        models: List of model names that participated
        responses: Dict mapping model name to response text
        winner: The model whose response won (if user voted)

    Returns:
        Dict with rankings and match info
    """
    ranker = get_ranker()

    if winner and winner in models:
        # Find the loser (the one with lowest rating)
        losers = [m for m in models if m != winner]
        loser = min(losers, key=lambda m: ranker.get_rating(m)) if losers else winner
        changes = ranker.record_match(winner, loser)
    else:
        changes = {}

    return {
        "models": models,
        "responses": responses,
        "rating_changes": changes,
        "rankings": dict(ranker.get_rankings()),
    }
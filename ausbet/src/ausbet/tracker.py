"""Bet tracking & bankroll: SQLite-backed store with P&L statistics."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RESULTS = ("won", "lost", "void")


@dataclass
class Bet:
    """A single recorded bet. `odds` is always decimal."""

    bookmaker: str
    sport: str
    selection: str
    odds: float
    stake: float
    competition: str = ""
    market: str = ""
    result: str | None = None  # None = pending, else won / lost / void
    payout: float | None = None  # actual return incl. stake (defaults to odds*stake on win)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    id: int | None = None

    def __post_init__(self) -> None:
        if self.odds < 1.0:
            raise ValueError(f"odds must be >= 1.0, got {self.odds}")
        if self.stake <= 0:
            raise ValueError(f"stake must be > 0, got {self.stake}")
        if self.result is not None and self.result not in RESULTS:
            raise ValueError(f"result must be one of {RESULTS}, got {self.result!r}")


    @property
    def return_amount(self) -> float:
        """Actual return for settled bets; 0 for pending (not yet decided)."""
        if self.result == "won":
            return self.payout if self.payout is not None else round(self.odds * self.stake, 2)
        if self.result == "lost":
            return self.payout if self.payout is not None else 0.0
        if self.result == "void":
            return self.payout if self.payout is not None else self.stake
        return 0.0


@dataclass
class Stats:
    """Rolled-up P&L. `void` bets count as settled with stake returned."""

    total_bets: int = 0
    settled: int = 0
    pending: int = 0
    staked: float = 0.0
    returned: float = 0.0
    profit: float = 0.0
    roi_pct: float = 0.0
    strike_rate_pct: float = 0.0
    avg_odds: float = 0.0
    by_sport: dict[str, dict] = field(default_factory=dict)
    by_bookmaker: dict[str, dict] = field(default_factory=dict)


class BetStore:
    """SQLite persistence for bets. Stdlib-only."""

    def __init__(self, db_path: str | Path = "ausbet.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                sport TEXT NOT NULL,
                competition TEXT NOT NULL DEFAULT '',
                market TEXT NOT NULL DEFAULT '',
                selection TEXT NOT NULL,
                odds REAL NOT NULL,
                stake REAL NOT NULL,
                result TEXT,
                payout REAL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def add(self, bet: Bet) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO bets (timestamp, bookmaker, sport, competition, market,
                              selection, odds, stake, result, payout)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bet.timestamp, bet.bookmaker, bet.sport, bet.competition, bet.market,
             bet.selection, bet.odds, bet.stake, bet.result, bet.payout),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list(self, pending_only: bool = False, limit: int = 100) -> list[Bet]:
        q = "SELECT * FROM bets"
        if pending_only:
            q += " WHERE result IS NULL"
        q += " ORDER BY id DESC LIMIT ?"
        rows = self._conn.execute(q, (limit,)).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def get(self, bet_id: int) -> Bet | None:
        row = self._conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return self._row_to_bet(row) if row else None

    def settle(self, bet_id: int, result: str, payout: float | None = None) -> Bet:
        if result not in RESULTS:
            raise ValueError(f"result must be one of {RESULTS}, got {result!r}")
        bet = self.get(bet_id)
        if bet is None:
            raise KeyError(f"no bet with id {bet_id}")
        if result == "won":
            payout = round(payout if payout is not None else bet.odds * bet.stake, 2)
        elif result == "void":
            payout = round(payout if payout is not None else bet.stake, 2)
        else:  # lost
            payout = round(payout or 0.0, 2)
        self._conn.execute(
            "UPDATE bets SET result = ?, payout = ? WHERE id = ?", (result, payout, bet_id)
        )
        self._conn.commit()
        updated = self.get(bet_id)
        assert updated is not None
        return updated

    def delete(self, bet_id: int) -> None:
        cur = self._conn.execute("DELETE FROM bets WHERE id = ?", (bet_id,))
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no bet with id {bet_id}")

    def export_csv(self, path: str | Path) -> Path:
        path = Path(path)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=[f.name for f in Bet.__dataclass_fields__.values()])
            writer.writeheader()
            for bet in self.list(limit=10_000):
                writer.writerow(asdict(bet))
        return path

    def stats(self) -> Stats:
        bets = self.list(limit=10_000)
        settled = [b for b in bets if b.result is not None]
        pending = [b for b in bets if b.result is None]
        staked = sum(b.stake for b in settled)
        returned = sum(b.return_amount for b in settled)
        wins = [b for b in settled if b.result == "won"]
        decided = [b for b in settled if b.result in ("won", "lost")]

        def dim(bets_: list[Bet], key_field: str) -> dict[str, dict]:
            out: dict[str, dict] = {}
            for b in bets_:
                if b.result is None:
                    continue
                key = getattr(b, key_field)
                d = out.setdefault(key, {"bets": 0, "staked": 0.0, "profit": 0.0})
                d["bets"] += 1
                d["staked"] += b.stake
                d["profit"] += b.return_amount - b.stake
            for d in out.values():
                d["roi_pct"] = round(d["profit"] / d["staked"] * 100.0, 2) if d["staked"] else 0.0
            return out

        by_bookmaker = dim(settled, "bookmaker")
        by_sport = dim(settled, "sport")

        return Stats(
            total_bets=len(bets),
            settled=len(settled),
            pending=len(pending),
            staked=round(staked, 2),
            returned=round(returned, 2),
            profit=round(returned - staked, 2),
            roi_pct=round((returned - staked) / staked * 100.0, 2) if staked else 0.0,
            strike_rate_pct=round(len(wins) / len(decided) * 100.0, 2) if decided else 0.0,
            avg_odds=round(sum(b.odds for b in decided) / len(decided), 2) if decided else 0.0,
            by_sport=by_sport,
            by_bookmaker=by_bookmaker,
        )

    @staticmethod
    def _row_to_bet(row: sqlite3.Row) -> Bet:
        return Bet(
            id=row["id"],
            timestamp=row["timestamp"],
            bookmaker=row["bookmaker"],
            sport=row["sport"],
            competition=row["competition"] or "",
            market=row["market"] or "",
            selection=row["selection"],
            odds=row["odds"],
            stake=row["stake"],
            result=row["result"],
            payout=row["payout"],
        )

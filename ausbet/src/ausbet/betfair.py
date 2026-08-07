"""Betfair Exchange adapter (API-ng): back + lay prices as an OddsSource.

Auth uses the interactive login endpoint (username/password + app key).
Credentials come from env vars:

    BETFAIR_APP_KEY     your application key (register at developer.betfair.com)
    BETFAIR_USERNAME    exchange account username
    BETFAIR_PASSWORD    exchange account password

Offline mode: pass `fixture=` (or `--fixture`) with a JSON file shaped like

    {
      "catalogue": [
        {"marketId": "1.234567890", "marketName": "Match Odds",
         "marketStartTime": "...", "event": {"name": "Geelong v Collingwood"},
         "runners": [{"selectionId": 1, "runnerName": "Geelong"}, ...]}
      ],
      "book": [
        {"marketId": "1.234567890",
         "runners": [{"selectionId": 1, "ex": {"availableToBack": [{"price": 1.88, "size": 2500}],
                                                "availableToLay": [{"price": 1.89, "size": 1200}]}}, ...]}
      ]
    }

Lay prices ride along on `Outcome.lay`; the comparator renders them as a
side-by-side when present. Back prices are what makes Betfair comparable with
the fixed-odds bookmakers.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ausbet.compare import MarketOdds, OddsSource, Outcome

EXCHANGE_BASE = "https://api.betfair.com/exchange/betting/rest/v1.0"
IDENTITY_LOGIN = "https://identitysso.betfair.com/api/login"

# Common event types (id -> label). Pass your own via event_type_ids.
EVENT_TYPES: dict[int, str] = {
    7: "horse racing",
    1: "soccer",
    4: "cricket",
    5: "rugby union",
    16: "american football",
    17: "basketball",
    20: "greyhound racing",
    1477: "NRL",
    61420: "AFL",
}


class BetfairError(RuntimeError):
    pass


class BetfairExchangeSource:
    """Implements the OddsSource protocol with Betfair exchange back prices."""

    name = "betfair-exchange"

    def __init__(
        self,
        app_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        event_type_ids: tuple[str, ...] = ("61420",),
        max_results: int = 15,
        fixture: str | Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.app_key = app_key or os.environ.get("BETFAIR_APP_KEY", "")
        self.username = username or os.environ.get("BETFAIR_USERNAME", "")
        self.password = password or os.environ.get("BETFAIR_PASSWORD", "")
        self.event_type_ids = list(event_type_ids)
        self.max_results = max_results
        self.fixture = Path(fixture) if fixture else None
        self.timeout = timeout
        self._token: str | None = None

    # ------------------------------------------------------------- auth

    def login(self) -> str:
        if not (self.app_key and self.username and self.password):
            raise RuntimeError(
                "Betfair credentials missing — set BETFAIR_APP_KEY, BETFAIR_USERNAME "
                "and BETFAIR_PASSWORD, or use --fixture for offline mode."
            )
        body = urllib.parse.urlencode(
            {"username": self.username, "password": self.password}
        ).encode()
        req = urllib.request.Request(
            IDENTITY_LOGIN,
            data=body,
            headers={
                "X-Application": self.app_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise BetfairError(f"login request failed: {exc}") from exc
        if payload.get("status") != "SUCCESS":
            raise BetfairError(f"login failed: {payload.get('error', 'unknown error')}")
        self._token = payload["token"]
        return self._token

    def logout(self) -> None:
        self._token = None

    # ------------------------------------------------------------- api

    def _post(self, endpoint: str, payload: dict) -> list:
        if not self._token:
            self.login()
        url = f"{EXCHANGE_BASE}/{endpoint}/"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "X-Authentication": self._token or "",
                "X-Application": self.app_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise BetfairError(f"{endpoint} failed: {exc}") from exc

    # ------------------------------------------------------------- fetch

    def fetch(self) -> list[MarketOdds]:
        if self.fixture:
            return self._parse(json.loads(self.fixture.read_text(encoding="utf-8")))
        catalogue = self._post(
            "listMarketCatalogue",
            {
                "filter": {"eventTypeIds": self.event_type_ids},
                "maxResults": self.max_results,
                "sort": "FIRST_TO_START",
                "marketProjection": ["COMPETITION", "EVENT", "RUNNER_DESCRIPTION"],
            },
        )
        market_ids = [m["marketId"] for m in catalogue]
        if not market_ids:
            return []
        book = self._post(
            "listMarketBook",
            {
                "marketIds": market_ids,
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
            },
        )
        return self._parse({"catalogue": catalogue, "book": book})

    @staticmethod
    def _parse(payload: dict) -> list[MarketOdds]:
        """Pure catalogue+book -> MarketOdds. Back = Outcome.odds, lay rides along."""
        book_by_id = {b["marketId"]: b for b in payload.get("book", [])}
        markets: list[MarketOdds] = []
        for cat in payload.get("catalogue", []):
            market_id = cat.get("marketId")
            rb = book_by_id.get(market_id, {})
            runners_book = {rd["selectionId"]: rd for rd in rb.get("runners", [])}
            outcomes = []
            for runner in cat.get("runners", []):
                rd = runners_book.get(runner["selectionId"], {})
                ex = rd.get("ex", {})
                backs = ex.get("availableToBack", []) or []
                lays = ex.get("availableToLay", []) or []
                if not backs:
                    continue  # no back price -> nothing to compare
                outcomes.append(
                    Outcome(
                        name=runner.get("runnerName", str(runner["selectionId"])),
                        bookmaker="Betfair",
                        odds=float(backs[0]["price"]),
                        lay=float(lays[0]["price"]) if lays else None,
                    )
                )
            if not outcomes:
                continue
            event = cat.get("event", {}).get("name", "") or cat.get("competition", {}).get("name", "")
            markets.append(
                MarketOdds(
                    sport="Betfair Exchange",
                    event=event,
                    market=cat.get("marketName", "Match Odds"),
                    outcomes=outcomes,
                    start_time=cat.get("marketStartTime"),
                    market_id=market_id,
                )
            )
        return markets

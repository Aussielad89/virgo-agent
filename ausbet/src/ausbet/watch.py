"""Arb watcher: poll an odds source and alert when a market's best prices
sum to under 100% (a guaranteed-profit structure). Modeled on the virgo
watchdog pattern: a bounded loop with a `--once` mode for cron use.

Notification: console by default, optional HTTP POST webhook (json payload).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ausbet import arbitrage as arb
from ausbet.compare import MarketOdds, compare


@dataclass
class ArbAlert:
    """One detected arbitrage opportunity."""

    sport: str
    event: str
    market: str
    overround_pct: float
    odds: list[float]
    selections: list[str]
    stakes: list[float]
    profit: float
    roi_pct: float
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def summary(self) -> str:
        lines = [
            f"ARB {self.detected_at} — {self.sport} | {self.event} [{self.market}]",
            f"  overround {self.overround_pct:.2f}%",
        ]
        for name, stake, o in zip(self.selections, self.stakes, self.odds):
            lines.append(f"  {name:<24} ${stake:>8.2f} @ {o:.2f}")
        lines.append(f"  lock ${self.profit:+.2f} on ${sum(self.stakes):.2f} (ROI {self.roi_pct:+.2f}%)")
        return "\n".join(lines)


def scan_for_arbs(
    markets: list[MarketOdds],
    min_roi: float = 0.0,
    stake: float = 100.0,
) -> list[ArbAlert]:
    """Find markets whose best-of-book prices imply < 100% overround."""
    alerts: list[ArbAlert] = []
    for comp in compare(markets):
        if comp.best_overround_pct >= 100.0:
            continue
        plan = arb.arbitrage_stakes([o for _, o in comp.best.values()], stake)
        if plan.roi_pct < min_roi:
            continue
        alerts.append(
            ArbAlert(
                sport=comp.sport,
                event=comp.event,
                market=comp.market,
                overround_pct=comp.best_overround_pct,
                odds=plan.odds,
                selections=list(comp.best),
                stakes=plan.stakes,
                profit=plan.profit,
                roi_pct=plan.roi_pct,
            )
        )
    return alerts


def watch_once(source, min_roi: float = 0.0, stake: float = 100.0) -> list[ArbAlert]:
    """Single fetch + scan. Raises on source errors so callers can decide."""
    return scan_for_arbs(source.fetch(), min_roi, stake)


def notify(alerts: list[ArbAlert], webhook_url: str | None = None) -> None:
    for a in alerts:
        print(a.summary())
        print()
    if webhook_url and alerts:
        payload = json.dumps(
            {
                "agent": "ausbet-watch",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "arbs": [a.__dict__ for a in alerts],
            },
            default=str,
        ).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"webhook returned HTTP {resp.status}")


def watch_loop(
    source,
    interval: float = 300.0,
    cycles: int = 0,
    min_roi: float = 0.0,
    stake: float = 100.0,
    webhook_url: str | None = None,
    quiet: bool = False,
) -> None:
    """Run N cycles (0 = forever). Each cycle: fetch, scan, alert if any."""
    n = 0
    while cycles == 0 or n < cycles:
        n += 1
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            markets = source.fetch()
            alerts = scan_for_arbs(markets, min_roi, stake)
        except (RuntimeError, OSError, ValueError) as exc:
            if not quiet:
                print(f"[{stamp}] source error: {exc}", file=sys.stderr)
        else:
            if alerts:
                notify(alerts, webhook_url)
            elif not quiet:
                print(f"[{stamp}] checked {len(markets)} markets — no arbs")
        if cycles == 0 or n < cycles:
            time.sleep(max(1.0, interval))

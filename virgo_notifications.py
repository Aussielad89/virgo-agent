"""
virgo_notifications — notification store + source scanning for Virgo.

Aggregates framework outputs (alerts, diagnostics report, network map,
activity log) into one deduped, JSON-backed feed that the desktop GUI
surfaces as a notification centre with system toasts.

Pure stdlib so it can be imported and tested without PyQt6.

Usage:
    from virgo_notifications import store
    new_items = store.scan_all()        # returns only newly recorded items
    store.emit("chat", "Memory saved", "Recorded exchange", severity="info")
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import OUTDIR  # noqa: E402

STORE_PATH = HERE / ".virgo_notifications.json"

_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _now() -> str:
    """ISO timestamp with second precision (local time)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _digest(*parts: str) -> str:
    """Short content hash used for deduplication."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()[:16]


def _severity(text: str) -> str:
    """Guess a severity level from free-form text."""
    low = (text or "").lower()
    if "critical" in low or "error" in low:
        return "critical"
    if "warning" in low or "warn" in low:
        return "warning"
    return "info"


class NotificationStore:
    """Persistent, deduped notification feed.

    Sources emit items with ``emit()``; duplicate content (same source,
    title and message) is dropped so re-scanning files never duplicates.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else STORE_PATH
        self._items: list[dict] = []
        self._seen: set[str] = set()
        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else []
        except Exception:
            items = []
        for it in items:
            if isinstance(it, dict) and it.get("digest"):
                self._items.append(it)
                self._seen.add(it["digest"])

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")
        except OSError:
            pass  # read-only location: keep the in-memory feed usable

    # ── public API ───────────────────────────────────────────────────

    def emit(
        self,
        source: str,
        title: str,
        message: str,
        severity: str = "info",
        ts: str | None = None,
    ) -> dict | None:
        """Record a notification; returns the new item or None on duplicate."""
        digest = _digest(source, title, message)
        if digest in self._seen:
            return None
        self._seen.add(digest)
        item = {
            "id": len(self._items) + 1,
            "ts": ts or _now(),
            "source": source,
            "severity": severity if severity in _SEVERITY_ORDER else "info",
            "title": title,
            "message": message,
            "digest": digest,
            "read": False,
        }
        self._items.append(item)
        self._save()
        return item

    def all(self) -> list[dict]:
        """Every stored notification (oldest first)."""
        return list(self._items)

    def unread(self) -> list[dict]:
        return [it for it in self._items if not it.get("read")]

    def mark_read(self, nid: int) -> None:
        for it in self._items:
            if it.get("id") == nid:
                it["read"] = True
        self._save()

    def mark_all_read(self) -> None:
        for it in self._items:
            it["read"] = True
        self._save()

    def clear(self) -> None:
        self._items = []
        self._seen = set()
        self._save()

    # ── source scanning ──────────────────────────────────────────────

    def scan_alerts(self) -> list[dict]:
        """Read ALERTS_TRIGGERED.txt lines into notifications."""
        path = OUTDIR / "ALERTS_TRIGGERED.txt"
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return []
        new: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            it = self.emit("alerts", "Alert triggered", line, severity=_severity(line))
            if it:
                new.append(it)
        return new

    def scan_report(self) -> list[dict]:
        """Surface findings from the diagnostics report JSON."""
        path = OUTDIR / "virgo_full_report.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        new: list[dict] = []

        log_analysis = data.get("3_log_analysis")
        if isinstance(log_analysis, list):
            for entry in log_analysis[:10]:
                if not isinstance(entry, dict):
                    continue
                raw = str(entry.get("raw_log", "")).strip()
                action = str(entry.get("suggested_action", "")).strip()
                msg = f"{raw}\n{action}" if action else raw
                if not msg:
                    continue
                it = self.emit("diagnostics", "Diagnostic finding", msg, severity=_severity(msg))
                if it:
                    new.append(it)

        health = data.get("2_system_health")
        if isinstance(health, dict) and health:
            summary = ", ".join(f"{k}={v}" for k, v in list(health.items())[:6])
            it = self.emit("diagnostics", "System health", summary, severity="info")
            if it:
                new.append(it)
        return new

    def scan_network(self) -> list[dict]:
        """Summarise the latest network scan into one notification."""
        path = OUTDIR / "virgo_network_map.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            hosts = data.get("subnet_scan_results", {}) if isinstance(data, dict) else {}
        except Exception:
            return []
        if not isinstance(hosts, dict) or not hosts:
            return []
        total_ports = sum(len(v) if isinstance(v, list) else 1 for v in hosts.values())
        sample = ", ".join(
            f"{ip}:{','.join(map(str, ports)) if isinstance(ports, list) else ports}"
            for ip, ports in list(hosts.items())[:5]
        )
        it = self.emit(
            "network",
            "Network scan",
            f"{len(hosts)} host(s) found, {total_ports} open port(s). {sample}",
            severity="info",
        )
        return [it] if it else []

    def scan_activity(self) -> list[dict]:
        """Import recent events from the activity log."""
        path = OUTDIR / "virgo_activity_log.json"
        if not path.exists():
            return []
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(events, list):
            return []
        new: list[dict] = []
        for ev in events[-20:]:
            if not isinstance(ev, dict):
                continue
            event = str(ev.get("event", "")).strip()
            detail = str(ev.get("detail", "")).strip()
            if not event and not detail:
                continue
            ts = str(ev.get("timestamp", ""))[:19]
            it = self.emit(
                "activity",
                f"Activity: {event or 'event'}",
                detail or event,
                severity="info",
                ts=ts or None,
            )
            if it:
                new.append(it)
        return new

    def scan_all(self) -> list[dict]:
        """Scan every source; returns only the newly recorded items."""
        new: list[dict] = []
        for fn in (self.scan_alerts, self.scan_report, self.scan_network, self.scan_activity):
            try:
                new.extend(fn())
            except Exception:
                continue  # one bad source must not break the rest
        return new


# Module-level singleton shared by the desktop pages.
store = NotificationStore()

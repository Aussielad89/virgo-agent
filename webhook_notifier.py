"""Dispatch webhooks using configs from router.json webhooks section."""

import json
import os
import urllib.request
from pathlib import Path
from _log import log


def _load_webhooks() -> list[dict]:
    repo_root = Path(__file__).resolve().parent
    router_path = repo_root / "router.json"
    if not router_path.exists():
        return []
    try:
        with router_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("webhooks") or []
    except Exception as exc:
        log(f"webhook_notifier: failed to load router.json: {exc}")
        return []


def dispatch(event: str, payload: dict) -> bool:
    webhooks = _load_webhooks()
    if not webhooks:
        return False
    success = False
    for config in webhooks:
        url = config.get("url")
        if not url:
            continue
        try:
            body = json.dumps({"event": event, "payload": payload}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status < 300:
                    success = True
        except Exception as exc:
            log(f"webhook_notifier: dispatch failed for {url}: {exc}")
    return success

"""
a2a_client — call another A2A (Agent-to-Agent) agent from Virgo.

Lets Virgo *talk to* a remote A2A agent discovered via its AgentCard:

  * ``fetch_agent_card(url)`` — GET the ``/.well-known/agent.json``.
  * ``send_task(url, text)``  — JSON-RPC ``tasks/send``; returns the agent's
                            reply text (the first artifact part).
  * ``A2AClient``            — small wrapper that caches the card and exposes
                            ``send(text)`` plus ``skills`` for introspection.

Stdlib only (``urllib.request``). Failures return error strings rather than
raising, so the client is safe to embed in a tool/agent without taking down
the caller.

Example::

    from a2a_client import A2AClient
    peer = A2AClient("http://127.0.0.1:8080")
    print(peer.card["name"])
    print(peer.send("summarise the last scan"))
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from _console import icon
from _log import log

PROTOCOL_VERSION = "0.2.0"
DEFAULT_TIMEOUT = 30.0


def _http_json(url: str, payload: dict | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET *url* (when *payload* is None) or POST JSON and parse the response."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (caller-supplied url)
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _card_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/.well-known/agent.json"):
        return base
    return base + "/.well-known/agent.json"


def fetch_agent_card(base_url: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """Fetch and return the remote agent's AgentCard, or None on failure."""
    try:
        return _http_json(_card_url(base_url), timeout=timeout)
    except Exception as exc:
        log.warning("a2a: cannot fetch AgentCard from %s: %s", base_url, exc)
        return None


def _rpc(url: str, method: str, params: dict, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": _new_id(),
        "method": method,
        "params": params,
    }
    return _http_json(url, payload, timeout=timeout)


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex


def _first_text(task: dict) -> str:
    """Extract the first text artifact from a Task response."""
    for art in task.get("artifacts", []) or []:
        for part in art.get("parts", []) or []:
            if isinstance(part, dict) and part.get("kind") == "text":
                return part.get("text", "")
            if isinstance(part, dict) and "text" in part:
                return str(part["text"])
    # Fall back to history messages.
    for msg in task.get("history", []) or []:
        if isinstance(msg, dict) and msg.get("role") == "agent":
            return _first_text_from_parts(msg.get("parts", []))
    return "(no text result)"


def _first_text_from_parts(parts: list) -> str:
    out = []
    for part in parts or []:
        if isinstance(part, dict) and part.get("kind") == "text":
            out.append(part.get("text", ""))
    return "\n".join(out)


def send_task(
    base_url: str,
    text: str,
    *,
    context_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Send *text* to a remote A2A agent and return its reply text.

    Returns an ``ERROR: ...`` string on any failure instead of raising.
    """
    endpoint = base_url.rstrip("/") + "/"
    task_id = _new_id()
    params: dict[str, Any] = {
        "id": task_id,
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
        },
    }
    if context_id:
        params["contextId"] = context_id
    try:
        resp = _rpc(endpoint, "tasks/send", params, timeout=timeout)
    except Exception as exc:
        return f"ERROR: a2a call failed: {exc}"
    if "error" in resp:
        return f"ERROR: {resp['error'].get('message', 'unknown a2a error')}"
    return _first_text(resp.get("result", {}))


# ── Convenience wrapper ───────────────────────────────────────────────

@dataclass
class A2AClient:
    """Stateful handle to a remote A2A agent (caches its AgentCard)."""

    base_url: str
    card: dict | None = field(default=None, repr=False)
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        self.card = fetch_agent_card(self.base_url, timeout=self.timeout)

    @property
    def name(self) -> str:
        return (self.card or {}).get("name", self.base_url)

    @property
    def skills(self) -> list[dict]:
        return (self.card or {}).get("skills", []) or []

    @property
    def available(self) -> bool:
        return self.card is not None

    def send(self, text: str, *, context_id: str | None = None) -> str:
        return send_task(
            self.base_url,
            text,
            context_id=context_id,
            timeout=self.timeout,
        )

    def discover(self, goal_hint: str = "") -> list[dict]:
        """Return skills whose tags/examples match *goal_hint* (best-effort)."""
        if not goal_hint:
            return self.skills
        hint = goal_hint.lower()
        return [
            s
            for s in self.skills
            if any(hint in (t.lower()) for t in (s.get("tags", []) + s.get("examples", [])))
        ]


def main() -> None:  # pragma: no cover - manual CLI
    import sys

    if len(sys.argv) < 2:
        print(f"{icon('agent')}  Usage: python a2a_client.py <base_url> [message]")
        return
    base = sys.argv[1]
    msg = " ".join(sys.argv[2:]) or "ping"
    client = A2AClient(base)
    if not client.available:
        print(f"{icon('error')}  Could not reach A2A agent at {base}")
        return
    print(f"{icon('agent')}  {client.name}: sending {msg!r}")
    print(client.send(msg))


if __name__ == "__main__":
    main()

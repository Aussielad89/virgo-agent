"""Tests for the A2A (Agent-to-Agent) server + client."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from a2a_server import (
    _default_runner,  # noqa: F401 (importability smoke)
    _dispatch,
    _goal_from_message,
    _handle_tasks_get,
    _TaskStore,
    build_agent_card,
)
from a2a_client import _first_text, send_task


def _fake_runner(goal: str) -> str:
    return f"ran: {goal}"


def _store() -> _TaskStore:
    return _TaskStore()


# ── AgentCard ─────────────────────────────────────────────────────────

def test_agent_card_shape():
    card = build_agent_card("127.0.0.1", 8080)
    assert card["name"] == "Virgo"
    assert card["url"] == "http://127.0.0.1:8080/"
    assert "/.well-known/agent.json" not in card["url"]
    assert any(s["id"] == "codegen" for s in card["skills"])
    assert card["capabilities"]["stateTransitionHistory"] is True


# ── message parsing ───────────────────────────────────────────────────

def test_goal_from_message_text_part():
    msg = {"role": "user", "parts": [{"kind": "text", "text": "do the thing"}]}
    assert _goal_from_message(msg) == "do the thing"


def test_goal_from_message_legacy_text_key():
    assert _goal_from_message({"parts": [{"text": "hi"}]}) == "hi"


def test_goal_from_message_empty():
    assert _goal_from_message({}) == ""


# ── dispatch routing ──────────────────────────────────────────────────

def test_tasks_send_returns_completed_task():
    store = _store()
    resp = _dispatch(
        {
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": "t1",
                "message": {"role": "user", "parts": [{"kind": "text", "text": "scan"}]},
            },
        },
        store,
        _fake_runner,
    )
    assert resp["id"] == 1
    task = resp["result"]
    assert task["status"]["state"] == "completed"
    assert task["id"] == "t1"
    artifact_text = task["artifacts"][0]["parts"][0]["text"]
    assert artifact_text == "ran: scan"
    # It should be retrievable via tasks/get
    stored = store.get("t1")
    assert stored is not None


def test_tasks_send_empty_goal_errors():
    resp = _dispatch(
        {"id": 2, "method": "tasks/send", "params": {"message": {"parts": []}}},
        _store(),
        _fake_runner,
    )
    assert resp["error"]["code"] == -32602


def test_tasks_get_unknown_errors():
    resp = _dispatch(
        {"id": 3, "method": "tasks/get", "params": {"id": "nope"}},
        _store(),
        _fake_runner,
    )
    assert resp["error"]["code"] == -32001


def test_dispatch_unknown_method_errors():
    resp = _dispatch({"id": 4, "method": "bogus", "params": {}}, _store(), _fake_runner)
    assert resp["error"]["code"] == -32601


def test_dispatch_survives_handler_crash():
    def _boom(goal: str) -> str:
        raise RuntimeError("kaboom")

    resp = _dispatch(
        {
            "id": 5,
            "method": "tasks/send",
            "params": {"message": {"parts": [{"kind": "text", "text": "x"}]}},
        },
        _store(),
        _boom,
    )
    # The server layer turns a runner exception into a completed task whose
    # artifact reports the error rather than crashing the dispatch.
    assert resp["id"] == 5
    assert "kaboom" in resp["result"]["artifacts"][0]["parts"][0]["text"]


# ── client text extraction ────────────────────────────────────────────

def test_first_text_from_artifact():
    task = {
        "artifacts": [{"parts": [{"kind": "text", "text": "hello"}]}],
        "history": [],
    }
    assert _first_text(task) == "hello"


def test_first_text_fallback_to_history():
    task = {
        "artifacts": [],
        "history": [{"role": "agent", "parts": [{"kind": "text", "text": "from hist"}]}],
    }
    assert _first_text(task) == "from hist"


# ── live in-process HTTP round-trip ───────────────────────────────────

def _start_server():
    from a2a_server import _make_server

    # Bind to an ephemeral port so parallel/sequential tests never collide
    # on a TIME_WAIT socket from a prior shutdown.
    probe = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: None)
    free_port = probe.server_address[1]
    probe.server_close()

    srv = _make_server("127.0.0.1", free_port, runner=_fake_runner)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{free_port}"
    # wait for the port to be open
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    return srv, base


def test_live_agent_card_http():
    srv, base = _start_server()
    try:
        with urllib.request.urlopen(base + "/.well-known/agent.json", timeout=5) as r:
            card = json.loads(r.read())
        assert card["name"] == "Virgo"
    finally:
        srv.shutdown()


def test_live_tasks_send_http():
    srv, base = _start_server()
    try:
        out = send_task(base, "live ping", timeout=5)
        assert out == "ran: live ping"
    finally:
        srv.shutdown()

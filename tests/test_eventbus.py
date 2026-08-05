"""
Tests for virgo_eventbus — the Event / Webhook Bus.

These exercise the matching engine, cron parser, persistence, and each
source adapter (webhook via a real local HTTP server, file-drop via a temp
dir, telegram via the listener hook).  They avoid the heavy orchestrator by
injecting a fake workflow runner.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from virgo_eventbus import (
    BusEvent,
    CronSource,
    EventBus,
    FileDropSource,
    TelegramSource,
    Trigger,
    WebhookSource,
    cron_matches,
    get_bus,
    trigger_matches,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _tmp_config() -> Path:
    d = Path(tempfile.mkdtemp(prefix="virgo_eventbus_"))
    return d / "eventbus.json"


def _fake_runner(goal, action, event):  # noqa: ANN001
    return {"status": "ok", "goal": goal}


# ── cron parser ──────────────────────────────────────────────────────────


def test_cron_matches_every_minute():
    from datetime import datetime

    assert cron_matches("* * * * *", datetime(2026, 1, 1, 12, 30))
    assert cron_matches("*/1 * * * *", datetime(2026, 1, 1, 12, 30))


def test_cron_matches_step():
    from datetime import datetime

    assert cron_matches("*/5 * * * *", datetime(2026, 1, 1, 10, 0))
    assert not cron_matches("*/5 * * * *", datetime(2026, 1, 1, 10, 1))
    assert cron_matches("0,30 * * * *", datetime(2026, 1, 1, 10, 30))


def test_cron_matches_dow_and_hour():
    from datetime import datetime

    # Friday 2026-07-31 09:00 -> "0 9 * * 1-5" should match
    assert cron_matches("0 9 * * 1-5", datetime(2026, 7, 31, 9, 0))
    # Saturday 2026-08-01 09:00 -> should NOT match weekday schedule
    assert not cron_matches("0 9 * * 1-5", datetime(2026, 8, 1, 9, 0))
    # 9am every day
    assert cron_matches("0 9 * * *", datetime(2026, 8, 1, 9, 0))
    assert not cron_matches("0 9 * * *", datetime(2026, 8, 1, 10, 0))


def test_cron_invalid_expr_returns_false():
    assert cron_matches("not a cron", None) is False
    assert cron_matches("* * *", None) is False


# ── matching ─────────────────────────────────────────────────────────────


def test_trigger_matches_text_filters():
    t = Trigger(
        id="1", name="t", source="webhook",
        match={"contains": "ping"}, action={"type": "notify"},
    )
    assert trigger_matches(t, BusEvent("e", "webhook", "w", "please ping me"))
    assert not trigger_matches(t, BusEvent("e", "webhook", "w", "hello"))
    assert not trigger_matches(t, BusEvent("e", "telegram", "t", "ping"))  # wrong source


def test_trigger_matches_exact_startswith_regex_glob():
    exact = Trigger(id="1", name="t", source="webhook", match={"exact": "go"}, action={})
    assert trigger_matches(exact, BusEvent("e", "webhook", "w", "go"))
    assert not trigger_matches(exact, BusEvent("e", "webhook", "w", "go now"))

    sw = Trigger(id="2", name="t", source="webhook", match={"startswith": "run"}, action={})
    assert trigger_matches(sw, BusEvent("e", "webhook", "w", "run me"))

    rx = Trigger(id="3", name="t", source="webhook", match={"regex": r"^\d+$"}, action={})
    assert trigger_matches(rx, BusEvent("e", "webhook", "w", "123"))
    assert not trigger_matches(rx, BusEvent("e", "webhook", "w", "abc"))

    gl = Trigger(id="4", name="t", source="file", match={"glob": "*.py"}, action={})
    assert trigger_matches(gl, BusEvent("e", "file", "f", "main.py"))
    assert not trigger_matches(gl, BusEvent("e", "file", "f", "main.txt"))


def test_trigger_matches_payload_filters():
    uname = Trigger(
        id="1", name="t", source="telegram",
        match={"username": "alice"}, action={},
    )
    assert trigger_matches(
        uname,
        BusEvent("e", "telegram", "t", "hi", {"username": "alice"}),
    )
    assert not trigger_matches(
        uname,
        BusEvent("e", "telegram", "t", "hi", {"username": "bob"}),
    )
    tag = Trigger(
        id="2", name="t", source="webhook",
        match={"tag": "deploy"}, action={},
    )
    assert trigger_matches(
        tag, BusEvent("e", "webhook", "w", "x", {"tag": "deploy"})
    )


# ── bus core ─────────────────────────────────────────────────────────────


def test_bus_emit_fires_matching_trigger():
    bus = EventBus(config_path=_tmp_config())
    bus.workflow_runner = _fake_runner
    bus.add_trigger(
        Trigger(
            id="tw", name="wh", source="webhook",
            match={"contains": "ping"}, action={"type": "notify", "message": "pong"},
        )
    )
    fired = bus.emit(BusEvent("x", "webhook", "w", "ping now"))
    assert fired == ["tw"]
    assert bus.stats["fired"] == 1
    assert bus.stats["events"] == 1


def test_bus_disabled_trigger_does_not_fire():
    bus = EventBus(config_path=_tmp_config())
    bus.workflow_runner = _fake_runner
    bus.add_trigger(
        Trigger(
            id="tw", name="wh", source="webhook",
            match={"contains": "ping"}, action={"type": "notify"}, enabled=False,
        )
    )
    fired = bus.emit(BusEvent("x", "webhook", "w", "ping now"))
    assert fired == []


def test_bus_trigger_workflow_now():
    bus = EventBus(config_path=_tmp_config())
    bus.workflow_runner = _fake_runner
    t = bus.add_trigger(
        Trigger(id="tw", name="wh", source="webhook", match={},
                action={"type": "pipeline", "goal": "do a thing"})
    )
    result = bus.trigger_workflow_now(t.id)
    assert result["status"] == "ok"
    assert bus.get_trigger(t.id).runs == 1
    assert bus.get_trigger(t.id).last_run is not None


def test_bus_persistence_roundtrip():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    bus.add_trigger(
        Trigger(id="abc", name="persisted", source="cron",
                match={"schedule": "0 9 * * *"}, action={"type": "notify"})
    )
    assert cfg.exists()
    # A fresh bus with the same config path should reload the trigger.
    bus2 = EventBus(config_path=cfg)
    loaded = bus2.get_trigger("abc")
    assert loaded is not None
    assert loaded.name == "persisted"
    assert loaded.match["schedule"] == "0 9 * * *"


def test_bus_remove_and_enable():
    bus = EventBus(config_path=_tmp_config())
    t = bus.add_trigger(
        Trigger(id="rm", name="x", source="webhook", match={}, action={})
    )
    assert bus.remove_trigger("rm") is True
    assert bus.get_trigger("rm") is None
    assert bus.enable_trigger("rm", True) is False  # gone


# ── run_action variants ──────────────────────────────────────────────────


def test_run_action_notify_and_pipeline_and_shell():
    from virgo_eventbus import run_action

    ev = BusEvent("e", "webhook", "w", "hi")
    n = run_action({"type": "notify", "message": "ok"}, ev, _fake_runner)
    assert n["status"] == "notified"

    p = run_action({"type": "pipeline", "goal": "build"}, ev, _fake_runner)
    assert p["status"] == "ok"

    # shell: echo should succeed
    sh = run_action({"type": "shell", "cmd": "echo hello-from-bus"}, ev, _fake_runner)
    assert sh["status"] == "ok"
    assert "hello-from-bus" in sh["stdout"]

    # shell: failing command -> error
    sh2 = run_action({"type": "shell", "cmd": "exit 3"}, ev, _fake_runner)
    assert sh2["status"] == "error"


# ── webhook source (real local server) ───────────────────────────────────


def test_webhook_source_receives_post_and_fires():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    bus.workflow_runner = _fake_runner
    port = _free_port()
    src = WebhookSource(bus, host="127.0.0.1", port=port, path="/webhook")
    bus.sources["webhook"] = src
    bus.add_trigger(
        Trigger(id="wh", name="wh", source="webhook",
                match={"contains": "ping"}, action={"type": "notify", "message": "pong"})
    )

    captured: list[str] = []
    bus.set_listener(lambda ev, fired: captured.extend(fired))

    src.start()
    try:
        # give the server a moment to bind
        time.sleep(0.6)
        payload = json.dumps({"text": "ping me"}).encode()
        req = Request(
            f"http://127.0.0.1:{port}/webhook",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        assert body["status"] == "received"
        # wait for the listener callback (queued, async)
        deadline = time.time() + 3
        while not captured and time.time() < deadline:
            time.sleep(0.05)
        assert "wh" in captured, f"trigger not fired; captured={captured}"
    finally:
        src.stop()


def test_webhook_source_token_gate():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    port = _free_port()
    src = WebhookSource(bus, host="127.0.0.1", port=port, path="/webhook", token="secret")
    src.start()
    try:
        time.sleep(0.6)
        # no token -> 401
        req = Request(
            f"http://127.0.0.1:{port}/webhook",
            data=b'{"text":"x"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=5) as resp:
                status = resp.status
        except Exception as exc:  # urllib raises on 401
            status = getattr(exc, "code", None)
        assert status == 401
    finally:
        src.stop()


# ── file-drop source ─────────────────────────────────────────────────────


def test_file_drop_source_emits_on_change():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    watch_dir = tempfile.mkdtemp(prefix="virgo_watch_")
    src = FileDropSource(bus, watch_dir=watch_dir, interval=0.2, debounce=0.1)

    captured: list[BusEvent] = []
    bus.set_listener(lambda ev, fired: captured.append(ev))

    src.start()
    try:
        # Let the watcher take its initial (empty) snapshot before we drop a
        # file — otherwise the change is invisible and never detected.
        time.sleep(0.5)
        # create a file
        Path(watch_dir, "hello.txt").write_text("hi", encoding="utf-8")
        deadline = time.time() + 6
        while not any(e.source == "file" for e in captured) and time.time() < deadline:
            time.sleep(0.1)
        file_events = [e for e in captured if e.source == "file"]
        assert file_events, "no file event captured"
        assert "hello.txt" in file_events[0].payload.get("changed", [])
    finally:
        src.stop()


# ── telegram source ───────────────────────────────────────────────────────


def test_telegram_source_starts_and_registers_listener_without_token():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    src = TelegramSource(bus, autostart_bot=True)
    # With no TELEGRAM_BOT_TOKEN set, start() must register the listener
    # and return without crashing.
    src.start()
    try:
        # Emit a synthetic message through the bot's broadcast path.
        from virgo_bot import MESSAGE_LISTENERS, _broadcast_message

        assert src._listener_ref in MESSAGE_LISTENERS
        captured: list[BusEvent] = []
        bus.set_listener(lambda ev, fired: captured.append(ev))
        _broadcast_message(
            {"chat_id": 123, "text": "ping from tg", "username": "alice",
             "timestamp": "2026-01-01T00:00:00Z"}
        )
        assert any(e.source == "telegram" and e.text == "ping from tg" for e in captured)
    finally:
        src.stop()


# ── cron source integration (short tick) ─────────────────────────────────


def test_cron_source_fires_enabled_cron_trigger():
    cfg = _tmp_config()
    bus = EventBus(config_path=cfg)
    bus.workflow_runner = _fake_runner
    src = CronSource(bus)
    src.TICK = 0.3  # speed up the check loop for the test
    bus.add_trigger(
        Trigger(id="cron1", name="every minute", source="cron",
                match={"schedule": "* * * * *"},
                action={"type": "notify", "message": "tick"})
    )
    captured: list[BusEvent] = []
    bus.set_listener(lambda ev, fired: captured.append(ev))
    src.start()
    try:
        deadline = time.time() + 4
        while not any(e.source == "cron" for e in captured) and time.time() < deadline:
            time.sleep(0.1)
        cron_events = [e for e in captured if e.source == "cron"]
        assert cron_events, "cron source did not fire"
    finally:
        src.stop()


# ── get_bus singleton ─────────────────────────────────────────────────────


def test_get_bus_singleton():
    a = get_bus()
    b = get_bus()
    assert a is b


if __name__ == "__main__":
    import subprocess
    import sys

    raise SystemExit(
        subprocess.run(
            [sys.executable, "-m", "pytest", __file__, "-v"]
        ).returncode
    )

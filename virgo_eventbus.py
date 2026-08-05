"""
virgo_eventbus — Event / Webhook Bus to trigger Virgo workflows externally.

The bus turns *external events* into *workflow runs*.  Four event sources are
shipped:

    telegram  inbound Telegram messages  (reuses virgo_bot's listener hook)
    file      file-drop watcher          (reuses virgo_watcher.FileWatcher)
    cron      scheduled triggers         (built-in 5-field cron, no deps)
    webhook   inbound HTTP webhook       (Flask, with stdlib http.server fallback)

Flow
----
A ``Source`` adapter emits a :class:`BusEvent`.  The bus matches the event
against every enabled :class:`Trigger` whose ``source`` matches.  A matching
trigger enqueues its *action* on a worker thread, which runs it:

    action.type == "pipeline"  -> run the Virgo orchestrator pipeline
                                  (the existing workflow engine) for a goal
    action.type == "shell"     -> run a shell command
    action.type == "notify"    -> just log (no side effect)

Import safety
-------------
Heavy dependencies (``flask``, ``virgo_bot``, ``orchestrator``) are imported
*lazily* inside the functions that need them, so simply importing this module
never requires them.  The desktop UI can therefore always import the bus.

Usage
-----
    from virgo_eventbus import get_bus
    bus = get_bus()
    bus.add_trigger(Trigger(
        name="Nightly report",
        source="cron",
        match={"schedule": "0 9 * * *"},
        action={"type": "pipeline", "goal": "generate the daily report"},
    ))
    bus.start()
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in os.sys.path:  # pragma: no cover - best effort
    os.sys.path.insert(0, str(HERE))

from _console import icon
from _log import OUTDIR, log

# Where trigger config is persisted between sessions.
CONFIG_PATH = OUTDIR / "virgo_eventbus.json"

SOURCE_NAMES = ("telegram", "file", "cron", "webhook")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


# ═════════════════════════════════════════════════════════════════════════
# Data model
# ═════════════════════════════════════════════════════════════════════════


@dataclass
class BusEvent:
    """An event arriving from one of the bus sources."""

    id: str
    source: str
    name: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Trigger:
    """A subscription: when *source* emits an event matching *match*,
    run *action*."""

    id: str
    name: str
    source: str  # one of SOURCE_NAMES
    match: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    runs: int = 0
    last_run: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trigger":
        return cls(
            id=d.get("id") or _short_id(),
            name=d.get("name", "untitled"),
            source=d.get("source", "webhook"),
            match=d.get("match", {}) or {},
            action=d.get("action", {}) or {},
            enabled=bool(d.get("enabled", True)),
            runs=int(d.get("runs", 0)),
            last_run=d.get("last_run"),
        )


# ═════════════════════════════════════════════════════════════════════════
# Matching
# ═════════════════════════════════════════════════════════════════════════


def trigger_matches(trigger: Trigger, event: BusEvent) -> bool:
    """Return True if *event* satisfies *trigger.match* (source already matched)."""
    if trigger.source != event.source:
        return False
    m = trigger.match or {}
    text = event.text or ""

    if "exact" in m and m["exact"] != text:
        return False
    if "contains" in m and m["contains"] not in text:
        return False
    if "startswith" in m and not text.startswith(str(m["startswith"])):
        return False
    if "endswith" in m and not text.endswith(str(m["endswith"])):
        return False
    if "regex" in m:
        try:
            if not re.compile(m["regex"]).search(text):
                return False
        except re.error:
            return False
    if "glob" in m:
        import fnmatch

        if not fnmatch.fnmatch(text, m["glob"]):
            return False
    # payload-based matchers
    if "username" in m and event.payload.get("username") != m["username"]:
        return False
    if "tag" in m and event.payload.get("tag") != m["tag"]:
        return False
    if "path" in m and event.payload.get("path") != m["path"]:
        return False
    if "header" in m:
        for k, v in m["header"].items():
            if event.payload.get("headers", {}).get(k) != v:
                return False
    return True


# ═════════════════════════════════════════════════════════════════════════
# Cron parsing (dependency-free, 5-field)
# ═════════════════════════════════════════════════════════════════════════


def _cron_field(field: str, current: int, low: int, high: int) -> bool:
    """Evaluate one cron field (e.g. '*/5', '1-3', '2,4,6', '*', '5')."""
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and current % step == 0:
                return True
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if int(a) <= current <= int(b):
                return True
            continue
        if int(part) == current:
            return True
    return False


def cron_matches(expr: str, dt: datetime | None = None) -> bool:
    """Return True if *expr* (``m h dom mon dow``) matches the minute of *dt*.

    dow: 0=Sunday..6=Saturday (also accepts 7==Sunday).  dom/mon/dow may be '*'.
    """
    dt = dt or datetime.now()
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, mon, dow = parts
    if not _cron_field(minute, dt.minute, 0, 59):
        return False
    if not _cron_field(hour, dt.hour, 0, 23):
        return False
    if not _cron_field(mon, dt.month, 1, 12):
        return False
    # day-of-month / day-of-week: cron treats either matching as a hit
    if dom != "*" or dow != "*":
        dom_ok = _cron_field(dom, dt.day, 1, 31) if dom != "*" else False
        w = dt.weekday()  # Mon=0..Sun=6
        dow_val = (w + 1) % 7  # convert to 0=Sun..6=Sat
        dow_ok = _cron_field(dow, dow_val, 0, 7) if dow != "*" else False
        if dom != "*" and dow != "*":
            if not (dom_ok or dow_ok):
                return False
        elif dom != "*":
            if not dom_ok:
                return False
        elif dow != "*":
            if not dow_ok:
                return False
    return True


# ═════════════════════════════════════════════════════════════════════════
# Workflow action execution (the connection to the workflow engine)
# ═════════════════════════════════════════════════════════════════════════


def default_workflow_runner(goal: str, action: dict[str, Any], event: BusEvent) -> dict[str, Any]:
    """Run a Virgo orchestrator pipeline for *goal* (the existing workflow engine).

    Mirrors the in-process invocation used by ``virgo_watcher.run_pipeline`` so
    the bus connects directly to the same engine the CLI/dashboard use.
    """
    base_path = action.get("dir") or str(Path.cwd())
    max_iterations = int(action.get("max_iterations", 3))
    try:
        from environment import AgentEnvironment
        from orchestrator import Orchestrator
        from tools import ToolRegistry
    except Exception as exc:  # pragma: no cover - import guard
        return {"status": "error", "error": f"workflow engine import failed: {exc}"}

    try:
        env = AgentEnvironment(base_path=base_path)
        registry = ToolRegistry()
        orch = Orchestrator(
            env,
            registry,
            base_path=base_path,
            workspace_excludes=[
                "__pycache__",
                ".git",
                ".venv",
                "agent_env",
                ".virgo_memory",
                ".coverage",
                "dist",
                "virgo_agent.egg-info",
            ],
        )
        state = orch.run(
            goal=goal,
            max_iterations=max_iterations,
            auto_approve=True,
            run_critic=False,
            auto_depend=False,
        )
        files = [gf.path for gf in state.generated_files] if state else []
        return {
            "status": "ok",
            "goal": goal,
            "phase": getattr(state, "phase", None),
            "files": len(files),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def run_action(action: dict[str, Any], event: BusEvent, runner: Callable) -> dict[str, Any]:
    """Execute a trigger action.  Dispatches on ``action['type']``."""
    atype = (action or {}).get("type", "pipeline")
    if atype == "notify":
        return {"status": "notified", "message": action.get("message", event.text)}
    if atype == "shell":
        cmd = action.get("cmd", "")
        if not cmd:
            return {"status": "error", "error": "shell action has no 'cmd'"}
        import subprocess

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=int(action.get("timeout", 300)),
            )
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-2000:],
                "stderr": (proc.stderr or "")[-2000:],
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "shell command timed out"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
    # default: pipeline
    goal = action.get("goal") or event.text
    if not goal:
        return {"status": "error", "error": "pipeline action needs a 'goal'"}
    return runner(goal, action, event)


# ═════════════════════════════════════════════════════════════════════════
# Source adapters
# ═════════════════════════════════════════════════════════════════════════


class BaseSource:
    """Base class for event sources."""

    name = "base"

    def __init__(self, bus: "EventBus") -> None:
        self.bus = bus
        self._running = False

    def start(self) -> None:  # pragma: no cover - overridden
        self._running = True

    def stop(self) -> None:  # pragma: no cover - overridden
        self._running = False

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "running": self._running}


class TelegramSource(BaseSource):
    """Emits an event for every authorized inbound Telegram message.

    Reuses ``virgo_bot``: it registers a listener via ``add_message_listener``
    (which we added to virgo_bot) and optionally starts the bot if it isn't
    already polling.  This avoids running a second polling loop on the token.
    """

    name = "telegram"

    def __init__(self, bus: "EventBus", autostart_bot: bool = True) -> None:
        super().__init__(bus)
        self.autostart_bot = autostart_bot
        self._listener_ref: Callable[[dict], None] | None = None

    def _on_message(self, data: dict) -> None:
        evt = BusEvent(
            id=_short_id(),
            source="telegram",
            name="telegram",
            text=data.get("text", ""),
            payload={
                "chat_id": data.get("chat_id"),
                "username": data.get("username"),
                "timestamp": data.get("timestamp"),
            },
        )
        self.bus.emit(evt)

    def start(self) -> None:
        try:
            from virgo_bot import (
                add_message_listener,
                is_running,
                start_polling,
            )
        except Exception as exc:
            log.warning("Telegram source unavailable: %s", exc)
            return

        if self.autostart_bot and not is_running():
            try:
                start_polling()
            except Exception as exc:  # pragma: no cover - env dependent
                log.warning("Could not autostart Telegram bot: %s", exc)

        self._listener_ref = self._on_message
        add_message_listener(self._listener_ref)
        self._running = True
        log.info("Telegram event source started")

    def stop(self) -> None:
        if self._listener_ref is not None:
            try:
                from virgo_bot import remove_message_listener

                remove_message_listener(self._listener_ref)
            except Exception:
                pass
            self._listener_ref = None
        self._running = False


class FileDropSource(BaseSource):
    """Emits an event whenever files change under a watched directory."""

    name = "file"

    def __init__(
        self,
        bus: "EventBus",
        watch_dir: str = ".",
        goal: str = "",
        interval: float = 2.0,
        debounce: float = 1.0,
    ) -> None:
        super().__init__(bus)
        self.watch_dir = watch_dir
        self.goal = goal
        self.interval = interval
        self.debounce = debounce
        self._thread: threading.Thread | None = None
        self._watcher = None

    def _on_change(self, changed: list[str]) -> None:
        evt = BusEvent(
            id=_short_id(),
            source="file",
            name="file-drop",
            text=changed[0] if changed else "file change",
            payload={"changed": changed, "dir": str(self.watch_dir)},
        )
        self.bus.emit(evt)

    def start(self) -> None:
        try:
            from virgo_watcher import FileWatcher
        except Exception as exc:
            log.warning("File-drop source unavailable: %s", exc)
            return

        self._watcher = FileWatcher(
            self.watch_dir,
            interval=self.interval,
            debounce=self.debounce,
        )
        self._thread = threading.Thread(
            target=self._watcher.start,
            args=(self._on_change,),
            daemon=True,
        )
        self._thread.start()
        self._running = True
        log.info("File-drop event source started on %s", self.watch_dir)

    def stop(self) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                pass
        self._running = False


class CronSource(BaseSource):
    """Fires events for every enabled ``cron`` trigger when its schedule hits."""

    name = "cron"
    TICK = 15  # seconds between schedule checks

    def __init__(self, bus: "EventBus") -> None:
        super().__init__(bus)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fired_minute: dict[str, str] = {}

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            for trig in list(self.bus.triggers):
                if trig.source != "cron" or not trig.enabled:
                    continue
                schedule = (trig.match or {}).get("schedule", "")
                if not schedule:
                    continue
                if not cron_matches(schedule, now):
                    continue
                if self._fired_minute.get(trig.id) == minute_key:
                    continue
                self._fired_minute[trig.id] = minute_key
                goal = trig.action.get("goal") or trig.name
                evt = BusEvent(
                    id=_short_id(),
                    source="cron",
                    name=trig.name,
                    text=goal,
                    payload={"trigger_id": trig.id, "tag": (trig.match or {}).get("tag")},
                )
                self.bus.emit(evt)
            self._stop.wait(self.TICK)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._running = True
        log.info("Cron event source started")

    def stop(self) -> None:
        self._stop.set()
        self._running = False


class WebhookSource(BaseSource):
    """HTTP webhook endpoint.  Uses Flask if available, else stdlib fallback.

    Accepts POST to the configured path (default ``/webhook``) and any
    ``/webhook/<name>`` sub-path.  The JSON body becomes the event payload;
    a top-level ``text`` field becomes the event text, otherwise the body is
    summarised.  An optional ``token`` query/header check can gate access.
    """

    name = "webhook"

    def __init__(
        self,
        bus: "EventBus",
        host: str = "0.0.0.0",
        port: int = 8765,
        path: str = "/webhook",
        token: str = "",
    ) -> None:
        super().__init__(bus)
        self.host = host
        self.port = port
        self.path = path.rstrip("/") or "/webhook"
        self.token = token
        self._thread: threading.Thread | None = None
        self._server = None
        self._flask_app = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"

    def _authorized(self, provided: str | None) -> bool:
        if not self.token:
            return True
        return provided == self.token

    def _handle(self, path: str, method: str, headers: dict, body: bytes) -> tuple[int, str]:
        try:
            raw = json.loads(body.decode("utf-8", "replace") or "{}")
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {"value": raw}

        provided = headers.get("X-Webhook-Token") or headers.get("Authorization")
        if provided and provided.lower().startswith("bearer "):
            provided = provided[7:]
        if not self._authorized(provided):
            return 401, json.dumps({"error": "unauthorized"})

        # Flatten body into payload; keep headers for matching.
        payload = dict(raw)
        payload["path"] = path
        payload["method"] = method
        payload["headers"] = {k: v for k, v in headers.items()}

        text = str(raw.get("text") or raw.get("message") or raw.get("event") or "")
        name = path[len(self.path):].strip("/") or "webhook"
        evt = BusEvent(
            id=_short_id(),
            source="webhook",
            name=name,
            text=text,
            payload=payload,
        )
        self.bus.emit(evt)
        return 200, json.dumps({"status": "received", "event_id": evt.id})

    def _start_flask(self) -> None:
        from flask import Flask, request

        app = Flask("virgo_eventbus")
        self._flask_app = app

        @app.route(self.path, methods=["POST"])
        @app.route(self.path + "/<path:name>", methods=["POST"])
        def _ingest(name: str = ""):  # noqa: ANN001
            status, body = self._handle(
                f"{self.path}/{name}" if name else self.path,
                request.method,
                {k: v for k, v in request.headers.items()},
                request.get_data(),
            )
            return body, status

        @app.route(self.path, methods=["GET"])
        def _health():
            return json.dumps({"status": "virgo event bus webhook", "source": "webhook"}), 200

        app.run(host=self.host, port=self.port, threaded=True, use_reloader=False)

    def _start_stdlib(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        source = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""
                status, out = source._handle(
                    self.path,
                    self.command,
                    {k: v for k, v in self.headers.items()},
                    body,
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out.encode("utf-8"))

            def log_message(self, *args):  # silence default logging
                return

        self._server = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._server.serve_forever()

    def start(self) -> None:
        try:
            import flask  # noqa: F401

            backend = "flask"
        except Exception:
            backend = "stdlib"

        self._backend = backend
        target = self._start_flask if backend == "flask" else self._start_stdlib
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        self._running = True
        log.info("Webhook event source started on %s (backend: %s)", self.url, backend)

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        # Flask's dev server thread cannot be cleanly shut down without the
        # server object; we mark stopped and rely on daemon-thread exit at
        # process end.  Re-starting picks a fresh server.
        self._running = False


# ═════════════════════════════════════════════════════════════════════════
# Event bus
# ═════════════════════════════════════════════════════════════════════════


class EventBus:
    """The Event / Webhook Bus: matches events to triggers and runs actions."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else CONFIG_PATH
        self.triggers: list[Trigger] = []
        self.sources: dict[str, BaseSource] = {}
        self._queue: queue.Queue[tuple[str, BusEvent]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._listener: Callable[[BusEvent, list[str]], None] | None = None
        self.workflow_runner: Callable = default_workflow_runner
        self.stats = {"events": 0, "fired": 0, "errors": 0}
        self._register_builtin_sources()
        self._load()

    # ── Lifecycle ──────────────────────────────────────────────────

    def _register_builtin_sources(self) -> None:
        self.sources = {
            "telegram": TelegramSource(self),
            "file": FileDropSource(self),
            "cron": CronSource(self),
            "webhook": WebhookSource(self),
        }

    def set_listener(self, fn: Callable[[BusEvent, list[str]], None]) -> None:
        """Register a UI/log callback invoked as ``fn(event, fired_trigger_ids)``."""
        self._listener = fn

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        for src in self.sources.values():
            try:
                src.start()
            except Exception as exc:
                log.warning("Source %s failed to start: %s", src.name, exc)
        log.info("Event bus started (%d triggers)", len(self.triggers))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for src in self.sources.values():
            try:
                src.stop()
            except Exception as exc:
                log.warning("Source %s failed to stop: %s", src.name, exc)
        # Unblock the worker loop
        self._queue.put(("__stop__", None))  # type: ignore[arg-type]
        log.info("Event bus stopped")

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "triggers": len(self.triggers),
            "enabled_triggers": sum(1 for t in self.triggers if t.enabled),
            "stats": dict(self.stats),
            "sources": {name: src.status() for name, src in self.sources.items()},
        }

    # ── Trigger management ─────────────────────────────────────────

    def add_trigger(self, trigger: Trigger) -> Trigger:
        with self._lock:
            self.triggers.append(trigger)
            self._save()
        return trigger

    def remove_trigger(self, trigger_id: str) -> bool:
        with self._lock:
            before = len(self.triggers)
            self.triggers = [t for t in self.triggers if t.id != trigger_id]
            removed = len(self.triggers) != before
            if removed:
                self._save()
        return removed

    def get_trigger(self, trigger_id: str) -> Trigger | None:
        with self._lock:
            return next((t for t in self.triggers if t.id == trigger_id), None)

    def enable_trigger(self, trigger_id: str, enabled: bool) -> bool:
        with self._lock:
            trig = next((t for t in self.triggers if t.id == trigger_id), None)
            if trig is None:
                return False
            trig.enabled = enabled
            self._save()
        return True

    def list_triggers(self) -> list[Trigger]:
        with self._lock:
            return list(self.triggers)

    def trigger_workflow_now(self, trigger_id: str) -> dict[str, Any] | None:
        """Manually fire a trigger (used by the UI 'Run now' button)."""
        trig = self.get_trigger(trigger_id)
        if trig is None:
            return None
        evt = BusEvent(
            id=_short_id(),
            source=trig.source,
            name=trig.name,
            text=trig.action.get("goal", "") or "",
            payload={"manual": True, "trigger_id": trig.id},
        )
        return self._dispatch(trig, evt)

    # ── Event ingest ───────────────────────────────────────────────

    def emit(self, event: BusEvent) -> list[str]:
        """Match *event* against triggers; enqueue + return fired trigger ids."""
        with self._lock:
            fired = [
                t.id for t in self.triggers if t.enabled and trigger_matches(t, event)
            ]
        self.stats["events"] += 1
        if fired:
            self.stats["fired"] += len(fired)
            for tid in fired:
                self._queue.put((tid, event))
        if self._listener:
            try:
                self._listener(event, fired)
            except Exception as exc:
                log.warning("event listener error: %s", exc)
        return fired

    def _dispatch(self, trig: Trigger, event: BusEvent) -> dict[str, Any]:
        """Run *trig*'s action immediately (used by worker + manual fire)."""
        try:
            result = run_action(trig.action, event, self.workflow_runner)
            status = result.get("status", "ok")
        except Exception as exc:  # pragma: no cover - defensive
            result = {"status": "error", "error": str(exc)}
            status = "error"
        with self._lock:
            trig.runs += 1
            trig.last_run = _now_iso()
            if status == "error":
                self.stats["errors"] += 1
            self._save()
        return result

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item[0] == "__stop__":
                break
            trigger_id, event = item
            trig = self.get_trigger(trigger_id)
            if trig is None or not trig.enabled:
                continue
            self._dispatch(trig, event)

    # ── Persistence ────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = {
                "triggers": [t.to_dict() for t in self.triggers],
                "stats": dict(self.stats),
            }
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("Failed to save event bus config: %s", exc)

    def _load(self) -> None:
        try:
            if not self.config_path.exists():
                return
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            with self._lock:
                self.triggers = [
                    Trigger.from_dict(t) for t in data.get("triggers", [])
                ]
                self.stats.update(data.get("stats", {}))
        except Exception as exc:
            log.warning("Failed to load event bus config: %s", exc)


# ═════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═════════════════════════════════════════════════════════════════════════


_bus_singleton: EventBus | None = None


def get_bus() -> EventBus:
    """Return the process-wide EventBus singleton."""
    global _bus_singleton
    if _bus_singleton is None:
        _bus_singleton = EventBus()
    return _bus_singleton


# ═════════════════════════════════════════════════════════════════════════
# CLI smoke test
# ═════════════════════════════════════════════════════════════════════════


def _demo() -> None:
    bus = get_bus()
    bus.add_trigger(
        Trigger(
            name="Demo: ping webhook",
            source="webhook",
            match={"contains": "ping"},
            action={"type": "notify", "message": "pong"},
        )
    )
    bus.start()
    print(f"{icon('ok')} Event bus running. Webhook URL: {bus.sources['webhook'].url}")
    print(f"{icon('info')} POST {{\"text\": \"ping\"}} to that URL to fire a trigger.")
    print(f"{icon('info')} Triggers: {len(bus.list_triggers())}")
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        bus.stop()
        print(f"\n{icon('ok')} Event bus stopped.")


if __name__ == "__main__":
    _demo()

"""
a2a_server — expose Virgo as an A2A (Agent-to-Agent) agent.

Implements the discovery + task portions of Google's A2A specification so
Virgo can be *called* by other A2A agents (and advertise itself):

  * ``AgentCard`` served at ``/.well-known/agent.json`` — capabilities,
    skills, and the endpoint URL.
  * JSON-RPC 2.0 over HTTP:
        ``tasks/send``   -> run a goal through :mod:`agent_runtime`, return
                            the result as a Task with artifacts
        ``tasks/get``    -> fetch a previously submitted task by id
        ``message/send`` -> alias of ``tasks/send`` (legacy clients)

Stdlib only (``http.server``). The agent body reuses
``agent_runtime.build_runtime`` — which already folds in MCP tools — so an
A2A caller indirectly gets Virgo's full tool set, including any connected
MCP servers.

Run::

    python a2a_server.py --host 127.0.0.1 --port 8080
    python a2a_server.py --host 0.0.0.0 --port 8080 --llm   # with an LLM

The server is intentionally tolerant: a malformed request becomes a proper
JSON-RPC error, and one bad task never kills the loop.
"""

from __future__ import annotations

import argparse
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from _console import icon
from _log import log

# ── A2A protocol constants ────────────────────────────────────────────
PROTOCOL_VERSION = "0.2.0"
AGENT_NAME = "virgo"
AGENT_VERSION = "0.1.0"

# A task runner maps a goal string -> result text.  Swap for tests.
TaskRunner = Callable[[str], str]


# ── AgentCard (discovery) ─────────────────────────────────────────────

def build_agent_card(host: str = "127.0.0.1", port: int = 8080) -> dict:
    """Return the A2A AgentCard describing this agent."""
    base = f"http://{host}:{port}"
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": "Virgo",
        "description": (
            "Autonomous multi-agent code-generation and system-monitoring "
            "agent. Runs a ReAct loop over builtin tools and any connected "
            "MCP servers."
        ),
        "url": base + "/",
        "provider": {
            "organization": "virgo-agent",
            "url": "https://github.com/Aussielad89/virgo-agent",
        },
        "version": AGENT_VERSION,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "codegen",
                "name": "Code generation",
                "description": "Generate or repair code from a natural-language goal.",
                "tags": ["code", "python"],
                "examples": ["build a port scanner in python"],
            },
            {
                "id": "diagnostics",
                "name": "System diagnostics",
                "description": "Run diagnostics and evaluate alerts on a host.",
                "tags": ["ops", "monitoring"],
            },
            {
                "id": "recon",
                "name": "Network recon",
                "description": "Scan a subnet, discover hosts, grab banners.",
                "tags": ["recon", "network"],
            },
        ],
        "authentication": {"schemes": ["none"]},
    }


# ── In-memory task store ──────────────────────────────────────────────

class _TaskStore:
    """Holds submitted tasks so ``tasks/get`` can retrieve them later."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def put(self, task: dict) -> None:
        with self._lock:
            self._tasks[task["id"]] = task

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            return self._tasks.get(task_id)


# ── Default runner (real agent) ───────────────────────────────────────

def _default_runner(goal: str, use_llm: bool = False) -> str:
    """Execute *goal* through the agent runtime; return transcript text."""
    try:
        from agent_runtime import build_runtime
    except Exception as exc:  # pragma: no cover - import shim
        return f"ERROR: agent_runtime unavailable: {exc}"

    client = None
    if use_llm:
        try:
            import main as _main

            client = _main.get_client_for("agent")
        except Exception as exc:
            log.warning("a2a: LLM client unavailable (%s) — deterministic loop", exc)

    try:
        rt = build_runtime(client=client, config=None, include_mcp=True)
        result = rt.run(goal)
    except Exception as exc:
        return f"ERROR: agent failed: {exc}"
    return result.transcript


# ── JSON-RPC handlers ─────────────────────────────────────────────────

def _rpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _goal_from_message(message: Any) -> str:
    """Extract plain text from an A2A Message's parts."""
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("kind") == "text":
            chunks.append(part.get("text", ""))
        elif isinstance(part, dict) and "text" in part:
            chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()


def _handle_tasks_send(
    req: dict,
    store: _TaskStore,
    runner: TaskRunner,
) -> dict:
    """Handle ``tasks/send`` — run the goal and return a completed Task."""
    params = req.get("params", {}) or {}
    task_id = params.get("id") or uuid.uuid4().hex
    message = params.get("message", {})
    goal = _goal_from_message(message)
    if not goal:
        return _rpc_error(req.get("id"), -32602, "tasks/send requires a non-empty message")

    context_id = params.get("contextId") or uuid.uuid4().hex
    log.info("a2a: task %s -> %r", task_id, goal[:60])
    try:
        output = runner(goal)
    except Exception as exc:  # turn a crashing runner into an errored task,
        # not a killed server / -32603
        output = f"ERROR: agent failed: {exc}"

    task = {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": "completed",
            "timestamp": _now(),
        },
        "artifacts": [
            {
                "artifactId": uuid.uuid4().hex,
                "name": "result",
                "parts": [{"kind": "text", "text": output}],
            }
        ],
        "history": [{"role": "user", "parts": [{"kind": "text", "text": goal}]}],
    }
    store.put(task)
    return _rpc_result(req.get("id"), task)


def _handle_tasks_get(req: dict, store: _TaskStore) -> dict:
    """Handle ``tasks/get`` — return a stored task or a 404-style error."""
    params = req.get("params", {}) or {}
    task_id = params.get("id")
    if not task_id:
        return _rpc_error(req.get("id"), -32602, "tasks/get requires an id")
    task = store.get(task_id)
    if task is None:
        return _rpc_error(req.get("id"), -32001, f"unknown task: {task_id}")
    return _rpc_result(req.get("id"), task)


def _dispatch(
    req: dict,
    store: _TaskStore,
    runner: TaskRunner,
) -> dict:
    """Route one A2A JSON-RPC request to its handler. Never raises."""
    method = req.get("method", "")
    req_id = req.get("id")
    try:
        if method in ("tasks/send", "message/send"):
            return _handle_tasks_send(req, store, runner)
        if method == "tasks/get":
            return _handle_tasks_get(req, store)
        return _rpc_error(req_id, -32601, f"Method not found: {method}")
    except Exception as exc:  # defensive: never kill the server
        log.warning("a2a: dispatch error: %s", exc)
        return _rpc_error(req_id, -32603, f"Internal error: {exc}")


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ── HTTP server ───────────────────────────────────────────────────────

class _A2AHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path in ("/.well-known/agent.json", "/agent.json") or self.path == "/":
            self._send_json(self.card)
        else:
            self._send_json(_rpc_error(None, -32601, f"No route: {self.path}"), status=404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(_rpc_error(None, -32700, "Parse error"), status=400)
            return
        resp = _dispatch(req, self.store, self.runner)
        self._send_json(resp)

    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        pass


def _make_server(
    host: str,
    port: int,
    *,
    use_llm: bool = False,
    runner: TaskRunner | None = None,
) -> ThreadingHTTPServer:
    store = _TaskStore()
    card = build_agent_card(host, port)
    active_runner = runner or (lambda g: _default_runner(g, use_llm=use_llm))

    # Build a dedicated handler subclass so store/card/runner are guaranteed
    # to be present on every request instance.
    # NOTE: `runner` is a callable, so it must be wrapped in staticmethod —
    # assigning a plain function as a class attribute turns `self.runner`
    # into a *bound* method (self becomes the first arg), which breaks the
    # call signature. store/card are non-callable so they're fine as-is.
    class _Handler(_A2AHandler):
        pass

    _Handler.store = store
    _Handler.card = card
    _Handler.runner = staticmethod(active_runner)

    return ThreadingHTTPServer((host, port), _Handler)


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve Virgo as an A2A agent")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--llm", action="store_true", help="Use an LLM-backed agent")
    args = ap.parse_args()

    server = _make_server(args.host, args.port, use_llm=args.llm)
    print(f"{icon('rocket')}  Virgo A2A agent on http://{args.host}:{args.port}/")
    print(f"   AgentCard: http://{args.host}:{args.port}/.well-known/agent.json")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{icon('stop')}  stopped")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

"""
server — virgo web dashboard (FastAPI + HTMX + SSE).

Displays pipeline state in real time, lists saved sessions,
provides live log streaming via SSE, and lets you trigger
agent runs from the browser.

Start with::

    virgo serve
    # or:  python -c "import server; server.serve()"
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# ---------------------------------------------------------------------------
# Lazy imports — report friendly errors if dependencies are missing
# ---------------------------------------------------------------------------

_IMPORTS_OK = True
try:
    import uvicorn  # noqa: F401
    from fastapi import FastAPI, Request  # noqa: F401
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse  # noqa: F401
except ImportError as exc:
    _IMPORTS_OK = False
    _IMPORT_ERROR = exc


# ===========================================================================
# HTML templates (embedded — no external files needed)
# ===========================================================================

_LAYOUT = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>virgo &mdash; dashboard</title>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <style>
    {% raw %}
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      background:#0d0d12; color:#c0c0d0; font-family:system-ui,sans-serif;
      padding:2rem;
    }
    .container { max-width:960px; margin:0 auto; }
    h1 { font-size:1.5rem; font-weight:600; color:#00ffff; margin-bottom:0.25rem; }
    h2 { font-size:1.1rem; font-weight:500; color:#fff; margin:1.5rem 0 0.5rem; }
    .sub { color:#888; font-size:0.85rem; margin-bottom:1.5rem; }
    table { width:100%; border-collapse:collapse; font-size:0.85rem; }
    th,td { text-align:left; padding:0.5rem 0.75rem; border-bottom:1px solid #1e1e2a; }
    th { color:#00ffff; font-weight:500; }
    tr:hover td { background:#14141e; }
    .badge {
      display:inline-block; padding:0.15rem 0.5rem; border-radius:4px;
      font-size:0.75rem; font-weight:600;
    }
    .badge-pass { background:#003322; color:#00ff88; }
    .badge-fail { background:#330011; color:#ff4466; }
    .badge-run  { background:#002233; color:#00ccff; }
    .badge-info { background:#222233; color:#8888ff; }
    .log-box {
      background:#0a0a0f; border:1px solid #1a1a2a; border-radius:6px;
      padding:1rem; font-family:"JetBrains Mono","Fira Code",monospace;
      font-size:0.8rem; line-height:1.5; max-height:500px; overflow-y:auto;
      white-space:pre-wrap; margin-top:0.5rem;
    }
    .log-line { color:#888; }
    .log-line:hover { color:#fff; }
    .log-ts { color:#555; font-size:0.7rem; }
    a { color:#00ccff; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .nav { display:flex; gap:1.5rem; margin-bottom:1.5rem; align-items:center; }
    .nav a { font-size:0.9rem; }
    .status-dot {
      display:inline-block; width:8px; height:8px; border-radius:50%;
      margin-right:0.4rem;
    }
    .dot-green { background:#00ff88; }
    .dot-red   { background:#ff4466; }
    .dot-blue  { background:#00ccff; }
    .empty { color:#555; font-style:italic; }
    input, button, select {
      background:#1a1a2a; color:#c0c0d0; border:1px solid #2a2a3a;
      padding:0.5rem 0.75rem; border-radius:4px; font-size:0.85rem;
    }
    button {
      background:#00ccff; color:#0d0d12; font-weight:600; cursor:pointer;
      border:none; padding:0.5rem 1rem;
    }
    button:hover { background:#00ffff; }
    button:disabled { opacity:0.5; cursor:not-allowed; }
    .run-form { display:flex; gap:0.75rem; align-items:center; flex-wrap:wrap; }
    .run-form input { flex:1; min-width:200px; }
    .stats { display:flex; gap:1.5rem; margin:1rem 0; }
    .stat-card { background:#14141e; border:1px solid #1e1e2a; border-radius:6px;
                  padding:0.75rem 1rem; flex:1; }
    .stat-card .num { font-size:1.5rem; font-weight:700; color:#00ffff; }
    .stat-card .lbl { font-size:0.75rem; color:#888; }
    .toast {
      position:fixed; bottom:2rem; right:2rem; background:#1a1a2a;
      border:1px solid #2a2a3a; border-radius:6px; padding:0.75rem 1rem;
      font-size:0.85rem; display:none; z-index:1000;
    }
    {% endraw %}
  </style>
</head>
<body>
  <div class="container">
    <div class="nav">
      <a href="/">&#9664; sessions</a>
      <a href="/run">&#9654; run</a>
      <a href="/status">&#9679; status</a>
      <span style="color:#333">|</span>
      <span style="color:#00ffff;font-weight:600;">virgo</span>
      <span style="color:#555;font-size:0.8rem;">multi-agent state machine</span>
    </div>
    {{ content|safe }}
  </div>
  <div id="toast" class="toast"></div>
  {% raw %}
  <script>
    function showToast(msg, color) {
      var t = document.getElementById('toast');
      t.style.display = 'block'; t.style.borderColor = color || '#2a2a3a';
      t.innerHTML = msg;
      setTimeout(function(){ t.style.display = 'none'; }, 4000);
    }
  </script>
  {% endraw %}
</body>
</html>
"""

_SESSIONS_PAGE = """\
<h1>&#9672; sessions</h1>
<div class="sub">
  saved pipeline runs &mdash;
  <a href="/log">live log</a> &mdash;
  <a href="/run">new run</a>
</div>

<div class="stats">
  <div class="stat-card"><div class="num">{{ stats.count }}</div><div class="lbl">total runs</div></div>
  <div class="stat-card"><div class="num">{{ stats.passed }}</div><div class="lbl">passed</div></div>
  <div class="stat-card"><div class="num">{{ stats.failed }}</div><div class="lbl">failed</div></div>
</div>

<table>
  <tr><th>run</th><th>goal</th><th>phase</th><th>files</th><th>status</th></tr>
  {% for s in sessions %}
  <tr>
    <td><a href="/session/{{ s.name }}">{{ s.name }}</a></td>
    <td>{{ s.goal }}</td>
    <td>{{ s.phase }}</td>
    <td>{{ s.generated }}</td>
    <td>
      {% if s.loop_passed == true %}<span class="badge badge-pass">PASS</span>
      {% elif s.loop_passed == false %}<span class="badge badge-fail">FAIL</span>
      {% else %}<span class="badge badge-run">incomplete</span>{% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="5" class="empty">no saved sessions yet</td></tr>
  {% endfor %}
</table>
"""

_SESSION_PAGE = """\
<h1>&#9672; {{ name }}</h1>
<div class="sub">{{ goal[:120] }}</div>

<h2>details</h2>
<table>
  <tr><th>phase</th><td>{{ phase }}</td></tr>
  <tr><th>iteration</th><td>{{ iteration }}{% if loop_passed == true %} &mdash; <span class="badge badge-pass">PASS</span>{% endif %}</td></tr>
  <tr><th>generated files</th><td>{{ generated|length }}</td></tr>
  <tr><th>test logs</th><td>{{ test_logs|length }}</td></tr>
</table>

{% if generated %}
<h2>generated files</h2>
<table>
  <tr><th>file</th><th>iteration</th><th>status</th></tr>
  {% for gf in generated %}
  <tr>
    <td>{{ gf.path }}</td>
    <td>{{ gf.iteration }}</td>
    <td>{% if gf.passed == true %}<span class="badge badge-pass">PASS</span>{% else %}<span class="badge badge-fail">FAIL</span>{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if test_logs %}
<h2>test logs</h2>
{% for tl in test_logs %}
<div class="log-box">
  <div class="log-line">exit {{ tl.returncode }} &mdash; {{ tl.file }} (iteration {{ tl.iteration }})</div>
  {% if tl.stderr %}<div class="log-line" style="color:#ff6677;">{{ tl.stderr[:800] }}</div>{% endif %}
  {% if tl.stdout %}<div class="log-line">{{ tl.stdout[:800] }}</div>{% endif %}
</div>
{% endfor %}
{% endif %}
"""

_RUN_PAGE = """\
<h1>&#9654; run pipeline</h1>
<div class="sub">trigger a new agent run from the browser</div>

<form class="run-form" hx-post="/run" hx-target="#run-output" hx-indicator="#run-spinner">
  <input type="text" name="goal" placeholder="e.g. parse mock_logs.txt" required>
  <label><input type="checkbox" name="use_llm" value="1"> use LLM</label>
  <button type="submit">&#9654; run</button>
  <span id="run-spinner" style="display:none;">running...</span>
</form>

<div id="run-output" class="log-box" style="margin-top:1rem;">
  <div class="log-line">output will appear here</div>
</div>

<h2 style="margin-top:2rem;">quick goals</h2>
<div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
  <button hx-post="/run" hx-vals='{"goal":"Scan and parse mock_logs.txt"}'
          hx-target="#run-output">parse mock_logs.txt</button>
  <button hx-post="/run" hx-vals='{"goal":"Write hello.py and run it"}'
          hx-target="#run-output">hello.py</button>
  <button hx-post="/run" hx-vals='{"goal":"List all Python files in the workspace"}'
          hx-target="#run-output">list .py files</button>
</div>
"""

_STATUS_PAGE = """\
<h1>&#9679; system status</h1>
<div class="sub">virgo agent runtime health and stats</div>

<div class="stats" id="status-stats">
  <div class="stat-card"><div class="num">{{ sessions }}</div><div class="lbl">sessions</div></div>
  <div class="stat-card"><div class="num">{{ experiences }}</div><div class="lbl">experiences</div></div>
  <div class="stat-card"><div class="num">{{ plugins }}</div><div class="lbl">plugins</div></div>
  <div class="stat-card"><div class="num">{{ embeddings }}</div><div class="lbl">embeddings</div></div>
</div>

<div class="log-box" id="live-status">
  <div class="log-line">system healthy &mdash; {{ llm_status }}</div>
  <div class="log-line">virgo-agent v{{ version }}</div>
  <div class="log-line">python {{ python_version }}</div>
</div>

<h2>live log</h2>
<div class="log-box" id="log-box"
     hx-ext="sse"
     sse-connect="/log-sse"
     sse-swap="message"
     hx-swap="beforeend">
  <div class="log-line">waiting for log events...</div>
</div>
"""

_LOG_PAGE = """\
<h1>&#9672; live log</h1>
<div class="sub">pipeline output streams here in real time (SSE)</div>
<div class="log-box" id="log-box"
     hx-ext="sse"
     sse-connect="/log-sse"
     sse-swap="message"
     hx-swap="beforeend">
  <div class="log-line">connecting...</div>
</div>
"""


# ===========================================================================
# FastAPI application
# ===========================================================================


def _build_app() -> Any:
    """Create and return the FastAPI ASGI app."""
    import jinja2
    from fastapi import FastAPI, Form
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from sse_starlette.sse import EventSourceResponse

    app = FastAPI(title="virgo", version="0.6.0")
    env = jinja2.Environment(autoescape=True)

    # Shared log buffer (thread-safe)
    log_buffer: list[str] = []
    sse_clients: list[asyncio.Queue] = []

    def _log_line(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_buffer.append(line)
        if len(log_buffer) > 500:
            log_buffer[:100] = []
        # Notify SSE clients
        for q in sse_clients[:]:
            try:
                q.put_nowait(line)
            except Exception:
                if q in sse_clients:
                    sse_clients.remove(q)

    app.state.log_buffer = log_buffer
    app.state.log_line = _log_line
    app.state.sse_clients = sse_clients
    _log_line("virgo dashboard started")

    # ── Routes ────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def sessions_page():
        from memory import list_sessions

        sessions = list_sessions()
        passed = sum(1 for s in sessions if s.get("loop_passed") is True)
        failed = sum(1 for s in sessions if s.get("loop_passed") is False)
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _SESSIONS_PAGE + "{% endblock %}"
            )
        )
        return tpl.render(
            sessions=sessions, stats={"count": len(sessions), "passed": passed, "failed": failed}
        )

    @app.get("/session/{name}", response_class=HTMLResponse)
    async def session_page(name: str):
        from memory import load_state

        try:
            data = load_state(name)
        except FileNotFoundError:
            return HTMLResponse("<h1>not found</h1>", status_code=404)
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _SESSION_PAGE + "{% endblock %}"
            )
        )
        return tpl.render(
            name=name,
            goal=data.get("goal", ""),
            phase=data.get("phase", ""),
            iteration=data.get("iteration", 0),
            loop_passed=data.get("loop_passed"),
            generated=data.get("generated_files", []),
            test_logs=data.get("test_logs", []),
        )

    @app.get("/run", response_class=HTMLResponse)
    async def run_page():
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _RUN_PAGE + "{% endblock %}"
            )
        )
        return tpl.render()

    @app.post("/run", response_class=HTMLResponse)
    async def run_pipeline(goal: str = Form(...), use_llm: str = Form("0")):
        """Trigger a pipeline run asynchronously and stream output via SSE."""
        _log_line(f"Web run: {goal[:80]}" + (" (LLM)" if use_llm == "1" else ""))
        import subprocess
        import sys

        from cli import HERE as _HERE

        cmd = [sys.executable, str(_HERE / "cli.py"), "run", "--goal", goal, "--auto-approve"]
        if use_llm == "1":
            cmd.append("--llm")

        def _run():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                _log_line(f"Web run complete: exit {result.returncode}")
                for line in (result.stdout or "").splitlines()[-50:]:
                    if line.strip():
                        _log_line(f"  {line.strip()[:120]}")
                if result.stderr:
                    for line in result.stderr.splitlines()[-20:]:
                        if line.strip():
                            _log_line(f"  err: {line.strip()[:120]}")
            except subprocess.TimeoutExpired:
                _log_line("Web run timed out after 300s")
            except Exception as exc:
                _log_line(f"Web run error: {exc}")

        import threading

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        return f"""<div class="log-line" style="color:#00ff88;">&#9654; started: {goal[:80]}</div>
<div class="log-line">view output in the <a href="/log">live log</a></div>"""

    @app.get("/status", response_class=HTMLResponse)
    async def status_page():
        from memory import list_sessions

        sessions = list_sessions()
        try:
            from experience import get_memory

            mem = get_memory()
            mem_stats = mem.stats()
        except Exception:
            mem_stats = {"count": 0, "with_embeddings": 0}
        try:
            from plugins import discover

            plugin_count = len(discover())
        except Exception:
            plugin_count = 0
        try:
            # Check LLM status
            import urllib.request

            base = os.environ.get("LLM_BASE_URL", "http://localhost:20128/v1")
            req = urllib.request.Request(f"{base.rstrip('/')}/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                llm_status = "LLM connected" if resp.status == 200 else "LLM unreachable"
        except Exception:
            llm_status = "LLM offline"
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _STATUS_PAGE + "{% endblock %}"
            )
        )
        return tpl.render(
            sessions=len(sessions),
            experiences=mem_stats.get("count", 0),
            embeddings=mem_stats.get("with_embeddings", 0),
            plugins=plugin_count,
            llm_status=llm_status,
            version="0.6.0",
            python_version=sys.version.split()[0],
        )

    @app.get("/log", response_class=HTMLResponse)
    async def log_page():
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _LOG_PAGE + "{% endblock %}"
            )
        )
        return tpl.render()

    @app.get("/log-stream", response_class=PlainTextResponse)
    async def log_stream():
        lines = "\n".join(app.state.log_buffer[-100:]) or "waiting..."
        return lines

    @app.get("/log-sse")
    async def log_sse(request: Request):
        """Server-Sent Events endpoint for real-time log streaming."""
        queue: asyncio.Queue = asyncio.Queue()
        app.state.sse_clients.append(queue)

        # Send existing log buffer on connect
        for line in app.state.log_buffer[-50:]:
            await queue.put(line)

        async def event_generator() -> AsyncGenerator[dict, None]:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        line = await asyncio.wait_for(queue.get(), timeout=10)
                        yield {"event": "message", "data": f"<div class='log-line'>{line}</div>"}
                    except TimeoutError:
                        yield {"event": "heartbeat", "data": ""}
            finally:
                if queue in app.state.sse_clients:
                    app.state.sse_clients.remove(queue)

        return EventSourceResponse(event_generator())

    # ── JSON API ──────────────────────────────────────────────────

    @app.get("/api/sessions")
    async def api_sessions():
        from memory import list_sessions

        return JSONResponse(list_sessions())

    @app.get("/api/session/{name}")
    async def api_session(name: str):
        from memory import load_state

        try:
            return JSONResponse(load_state(name))
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/status")
    async def api_status():
        from memory import list_sessions

        sessions = list_sessions()
        try:
            from experience import get_memory

            mem = get_memory()
            mem_stats = mem.stats()
        except Exception:
            mem_stats = {"count": 0}
        return JSONResponse(
            {
                "sessions": len(sessions),
                "experiences": mem_stats.get("count", 0),
                "version": "0.6.0",
            }
        )

    return app


# ===========================================================================
# Public API
# ===========================================================================


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start the virgo web dashboard."""
    if not _IMPORTS_OK:
        print(f"[virgo] Missing dependencies: {_IMPORT_ERROR}")
        try:
            print("[virgo] Attempting auto-install...")
            import subprocess
            import sys

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "fastapi",
                    "uvicorn",
                    "jinja2",
                    "sse-starlette",
                    "-q",
                ],
                check=True,
            )
            import importlib

            for mod_name in ("fastapi", "uvicorn", "jinja2", "sse_starlette"):
                importlib.invalidate_caches()
                importlib.import_module(mod_name)
            print("[virgo] Dependencies installed successfully!")
        except Exception:
            print("[virgo] Auto-install failed. Install manually:")
            print("  pip install fastapi uvicorn jinja2 sse-starlette")
            sys.exit(1)

    import uvicorn

    app = _build_app()
    print(f"\n  [virgo] Dashboard at  http://{host}:{port}")
    print("  [virgo] Routes:  /sessions  /run  /status  /log  /api/*")
    print("  [virgo] Ctrl+C to stop\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ===========================================================================
# CLI shortcut
# ===========================================================================

if __name__ == "__main__":
    serve()

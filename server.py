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


# ---------------------------------------------------------------------------
# Web-run bookkeeping (module-level, shared across requests)
# ---------------------------------------------------------------------------

_WEB_PROCS: dict[str, Any] = {}  # ts -> Popen for in-flight web runs
_WEB_HISTORY: list[dict[str, Any]] = []  # {ts, goal, exit, duration_s} entries


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
    :root {
      --bg: #1e1e2e;
      --surface: #313244;
      --overlay: #45475a;
      --text: #cdd6f4;
      --subtext: #a6adc8;
      --accent: #89b4fa;
      --accent2: #a6e3a1;
      --red: #f38ba8;
      --yellow: #f9e2af;
      --cyan: #94e2d5;
      --mantle: #181825;
      --crust: #11111b;
      --radius: 12px;
      --radius-sm: 8px;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
    }
    a { color: var(--accent); text-decoration: none; transition: color 0.2s ease; }
    a:hover { color: var(--cyan); text-decoration: underline; }
    /* Header */
    .header {
      background: var(--crust);
      border-bottom: 1px solid var(--surface);
      padding: 0.75rem 2rem;
      display: flex;
      align-items: center;
      gap: 1.5rem;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .header-logo { display: flex; align-items: center; }
    .header-logo svg { height: 32px; width: auto; display: block; }
    .header-nav {
      display: flex;
      gap: 0.5rem;
      margin-left: auto;
      align-items: center;
    }
    .header-nav a {
      color: var(--subtext);
      text-decoration: none;
      font-size: 0.85rem;
      padding: 0.4rem 0.85rem;
      border-radius: var(--radius-sm);
      transition: all 0.2s ease;
      font-weight: 500;
    }
    .header-nav a:hover {
      color: var(--text);
      background: var(--surface);
      text-decoration: none;
    }
    /* Container */
    .container { max-width: 960px; margin: 0 auto; padding: 2rem; }
    h1 {
      font-size: 1.5rem; font-weight: 700; color: var(--text);
      margin-bottom: 0.25rem; letter-spacing: -0.02em;
    }
    h2 {
      font-size: 1.1rem; font-weight: 600; color: var(--text);
      margin: 1.5rem 0 0.75rem; letter-spacing: -0.01em;
    }
    .sub { color: var(--subtext); font-size: 0.85rem; margin-bottom: 1.5rem; }
    .sub a { color: var(--accent); }
    /* Tables */
    table {
      width: 100%; border-collapse: separate; border-spacing: 0;
      font-size: 0.85rem; overflow: hidden; border-radius: var(--radius-sm);
    }
    th, td { text-align: left; padding: 0.65rem 0.85rem; }
    th {
      background: var(--mantle); color: var(--accent); font-weight: 600;
      font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
    }
    th:first-child { border-radius: var(--radius-sm) 0 0 0; }
    th:last-child { border-radius: 0 var(--radius-sm) 0 0; }
    td { background: var(--surface); border-bottom: 1px solid var(--mantle); }
    tr:last-child td:first-child { border-radius: 0 0 0 var(--radius-sm); }
    tr:last-child td:last-child { border-radius: 0 0 var(--radius-sm) 0; }
    tr:hover td { background: var(--overlay); transition: background 0.15s ease; }
    /* Badges */
    .badge {
      display: inline-block; padding: 0.15rem 0.55rem; border-radius: 6px;
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.02em;
    }
    .badge-pass { background: rgba(166,227,161,0.15); color: var(--accent2); }
    .badge-fail { background: rgba(243,139,168,0.15); color: var(--red); }
    .badge-run  { background: rgba(137,180,250,0.15); color: var(--accent); }
    .badge-info { background: rgba(148,226,213,0.15); color: var(--cyan); }
    /* Log box */
    .log-box {
      background: var(--crust); border: 1px solid var(--surface);
      border-radius: var(--radius-sm); padding: 1rem;
      font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
      font-size: 0.78rem; line-height: 1.6; max-height: 500px;
      overflow-y: auto; white-space: pre-wrap; margin-top: 0.5rem;
      scrollbar-width: thin; scrollbar-color: var(--overlay) transparent;
    }
    .log-line { color: var(--subtext); }
    .log-line:hover { color: var(--text); }
    .log-ts { color: var(--overlay); font-size: 0.65rem; }
    .status-dot {
      display: inline-block; width: 8px; height: 8px; border-radius: 50%;
      margin-right: 0.4rem; transition: all 0.2s ease;
    }
    .dot-green { background: var(--accent2); box-shadow: 0 0 6px rgba(166,227,161,0.4); }
    .dot-red   { background: var(--red); box-shadow: 0 0 6px rgba(243,139,168,0.4); }
    .dot-blue  { background: var(--accent); box-shadow: 0 0 6px rgba(137,180,250,0.4); }
    .empty { color: var(--overlay); font-style: italic; }
    /* Forms */
    input, button, select {
      background: var(--surface); color: var(--text);
      border: 1px solid var(--overlay); padding: 0.55rem 0.85rem;
      border-radius: var(--radius-sm); font-size: 0.85rem;
      font-family: inherit; transition: all 0.2s ease;
    }
    input:focus, select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(137,180,250,0.15); }
    button {
      background: var(--accent); color: var(--crust); font-weight: 600;
      cursor: pointer; border: none; padding: 0.55rem 1.1rem;
      border-radius: var(--radius-sm); transition: all 0.2s ease;
    }
    button:hover {
      background: var(--cyan); transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(148,226,213,0.25);
    }
    button:active { transform: translateY(0); }
    button:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }
    .run-form { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
    .run-form input { flex: 1; min-width: 200px; }
    /* Stat cards */
    .stats { display: flex; gap: 1rem; margin: 1rem 0; }
    .stat-card {
      background: var(--surface); border: 1px solid var(--overlay);
      border-radius: var(--radius); padding: 1.1rem 1.25rem;
      flex: 1; position: relative; overflow: hidden;
      transition: all 0.25s ease;
    }
    .stat-card::before {
      content: ''; position: absolute; top: 0; left: 0; right: 0;
      height: 3px; border-radius: var(--radius) var(--radius) 0 0;
    }
    .stat-card:nth-child(1)::before { background: linear-gradient(90deg, var(--accent), var(--cyan)); }
    .stat-card:nth-child(2)::before { background: linear-gradient(90deg, var(--accent2), var(--cyan)); }
    .stat-card:nth-child(3)::before { background: linear-gradient(90deg, var(--yellow), var(--red)); }
    .stat-card:nth-child(4)::before { background: linear-gradient(90deg, var(--cyan), var(--accent)); }
    .stat-card:hover {
      border-color: var(--accent); transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    .stat-card .num { font-size: 1.6rem; font-weight: 800; color: var(--text); letter-spacing: -0.03em; }
    .stat-card .lbl { font-size: 0.7rem; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.2rem; }
    /* Toast */
    .toast {
      position: fixed; bottom: 2rem; right: 2rem; background: var(--surface);
      border: 1px solid var(--overlay); border-radius: var(--radius-sm);
      padding: 0.85rem 1.1rem; font-size: 0.85rem; display: none;
      z-index: 1000; color: var(--text); box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }
    /* Quick buttons */
    .quick-btns { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .quick-btns button {
      background: var(--surface); color: var(--subtext);
      border: 1px solid var(--overlay); font-weight: 500;
      transform: none; box-shadow: none;
    }
    .quick-btns button:hover {
      background: var(--overlay); color: var(--text);
      border-color: var(--accent); transform: translateY(-1px);
    }
    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--overlay); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--subtext); }
    {% endraw %}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-logo">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300" height="32" style="width:auto;display:block;">
        <defs>
          <radialGradient id="glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#00d9ff" stop-opacity="0.9"/>
            <stop offset="100%" stop-color="#00d9ff" stop-opacity="0"/>
          </radialGradient>
          <radialGradient id="glowWhite" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.8"/>
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
          </radialGradient>
          <filter id="neon">
            <feGaussianBlur stdDeviation="2.5" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        <g transform="translate(30,50) scale(0.5)">
          <g filter="url(#neon)" fill="none" stroke="#00d9ff" stroke-width="1.8" opacity="0.65">
            <line x1="80" y1="80" x2="140" y2="120"/>
            <line x1="140" y1="120" x2="200" y2="100"/>
            <line x1="200" y1="100" x2="260" y2="140"/>
            <line x1="260" y1="140" x2="310" y2="180"/>
            <line x1="310" y1="180" x2="340" y2="260"/>
            <line x1="260" y1="140" x2="230" y2="210"/>
            <line x1="230" y1="210" x2="250" y2="290"/>
            <line x1="230" y1="210" x2="170" y2="250"/>
            <line x1="170" y1="250" x2="120" y2="300"/>
            <line x1="200" y1="100" x2="160" y2="180" stroke-width="1.2" opacity="0.55"/>
            <line x1="140" y1="120" x2="170" y2="250" stroke-width="1.2" opacity="0.55"/>
            <line x1="310" y1="180" x2="250" y2="290" stroke-width="1.2" opacity="0.55"/>
          </g>
          <line x1="260" y1="140" x2="310" y2="180" stroke="#ffffff" stroke-width="2.4" opacity="0.85" filter="url(#neon)"/>
          <circle cx="80" cy="80" r="5" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="80" cy="80" r="12" fill="url(#glowWhite)" opacity="0.3"/>
          <circle cx="140" cy="120" r="4" fill="#00d9ff" filter="url(#neon)"/>
          <circle cx="140" cy="120" r="10" fill="url(#glow)" opacity="0.4"/>
          <circle cx="200" cy="100" r="5" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="200" cy="100" r="12" fill="url(#glowWhite)" opacity="0.3"/>
          <circle cx="260" cy="140" r="7" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="260" cy="140" r="18" fill="url(#glowWhite)" opacity="0.4"/>
          <circle cx="260" cy="140" r="4" fill="#00d9ff"/>
          <circle cx="310" cy="180" r="4.5" fill="#00d9ff" filter="url(#neon)"/>
          <circle cx="310" cy="180" r="11" fill="url(#glow)" opacity="0.35"/>
          <circle cx="340" cy="260" r="4" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="340" cy="260" r="10" fill="url(#glowWhite)" opacity="0.25"/>
          <circle cx="230" cy="210" r="3.5" fill="#00d9ff" filter="url(#neon)"/>
          <circle cx="230" cy="210" r="9" fill="url(#glow)" opacity="0.3"/>
          <circle cx="250" cy="290" r="4" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="250" cy="290" r="10" fill="url(#glowWhite)" opacity="0.25"/>
          <circle cx="170" cy="250" r="3.5" fill="#00d9ff" filter="url(#neon)"/>
          <circle cx="170" cy="250" r="9" fill="url(#glow)" opacity="0.3"/>
          <circle cx="120" cy="300" r="4" fill="#ffffff" filter="url(#neon)"/>
          <circle cx="120" cy="300" r="10" fill="url(#glowWhite)" opacity="0.25"/>
          <circle cx="160" cy="180" r="3" fill="#00d9ff" filter="url(#neon)"/>
          <circle cx="160" cy="180" r="8" fill="url(#glow)" opacity="0.2"/>
        </g>
        <text x="270" y="150" font-family="'Segoe UI','Helvetica Neue',Arial,sans-serif" font-size="112" font-weight="800" letter-spacing="6" fill="#ffffff">VIRGO</text>
        <rect x="274" y="170" width="360" height="5" rx="2.5" fill="#00d9ff"/>
        <text x="276" y="212" font-family="'Segoe UI','Helvetica Neue',Arial,sans-serif" font-size="30" font-weight="600" letter-spacing="2" fill="#00d9ff">multi-agent state machine</text>
      </svg>
    </div>
    <div class="header-nav">
      <a href="/">&#9664; sessions</a>
      <a href="/run">&#9654; run</a>
      <a href="/status">&#9679; status</a>
    </div>
  </div>
  <div class="container">
    {{ content|safe }}
  </div>
  <div id="toast" class="toast"></div>
  {% raw %}
  <script>
    function showToast(msg, color) {
      var t = document.getElementById('toast');
      t.style.display = 'block'; t.style.borderColor = color || '#45475a';
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

<h2>web runs</h2>
<table>
  <tr><th>time</th><th>goal</th><th>status</th></tr>
  {% for r in web_runs %}
  <tr>
    <td>{{ r.ts }}</td>
    <td>{{ r.goal }}</td>
    <td>
      {% if r.exit == 'running' %}<span class="badge badge-run">running</span>
      {% else %}{{ r.exit }}{% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="3" class="empty">no web runs yet</td></tr>
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

<h2>quick goals</h2>
<div class="quick-btns">
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


def _build_app(token: str = "") -> Any:
    """Create and return the FastAPI ASGI app."""
    import jinja2
    from fastapi import Depends, FastAPI, Form, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from sse_starlette.sse import EventSourceResponse

    app = FastAPI(title="virgo", version="0.6.0")
    env = jinja2.Environment(autoescape=True)

    def _auth(request: Request):
        """Reject protected routes unless the token matches (?token= or header).

        No-op when *token* is empty so the dashboard behaves exactly as before.
        """
        if not token:
            return None
        q = request.query_params.get("token", "")
        h = request.headers.get("x-virgo-token", "")
        if q == token or h == token:
            return None
        raise HTTPException(status_code=401, detail="unauthorized")

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
            sessions=sessions,
            stats={"count": len(sessions), "passed": passed, "failed": failed},
            web_runs=list(reversed(_WEB_HISTORY)),
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

    @app.get("/run", response_class=HTMLResponse, dependencies=[Depends(_auth)])
    async def run_page():
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _RUN_PAGE + "{% endblock %}"
            )
        )
        return tpl.render()

    @app.post("/run", response_class=HTMLResponse, dependencies=[Depends(_auth)])
    async def run_pipeline(goal: str = Form(...), use_llm: str = Form("0")):
        """Trigger a pipeline run asynchronously and stream output via SSE."""
        _log_line(f"Web run: {goal[:80]}" + (" (LLM)" if use_llm == "1" else ""))
        import subprocess
        import sys

        from cli import HERE as _HERE

        cmd = [sys.executable, str(_HERE / "cli.py"), "run", "--goal", goal, "--auto-approve"]
        if use_llm == "1":
            cmd.append("--llm")

        ts = time.strftime("%Y%m%d-%H%M%S")
        entry = {"ts": ts, "goal": goal[:80], "exit": "running", "duration_s": 0}
        _WEB_HISTORY.append(entry)

        def _run():
            started = time.time()
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                _WEB_PROCS[ts] = proc
                try:
                    out, err = proc.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    _log_line("Web run timed out after 300s")
                    entry["exit"] = "timeout"
                    return
                _log_line(f"Web run complete: exit {proc.returncode}")
                entry["exit"] = proc.returncode
                for line in (out or "").splitlines()[-50:]:
                    if line.strip():
                        _log_line(f"  {line.strip()[:120]}")
                if err:
                    for line in err.splitlines()[-20:]:
                        if line.strip():
                            _log_line(f"  err: {line.strip()[:120]}")
            except Exception as exc:  # noqa: BLE001
                _log_line(f"Web run error: {exc}")
                entry["exit"] = "error"
            finally:
                entry["duration_s"] = round(time.time() - started, 1)
                _WEB_PROCS.pop(ts, None)

        import threading

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        return f"""<div class="log-line" style="color:#00ff88;">&#9654; started: {goal[:80]}</div>
<div class="log-line">view output in the <a href="/log">live log</a></div>"""

    @app.get("/status", response_class=HTMLResponse, dependencies=[Depends(_auth)])
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

    @app.get("/log", response_class=HTMLResponse, dependencies=[Depends(_auth)])
    async def log_page():
        tpl = env.from_string(
            _LAYOUT.replace(
                "{{ content|safe }}", "{% block content %}" + _LOG_PAGE + "{% endblock %}"
            )
        )
        return tpl.render()

    @app.get("/log-stream", response_class=PlainTextResponse, dependencies=[Depends(_auth)])
    async def log_stream():
        lines = "\n".join(app.state.log_buffer[-100:]) or "waiting..."
        return lines

    @app.get("/log-sse", dependencies=[Depends(_auth)])
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

    @app.get("/api/sessions", dependencies=[Depends(_auth)])
    async def api_sessions():
        from memory import list_sessions

        return JSONResponse(list_sessions())

    @app.get("/api/session/{name}", dependencies=[Depends(_auth)])
    async def api_session(name: str):
        from memory import load_state

        try:
            return JSONResponse(load_state(name))
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/status", dependencies=[Depends(_auth)])
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

    @app.post("/api/stop", response_class=PlainTextResponse, dependencies=[Depends(_auth)])
    async def api_stop():
        """Terminate all in-flight web runs (terminate, then kill after 3s)."""
        stopped = 0
        for _ts, proc in list(_WEB_PROCS.items()):
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:  # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                stopped += 1
        _log_line(f"Stopped {stopped} web run(s) via /api/stop")
        return f"stopped {stopped} run(s)"

    @app.get("/api/history", dependencies=[Depends(_auth)])
    async def api_history():
        """Return web-run history, newest first."""
        return JSONResponse(list(reversed(_WEB_HISTORY)))

    @app.post("/api/bench", response_class=HTMLResponse, dependencies=[Depends(_auth)])
    async def api_bench():
        """Write a bench trigger file for the desktop app to pick up."""
        from _log import OUTDIR

        OUTDIR.mkdir(exist_ok=True)
        (OUTDIR / "BENCH_TRIGGER.txt").write_text(
            time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8"
        )
        _log_line("Bench triggered from web")
        return '<div class="log-line" style="color:#00ff88;">bench triggered in desktop app</div>'

    return app


# ===========================================================================
# Public API
# ===========================================================================


def serve(host: str = "127.0.0.1", port: int = 8765, token: str = "") -> None:
    """Start the virgo web dashboard.

    Host/port/token can be overridden via VIRGO_DASH_HOST / VIRGO_DASH_PORT /
    VIRGO_DASH_TOKEN environment variables.  When *token* is non-empty, all
    control routes (/run, /api/*, /status, /log) require it via ``?token=``
    or the ``X-Virgo-Token`` header.
    """
    host = os.environ.get("VIRGO_DASH_HOST", host)
    try:
        port = int(os.environ.get("VIRGO_DASH_PORT", port))
    except ValueError:
        pass
    token = os.environ.get("VIRGO_DASH_TOKEN", token)
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

    app = _build_app(token=token)
    print(f"\n  [virgo] Dashboard at  http://{host}:{port}")
    if token:
        print("  [virgo] Auth: token required (X-Virgo-Token header or ?token=)")
    print("  [virgo] Routes:  /sessions  /run  /status  /log  /api/*")
    print("  [virgo] Ctrl+C to stop\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ===========================================================================
# CLI shortcut
# ===========================================================================

if __name__ == "__main__":
    serve()

"""
server — virgo web dashboard (FastAPI + HTMX).

Displays pipeline state in real time, lists saved sessions,
and provides a live log view.

Start with::

    virgo serve
    # or:  python -c "import server; server.serve()"
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# ---------------------------------------------------------------------------
# Lazy imports — report friendly errors if dependencies are missing
# ---------------------------------------------------------------------------

_IMPORTS_OK = True
try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    import uvicorn
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
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
      background:#0d0d12; color:#c0c0d0; font-family:system-ui,sans-serif;
      padding:2rem;
    }}
    .container {{ max-width:960px; margin:0 auto; }}
    h1 {{ font-size:1.5rem; font-weight:600; color:#00ffff; margin-bottom:0.25rem; }}
    h2 {{ font-size:1.1rem; font-weight:500; color:#fff; margin:1.5rem 0 0.5rem; }}
    .sub {{ color:#888; font-size:0.85rem; margin-bottom:1.5rem; }}
    table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
    th,td {{ text-align:left; padding:0.5rem 0.75rem; border-bottom:1px solid #1e1e2a; }}
    th {{ color:#00ffff; font-weight:500; }}
    tr:hover td {{ background:#14141e; }}
    .badge {{
      display:inline-block; padding:0.15rem 0.5rem; border-radius:4px;
      font-size:0.75rem; font-weight:600;
    }}
    .badge-pass {{ background:#003322; color:#00ff88; }}
    .badge-fail {{ background:#330011; color:#ff4466; }}
    .badge-run  {{ background:#002233; color:#00ccff; }}
    .log-box {{
      background:#0a0a0f; border:1px solid #1a1a2a; border-radius:6px;
      padding:1rem; font-family:"JetBrains Mono","Fira Code",monospace;
      font-size:0.8rem; line-height:1.5; max-height:400px; overflow-y:auto;
      white-space:pre-wrap; margin-top:0.5rem;
    }}
    .log-line {{ color:#888; }}
    .log-line:hover {{ color:#fff; }}
    a {{ color:#00ccff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .nav {{ display:flex; gap:1.5rem; margin-bottom:1.5rem; }}
    .nav a {{ font-size:0.9rem; }}
    .status-dot {{
      display:inline-block; width:8px; height:8px; border-radius:50%;
      margin-right:0.4rem;
    }}
    .dot-green {{ background:#00ff88; }}
    .dot-red   {{ background:#ff4466; }}
    .dot-blue  {{ background:#00ccff; }}
    .empty {{ color:#555; font-style:italic; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="nav">
      <a href="/">&#9664; sessions</a>
      <span style="color:#333">|</span>
      <span style="color:#00ffff;font-weight:600;">virgo</span>
      <span style="color:#555;font-size:0.8rem;">multi-agent state machine</span>
    </div>
    {{ content|safe }}
  </div>
</body>
</html>
"""

_SESSIONS_PAGE = """\
<h1>&#9672; sessions</h1>
<div class="sub">saved pipeline runs &mdash; <a href="/log">live log</a></div>
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

_LOG_PAGE = """\
<h1>&#9672; live log</h1>
<div class="sub">pipeline output streams here in real time</div>
<div class="log-box" id="log-box"
     hx-get="/log-stream"
     hx-trigger="every 2s"
     hx-target="#log-box"
     hx-swap="innerHTML"
     hx-select="#log-box">
  <div class="log-line">waiting for data...</div>
</div>
"""


# ===========================================================================
# FastAPI application
# ===========================================================================

def _build_app() -> Any:
    """Create and return the FastAPI ASGI app."""
    import jinja2
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, PlainTextResponse

    app = FastAPI(title="virgo", version="0.1.0")
    env = jinja2.Environment(autoescape=True)

    # Shared log buffer (thread-safe)
    log_buffer: list[str] = []
    import atexit

    def _log_line(msg: str) -> None:
        log_buffer.append(msg)
        if len(log_buffer) > 500:
            log_buffer[:100] = []

    app.state.log_buffer = log_buffer
    app.state.log_line = _log_line

    @app.get("/", response_class=HTMLResponse)
    async def sessions_page():
        from memory import list_sessions
        sessions = list_sessions()
        tpl = env.from_string(_LAYOUT.replace("{{ content|safe }}",
                              "{% block content %}" + _SESSIONS_PAGE + "{% endblock %}"))
        return tpl.render(sessions=sessions)

    @app.get("/session/{name}", response_class=HTMLResponse)
    async def session_page(name: str):
        from memory import load_state
        try:
            data = load_state(name)
        except FileNotFoundError:
            return HTMLResponse("<h1>not found</h1>", status_code=404)
        tpl = env.from_string(_LAYOUT.replace("{{ content|safe }}",
                              "{% block content %}" + _SESSION_PAGE + "{% endblock %}"))
        return tpl.render(
            name=name, goal=data.get("goal", ""),
            phase=data.get("phase", ""), iteration=data.get("iteration", 0),
            loop_passed=data.get("loop_passed"),
            generated=data.get("generated_files", []),
            test_logs=data.get("test_logs", []),
        )

    @app.get("/log", response_class=HTMLResponse)
    async def log_page():
        tpl = env.from_string(_LAYOUT.replace("{{ content|safe }}",
                              "{% block content %}" + _LOG_PAGE + "{% endblock %}"))
        return tpl.render()

    @app.get("/log-stream", response_class=PlainTextResponse)
    async def log_stream():
        lines = "\n".join(app.state.log_buffer[-100:]) or "waiting..."
        return lines

    # Expose app and helpers
    app.state.log_line("virgo dashboard started")

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
            import subprocess, sys
            subprocess.run([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "jinja2", "-q"],
                         check=True)
            # Re-check imports
            import importlib
            for mod_name in ("fastapi", "uvicorn", "jinja2"):
                importlib.invalidate_caches()
                importlib.import_module(mod_name)
            print("[virgo] Dependencies installed successfully!")
        except Exception:
            print("[virgo] Auto-install failed. Install manually:")
            print("  pip install fastapi uvicorn jinja2")
            sys.exit(1)

    import uvicorn
    app = _build_app()
    print(f"\n  [virgo] Dashboard at  http://{host}:{port}")
    print(f"  [virgo] Ctrl+C to stop\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ===========================================================================
# CLI shortcut
# ===========================================================================

if __name__ == "__main__":
    serve()

"""
ollama_tools_plugin — Manage Ollama models from within the agent.

Tools:
  - ollama list     → List models pulled locally (GET /api/tags)
  - ollama pull     → Pull a model by name          (POST /api/pull)
  - ollama status   → Check whether Ollama is running

All calls go through ``urllib``.  The plugin exports a ``register(registry)``
function so the plugin loader in ``plugins.py`` picks it up automatically.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

OLLAMA_BASE = "http://localhost:11434"

# ── helpers ──────────────────────────────────────────────────────────


def _ollama_running() -> bool:
    """Return True iff the Ollama REST API responds at *OLLAMA_BASE*."""
    try:
        req = urllib.request.Request(OLLAMA_BASE, method="HEAD")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _fmt_err(msg: str, detail: str = "") -> str:
    if detail:
        return f"❌ {msg}: {detail}"
    return f"❌ {msg}"


# ── tool implementations ─────────────────────────────────────────────


def tool_ollama_list(**kwargs: Any) -> str:
    """List all models currently pulled in the local Ollama instance.

    Calls ``GET {OLLAMA_BASE}/api/tags`` and returns a human-readable
    summary of every model (name, size, modified date).
    """
    _ = kwargs  # accept (and ignore) any extra kwargs

    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        models = data.get("models", [])
        if not models:
            return "📭 No models pulled yet."

        lines: list[str] = []
        for m in models:
            name = m.get("name", "?")
            size = m.get("size", 0)
            modified = m.get("modified_at", "?")[:19]  # trim sub-seconds
            size_str = (
                f"{size / 1e9:.1f} GB"
                if size > 1e9
                else f"{size / 1e6:.1f} MB"
            )
            lines.append(f"  · {name:30s} {size_str:>8s}  {modified}")

        return f"📋 Ollama models ({len(models)}):\n" + "\n".join(lines)

    except urllib.error.HTTPError as exc:
        return _fmt_err("Failed to list models", f"HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        return _fmt_err("Cannot reach Ollama", str(exc.reason))
    except (json.JSONDecodeError, OSError) as exc:
        return _fmt_err("Failed to parse response", str(exc))


def tool_ollama_pull(model: str = "", **kwargs: Any) -> str:
    """Pull (download) an Ollama model by name.

    Required keyword argument:

        model   —  Model identifier, e.g. ``"llama3.2"`` or
                   ``"mistral:7b"``.  Must not be empty.

    Sends ``POST {OLLAMA_BASE}/api/pull`` with ``{"name": model}``.
    Returns the server response status or an error message.
    """
    _ = kwargs

    if not model:
        return _fmt_err("Missing required argument", "model=<name> is required")

    payload = json.dumps({"name": model}).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/pull",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read().decode()

        # The pull endpoint streams JSON-lines; collect the final status.
        last_status = "done"
        for line in body.strip().splitlines():
            if line:
                try:
                    chunk = json.loads(line)
                    if chunk.get("status"):
                        last_status = chunk["status"]
                except json.JSONDecodeError:
                    pass

        return f"✅ Pulled model `{model}`  ({last_status})"

    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        try:
            detail += f" — {json.loads(exc.read().decode()).get('error', exc.reason)}"
        except Exception:
            detail += f" {exc.reason}"
        return _fmt_err(f"Failed to pull `{model}`", detail)
    except urllib.error.URLError as exc:
        return _fmt_err("Cannot reach Ollama", str(exc.reason))
    except (json.JSONDecodeError, OSError) as exc:
        return _fmt_err(f"Failed to pull `{model}`", str(exc))


def tool_ollama_status(**kwargs: Any) -> str:
    """Check whether the Ollama service is running and responsive.

    Sends a lightweight HEAD request to ``{OLLAMA_BASE}``.  Returns a
    human-readable status message.
    """
    _ = kwargs

    if _ollama_running():
        return "✅ Ollama is running"
    return "❌ Ollama is not running (or not reachable at localhost:11434)"


# ── plugin registration ──────────────────────────────────────────────


def register(registry: Any) -> None:
    """Register all three Ollama tools with the *registry* (ToolRegistry).

    This is the canonical entry point called by ``plugins.load_path()``.
    """
    from tools import Tool  # late import so the plugin is self-contained

    registry.register(
        Tool(
            name="ollama list",
            fn=tool_ollama_list,
            description="List all Ollama models pulled locally (GET /api/tags).",
        )
    )
    registry.register(
        Tool(
            name="ollama pull",
            fn=tool_ollama_pull,
            description=(
                "Pull / download an Ollama model by name. "
                "Takes a 'model' keyword argument (e.g. 'llama3.2')."
            ),
        )
    )
    registry.register(
        Tool(
            name="ollama status",
            fn=tool_ollama_status,
            description="Check whether the Ollama service is running.",
        )
    )

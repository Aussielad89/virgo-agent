"""
chat_tools — plugin SDK for chat commands in Virgo.

Lets plugins register ``/command`` handlers that are automatically
discovered by both the CLI chat and the PyQt6 desktop chat.

Usage
-----
Create a file in ``plugins/`` with::

    __plugin_meta__ = {
        "name": "my-tools",
        "version": "0.1.0",
        "description": "Useful chat commands",
    }

    def chat_tools() -> list[ChatTool]:
        return [
            ChatTool(
                name="/hello",
                description="Greet someone",
                handler=lambda name="World": f"Hello {name}!",
                args=[
                    {"name": "name", "type": "str", "default": "World",
                     "help": "Who to greet"},
                ],
            ),
        ]

Chat tools are hot-reloaded alongside regular plugins.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).parent
PLUGIN_DIRS = [
    HERE / "plugins",
    Path.home() / ".virgo" / "plugins",
]


class ChatTool:
    """A ``/command`` that the chat UI can invoke."""

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., str],
        args: list[dict[str, Any]] | None = None,
    ) -> None:
        self.name = name.lstrip("/")                     # "hello" not "/hello"
        self.slash = f"/{self.name}"                      # "/hello"
        self.description = description
        self.handler = handler
        self.args = args or []

    def __call__(self, raw: str) -> str:
        """Parse *raw* (text after ``/name``) and call the handler."""
        tokens = raw.split()
        kwargs: dict[str, Any] = {}
        for i, arg in enumerate(self.args):
            if i < len(tokens):
                kwargs[arg["name"]] = self._coerce(tokens[i], arg)
            elif "default" in arg:
                kwargs[arg["name"]] = arg["default"]
            elif arg.get("required"):
                return f"Error: missing required argument `{arg['name']}`"
        return self.handler(**kwargs)

    def _coerce(self, val: str, spec: dict) -> Any:
        typ = spec.get("type", "str")
        try:
            if typ == "int":
                return int(val)
            if typ == "float":
                return float(val)
            if typ == "bool":
                return val.lower() in ("1", "true", "yes", "on")
        except ValueError:
            return val
        return val

    def to_help(self) -> str:
        """Format this tool as a /help line."""
        parts = [f"  {self.slash}"]
        for arg in self.args:
            p = arg["name"]
            if "default" in arg:
                parts.append(f"[{p}]")
            else:
                parts.append(f"<{p}>")
        help_str = arg.get("help", "") if self.args else ""
        line = " ".join(parts)
        if help_str:
            line += f"  — {help_str}"
        else:
            line += f"  — {self.description}"
        return line


# ── Discovery ────────────────────────────────────────────────────────


def discover_chat_tools(
    extra_dirs: list[Path] | None = None,
) -> list[ChatTool]:
    """Scan plugin directories for ``chat_tools()`` exports.

    Returns a list of ``ChatTool`` instances found across all plugins.
    """
    found: list[ChatTool] = []
    dirs = list(PLUGIN_DIRS)
    if extra_dirs:
        dirs.extend(extra_dirs)

    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            module = _load_plugin_module(f)
            if module is None:
                continue
            fn = getattr(module, "chat_tools", None)
            if fn is None or not callable(fn):
                continue
            try:
                tools = fn()
                if isinstance(tools, list):
                    for t in tools:
                        if isinstance(t, ChatTool):
                            found.append(t)
            except Exception:
                pass
    return found


def _load_plugin_module(path: Path):
    """Import a single plugin file as a module, return the module object."""
    import importlib.util

    name = f"_chat_tool_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# ── Desktop chat integration helper ──────────────────────────────────


def build_help_text(tools: list[ChatTool]) -> str:
    """Build a /help-style listing from chat tools."""
    if not tools:
        return ""
    return "Chat plugins:\n" + "\n".join(t.to_help() for t in tools)

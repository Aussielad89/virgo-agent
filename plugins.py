"""
plugins — dynamic tool loader for virgo.

Scans ``plugins/`` and ``~/.virgo/plugins/`` for Python files that
export ``Tool`` instances or ``register(registry)`` functions.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
PLUGIN_DIRS = [
    HERE / "plugins",
    Path.home() / ".virgo" / "plugins",
]


def discover() -> list[Path]:
    """Return all Python files found in plugin directories."""
    files: list[Path] = []
    for d in PLUGIN_DIRS:
        if d.exists():
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                files.append(f)
    return files


def load_path(path: Path, registry: Any) -> None:
    """Load a single plugin file and register any tools it exports.

    Plugins can export:
      - A top-level ``register(registry)`` function.
      - Top-level ``Tool`` instances (detected by class name or
        ``tool`` prefix).
    """
    # Import the module
    module_name = f"_virgo_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        print(f"  [plugins]  Could not load: {path.name}")
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # 1. Look for a register() function
    if hasattr(module, "register"):
        fn = getattr(module, "register")
        if callable(fn):
            fn(registry)
            print(f"  [plugins]  Loaded: {path.name}  (register())")
            return

    # 2. Look for Tool instances
    from tools import Tool

    count = 0
    for name, obj in inspect.getmembers(module):
        if isinstance(obj, Tool):
            registry.register(obj)
            count += 1
        elif (inspect.isfunction(obj) and
              obj.__module__ == module.__name__ and
              (name.startswith("tool_") or name.startswith("_tool_"))):
            # Wrap function as a Tool
            tool_name = name.removeprefix("_").removeprefix("tool_").replace("_", " ")
            registry.register(Tool(name=tool_name, fn=obj, description=obj.__doc__ or ""))
            count += 1

    if count:
        print(f"  [plugins]  Loaded: {path.name}  ({count} tool(s))")
    else:
        print(f"  [plugins]  Skipped: {path.name}  (no tools found)")


def load_all(registry: Any) -> int:
    """Discover and load all plugins, returning the count loaded."""
    files = discover()
    for path in files:
        try:
            load_path(path, registry)
        except Exception as exc:
            print(f"  [plugins]  Error loading {path.name}: {exc}")
    return len(files)


def create_plugin(
    name: str,
    code: str,
    directory: Optional[Path] = None,
) -> Path:
    """Create a new plugin file in the specified plugin directory."""
    dest = (directory or PLUGIN_DIRS[0])
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    path.write_text(code, encoding="utf-8")
    return path

"""
plugins — dynamic tool loader for virgo.

Scans ``plugins/`` and ``~/.virgo/plugins/`` for Python files that
export ``Tool`` instances or ``register(registry)`` functions.

Supports **hot-reload** via ``watch_plugins()``, which watches plugin
directories for file changes and reloads changed plugins automatically.
Uses ``watchdog`` if available, otherwise falls back to polling every 2s.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import threading
import time
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


# ── Hot-reload ───────────────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    """Return a stable hash of the file's mtime + size for change detection."""
    try:
        st = path.stat()
        return f"{st.st_mtime}:{st.st_size}"
    except OSError:
        return ""


def watch_plugins(
    registry: Any,
    *,
    interval: float = 2.0,
    callback: Optional[callable] = None,
) -> threading.Thread:
    """Start a background thread watching plugin directories for changes.

    When a plugin file is modified, it is automatically reloaded into
    *registry*. The thread runs until the main program exits (daemon=True).

    If *callback* is provided, it is called with ``(event, path)`` where
    *event* is ``"created"``, ``"modified"``, or ``"deleted"``.

    Uses ``watchdog`` if available for instant notification; otherwise
    polls file hashes every *interval* seconds.

    Returns the background ``threading.Thread`` (already started).
    """
    # Try watchdog first for instant file notification
    try:
        import watchdog.events  # type: ignore
        import watchdog.observers  # type: ignore
        _HAS_WATCHDOG = True
    except ImportError:
        _HAS_WATCHDOG = False

    loaded: dict[str, str] = {}  # path -> hash
    # Initialize with current files
    for f in discover():
        loaded[str(f)] = _file_hash(f)

    _lock = threading.Lock()

    def _do_reload(path: Path) -> None:
        """Reload a single plugin file."""
        with _lock:
            try:
                # Clear the module from cache if already loaded
                module_name = f"_virgo_plugin_{path.stem}"
                if module_name in sys.modules:
                    del sys.modules[module_name]
                load_path(path, registry)
                if callback:
                    callback("modified", path)
            except Exception as exc:
                print(f"  [plugins]  Hot-reload error for {path.name}: {exc}")

    if _HAS_WATCHDOG:
        class _Handler(watchdog.events.FileSystemEventHandler):
            def on_created(self, event):
                if event.src_path.endswith(".py") and not Path(event.src_path).name.startswith("_"):
                    _do_reload(Path(event.src_path))
                    if callback:
                        callback("created", Path(event.src_path))

            def on_modified(self, event):
                if event.src_path.endswith(".py") and not Path(event.src_path).name.startswith("_"):
                    _do_reload(Path(event.src_path))

            def on_deleted(self, event):
                if callback and event.src_path.endswith(".py"):
                    callback("deleted", Path(event.src_path))

        observer = watchdog.observers.Observer()
        for d in PLUGIN_DIRS:
            if d.exists():
                observer.schedule(_Handler(), str(d), recursive=False)
        observer.daemon = True
        observer.start()
        print(f"  [plugins]  Hot-reload active (watchdog, {len(loaded)} plugin(s))")
        # Return a thread that keeps the observer alive
        t = threading.Thread(target=lambda: observer.join(), daemon=True)
        t.start()
        return t

    # Fallback: polling thread
    def _poll() -> None:
        while True:
            time.sleep(interval)
            current = discover()
            current_map: dict[str, str] = {}
            for f in current:
                fstr = str(f)
                h = _file_hash(f)
                current_map[fstr] = h
                if fstr not in loaded:
                    # New plugin
                    _do_reload(f)
                    if callback:
                        callback("created", f)
                elif loaded[fstr] != h:
                    # Changed plugin
                    _do_reload(f)
            # Check for deletions
            for fstr in list(loaded.keys()):
                if fstr not in current_map:
                    if callback:
                        callback("deleted", Path(fstr))
            loaded.clear()
            loaded.update(current_map)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    print(f"  [plugins]  Hot-reload active (polling, {len(loaded)} plugin(s))")
    return t

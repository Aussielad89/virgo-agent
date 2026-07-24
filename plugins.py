"""
plugins — dynamic tool loader for virgo.

Scans ``plugins/`` and ``~/.virgo/plugins/`` for Python files that
export ``Tool`` instances or ``register(registry)`` functions.

Supports **hot-reload** via ``watch_plugins()``, which watches plugin
directories for file changes and reloads changed plugins automatically.
Uses ``watchdog`` if available, otherwise falls back to polling every 2s.

Plugin SDK features:
  - ``reload_plugin(name)`` — re-import and re-register a plugin
  - ``list_plugins()`` — detailed info about all loaded plugins
  - ``install_plugin(source)`` — copy a plugin into a plugin directory
  - ``__plugin_meta__`` metadata convention
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
import threading
import time
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
PLUGIN_DIRS = [
    HERE / "plugins",
    Path.home() / ".virgo" / "plugins",
]

# Track loaded plugin metadata (filename -> meta dict)
_loaded_plugins: dict[str, dict[str, Any]] = {}
# Track loaded module names for clean reload
_loaded_modules: dict[str, str] = {}


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


def _extract_meta(module: object) -> dict[str, Any]:
    """Extract ``__plugin_meta__`` from a module, returning defaults if absent."""
    default: dict[str, Any] = {
        "name": "",
        "version": "0.0.0",
        "description": "",
        "author": "unknown",
    }
    meta = getattr(module, "__plugin_meta__", None)
    if isinstance(meta, dict):
        return {**default, **meta}
    return default


def load_path(path: Path, registry: Any) -> None:
    """Load a single plugin file and register any tools it exports.

    Plugins can export:
      - A top-level ``register(registry)`` function.
      - Top-level ``Tool`` instances (detected by class name or
        ``tool`` prefix).
    """
    from _console import icon

    # Import the module
    module_name = f"_virgo_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
    except Exception:
        print(f"  {icon('warn')}  Could not load: {path.name}")
        return
    if spec is None or spec.loader is None:
        print(f"  {icon('warn')}  Could not load: {path.name}")
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError:
        print(f"  {icon('warn')}  File not found: {path.name}")
        return
    except Exception:
        print(f"  {icon('warn')}  Error loading {path.name}")
        return

    # Store metadata
    meta = _extract_meta(module)
    _loaded_plugins[path.stem] = meta
    _loaded_modules[path.stem] = module_name

    # 1. Look for a register() function
    if hasattr(module, "register"):
        fn = module.register
        if callable(fn):
            fn(registry)
            label = meta.get("name") or path.stem
            ver = meta.get("version", "")
            ver_str = f" v{ver}" if ver and ver != "0.0.0" else ""
            print(f"  {icon('tool')}  Loaded: {path.name}{ver_str}  ({label})")
            return

    # 2. Look for Tool instances
    from tools import Tool

    count = 0
    for name, obj in inspect.getmembers(module):
        if isinstance(obj, Tool):
            registry.register(obj)
            count += 1
        elif (
            inspect.isfunction(obj)
            and obj.__module__ == module.__name__
            and (name.startswith("tool_") or name.startswith("_tool_"))
        ):
            # Wrap function as a Tool
            tool_name = name.removeprefix("_").removeprefix("tool_").replace("_", " ")
            registry.register(Tool(name=tool_name, fn=obj, description=obj.__doc__ or ""))
            count += 1

    if count:
        label = meta.get("name") or path.stem
        print(f"  {icon('tool')}  Loaded: {path.name}  ({label}, {count} tool(s))")
    else:
        print(f"  {icon('warn')}  Skipped: {path.name}  (no tools found)")


def load_all(registry: Any) -> int:
    """Discover and load all plugins, returning the count loaded."""
    files = discover()
    for path in files:
        try:
            load_path(path, registry)
        except Exception as exc:
            from _console import icon

            print(f"  {icon('error')}  Error loading {path.name}: {exc}")
    return len(files)


def create_plugin(
    name: str,
    code: str,
    directory: Path | None = None,
) -> Path:
    """Create a new plugin file in the specified plugin directory."""
    dest = directory or PLUGIN_DIRS[0]
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    path.write_text(code, encoding="utf-8")
    return path


# ── Plugin SDK: reload ──────────────────────────────────────────────


def reload_plugin(name: str, registry: Any) -> bool:
    """Reload a single plugin by name (without ``.py`` suffix).

    Re-imports the module and re-registers its tools. Returns ``True``
    on success, ``False`` if the plugin wasn't found.

    Parameters
    ----------
    name : str
        Plugin stem name (e.g. ``"hello_plugin"``, not ``"hello_plugin.py"``).
    registry : ToolRegistry
        The registry to register tools into.
    """
    # Strip .py if provided
    stem = name.rsplit(".", 1)[0] if name.endswith(".py") else name

    # Find the plugin file
    for d in PLUGIN_DIRS:
        candidate = d / f"{stem}.py"
        if candidate.exists():
            # Clear from cache
            if stem in _loaded_modules:
                mod_name = _loaded_modules[stem]
                if mod_name in sys.modules:
                    del sys.modules[mod_name]
                del _loaded_modules[stem]
            if stem in _loaded_plugins:
                del _loaded_plugins[stem]
            load_path(candidate, registry)
            return True

    from _console import icon

    print(f"  {icon('warn')}  Plugin {stem!r} not found in plugin directories.")
    return False


# ── Plugin SDK: list / info ─────────────────────────────────────────


def list_plugins() -> list[dict[str, Any]]:
    """Return detailed metadata about all loaded plugins.

    Returns a list of dicts with keys:
      - name: plugin stem name (file name without .py)
      - path: full path to the plugin file
      - meta: ``__plugin_meta__`` dict (or defaults)
      - loaded: whether it's currently loaded in memory
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path in discover():
        stem = path.stem
        seen.add(stem)
        meta = _loaded_plugins.get(stem, {})
        result.append(
            {
                "name": stem,
                "path": str(path.resolve()),
                "meta": {
                    "name": meta.get("name", stem),
                    "version": meta.get("version", "0.0.0"),
                    "description": meta.get("description", ""),
                    "author": meta.get("author", "unknown"),
                },
                "loaded": stem in _loaded_plugins,
            }
        )

    return result


def plugin_info(name: str) -> dict[str, Any] | None:
    """Return metadata for a single plugin by stem name.

    Returns ``None`` if the plugin file doesn't exist.
    """
    stem = name.rsplit(".", 1)[0] if name.endswith(".py") else name
    for d in PLUGIN_DIRS:
        candidate = d / f"{stem}.py"
        if candidate.exists():
            meta = _loaded_plugins.get(stem, {})
            return {
                "name": stem,
                "path": str(candidate.resolve()),
                "meta": {
                    "name": meta.get("name", stem),
                    "version": meta.get("version", "0.0.0"),
                    "description": meta.get("description", ""),
                    "author": meta.get("author", "unknown"),
                },
                "loaded": stem in _loaded_plugins,
            }
    return None


# ── Plugin SDK: install ─────────────────────────────────────────────


def install_plugin(
    source: str | Path,
    *,
    target_dir: Path | None = None,
    name: str | None = None,
) -> Path | None:
    """Install a plugin from a local path or GitHub URL.

    Parameters
    ----------
    source : str or Path
        Local path to a ``.py`` file, or a GitHub URL pointing to a raw
        plugin file (``https://raw.githubusercontent.com/...``).
    target_dir : Path, optional
        Directory to install into (defaults to ``PLUGIN_DIRS[0]``).
    name : str, optional
        Target filename (defaults to the source filename).

    Returns
    -------
    Path to the installed file, or ``None`` on failure.
    """
    from _console import icon

    dest_dir = target_dir or PLUGIN_DIRS[0]
    dest_dir.mkdir(parents=True, exist_ok=True)

    source_str = str(source)

    # GitHub URL
    if source_str.startswith("https://") or source_str.startswith("http://"):
        return _install_from_url(source_str, dest_dir, name)

    # Local path
    src_path = Path(source_str).resolve()
    if not src_path.exists():
        print(f"  {icon('error')}  Source not found: {src_path}")
        return None
    if not src_path.suffix == ".py":
        print(f"  {icon('error')}  Plugin source must be a ``.py`` file: {src_path}")
        return None

    dest_name = name or src_path.name
    dest_path = dest_dir / dest_name

    shutil.copy2(src_path, dest_path)
    print(f"  {icon('ok')}  Installed plugin: {dest_path}")

    # Auto-detect and install requirements
    _maybe_install_requirements(src_path)

    return dest_path


def install_plugin_from_github(
    repo: str,
    *,
    path: str = "",
    target_dir: Path | None = None,
    name: str | None = None,
) -> Path | None:
    """Install a plugin from a GitHub repository.

    Parameters
    ----------
    repo : str
        GitHub repository in ``owner/repo`` format.
    path : str
        Path within the repo to the plugin file (optional).
    target_dir : Path, optional
        Directory to install into.
    name : str, optional
        Target filename.

    Returns
    -------
    Path to the installed file, or ``None`` on failure.
    """
    from _console import icon

    # Clone to temp, copy the plugin file
    tmp_dir = Path(tempfile.mkdtemp(prefix="virgo_plugin_"))
    try:
        url = f"https://github.com/{repo}.git"
        print(f"  {icon('arrow')}  Cloning {repo}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(tmp_dir / "repo")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"  {icon('error')}  Git clone failed: {result.stderr}")
            return None

        repo_dir = tmp_dir / "repo"
        if path:
            source = repo_dir / path
        else:
            # Auto-find *.py files that have register() or __plugin_meta__
            candidates = []
            for f in sorted(repo_dir.rglob("*.py")):
                if f.name.startswith("_"):
                    continue
                content = f.read_text(encoding="utf-8", errors="replace")
                if "def register(" in content or "__plugin_meta__" in content:
                    candidates.append(f)

            if len(candidates) == 1:
                source = candidates[0]
            elif not candidates:
                print(f"  {icon('error')}  No plugin files found in {repo}")
                return None
            else:
                print(f"  {icon('warn')}  Multiple plugin candidates, using first: {candidates[0].name}")
                source = candidates[0]

        if not source.exists():
            print(f"  {icon('error')}  File not found: {source}")
            return None

        dest_dir = target_dir or PLUGIN_DIRS[0]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = name or source.name
        dest_path = dest_dir / dest_name

        shutil.copy2(source, dest_path)
        print(f"  {icon('ok')}  Installed plugin from {repo}: {dest_path}")

        _maybe_install_requirements(source)

        return dest_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _install_from_url(url: str, dest_dir: Path, name: str | None) -> Path | None:
    """Download a plugin from a URL and save it to *dest_dir*."""
    from _console import icon

    import urllib.request

    dest_name = name or url.rsplit("/", 1)[-1]
    if not dest_name.endswith(".py"):
        dest_name += ".py"

    dest_path = dest_dir / dest_name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "virgo-plugin-installer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        dest_path.write_text(content, encoding="utf-8")
        print(f"  {icon('ok')}  Installed plugin from URL: {dest_path}")
        return dest_path
    except Exception as exc:
        print(f"  {icon('error')}  Failed to download {url}: {exc}")
        return None


def _maybe_install_requirements(plugin_path: Path) -> None:
    """Check a plugin file for ``# requirements:`` or ``# pip:`` comments and install them."""
    from _console import icon

    content = plugin_path.read_text(encoding="utf-8", errors="replace")
    deps: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        for prefix in ("# requirements:", "# pip:", "# requires:"):
            if stripped.lower().startswith(prefix.lower()):
                dep = stripped[len(prefix):].strip()
                if dep:
                    deps.append(dep)

    if not deps:
        return

    print(f"  {icon('arrow')}  Installing plugin dependencies: {', '.join(deps)}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *deps],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print(f"  {icon('ok')}  Dependencies installed successfully.")
        else:
            print(f"  {icon('warn')}  Some dependencies may have failed: {result.stderr[:200]}")
    except Exception as exc:
        print(f"  {icon('warn')}  Could not install dependencies: {exc}")


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
    callback: callable | None = None,
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
    from _console import icon

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
                if path.stem in _loaded_modules:
                    del _loaded_modules[path.stem]
                if path.stem in _loaded_plugins:
                    del _loaded_plugins[path.stem]
                load_path(path, registry)
                if callback:
                    callback("modified", path)
            except Exception as exc:
                print(f"  {icon('error')}  Hot-reload error for {path.name}: {exc}")

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
        print(f"  {icon('refresh')}  Hot-reload active (watchdog, {len(loaded)} plugin(s))")
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
    print(f"  {icon('refresh')}  Hot-reload active (polling, {len(loaded)} plugin(s))")
    return t

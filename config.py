"""
config — pipeline configuration for virgo.

Supports JSON and TOML config files.  YAML is also supported if
``pyyaml`` is installed.

Looks for ``virgo.toml``, ``virgo.json``, or ``.virgo.toml`` in the
current directory and parent directories.

Example ``virgo.toml``::

    [model]
    planner = "qwen2.5-coder:7b"
    generator = "qwen2.5-coder:7b"
    fixer = "qwen2.5-coder:7b"
    timeout = 300

    [sandbox]
    mode = "allowlist"          # "allowlist" | "blocklist"
    allowed_commands = ["python", "pip", "git", "ls", "cat", "echo",
                        "pwd", "head", "tail", "wc", "sort", "grep",
                        "find", "mkdir", "cp", "mv", "which", "curl -s"]

    [plugins]
    watch = true                # hot-reload plugins
    dirs = ["plugins", "~/.virgo/plugins"]

    [chat]
    model = "qwen2.5-coder:7b"
    max_tokens = 2048
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Default config values
DEFAULT_CONFIG: dict[str, Any] = {
    "model": {
        "planner": os.getenv("MODEL_PLANNER", "ornith:latest"),
        "generator": os.getenv("MODEL_GENERATOR", "ornith:latest"),
        "fixer": os.getenv("MODEL_FIXER", "ornith:latest"),
        "timeout": int(os.getenv("LLM_TIMEOUT", "300")),
    },
    "sandbox": {
        "mode": "allowlist",
        "allowed_commands": [
            "python", "pip", "git", "ls", "cat", "echo",
            "pwd", "head", "tail", "wc", "sort", "grep",
            "find", "mkdir", "cp", "mv", "which",
        ],
    },
    "plugins": {
        "watch": True,
        "dirs": ["plugins"],
    },
    "chat": {
        "model": os.getenv("MODEL_PLANNER", "ornith:latest"),
        "max_tokens": 2048,
    },
}


def _find_config() -> Path | None:
    """Walk up from CWD looking for virgo.toml, .virgo.toml, or virgo.json."""
    start = Path.cwd()
    for parent in [start] + list(start.parents):
        for name in ("virgo.toml", ".virgo.toml", "virgo.json"):
            candidate = parent / name
            if candidate.exists():
                return candidate
    return None


def load(path: str = "") -> dict[str, Any]:
    """Load configuration from a file, merged with defaults.

    If *path* is empty, walks up the directory tree looking for
    ``virgo.toml``, ``.virgo.toml``, or ``virgo.json``.
    Returns defaults if no file is found.
    """
    config_path: Path | None = None

    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
    else:
        config_path = _find_config()

    if config_path is None:
        return dict(DEFAULT_CONFIG)

    ext = config_path.suffix.lower()
    raw: dict[str, Any] = {}

    if ext == ".toml":
        raw = _load_toml(config_path)
    elif ext == ".json":
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    elif ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "pyyaml is required for YAML configs. Install with: pip install pyyaml"
            )
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        raise ValueError(f"Unsupported config format: {ext} (use .toml, .json, .yaml, or .yml)")

    # Merge with defaults (config values take priority)
    merged = dict(DEFAULT_CONFIG)
    _deep_merge(merged, raw)
    return merged


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file. Uses stdlib tomllib (3.11+) or tomli."""
    import sys as _sys
    if _sys.version_info >= (3, 11):
        import tomllib
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    try:
        import tomli
        with open(path, "rb") as fh:
            return tomli.load(fh)
    except ImportError:
        raise ImportError(
            "tomli is required for TOML configs on Python <3.11. "
            "Install with: pip install tomli"
        )


def _deep_merge(base: dict, overlay: dict) -> None:
    """Recursively merge *overlay* into *base*."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def merge_with_cli(config: dict[str, Any], args: Any) -> dict[str, Any]:
    """Merge CLI args into config (CLI values take precedence)."""
    result = dict(config)

    cli_overrides = {
        "goal": getattr(args, "goal", None),
        "max_iterations": getattr(args, "iterations", None),
        "name": getattr(args, "name", None),
        "llm": getattr(args, "llm", None),
    }

    for key, value in cli_overrides.items():
        if value is not None:
            result[key] = value

    return result

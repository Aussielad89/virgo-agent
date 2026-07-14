"""
config — pipeline configuration for virgo.

Supports JSON config files.  YAML is also supported if ``pyyaml``
is installed.

Example ``pipeline.json``::

    {
      "goal": "Parse mock_logs.txt and extract ERROR lines",
      "max_iterations": 5,
      "max_plan_cycles": 3,
      "workspace_excludes": ["agent_env", ".git", "__pycache__"],
      "llm": false,
      "name": "log-parser"
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def load(path: str) -> dict[str, Any]:
    """Load a pipeline configuration from a JSON or YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    ext = p.suffix.lower()
    if ext == ".json":
        return json.loads(p.read_text(encoding="utf-8"))

    if ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "pyyaml is required for YAML configs. Install with: pip install pyyaml"
            )
        with open(p, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    raise ValueError(f"Unsupported config format: {ext} (use .json, .yaml, or .yml)")


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

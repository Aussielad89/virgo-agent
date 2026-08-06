"""
virgo_contextual_widget — Auto-generated contextual widgets for Virgo Desktop.

Dynamically creates mini-widgets that float in the corner of the
page area based on the agent's current activity. Each widget is
registered by a virgo module via a simple decorator and provides
a factory function that returns a QWidget.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

WIDGETS_DIR = HERE / ".virgo_widgets"
WIDGETS_DIR.mkdir(exist_ok=True)
WIDGET_REGISTRY: dict[str, dict[str, Any]] = {}


@dataclass
class WidgetProvider:
    name: str
    triggers: list[str] = field(default_factory=list)
    priority: int = 0
    factory: Callable | None = None
    widget_class: type | None = None


def widget_provider(
    name: str,
    triggers: list[str] | None = None,
    priority: int = 0,
) -> Callable:
    """Decorator to register a widget provider.

    Usage::

        @widget_provider(name="network_map", triggers=["network_scan"], priority=10)
        def network_map_widget(parent):
            return NetworkMapWidget(parent)
    """

    def decorator(func: Callable) -> Callable:
        WIDGET_REGISTRY[name] = {
            "name": name,
            "triggers": triggers or [],
            "priority": priority,
            "factory": func,
        }
        return func

    return decorator


def register_widget(
    name: str,
    factory: Callable,
    triggers: list[str] | None = None,
    priority: int = 0,
) -> None:
    """Register a widget provider programmatically."""
    WIDGET_REGISTRY[name] = {
        "name": name,
        "triggers": triggers or [],
        "priority": priority,
        "factory": factory,
    }
    log.info("widget: registered '%s' (triggers=%s, priority=%d)", name, triggers, priority)


def get_widget(name: str) -> Callable | None:
    """Get a widget factory by name."""
    entry = WIDGET_REGISTRY.get(name)
    if entry is None:
        return None
    return entry.get("factory")


def list_widgets() -> list[dict[str, Any]]:
    """List all registered widgets sorted by priority."""
    return sorted(
        [
            {
                "name": e["name"],
                "triggers": e["triggers"],
                "priority": e["priority"],
            }
            for e in WIDGET_REGISTRY.values()
        ],
        key=lambda x: -x["priority"],
    )


def get_widgets_for_triggers(triggers: list[str]) -> list[dict[str, Any]]:
    """Get widgets that match any of the given triggers."""
    matched = []
    for name, entry in WIDGET_REGISTRY.items():
        if any(t in triggers for t in entry["triggers"]):
            matched.append({
                "name": name,
                "triggers": entry["triggers"],
                "priority": entry["priority"],
                "factory": entry["factory"],
            })
    matched.sort(key=lambda x: -x["priority"])
    return matched


def save_registry() -> None:
    try:
        data = {
            name: {
                "triggers": e["triggers"],
                "priority": e["priority"],
            }
            for name, e in WIDGET_REGISTRY.items()
        }
        WIDGETS_DIR.joinpath("registry.json").write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_registry() -> None:
    reg_file = WIDGETS_DIR / "registry.json"
    if not reg_file.exists():
        return
    try:
        data = json.loads(reg_file.read_text(encoding="utf-8"))
        for name, entry in data.items():
            if name in WIDGET_REGISTRY:
                WIDGET_REGISTRY[name]["triggers"] = entry.get("triggers", [])
                WIDGET_REGISTRY[name]["priority"] = entry.get("priority", 0)
    except Exception:
        pass


import json


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Contextual Widgets")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("list", help="List registered widgets")
    sub.add_parser("triggers", help="Show trigger mappings")
    args = p.parse_args()
    if args.command == "list":
        for w in list_widgets():
            print(f"{w['name']}: triggers={w['triggers']}, priority={w['priority']}")
    elif args.command == "triggers":
        for name, entry in WIDGET_REGISTRY.items():
            print(f"{name}: {entry['triggers']}")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
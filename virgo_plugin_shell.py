"""
virgo_plugin_shell — Plugin shell system for Virgo Desktop.

Turns the desktop into a modular platform where any virgo_*.py
module can register itself as a first-class desktop component
with its own page, sidebar entry, and settings.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

PLUGIN_DIR = HERE / ".virgo_plugins"
PLUGIN_DIR.mkdir(exist_ok=True)
PLUGIN_REGISTRY_FILE = PLUGIN_DIR / "registry.json"


@dataclass
class PluginDescriptor:
    name: str
    module_name: str
    display_name: str = ""
    icon: str = "•"
    group: str = "Plugins"
    priority: int = 0
    page_class: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


def _load_registry() -> dict[str, Any]:
    if PLUGIN_REGISTRY_FILE.exists():
        try:
            return json.loads(PLUGIN_REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"plugins": []}


def _save_registry(data: dict[str, Any]) -> None:
    try:
        PLUGIN_REGISTRY_FILE.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def discover_plugins() -> list[PluginDescriptor]:
    """Scan for all virgo_*.py modules that expose DESKTOP_PLUGIN."""
    plugins: list[PluginDescriptor] = []
    here = HERE

    for f in sorted(here.glob("virgo_*.py")):
        module_name = f.stem
        if module_name == "virgo_desktop":
            continue
        try:
            spec = importlib.util.spec_from_file_location(module_name, f)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            plugin_info = getattr(mod, "DESKTOP_PLUGIN", None)
            if plugin_info is None:
                continue

            if isinstance(plugin_info, dict):
                plugins.append(PluginDescriptor(
                    name=module_name,
                    module_name=module_name,
                    display_name=plugin_info.get("name", module_name),
                    icon=plugin_info.get("icon", "•"),
                    group=plugin_info.get("group", "Plugins"),
                    priority=plugin_info.get("priority", 0),
                    page_class=plugin_info.get("page_class", ""),
                    settings=plugin_info.get("settings", {}),
                ))
        except Exception as exc:
            log.debug("plugin discover: %s failed (%s)", module_name, exc)

    # Also check registry for manually registered plugins
    registry = _load_registry()
    for entry in registry.get("plugins", []):
        if isinstance(entry, dict):
            desc = PluginDescriptor(
                name=entry.get("name", ""),
                module_name=entry.get("module_name", ""),
                display_name=entry.get("display_name", ""),
                icon=entry.get("icon", "•"),
                group=entry.get("group", "Plugins"),
                priority=entry.get("priority", 0),
                page_class=entry.get("page_class", ""),
                settings=entry.get("settings", {}),
                enabled=entry.get("enabled", True),
            )
            if desc.name not in [p.name for p in plugins]:
                plugins.append(desc)

    plugins.sort(key=lambda p: (-p.priority, p.name))
    return plugins


def register_plugin(descriptor: PluginDescriptor) -> None:
    """Register a plugin in the persistent registry."""
    registry = _load_registry()
    # Remove existing entry with same name
    registry["plugins"] = [
        p for p in registry["plugins"]
        if p.get("name") != descriptor.name
    ]
    registry["plugins"].append({
        "name": descriptor.name,
        "module_name": descriptor.module_name,
        "display_name": descriptor.display_name,
        "icon": descriptor.icon,
        "group": descriptor.group,
        "priority": descriptor.priority,
        "page_class": descriptor.page_class,
        "settings": descriptor.settings,
        "enabled": descriptor.enabled,
    })
    _save_registry(registry)
    log.info("plugin: registered '%s'", descriptor.name)


def enable_plugin(name: str) -> bool:
    registry = _load_registry()
    for p in registry.get("plugins", []):
        if p.get("name") == name:
            p["enabled"] = True
            _save_registry(registry)
            return True
    return False


def disable_plugin(name: str) -> bool:
    registry = _load_registry()
    for p in registry.get("plugins", []):
        if p.get("name") == name:
            p["enabled"] = False
            _save_registry(registry)
            return True
    return False


def get_enabled_plugins() -> list[PluginDescriptor]:
    """Get only enabled plugins."""
    all_plugins = discover_plugins()
    registry = _load_registry()
    disabled = {
        p.get("name")
        for p in registry.get("plugins", [])
        if not p.get("enabled", True)
    }
    return [p for p in all_plugins if p.name not in disabled]


def load_plugin_page(module_name: str) -> Any | None:
    """Dynamically load a plugin's page class."""
    try:
        mod = importlib.import_module(module_name)
        plugin_info = getattr(mod, "DESKTOP_PLUGIN", {})
        page_class_name = plugin_info.get("page_class", "")
        if page_class_name:
            return getattr(mod, page_class_name, None)
        # Fallback: look for a Page class
        return getattr(mod, "Page", None)
    except Exception as exc:
        log.error("plugin load failed for %s: %s", module_name, exc)
        return None


def get_plugin_settings(name: str) -> dict[str, Any]:
    registry = _load_registry()
    for p in registry.get("plugins", []):
        if p.get("name") == name:
            return p.get("settings", {})
    return {}


def update_plugin_settings(name: str, settings: dict[str, Any]) -> None:
    registry = _load_registry()
    for p in registry.get("plugins", []):
        if p.get("name") == name:
            p["settings"] = settings
            _save_registry(registry)
            return


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Plugin Shell")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("discover", help="Discover available plugins")
    sub.add_parser("enabled", help="List enabled plugins")
    reg = sub.add_parser("register")
    reg.add_argument("name")
    reg.add_argument("--module", required=True)
    reg.add_argument("--group", default="Plugins")
    reg.add_argument("--priority", type=int, default=0)
    enable = sub.add_parser("enable")
    enable.add_argument("name")
    disable = sub.add_parser("disable")
    disable.add_argument("name")
    args = p.parse_args()
    if args.command == "discover":
        for plugin in discover_plugins():
            status = "enabled" if plugin.enabled else "disabled"
            print(f"{plugin.icon} {plugin.display_name} [{plugin.name}] ({status})")
    elif args.command == "enabled":
        for plugin in get_enabled_plugins():
            print(f"{plugin.icon} {plugin.display_name} [{plugin.name}]")
    elif args.command == "register":
        desc = PluginDescriptor(
            name=args.name,
            module_name=args.module,
            group=args.group,
            priority=args.priority,
        )
        register_plugin(desc)
        print(f"Registered plugin: {args.name}")
    elif args.command == "enable":
        ok = enable_plugin(args.name)
        print(f"Enabled: {ok}")
    elif args.command == "disable":
        ok = disable_plugin(args.name)
        print(f"Disabled: {ok}")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()
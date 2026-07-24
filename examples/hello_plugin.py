"""
hello_plugin — a minimal example Virgo plugin.

Demonstrates the plugin SDK conventions:
  - ``__plugin_meta__`` for metadata
  - ``register(registry)`` for tool registration
  - Type hints, ``from __future__ import annotations``

Usage
-----
Place this file in a ``plugins/`` directory or run:
    virgo plugin install ./examples/hello_plugin.py
    virgo plugins --load
"""

from __future__ import annotations

from typing import Any

__plugin_meta__ = {
    "name": "hello_plugin",
    "version": "0.1.0",
    "description": "A friendly hello-world plugin for Virgo",
    "author": "Virgo Contributors",
}


def register(registry: Any) -> None:
    """Register this plugin's tools with the tool registry.

    Parameters
    ----------
    registry : ToolRegistry
        The virgo tool registry instance.
    """
    from tools import Tool

    registry.register(
        Tool(
            name="hello",
            fn=hello_world,
            description="Say hello to someone or the world",
        )
    )

    registry.register(
        Tool(
            name="goodbye",
            fn=goodbye,
            description="Say goodbye to someone",
        )
    )


def hello_world(name: str = "World") -> str:
    """Return a friendly greeting message.

    Parameters
    ----------
    name : str
        The person to greet (default: "World").

    Returns
    -------
    str
        A greeting string.
    """
    return f"Hello, {name}! Welcome to Virgo."


def goodbye(name: str = "friend") -> str:
    """Return a farewell message.

    Parameters
    ----------
    name : str
        The person to say goodbye to (default: "friend").

    Returns
    -------
    str
        A farewell string.
    """
    return f"Goodbye, {name}! Thanks for using Virgo."

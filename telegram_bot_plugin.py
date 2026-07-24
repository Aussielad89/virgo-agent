"""
telegram_bot_plugin — Virgo plugin for the Telegram bot.

Exports a ``register(registry)`` function that gives the plugin loader
access to the bot lifecycle.
"""

from __future__ import annotations

from typing import Any


def register(registry: Any) -> None:
    """Register the Telegram bot as a tool in the Virgo registry."""
    try:
        from virgo_bot import bot_status, is_running, start_polling, stop_polling
    except ImportError as exc:
        print(f"  [telegram_bot_plugin] Could not import virgo_bot: {exc}")
        return

    # Register bot tools
    from tools import Tool

    def tool_bot_start() -> str:
        """Start the Telegram bot in the background."""
        if is_running():
            return "Bot is already running."
        start_polling()
        return "Telegram bot started."

    def tool_bot_stop() -> str:
        """Stop the Telegram bot."""
        if not is_running():
            return "Bot is not running."
        stop_polling()
        return "Telegram bot stopped."

    def tool_bot_status() -> str:
        """Show the Telegram bot status."""
        st = bot_status()
        return (
            f"Running: {st['running']}\n"
            f"Started: {st['started']}\n"
            f"Uptime: {st['uptime_seconds']}s\n"
            f"Mode: {st['mode']}\n"
            f"Allowed chats: {st['allowed_chats']}\n"
            f"Poll interval: {st['poll_interval']}"
        )

    registry.register(Tool(name="telegram bot start", fn=tool_bot_start, description="Start the Telegram bot"))
    registry.register(Tool(name="telegram bot stop", fn=tool_bot_stop, description="Stop the Telegram bot"))
    registry.register(Tool(name="telegram bot status", fn=tool_bot_status, description="Show Telegram bot status"))
    print("  [telegram_bot_plugin]  Registered 3 bot tools")

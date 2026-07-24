"""
virgo_bot — Telegram bot for Virgo Agent.

Two modes:
  1. **python-telegram-bot** (if installed) — full async Application.
  2. **Pure urllib fallback** — polls getUpdates + sendMessage directly.

Config (via .env or env vars):
  TELEGRAM_BOT_TOKEN  — Bot token (required)
  TELEGRAM_CHAT_ID    — Allowed chat ID(s), comma-separated (empty = all)
  TELEGRAM_POLL_INTERVAL — Polling interval in seconds (default: 2)
  TELEGRAM_RATE_LIMIT — Max messages per minute per chat (default: 10)

Usage:
    python virgo_bot.py               # start polling (standalone)
    virgo bot start                   # via CLI
    virgo bot stop                    # via CLI
    virgo bot status                  # show bot status
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import OUTDIR, log

# ── Constants ────────────────────────────────────────────────────────────

BOT_LOGS_DIR = OUTDIR / "bot_logs"
BOT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS: list[str] = [
    cid.strip()
    for cid in os.environ.get("TELEGRAM_CHAT_ID", "").split(",")
    if cid.strip()
]
POLL_INTERVAL: float = float(os.environ.get("TELEGRAM_POLL_INTERVAL", "2"))
RATE_LIMIT: int = int(os.environ.get("TELEGRAM_RATE_LIMIT", "10"))

# ── State ────────────────────────────────────────────────────────────────

_bot_thread: threading.Thread | None = None
_bot_stop_event = threading.Event()
_bot_started: float | None = None
_bot_running = False
_bot_application: Any = None  # holds PTB Application if mode=ptb
_current_pipeline: Any = None  # reference to running pipeline (cancellable)

# Rate limiting state: chat_id -> [(timestamp, ...)]
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


# ===========================================================================
# Helpers
# ===========================================================================


def _save_telemetry(data: dict) -> None:
    """Save a telemetry record to the bot logs directory."""
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = BOT_LOGS_DIR / f"telegram_{ts}.json"
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to save telegram telemetry: %s", exc)


def _is_allowed(chat_id: str | int) -> bool:
    """Check if a chat id is in the allowed list (or allow all if none configured)."""
    if not CHAT_IDS:
        return True
    return str(chat_id) in CHAT_IDS


def _check_rate_limit(chat_id: str | int) -> bool:
    """Check and update the rate limit for a given chat.
    Returns True if the message is allowed, False if rate-limited.
    """
    cid = str(chat_id)
    now = time.monotonic()
    window = 60.0  # 1 minute

    with _rate_lock:
        bucket = _rate_buckets[cid]
        # Prune old entries
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= RATE_LIMIT:
            return False
        bucket.append(now)
    return True


def _get_status_text() -> str:
    """Return a formatted status message."""
    lines: list[str] = ["🤖 *Virgo Bot Status*", ""]
    if _bot_started:
        uptime = time.time() - _bot_started
        hours, rem = divmod(int(uptime), 3600)
        minutes, seconds = divmod(rem, 60)
        lines.append(f"• Status: **{'Running' if _bot_running else 'Stopped'}**")
        lines.append(f"• Uptime: `{hours}h {minutes}m {seconds}s`")
        lines.append(f"• Mode: `{'python-telegram-bot' if _PTB_AVAIL else 'urllib (fallback)'}`")
    else:
        lines.append("• Status: **Not started**")
    lines.append("")
    lines.append(f"• Allowed chats: `{', '.join(CHAT_IDS) if CHAT_IDS else 'ALL'}`")
    lines.append(f"• Poll interval: `{POLL_INTERVAL}s`")
    lines.append(f"• Rate limit: `{RATE_LIMIT} msg/min`")
    return "\n".join(lines)


# ── Check dependencies and import ─────────────────────────────────────

_PTB_AVAIL = False
try:
    import telegram  # noqa: F401
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.error import TelegramError
    from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

    _PTB_AVAIL = True
except ImportError:
    pass


# ===========================================================================
# python-telegram-bot implementation
# ===========================================================================


def _build_keyboard() -> InlineKeyboardMarkup:
    """Build the persistent command keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("/status", callback_data="/status"),
            InlineKeyboardButton("/alerts", callback_data="/alerts"),
        ],
        [
            InlineKeyboardButton("/search", callback_data="/search"),
            InlineKeyboardButton("/help", callback_data="/help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _ptb_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized. You are not in the allowed chat list.")
        return

    msg = (
        "👋 *Welcome to Virgo Bot!*\n\n"
        "I'm your Telegram interface to the Virgo Agent framework. "
        "I can run pipelines, show status, search the web, and more.\n\n"
        "Use the buttons below or type a command:\n"
        "• `/run <goal>` — Execute a pipeline\n"
        "• `/chat <message>` — Chat with Virgo\n"
        "• `/status` — Show bot/system status\n"
        "• `/alerts` — Show latest alerts\n"
        "• `/search <query>` — Web search\n"
        "• `/cancel` — Cancel a running pipeline\n"
        "• `/help` — Show all commands"
    )
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=_build_keyboard(),
    )


async def _ptb_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: C901
    """Handle /run command — trigger a pipeline run."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    text = update.message.text or ""
    goal = text.removeprefix("/run").strip()
    if not goal:
        await update.message.reply_text(
            "❓ Please provide a goal. Example:\n`/run parse mock_logs.txt`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🚀 Starting pipeline: `{goal}`...", parse_mode="Markdown")

    # Run the pipeline in a thread to not block
    def _pipeline_worker() -> None:
        try:
            from orchestrator import Orchestrator
            from tools import ToolRegistry

            from environment import AgentEnvironment

            env = AgentEnvironment(base_path=str(HERE))
            if env.is_ready:
                env.teardown()
            env.setup()
            registry = ToolRegistry()
            registry.register_defaults(env)

            # Load plugins
            from plugins import load_all

            load_all(registry)

            orch = Orchestrator(env, registry, base_path=str(HERE))
            state = orch.run(goal=goal, max_iterations=3)
            env.teardown()

            status = "✅ PASS" if state.loop_passed else "❌ FAIL"
            summary = (
                f"*Pipeline complete*\n"
                f"Goal: `{goal}`\n"
                f"Status: {status}\n"
                f"Files: {len(state.generated_files)}\n"
                f"Iterations: {state.iteration}"
            )
            asyncio_run(_ptb_send(cid, summary))
        except Exception as exc:
            asyncio_run(_ptb_send(cid, f"❌ Pipeline error: {exc}"))

    thread = threading.Thread(target=_pipeline_worker, daemon=True)
    thread.start()


def asyncio_run(coro: Any) -> None:
    """Run an async coroutine from a sync context."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        asyncio.run(coro)


async def _ptb_send(chat_id: int, text: str) -> None:
    """Send a message to a chat."""
    app = _bot_application
    if app is None:
        return
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc:
            log.warning("Failed to send message to %s: %s", chat_id, exc)


async def _ptb_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /chat command — chat with Virgo LLM."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    text = update.message.text or ""
    message = text.removeprefix("/chat").strip()
    if not message:
        await update.message.reply_text("❓ What would you like to say? Example:\n`/chat hello`", parse_mode="Markdown")
        return

    try:
        import main as _main

        client = _main.get_client_for("agent")
        response = client.chat(
            [{"role": "system", "content": "You are Virgo, a helpful AI assistant embedded in the Virgo Agent Framework. Be concise and practical."},
             {"role": "user", "content": message}],
            temperature=0.7,
            max_tokens=1024,
            role="agent",
        )
        reply = response or "🤔 No response from LLM."
    except Exception as exc:
        reply = f"⚠️ LLM unavailable: {exc}"

    await update.message.reply_text(reply, disable_web_page_preview=True)


async def _ptb_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(_get_status_text(), parse_mode="Markdown")


async def _ptb_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /alerts command — show latest alerts."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    try:
        from virgo_alerts import ALERTS_FILE

        if os.path.exists(ALERTS_FILE):
            alerts = Path(ALERTS_FILE).read_text(encoding="utf-8").strip()
            if alerts:
                await update.message.reply_text(f"🔔 *Latest Alerts:*\n```\n{alerts}\n```", parse_mode="Markdown")
                return
        await update.message.reply_text("✅ No active alerts.")
    except Exception as exc:
        await update.message.reply_text(f"⚠️ Could not read alerts: {exc}")


async def _ptb_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: C901
    """Handle /search command — web search via virgo_web_search."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    text = update.message.text or ""
    query = text.removeprefix("/search").strip()
    if not query:
        await update.message.reply_text("❓ What would you like to search? Example:\n`/search virgo agent framework`", parse_mode="Markdown")
        return

    await update.message.reply_text(f"🔍 Searching for: `{query}`...", parse_mode="Markdown")

    try:
        from virgo_web_search import web_search

        result = web_search(query)
        if result.get("status") == "error":
            await update.message.reply_text(f"❌ Search failed: {result.get('message', 'Unknown error')}")
            return

        results = result.get("results", [])
        if not results:
            await update.message.reply_text("📭 No results found.")
            return

        lines: list[str] = [f"🔍 *Search results for:* `{query}`", ""]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "").strip()
            url = r.get("url", "").strip()
            snippet = r.get("snippet", "").strip()
            lines.append(f"{i}. *{title}*")
            if url:
                lines.append(f"   `{url}`")
            if snippet:
                lines.append(f"   _{snippet[:150]}_")
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ Search error: {exc}")


async def _ptb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command — cancel running pipeline."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    global _current_pipeline
    if _current_pipeline is not None:
        _current_pipeline = None
        await update.message.reply_text("⏹️ Pipeline cancelled.")
    else:
        await update.message.reply_text("ℹ️ No pipeline is currently running.")


async def _ptb_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    msg = (
        "🤖 *Virgo Bot Commands*\n\n"
        "• `/start` — Welcome + help\n"
        "• `/run <goal>` — Trigger a pipeline run\n"
        "• `/chat <message>` — Chat with Virgo LLM\n"
        "• `/status` — Bot and system status\n"
        "• `/alerts` — Show latest alerts\n"
        "• `/search <query>` — Web search\n"
        "• `/cancel` — Cancel a running pipeline\n"
        "• `/help` — Show this help\n\n"
        "You can also send any message and I'll chat with you."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_build_keyboard())


async def _ptb_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command messages — simple chat back."""
    cid = update.effective_chat.id if update.effective_chat else None
    if cid is None:
        return
    if not _is_allowed(cid):
        return
    if not _check_rate_limit(cid):
        await update.message.reply_text("⏳ Rate limit reached. Please wait a moment.")
        return

    text = update.message.text or ""
    if not text.strip():
        return

    try:
        import main as _main

        client = _main.get_client_for("agent")
        response = client.chat(
            [{"role": "system", "content": "You are Virgo, a helpful AI assistant. Be concise and practical."},
             {"role": "user", "content": text}],
            temperature=0.7,
            max_tokens=1024,
            role="agent",
        )
        reply = response or "🤔 No response from LLM."
    except Exception:
        reply = f"🤖 *Virgo echo:* {text}"

    await update.message.reply_text(reply, disable_web_page_preview=True)


async def _ptb_error_handler(update: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors from the PTB framework."""
    log.error("PTB error: %s", context.error)
    _save_telemetry({"event": "error", "error": str(context.error), "update": str(update)[:500]})


# ===========================================================================
# urllib fallback implementation (no python-telegram-bot)
# ===========================================================================


def _api_url(method: str) -> str:
    """Build a URL for a Telegram Bot API method."""
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def _api_call(method: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a synchronous call to the Telegram Bot API with urllib."""
    import urllib.parse
    import urllib.request

    url = _api_url(method)
    if data:
        encoded = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    else:
        req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)  # type: ignore[no-any-return]
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def _send_message(chat_id: int | str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message via the Telegram Bot API."""
    text = text or "(empty)"
    result = _api_call("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    })
    if not result.get("ok"):
        # Retry without Markdown
        result = _api_call("sendMessage", {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        })
    return bool(result.get("ok"))


def _handle_fallback_message(msg: dict[str, Any]) -> None:  # noqa: C901
    """Process a single incoming message in urllib mode."""
    chat = msg.get("chat", {})
    cid = chat.get("id")
    if cid is None:
        return

    if not _is_allowed(cid):
        return

    text = msg.get("text", "").strip()
    if not text:
        return

    if not _check_rate_limit(cid):
        _send_message(cid, "⏳ Rate limit reached. Please wait a moment.")
        return

    # ── Parse commands ──────────────────────────────────────────────
    lower = text.lower()

    if lower == "/start":
        reply = (
            "👋 *Welcome to Virgo Bot!*\n\n"
            "I'm your Telegram interface to the Virgo Agent framework.\n\n"
            "• `/run <goal>` — Execute a pipeline\n"
            "• `/chat <message>` — Chat with Virgo\n"
            "• `/status` — Show bot/system status\n"
            "• `/alerts` — Show latest alerts\n"
            "• `/search <query>` — Web search\n"
            "• `/cancel` — Cancel a running pipeline\n"
            "• `/help` — Show all commands"
        )
        _send_message(cid, reply)

    elif lower == "/help":
        reply = (
            "🤖 *Virgo Bot Commands*\n\n"
            "• `/start` — Welcome\n"
            "• `/run <goal>` — Run pipeline\n"
            "• `/chat <message>` — Chat\n"
            "• `/status` — Status\n"
            "• `/alerts` — Alerts\n"
            "• `/search <query>` — Search\n"
            "• `/cancel` — Cancel\n"
            "• `/help` — This help"
        )
        _send_message(cid, reply)

    elif lower == "/status":
        _send_message(cid, _get_status_text())

    elif lower == "/alerts":
        try:
            from virgo_alerts import ALERTS_FILE

            if os.path.exists(ALERTS_FILE):
                alerts = Path(ALERTS_FILE).read_text(encoding="utf-8").strip()
                if alerts:
                    _send_message(cid, f"🔔 *Latest Alerts:*\n```\n{alerts}\n```")
                else:
                    _send_message(cid, "✅ No active alerts.")
            else:
                _send_message(cid, "✅ No active alerts.")
        except Exception as exc:
            _send_message(cid, f"⚠️ Alert error: {exc}")

    elif lower == "/cancel":
        global _current_pipeline
        if _current_pipeline is not None:
            _current_pipeline = None
            _send_message(cid, "⏹️ Pipeline cancelled.")
        else:
            _send_message(cid, "ℹ️ No pipeline is currently running.")

    elif lower.startswith("/run "):
        goal = text.removeprefix("/run").strip()
        _send_message(cid, f"🚀 Starting pipeline: `{goal}`...")

        def _fallback_run(chat_id: int, g: str) -> None:
            try:
                from orchestrator import Orchestrator
                from tools import ToolRegistry

                from environment import AgentEnvironment

                env = AgentEnvironment(base_path=str(HERE))
                if env.is_ready:
                    env.teardown()
                env.setup()
                registry = ToolRegistry()
                registry.register_defaults(env)

                from plugins import load_all

                load_all(registry)

                orch = Orchestrator(env, registry, base_path=str(HERE))
                state = orch.run(goal=g, max_iterations=3)
                env.teardown()

                status = "✅ PASS" if state.loop_passed else "❌ FAIL"
                summary = (f"*Pipeline complete*\nGoal: `{g}`\n"
                           f"Status: {status}\nFiles: {len(state.generated_files)}\n"
                           f"Iterations: {state.iteration}")
                _send_message(chat_id, summary)
            except Exception as exc:
                _send_message(chat_id, f"❌ Pipeline error: {exc}")

        threading.Thread(target=_fallback_run, args=(cid, goal), daemon=True).start()

    elif lower.startswith("/chat "):
        message = text.removeprefix("/chat").strip()
        try:
            import main as _main

            client = _main.get_client_for("agent")
            response = client.chat(
                [{"role": "system", "content": "You are Virgo, a helpful AI assistant."},
                 {"role": "user", "content": message}],
                temperature=0.7,
                max_tokens=1024,
                role="agent",
            )
            reply = response or "🤔 No response from LLM."
        except Exception as exc:
            reply = f"⚠️ LLM error: {exc}"
        _send_message(cid, reply)

    elif lower.startswith("/search "):
        query = text.removeprefix("/search").strip()
        _send_message(cid, f"🔍 Searching for: `{query}`...")

        try:
            from virgo_web_search import web_search

            result = web_search(query)
            if result.get("status") == "error":
                _send_message(cid, f"❌ Search failed: {result.get('message', 'Unknown error')}")
                return

            results = result.get("results", [])
            if not results:
                _send_message(cid, "📭 No results found.")
                return

            lines = [f"🔍 *Results for:* `{query}`", ""]
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                snippet = r.get("snippet", "").strip()
                lines.append(f"{i}. *{title}*")
                if url:
                    lines.append(f"   `{url}`")
                if snippet:
                    lines.append(f"   _{snippet[:150]}_")
                lines.append("")

            _send_message(cid, "\n".join(lines))
        except Exception as exc:
            _send_message(cid, f"⚠️ Search error: {exc}")

    else:
        # Non-command: chat back
        try:
            import main as _main

            client = _main.get_client_for("agent")
            response = client.chat(
                [{"role": "system", "content": "You are Virgo, a helpful AI assistant. Be concise."},
                 {"role": "user", "content": text}],
                temperature=0.7,
                max_tokens=1024,
                role="agent",
            )
            reply = response or "🤔 No response from LLM."
        except Exception:
            reply = f"🤖 *Virgo echo:* {text}"

        _send_message(cid, reply)

    # Telemetry
    _save_telemetry({
        "event": "message",
        "chat_id": cid,
        "text": text[:200],
        "timestamp": datetime.now(UTC).isoformat(),
    })


def _poll_loop() -> None:
    """Poll the Telegram API for new messages (urllib fallback mode)."""
    offset = 0
    while not _bot_stop_event.is_set():
        try:
            result = _api_call("getUpdates", {
                "offset": offset,
                "timeout": POLL_INTERVAL,
                "allowed_updates": json.dumps(["message"]),
            })
            if result.get("ok"):
                for update in result.get("result", []):
                    update_id = update.get("update_id", 0)
                    if update_id >= offset:
                        offset = update_id + 1
                    msg = update.get("message")
                    if msg:
                        _handle_fallback_message(msg)
        except Exception as exc:
            log.warning("Poll error: %s", exc)

        if _bot_stop_event.wait(POLL_INTERVAL):
            break


# ===========================================================================
# Public API
# ===========================================================================


def start_polling() -> None:
    """Start the Telegram bot polling in a background thread."""
    global _bot_thread, _bot_started, _bot_running, _bot_application

    if _bot_running:
        print(f"{icon('warn')} Bot is already running.")
        return

    if not BOT_TOKEN:
        print(f"{icon('error')} TELEGRAM_BOT_TOKEN is not set.")
        print("  Set it in .env or as an environment variable.")
        return

    _bot_stop_event.clear()
    _bot_started = time.time()

    ptb_avail = _PTB_AVAIL

    if ptb_avail:
        try:
            import asyncio

            from telegram.ext import ApplicationBuilder

            app = (
                ApplicationBuilder()
                .token(BOT_TOKEN)
                .build()
            )

            # Register handlers
            app.add_handler(CommandHandler("start", _ptb_start))
            app.add_handler(CommandHandler("run", _ptb_run))
            app.add_handler(CommandHandler("chat", _ptb_chat))
            app.add_handler(CommandHandler("status", _ptb_status))
            app.add_handler(CommandHandler("alerts", _ptb_alerts))
            app.add_handler(CommandHandler("search", _ptb_search))
            app.add_handler(CommandHandler("cancel", _ptb_cancel))
            app.add_handler(CommandHandler("help", _ptb_help))
            app.add_handler(CommandHandler("h", _ptb_help))

            # Fallback for non-command messages
            from telegram.ext import MessageHandler, filters

            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _ptb_fallback))

            app.add_error_handler(_ptb_error_handler)

            _bot_application = app

            # Set bot commands
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                app.bot.set_my_commands([
                    BotCommand("start", "Welcome + help"),
                    BotCommand("run", "Run a pipeline"),
                    BotCommand("chat", "Chat with Virgo"),
                    BotCommand("status", "Show status"),
                    BotCommand("alerts", "Show alerts"),
                    BotCommand("search", "Web search"),
                    BotCommand("cancel", "Cancel running pipeline"),
                    BotCommand("help", "Show help"),
                ])
            )
            loop.close()

            # Start in background thread
            def _run_ptb() -> None:
                global _bot_running
                _bot_running = True
                try:
                    app.run_polling(
                        poll_interval=POLL_INTERVAL,
                        close_loop=False,
                    )
                except Exception as exc:
                    log.error("PTB polling error: %s", exc)
                finally:
                    _bot_running = False

            _bot_thread = threading.Thread(target=_run_ptb, daemon=True)
            _bot_thread.start()

            print(f"{icon('ok')} Telegram bot started (mode: python-telegram-bot)")
            print(f"{icon('info')} Poll interval: {POLL_INTERVAL}s")
            print(f"{icon('info')} Allowed chats: {', '.join(CHAT_IDS) if CHAT_IDS else 'ALL'}")
            log.info("Telegram bot started (PTB mode)")
            return

        except Exception as exc:
            log.warning("PTB startup failed, falling back to urllib: %s", exc)
            ptb_avail = False  # force fallback

    # Urllib fallback mode
    def _run_fallback() -> None:
        global _bot_running
        _bot_running = True
        try:
            _poll_loop()
        except Exception as exc:
            log.error("Fallback polling error: %s", exc)
        finally:
            _bot_running = False

    _bot_thread = threading.Thread(target=_run_fallback, daemon=True)
    _bot_thread.start()

    print(f"{icon('ok')} Telegram bot started (mode: urllib fallback)")
    print(f"{icon('info')} Poll interval: {POLL_INTERVAL}s")
    print(f"{icon('info')} Allowed chats: {', '.join(CHAT_IDS) if CHAT_IDS else 'ALL'}")
    log.info("Telegram bot started (urllib mode)")


def stop_polling() -> None:
    """Stop the Telegram bot polling."""
    global _bot_running, _bot_application

    if not _bot_running:
        print(f"{icon('warn')} Bot is not running.")
        return

    _bot_stop_event.set()

    if _bot_application is not None:
        try:
            import asyncio

            stop_fn = _bot_application.stop()
            if hasattr(stop_fn, "__await__"):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(stop_fn, loop)
                    else:
                        loop.run_until_complete(stop_fn)
                except RuntimeError:
                    asyncio.run(stop_fn)
        except Exception:
            pass
        _bot_application = None

    _bot_running = False
    print(f"{icon('ok')} Telegram bot stopped.")
    log.info("Telegram bot stopped")


def bot_status() -> dict[str, Any]:
    """Return the current bot status as a dict."""
    uptime = (time.time() - _bot_started) if _bot_started else 0
    return {
        "running": _bot_running,
        "started": _bot_started is not None,
        "uptime_seconds": round(uptime, 2),
        "mode": "python-telegram-bot" if _PTB_AVAIL else "urllib (fallback)",
        "token_set": bool(BOT_TOKEN),
        "allowed_chats": CHAT_IDS if CHAT_IDS else "ALL",
        "poll_interval": POLL_INTERVAL,
        "rate_limit": RATE_LIMIT,
    }


def is_running() -> bool:
    """Check if the bot is currently running."""
    return _bot_running


# ===========================================================================
# Standalone entry
# ===========================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "start":
            start_polling()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                stop_polling()
        elif cmd == "stop":
            stop_polling()
        elif cmd == "status":
            st = bot_status()
            print(f"  Running:     {st['running']}")
            print(f"  Started:     {st['started']}")
            print(f"  Uptime:      {st['uptime_seconds']}s")
            print(f"  Mode:        {st['mode']}")
            print(f"  Token set:   {st['token_set']}")
            print(f"  Allowed:     {st['allowed_chats']}")
            print(f"  Poll int:    {st['poll_interval']}")
            print(f"  Rate limit:  {st['rate_limit']}")
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python virgo_bot.py [start|stop|status]")
    else:
        start_polling()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_polling()

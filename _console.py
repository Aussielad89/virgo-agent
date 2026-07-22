"""
Console-safe output helpers for virgo.

Provides ASCII-only fallbacks for emoji, safe on all terminal encodings
(especially Windows cp1252).
"""

from __future__ import annotations

import sys

# ── Stdout encoding fix ─────────────────────────────────────────────────────
# On Windows, CPython often inherits cp1252 for stdout, which chokes on
# any Unicode > U+00FF.  Wrapping with utf-8 + errors='replace' makes
# every print() safe — unknown chars become "?" instead of crashing.
_ORIGINAL_ENCODING = (sys.stdout.encoding or "").lower()
if sys.stdout.encoding and _ORIGINAL_ENCODING != "utf-8":
    import io

    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )


def _supports_emoji() -> bool:
    """Return True if the terminal is likely to handle Unicode emoji."""
    # Windows terminals (cmd.exe, PowerShell) have poor emoji support even
    # when the encoding is UTF-8.  Always use ASCII icons on Windows.
    if sys.platform == "win32":
        return False
    enc = (_ORIGINAL_ENCODING or "").lower()
    return "utf" in enc or enc in ("", "unknown")


# ── Icons ──────────────────────────────────────────────────────────────────
# These are used by virgo_*.py modules for status prefixes.
# On UTF-8 terminals the emoji is used; on cp1252/etc the ASCII text is used.

_ICONS: dict[str, tuple[str, str]] = {
    "rocket": ("\U0001f680", "[RUN]"),  # 🚀
    "error": ("\u274c", "[ERR]"),  # ❌
    "file": ("\U0001f4c4", "[FILE]"),  # 📄
    "warn": ("\u26a0\ufe0f", "[!]"),  # ⚠️
    "arrow": ("\U0001f449", ">"),  # 👉
    "history": ("\U0001f4dc", "[LOG]"),  # 📜
    "brain": ("\U0001f9e0", "[AI]"),  # 🧠
    "virgo": ("\U0001f6f8", "[VIRGO]"),  # 🛸
    "web": ("\U0001f310", "[WEB]"),  # 🌐
    "search": ("\U0001f50d", "[SRCH]"),  # 🔍
    "video": ("\U0001f4fa", "[VID]"),  # 📺
    "tool": ("\U0001f6e0", "[TOOL]"),  # 🛠
    "fix": ("\U0001f527", "[FIX]"),  # 🔧
    "check": ("\U0001f52c", "[CHK]"),  # 🔬
    "sat": ("\U0001f4e1", "[NET]"),  # 🛰️
    "ok": ("\u2705", "[OK]"),  # ✅
    "shield": ("\U0001f6e1", "[SHIELD]"),  # 🛡️
    "refresh": ("\U0001f504", "[SYNC]"),  # 🔄
    "save": ("\U0001f4be", "[SAVE]"),  # 💾
    "bolt": ("\u26a1", "[PWR]"),  # ⚡
    "sparkle": ("\u2728", "[+]"),  # ✨
    "done": ("\U0001f3c6", "[DONE]"),  # 🏆
    "alert": ("\U0001f514", "[ALERT]"),  # 🔔
    "antenna": ("\U0001f4e1", "[NET]"),  # 📡
    "goal": ("\U0001f3af", "[GOAL]"),  # 🎯
    "discover": ("\U0001f50d", "[SCAN]"),  # 🔍
    "code": ("\U0001f4bb", "[CODE]"),  # 💻
    "test": ("\U0001f6e0", "[TEST]"),  # 🛠
    "pass": ("\u2705", "[PASS]"),  # ✅
    "fail": ("\u274c", "[FAIL]"),  # ❌
    "info": ("\u2139", "[INFO]"),  # ℹ
    "syntax": ("\U0001f52c", "[SYNTAX]"),  # 🔬
    "audio": ("\U0001f399\ufe0f", "[AUDIO]"),  # 🎙️
    "mic": ("\U0001f3a4", "[MIC]"),  # 🎤
    "send": ("\U0001f4e4", "[SEND]"),  # 📤
    "compare": ("\U0001f9f5", "[AB]"),  # 🧵
}

_use_emoji = _supports_emoji()


def icon(name: str) -> str:
    """Return the icon string (emoji or ASCII) for *name*."""
    pair = _ICONS.get(name)
    if pair is None:
        return f"[{name}]"
    return pair[0] if _use_emoji else pair[1]

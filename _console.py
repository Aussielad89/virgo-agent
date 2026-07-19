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
    "rocket":     ("\U0001F680", "[RUN]"),    # 🚀
    "error":       ("\u274C",    "[ERR]"),     # ❌
    "file":        ("\U0001F4C4", "[FILE]"),   # 📄
    "warn":        ("\u26A0\uFE0F", "[!]"),    # ⚠️
    "arrow":       ("\U0001F449", ">"),        # 👉
    "history":     ("\U0001F4DC", "[LOG]"),    # 📜
    "brain":       ("\U0001F9E0", "[AI]"),     # 🧠
    "virgo":       ("\U0001F6F8", "[VIRGO]"),  # 🛸
    "web":         ("\U0001F310", "[WEB]"),    # 🌐
    "search":      ("\U0001F50D", "[SRCH]"),   # 🔍
    "video":       ("\U0001F4FA", "[VID]"),    # 📺
    "tool":        ("\U0001F6E0", "[TOOL]"),   # 🛠
    "fix":         ("\U0001F527", "[FIX]"),    # 🔧
    "check":       ("\U0001F52C", "[CHK]"),    # 🔬
    "sat":         ("\U0001F4E1", "[NET]"),    # 🛰️
    "ok":          ("\u2705",    "[OK]"),       # ✅
    "shield":      ("\U0001F6E1", "[SHIELD]"), # 🛡️
    "refresh":     ("\U0001F504", "[SYNC]"),   # 🔄
    "save":        ("\U0001F4BE", "[SAVE]"),   # 💾
    "bolt":        ("\u26A1",    "[PWR]"),     # ⚡
    "sparkle":     ("\u2728",    "[+]"),       # ✨
    "done":        ("\U0001F3C6", "[DONE]"),   # 🏆
    "alert":       ("\U0001F514", "[ALERT]"),  # 🔔
    "antenna":     ("\U0001F4E1", "[NET]"),    # 📡
    "goal":        ("\U0001F3AF", "[GOAL]"),   # 🎯
    "discover":    ("\U0001F50D", "[SCAN]"),   # 🔍
    "code":        ("\U0001F4BB", "[CODE]"),   # 💻
    "test":        ("\U0001F6E0", "[TEST]"),   # 🛠
    "pass":        ("\u2705",    "[PASS]"),    # ✅
    "fail":        ("\u274C",    "[FAIL]"),    # ❌
    "info":        ("\u2139",    "[INFO]"),    # ℹ
    "syntax":      ("\U0001F52C", "[SYNTAX]"), # 🔬
    "audio":       ("\U0001F399\ufe0f", "[AUDIO]"), # 🎙️
    "mic":         ("\U0001F3A4", "[MIC]"),   # 🎤
    "send":        ("\U0001F4E4", "[SEND]"),  # 📤
}

_use_emoji = _supports_emoji()


def icon(name: str) -> str:
    """Return the icon string (emoji or ASCII) for *name*."""
    pair = _ICONS.get(name)
    if pair is None:
        return f"[{name}]"
    return pair[0] if _use_emoji else pair[1]

"""
workflow — visual pipeline graph and progress tracker for virgo.

Renders an ASCII pipeline graph showing each stage with its
current status, and provides a real-time progress bar for the
WTF loop.
"""

from __future__ import annotations

import shutil
import sys
import time
from typing import Optional

# ===========================================================================
# Pipeline graph definition
# ===========================================================================

PHASES = [
    ("discover",  "Discover",   "🔍"),
    ("plan",      "Plan",       "🧠"),
    ("approve",   "Approve",    "👤"),
    ("generate",  "Generate",   "💻"),
    ("critic",    "Critic",     "🔬"),
    ("deps",      "Deps",       "📦"),
    ("test",      "WTF Loop",   "🔄"),
    ("complete",  "Complete",   "✅"),
]

# ASCII fallback when emoji aren't supported
PHASES_ASCII = [
    ("discover",  "Discover",   "[*]"),
    ("plan",      "Plan",       "[P]"),
    ("approve",   "Approve",    "[U]"),
    ("generate",  "Generate",   "[G]"),
    ("critic",    "Critic",     "[C]"),
    ("deps",      "Deps",       "[D]"),
    ("test",      "WTF Loop",   "[T]"),
    ("complete",  "Complete",   "[X]"),
]


def _supports_emoji() -> bool:
    enc = (sys.stdout.encoding or "").lower()
    return "utf" in enc or enc in ("", "unknown")


# ===========================================================================
# Pipeline graph
# ===========================================================================

def render_graph(current_phase: str, passed: Optional[bool] = None) -> str:
    """Render a multi-line ASCII pipeline graph."""
    phases = PHASES if _supports_emoji() else PHASES_ASCII
    lines: list[str] = []
    cols = shutil.get_terminal_size((80, 24)).columns
    width = min(cols, 100)

    sep = "=" if not _supports_emoji() else "─"
    lines.append("")
    lines.append("  " + sep * (width - 4))
    lines.append("   Pipeline Status")
    lines.append("  " + sep * (width - 4))

    for i, (key, name, icon) in enumerate(phases):
        status = _phase_status(key, current_phase, passed)
        bar = _progress_bar(i, len(phases), key, current_phase, passed, width - 10)
        lines.append(f"   {icon}  {name:12s}  {status:12s}  {bar}")

    lines.append("  " + sep * (width - 4))
    lines.append("")
    return "\n".join(lines)


def _phase_status(key: str, current: str, passed: Optional[bool]) -> str:
    """Return status text for a phase."""
    order = [p[0] for p in PHASES]
    try:
        cur_idx = order.index(current)
        ph_idx = order.index(key)
    except ValueError:
        return "---" if not _supports_emoji() else "───"

    if _supports_emoji():
        if passed is True and key == current:
            return "✓ PASS"
        if passed is False and key == current:
            return "✗ FAIL"
        if ph_idx < cur_idx:
            return "✓ done"
        if ph_idx == cur_idx:
            return "◉ now"
        return "○ wait"
    else:
        if passed is True and key == current:
            return "PASS"
        if passed is False and key == current:
            return "FAIL"
        if ph_idx < cur_idx:
            return "done"
        if ph_idx == cur_idx:
            return "NOW"
        return "wait"


def _progress_bar(
    idx: int, total: int, key: str, current: str,
    passed: Optional[bool], width: int,
) -> str:
    """Render a small ASCII progress bar for the phase."""
    order = [p[0] for p in PHASES]
    try:
        cur_idx = order.index(current)
        ph_idx = order.index(key)
    except ValueError:
        return ""

    bar_width = max(width - 40, 20)
    filled = 0

    if passed is True:
        filled = bar_width if ph_idx <= cur_idx else 0
    elif passed is False and ph_idx == cur_idx:
        filled = bar_width  # full but failed
    elif ph_idx < cur_idx:
        filled = bar_width
    elif ph_idx == cur_idx:
        # Animate partially filled based on time
        filled = int((time.time() % 2) * bar_width)
    else:
        filled = 0

    if _supports_emoji():
        full, empty = "▓", "░"
    else:
        full, empty = "#", "."

    blocks = full * filled + empty * (bar_width - filled)
    return f"[{blocks}]"


# ===========================================================================
# Progress bar for WTF loop
# ===========================================================================

class ProgressBar:
    """Simple inline progress bar for the WTF loop."""

    def __init__(self, total: int, prefix: str = "  Testing") -> None:
        self.total = total
        self.prefix = prefix
        self.start = time.time()
        self._width = min(shutil.get_terminal_size((80, 24)).columns - 20, 50)
        if _supports_emoji():
            self._full, self._empty = "█", "░"
        else:
            self._full, self._empty = "#", "."

    def update(self, iteration: int, passed: int, failed: int) -> None:
        """Print an updated progress line."""
        elapsed = time.time() - self.start
        frac = iteration / max(self.total, 1)
        filled = int(self._width * frac)
        bar = self._full * filled + self._empty * (self._width - filled)
        pct = int(frac * 100)
        eta = elapsed / max(frac, 0.01) - elapsed if frac > 0 else 0
        sys.stdout.write(
            f"\r  {self.prefix}: [{bar}] {pct}%  "
            f"{passed} pass, {failed} fail  "
            f"{elapsed:.1f}s / {eta:.0f}s   "
        )
        sys.stdout.flush()

    def done(self, passed: int, failed: int) -> None:
        """Finalise the progress bar."""
        elapsed = time.time() - self.start
        bar = self._full * self._width
        sys.stdout.write(
            f"\r  {self.prefix}: [{bar}] 100%  "
            f"{passed} pass, {failed} fail  "
            f"{elapsed:.1f}s total\n"
        )
        sys.stdout.flush()

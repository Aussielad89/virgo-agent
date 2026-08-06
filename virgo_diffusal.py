"""
virgo_diffusal — Live Code Diffusal engine.

Emits structured diff events during the WTF loop so the GUI can render
real-time before/after side-by-side diffs with syntax highlighting.

Usage (CLI):
    from virgo_diffusal import DiffusalEngine
    engine = DiffusalEngine()
    # In the fixer loop:
    engine.emit(file, old_content, new_content, iteration, error_msg)
    print(engine.format_last())  # ANSI-colored terminal diff

Usage (GUI):
    engine.on_diff = lambda event: self._render_diff(event)
    # engine.events contains all DiffEvent objects for the GUI
"""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DiffEvent:
    """A single diff event emitted during the WTF loop."""
    file: str
    old_content: str
    new_content: str
    iteration: int
    error_msg: str = ""
    timestamp: float = field(default_factory=time.time)
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(h.added for h in self.hunks)

    @property
    def removed(self) -> int:
        return sum(h.removed for h in self.hunks)

    @property
    def changed(self) -> bool:
        return self.added > 0 or self.removed > 0


@dataclass
class DiffHunk:
    """A single hunk within a diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]  # (tag, line) where tag is +, -, or space

    @property
    def added(self) -> int:
        return sum(1 for tag, _ in self.lines if tag == "+")

    @property
    def removed(self) -> int:
        return sum(1 for tag, _ in self.lines if tag == "-")


class DiffusalEngine:
    """Collects and formats code diffs during pipeline execution.

    The engine is lightweight — it stores events in memory and provides
    both ANSI terminal output and structured data for the GUI.
    """

    def __init__(self) -> None:
        self.events: list[DiffEvent] = []
        self.on_diff: Callable[[DiffEvent], None] | None = None
        self._diff_count = 0

    def emit(
        self,
        file: str,
        old_content: str,
        new_content: str,
        iteration: int,
        error_msg: str = "",
    ) -> DiffEvent:
        """Compute and emit a diff event. Returns the event for chaining."""
        hunks = self._compute_hunks(old_content, new_content)
        event = DiffEvent(
            file=file,
            old_content=old_content,
            new_content=new_content,
            iteration=iteration,
            error_msg=error_msg,
            hunks=hunks,
        )
        self.events.append(event)
        self._diff_count += 1

        if self.on_diff:
            try:
                self.on_diff(event)
            except Exception:
                pass  # Never let GUI callbacks break the pipeline

        return event

    def get_events_for_file(self, file: str) -> list[DiffEvent]:
        """Return all diff events for a specific file."""
        return [e for e in self.events if e.file == file]

    def get_stats(self) -> dict[str, Any]:
        """Return summary stats across all events."""
        total_added = sum(e.added for e in self.events)
        total_removed = sum(e.removed for e in self.events)
        files_changed = len(set(e.file for e in self.events))
        return {
            "total_diffs": self._diff_count,
            "files_changed": files_changed,
            "total_added": total_added,
            "total_removed": total_removed,
            "net_change": total_added - total_removed,
        }

    def format_last(self) -> str:
        """Return ANSI-colored terminal output for the most recent diff."""
        if not self.events:
            return ""
        return self.format_event(self.events[-1])

    def format_event(self, event: DiffEvent) -> str:
        """Return ANSI-colored terminal output for a specific diff event."""
        lines: list[str] = []

        # Header
        lines.append(f"\033[1;36m{'─' * 60}\033[0m")
        lines.append(
            f"  \033[1;33m⟳ DIFF #{self._diff_count}\033[0m  "
            f"\033[36m{event.file}\033[0m  "
            f"(iter {event.iteration})"
        )
        if event.error_msg:
            short_err = event.error_msg.strip().splitlines()[0][:80]
            lines.append(f"  \033[31mError: {short_err}\033[0m")
        lines.append(f"  \033[2m+{event.added} -{event.removed} lines\033[0m")
        lines.append(f"\033[1;36m{'─' * 60}\033[0m")

        # Diff content
        for hunk in event.hunks:
            lines.append(
                f"  \033[2m@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@\033[0m"
            )
            for tag, line in hunk.lines:
                if tag == "+":
                    lines.append(f"  \033[32m+ {line}\033[0m")
                elif tag == "-":
                    lines.append(f"  \033[31m- {line}\033[0m")
                else:
                    lines.append(f"  \033[2m  {line}\033[0m")

        lines.append(f"\033[1;36m{'─' * 60}\033[0m")
        return "\n".join(lines)

    def format_side_by_side(self, event: DiffEvent, width: int = 80) -> str:
        """Return a side-by-side text diff (useful for GUI text widgets)."""
        old_lines = event.old_content.splitlines(keepends=True)
        new_lines = event.new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{event.file}",
            tofile=f"b/{event.file}",
            lineterm="",
        )
        return "".join(diff)

    def format_html(self, event: DiffEvent) -> str:
        """Return an HTML diff suitable for rendering in a QTextBrowser."""
        old_lines = event.old_content.splitlines()
        new_lines = event.new_content.splitlines()
        differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=width if hasattr(self, '_w') else 80)
        html = differ.make_table(
            old_lines, new_lines,
            fromdesc=f"Before (iter {event.iteration})",
            todesc=f"After (iter {event.iteration})",
            context=True,
            numlines=3,
        )
        return html

    def _compute_hunks(self, old: str, new: str) -> list[DiffHunk]:
        """Compute diff hunks from two strings."""
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

        hunks: list[DiffHunk] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            hunk_lines: list[tuple[str, str]] = []
            if tag in ("replace", "delete"):
                for line in old_lines[i1:i2]:
                    hunk_lines.append(("-", line))
            if tag in ("replace", "insert"):
                for line in new_lines[j1:j2]:
                    hunk_lines.append(("+", line))

            if hunk_lines:
                hunks.append(DiffHunk(
                    old_start=i1 + 1,
                    old_count=i2 - i1,
                    new_start=j1 + 1,
                    new_count=j2 - j1,
                    lines=hunk_lines,
                ))

        return hunks

    def clear(self) -> None:
        """Reset all stored events."""
        self.events.clear()
        self._diff_count = 0

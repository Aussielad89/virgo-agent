"""
Feature pages — Diffusal, Debate, Self-Heal.

Three new GUI pages for the Virgo Desktop app showing live diffs,
agent-to-agent debate results, and self-healing status.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .base import PageWidget

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QFont, QTextCursor
    from PyQt6.QtWidgets import (
        QHBoxLayout, QLabel, QPushButton, QScrollArea,
        QSplitter, QTextBrowser, QTextEdit, QVBoxLayout,
        QGroupBox, QProgressBar, QFrame,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


# ═══════════════════════════════════════════════════════════════════════
# DiffusalPage — Live Code Diffs
# ═══════════════════════════════════════════════════════════════════════


class DiffusalPage(PageWidget):
    """Shows real-time before/after diffs during the WTF loop."""

    def __init__(self) -> None:
        super().__init__("Live Code Diffs", "Real-time before/after code changes during pipeline execution")

        # Diff count label
        self._count_label = QLabel("No diffs yet — run a pipeline to see live changes")
        self._count_label.setStyleSheet("color: #8888bb; font-size: 13px;")
        self.content.addWidget(self._count_label)

        # Stats bar
        stats_row = QHBoxLayout()
        self._added_label = QLabel("Added: 0")
        self._added_label.setStyleSheet("color: #00e5a0; font-weight: bold;")
        self._removed_label = QLabel("Removed: 0")
        self._removed_label.setStyleSheet("color: #ff5577; font-weight: bold;")
        self._files_label = QLabel("Files: 0")
        self._files_label.setStyleSheet("color: #7c6aff; font-weight: bold;")
        stats_row.addWidget(self._added_label)
        stats_row.addWidget(self._removed_label)
        stats_row.addWidget(self._files_label)
        stats_row.addStretch()
        self.content.addLayout(stats_row)

        # Diff browser
        self._diff_browser = QTextBrowser()
        self._diff_browser.setOpenExternalLinks(True)
        self._diff_browser.setStyleSheet("""
            QTextBrowser {
                background: #0a0a14;
                color: #e0e0ff;
                border: 1px solid #252545;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 13px;
            }
        """)
        self.content.addWidget(self._diff_browser, 1)

        # Event log
        self._event_log: list[dict[str, Any]] = []
        self._diff_count = 0

    def on_activate(self) -> None:
        """Called when the page becomes visible."""
        pass

    def receive_diff(self, event: Any) -> None:
        """Receive a DiffEvent from the DiffusalEngine and render it."""
        self._diff_count += 1
        self._event_log.append({
            "file": event.file,
            "iteration": event.iteration,
            "added": event.added,
            "removed": event.removed,
        })

        self._count_label.setText(f"Diff #{self._diff_count} — {event.file} (iter {event.iteration})")
        self._added_label.setText(f"Added: {sum(e['added'] for e in self._event_log)}")
        self._removed_label.setText(f"Removed: {sum(e['removed'] for e in self._event_log)}")
        self._files_label.setText(f"Files: {len(set(e['file'] for e in self._event_log))}")

        # Build HTML diff
        html = self._build_diff_html(event)
        self._diff_browser.append(html)
        # Scroll to bottom
        cursor = self._diff_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._diff_browser.setTextCursor(cursor)

    def _build_diff_html(self, event: Any) -> str:
        """Build HTML for a single diff event."""
        lines = []
        lines.append(f'<div style="margin: 8px 0; padding: 8px; border-left: 3px solid #7c6aff; background: #12122a; border-radius: 4px;">')
        lines.append(f'<b style="color: #7c6aff;">⟳ Diff #{self._diff_count}</b> '
                     f'<span style="color: #e0e0ff;">{event.file}</span> '
                     f'<span style="color: #8888bb;">(iter {event.iteration})</span>')
        if event.error_msg:
            short_err = event.error_msg.strip().splitlines()[0][:100]
            lines.append(f'<br><span style="color: #ff5577;">Error: {short_err}</span>')
        lines.append(f'<br><span style="color: #00e5a0;">+{event.added}</span> '
                     f'<span style="color: #ff5577;">-{event.removed}</span> lines')
        lines.append('<pre style="margin: 8px 0; padding: 8px; background: #08080f; border-radius: 4px; overflow-x: auto;">')

        for hunk in event.hunks:
            lines.append(f'<span style="color: #8888bb;">@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@</span>')
            for tag, line in hunk.lines:
                escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                if tag == '+':
                    lines.append(f'<span style="color: #00e5a0;">+ {escaped}</span>')
                elif tag == '-':
                    lines.append(f'<span style="color: #ff5577;">- {escaped}</span>')
                else:
                    lines.append(f'<span style="color: #555577;">  {escaped}</span>')
            lines.append('')

        lines.append('</pre></div>')
        return '\n'.join(lines)

    def clear(self) -> None:
        """Clear all displayed diffs."""
        self._diff_count = 0
        self._event_log.clear()
        self._diff_browser.clear()
        self._count_label.setText("No diffs yet — run a pipeline to see live changes")
        self._added_label.setText("Added: 0")
        self._removed_label.setText("Removed: 0")
        self._files_label.setText("Files: 0")


# ═══════════════════════════════════════════════════════════════════════
# DebatePage — Agent-to-Agent Debate
# ═══════════════════════════════════════════════════════════════════════


class DebatePage(PageWidget):
    """Shows Agent-to-Agent debate results — Performer vs Critic."""

    def __init__(self) -> None:
        super().__init__("Agent Debate", "Performer vs Critic — argue different approaches, pick the winner")

        # Status
        self._status = QLabel("No active debate — start one from the pipeline or CLI (--debate)")
        self._status.setStyleSheet("color: #8888bb; font-size: 13px;")
        self.content.addWidget(self._status)

        # Debate display
        self._debate_browser = QTextBrowser()
        self._debate_browser.setOpenExternalLinks(True)
        self._debate_browser.setStyleSheet("""
            QTextBrowser {
                background: #0a0a14;
                color: #e0e0ff;
                border: 1px solid #252545;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
            }
        """)
        self.content.addWidget(self._debate_browser, 1)

        # History
        self._history: list[dict[str, Any]] = []

    def on_activate(self) -> None:
        pass

    def receive_round(self, round_data: Any) -> None:
        """Receive a DebateRound and render it."""
        html = self._build_round_html(round_data)
        self._debate_browser.append(html)

    def receive_result(self, result: Any) -> None:
        """Receive the final DebateResult."""
        self._status.setText(
            f"Debate complete — Winner: {result.winner.upper()} "
            f"({result.duration:.1f}s, {'auto' if result.auto_picked else 'user'} picked)"
        )
        self._history.append({
            "goal": result.goal,
            "winner": result.winner,
            "approach": result.winner_approach,
            "auto": result.auto_picked,
            "duration": result.duration,
        })

        html = f'''
        <div style="margin: 12px 0; padding: 12px; border: 2px solid #00e5a0; background: #0a2a1a; border-radius: 8px;">
            <b style="color: #00e5a0; font-size: 16px;">🏆 Winner: {result.winner.upper()}</b><br>
            <span style="color: #e0e0ff;">Approach: {result.winner_approach}</span><br>
            <span style="color: #8888bb;">Duration: {result.duration:.1f}s | Auto: {result.auto_picked}</span>
        </div>
        '''
        self._debate_browser.append(html)

    def _build_round_html(self, round_data: Any) -> str:
        """Build HTML for a debate round."""
        color = "#7c6aff" if round_data.agent == "performer" else "#ffc53d"
        tag = "PERFORMER" if round_data.agent == "performer" else "CRITIC"
        # Truncate long arguments for display
        arg_preview = round_data.argument[:500].replace('\n', '<br>')
        return f'''
        <div style="margin: 8px 0; padding: 8px; border-left: 3px solid {color}; background: #12122a; border-radius: 4px;">
            <b style="color: {color};">{tag}</b> — Round {round_data.round_num}<br>
            <span style="color: #8888bb;">Approach: {round_data.approach}</span>
            <pre style="margin: 4px 0; color: #a0a0cc; font-size: 12px; white-space: pre-wrap;">{arg_preview}</pre>
        </div>
        '''


# ═══════════════════════════════════════════════════════════════════════
# SelfHealPage — Self-Healing Pipeline Status
# ═══════════════════════════════════════════════════════════════════════


class SelfHealPage(PageWidget):
    """Shows self-healing pipeline status — web research after repeated failures."""

    def __init__(self) -> None:
        super().__init__("Self-Healing", "Web research-driven recovery after repeated test failures")

        # Status
        self._status = QLabel("Self-healing disabled — enable with --selfheal flag")
        self._status.setStyleSheet("color: #8888bb; font-size: 13px;")
        self.content.addWidget(self._status)

        # Stats
        stats_row = QHBoxLayout()
        self._attempts_label = QLabel("Attempts: 0")
        self._attempts_label.setStyleSheet("color: #ffc53d; font-weight: bold;")
        self._recovered_label = QLabel("Recovered: 0")
        self._recovered_label.setStyleSheet("color: #00e5a0; font-weight: bold;")
        self._research_label = QLabel("Research items: 0")
        self._research_label.setStyleSheet("color: #7c6aff; font-weight: bold;")
        stats_row.addWidget(self._attempts_label)
        stats_row.addWidget(self._recovered_label)
        stats_row.addWidget(self._research_label)
        stats_row.addStretch()
        self.content.addLayout(stats_row)

        # Heal log
        self._heal_browser = QTextBrowser()
        self._heal_browser.setOpenExternalLinks(True)
        self._heal_browser.setStyleSheet("""
            QTextBrowser {
                background: #0a0a14;
                color: #e0e0ff;
                border: 1px solid #252545;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
            }
        """)
        self.content.addWidget(self._heal_browser, 1)

        # Tracking
        self._attempts = 0
        self._recovered_count = 0
        self._research_count = 0

    def on_activate(self) -> None:
        pass

    def receive_research(self, research: Any) -> None:
        """Receive a ResearchResult from the SelfHealEngine."""
        self._research_count += 1
        self._research_label.setText(f"Research items: {self._research_count}")
        html = f'''
        <div style="margin: 4px 0; padding: 6px; border-left: 2px solid #7c6aff; background: #12122a; border-radius: 4px;">
            <b style="color: #7c6aff;">🔍 Research #{self._research_count}</b>
            <a href="{research.url}" style="color: #7c6aff; font-size: 12px;">{research.title[:60]}</a><br>
            <span style="color: #8888bb; font-size: 12px;">{research.snippet[:150]}</span>
        </div>
        '''
        self._heal_browser.append(html)

    def receive_attempt(self, attempt: Any) -> None:
        """Receive a HealAttempt from the SelfHealEngine."""
        self._attempts += 1
        if attempt.recovered:
            self._recovered_count += 1

        self._attempts_label.setText(f"Attempts: {self._attempts}")
        self._recovered_label.setText(f"Recovered: {self._recovered_count}")

        status_color = "#00e5a0" if attempt.recovered else "#ff5577"
        status_text = "RECOVERED" if attempt.recovered else "FAILED"

        html = f'''
        <div style="margin: 8px 0; padding: 8px; border: 1px solid {status_color}; background: #12122a; border-radius: 4px;">
            <b style="color: {status_color};">Self-Heal: {status_text}</b>
            <span style="color: #e0e0ff;">{attempt.file}</span>
            <span style="color: #8888bb;">(iter {attempt.iteration}, {attempt.duration:.1f}s)</span><br>
            <span style="color: #ff5577; font-size: 12px;">Error: {attempt.error[:100]}</span><br>
            <span style="color: #8888bb; font-size: 12px;">Research items: {len(attempt.research)}</span>
        </div>
        '''
        self._heal_browser.append(html)

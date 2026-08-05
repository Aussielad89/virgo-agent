"""
Virgo Desktop pages — each page is a QWidget plugged into the main window.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import traceback
import winsound  # Windows-only; safe no-op elsewhere
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    Q_ARG,
    QDir,
    QEvent,
    QMetaObject,
    QModelIndex,
    QObject,
    QPointF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFileSystemModel,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QScrollArea,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import OUTDIR

# ═══════════════════════════════════════════════════════════════════════
# Helper: page wrapper with title bar
# ═══════════════════════════════════════════════════════════════════════


def _beep(kind: str = "done") -> None:
    """Play a short completion chime (Windows). kind: done|error."""
    try:
        if kind == "error":
            winsound.MessageBeep(winsound.MB_ICONHAND)
        else:
            winsound.MessageBeep(winsound.MB_ICONINFORMATION)
    except Exception:
        pass


class PageWidget(QWidget):
    """Base page with title + optional action bar."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.page_title = title
        self.page_subtitle = subtitle
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("pageTitle")
            title_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
            title_label.setFont(title_font)
            layout.addWidget(title_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet("color: #a6adc8; font-size: 13px;")
            sub.setWordWrap(True)
            layout.addWidget(sub)

        self.content = QVBoxLayout()
        self.content.setSpacing(12)
        layout.addLayout(self.content, 1)

    def on_activate(self) -> None:
        """Called when the page becomes visible."""
        pass

    def _add(self, widget: QWidget) -> None:
        self.content.addWidget(widget)

    def _add_row(self, *widgets: QWidget) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            row.addWidget(w)
        row.addStretch()
        self.content.addLayout(row)

    def _section(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gl = QVBoxLayout(gb)
        gl.setSpacing(8)
        gb.setCheckable(True)
        gb.setChecked(True)
        # Collapse/expand by hiding the section's content widgets.
        # Do NOT use setFixedHeight(sizeHint()) — that locks the box to a
        # tiny height if the toggle fires before children are added (the box
        # is setChecked(True) during construction), which smears the rows.
        gb.toggled.connect(
            lambda checked: _set_layout_visible(gl, checked)
        )
        gb.toggled.connect(
            lambda checked: gb.setStyleSheet(
                f"QGroupBox::title {{ subcontrol-position: top left; padding: 4px 8px; "
                f"color: {'#89b4fa' if checked else '#6c7086'}; }}"
            )
        )
        self.content.addWidget(gb)
        return gb


def _set_layout_visible(layout: "QLayout", visible: bool) -> None:
    """Recursively show/hide every widget inside *layout*.

    Used so a collapsible QGroupBox shrinks to its title bar when unchecked
    and restores naturally when checked, without forcing a fragile fixed
    height.
    """
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is not None:
            w.setVisible(visible)
        else:
            sub = item.layout()
            if sub is not None:
                _set_layout_visible(sub, visible)


# ═══════════════════════════════════════════════════════════════════════
# Pipeline page
# ═══════════════════════════════════════════════════════════════════════




class _StopStream(Exception):
    """Raised inside the stream writer to abort an in-flight reply."""




class _GuiStream:
    """A sys.stdout replacement that streams tokens into the chat box live,
    filtering out  blocks (including partial tags across chunks)."""

    def __init__(self, page: ChatPage) -> None:
        self._page = page
        self.text = ""
        self._started = False
        self._buf = ""  # buffer for partial tag detection

    def write(self, chunk: str) -> int:
        if not chunk:
            return 0
        if self._page._cancel:
            raise _StopStream()
        self.text += chunk

        # Strip think blocks from the chunk, handling partial tags
        clean = self._filter_think(chunk)
        if not clean:
            return len(chunk)

        if not self._started:
            self._started = True
            QMetaObject.invokeMethod(
                self._page, "_stream_start", Qt.ConnectionType.QueuedConnection
            )
        QMetaObject.invokeMethod(
            self._page, "_stream_chunk", Qt.ConnectionType.QueuedConnection, Q_ARG(str, clean)
        )
        return len(chunk)

    def _filter_think(self, chunk: str) -> str:
        """Strip  content, handling partial tags across chunks."""
        import re

        # Re-join buffer with current chunk
        combined = self._buf + chunk
        self._buf = ""

        # If there's an unclosed <think, hold it in buffer
        # Find the last <think or <th that isn't closed
        open_pos = combined.rfind("<think")
        close_pos = combined.rfind("</think>")
        if open_pos > close_pos:
            # Unclosed <think tag — buffer everything from the opening
            self._buf = combined[open_pos:]
            combined = combined[:open_pos]

        # Also check for partial opening <th at the very end
        for partial in ("<th", "<thi", "<thin", "<think"):
            if combined.endswith(partial) and partial != "<think>":
                self._buf = combined[-len(partial) :] + self._buf
                combined = combined[: -len(partial)]
                break

        # Strip fully closed think blocks (preserve surrounding whitespace)
        result = re.sub(r"\s*<think>.*?</think>\s*", "", combined, flags=re.DOTALL)
        return result

    def flush(self) -> None:
        pass


PREFERRED_MODELS: list[str] = [
    "phi4-mini-reasoning:3.8b",
    "qwen3.5:2b",
    "llama3.2:latest",
    "gemma3:4b",
    "deepseek-r1:1.5b",
    "ornith:latest",
]


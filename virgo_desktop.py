"""
Virgo Desktop — polished PyQt6 GUI for virgo-agent.

Usage:
    virgo-desktop
    python -m virgo_desktop
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon
import virgo_crash

# ── Theme system ────────────────────────────────────────────────────
THEMES: dict[str, dict[str, str]] = {
    "mocha": {
        "name": "Void",
        "base": "#0a0a12",
        "bg": "#0d0d1a",
        "surface": "#141428",
        "surface2": "#1a1a36",
        "crust": "#08080f",
        "border": "#252545",
        "border2": "#35356a",
        "text": "#e0e0ff",
        "subtext": "#8888bb",
        "disabled": "#4a4a6a",
        "accent": "#7c6aff",
        "accent2": "#00e5a0",
        "red": "#ff5577",
        "yellow": "#ffc53d",
        "green": "#00e5a0",
        "sidebar_active": "#1a1a3e",
    },
    "latte": {
        "name": "Catppuccin Latte",
        "base": "#ffffff",
        "bg": "#eff1f5",
        "surface": "#e6e9ef",
        "surface2": "#dce0e8",
        "crust": "#dce0e8",
        "border": "#ccd0da",
        "border2": "#bcc0cc",
        "text": "#4c4f69",
        "subtext": "#5c5f77",
        "disabled": "#9ca0b0",
        "accent": "#1e66f5",
        "accent2": "#40a02b",
        "red": "#d20f39",
        "yellow": "#df8e1d",
        "green": "#40a02b",
        "sidebar_active": "#ccd0da",
    },
    "nord": {
        "name": "Nord",
        "base": "#eceff4",
        "bg": "#2e3440",
        "surface": "#3b4252",
        "surface2": "#434c5e",
        "crust": "#434c5e",
        "border": "#4c566a",
        "border2": "#5e6a83",
        "text": "#eceff4",
        "subtext": "#d8dee9",
        "disabled": "#6c7086",
        "accent": "#88c0d0",
        "accent2": "#a3be8c",
        "red": "#bf616a",
        "yellow": "#ebcb8b",
        "green": "#a3be8c",
        "sidebar_active": "#4c566a",
    },
    "gruvbox": {
        "name": "Gruvbox Dark",
        "base": "#fbf1c7",
        "bg": "#282828",
        "surface": "#3c3836",
        "surface2": "#504945",
        "crust": "#504945",
        "border": "#665c54",
        "border2": "#7c6f64",
        "text": "#ebdbb2",
        "subtext": "#a89984",
        "disabled": "#6c7086",
        "accent": "#d79921",
        "accent2": "#689d6a",
        "red": "#cc241d",
        "yellow": "#d79921",
        "green": "#98971a",
        "sidebar_active": "#665c54",
    },
}


# ── User config + custom themes ───────────────────────────────────
CONFIG_PATH = HERE / ".virgo_desktop_config.json"
USER_THEMES_PATH = HERE / ".virgo_themes.json"

# Colour keys exposed in the in-app theme editor.
EDITABLE_THEME_KEYS = [
    ("bg", "Background"),
    ("surface", "Surface"),
    ("crust", "Crust"),
    ("border", "Border"),
    ("border2", "Border 2"),
    ("text", "Text"),
    ("subtext", "Subtext"),
    ("disabled", "Disabled"),
    ("accent", "Accent"),
    ("accent2", "Accent 2"),
    ("red", "Red"),
    ("yellow", "Yellow"),
    ("green", "Green"),
    ("sidebar_active", "Sidebar active"),
]


def load_user_themes() -> dict[str, dict[str, str]]:
    """Load user-saved custom themes from .virgo_themes.json."""
    if not USER_THEMES_PATH.exists():
        return {}
    try:
        data = json.loads(USER_THEMES_PATH.read_text())
        out: dict[str, dict[str, str]] = {}
        for k, v in data.items():
            if isinstance(v, dict) and "bg" in v:
                v = dict(v)
                v.setdefault("name", k)
                out[k] = v
        return out
    except Exception:
        return {}


def all_themes() -> dict[str, dict[str, str]]:
    """Built-in themes merged with any user-saved themes."""
    merged: dict[str, dict[str, str]] = dict(THEMES)
    merged.update(load_user_themes())
    return merged


def _build_stylesheet(t: dict[str, str]) -> str:
    """Build the full app stylesheet from a theme dict.

    Placeholders like ``@bg@`` are substituted with the theme's colour.
    """
    import textwrap

    raw = textwrap.dedent("""\
    /* ── Base ─────────────────────────────────────────────────────── */
    QMainWindow, QWidget {
        background-color: @bg@;
        color: @text@;
        font-family: @ui_font_family@;
        font-size: @ui_font_size@px;
    }

    /* ── Sidebar ──────────────────────────────────────────────────── */
    #sidebar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface@, stop:0.5 @crust@, stop:1 @surface@);
        border-right: 1px solid @border@;
        border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @accent@, stop:0.5 @accent2@, stop:1 @accent@);
    }
    #sidebarTitle {
        color: @accent@;
        padding: 0 4px;
        font-size: 15px;
        font-weight: bold;
        letter-spacing: 1px;
    }
    #sidebarHeader {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent25@, stop:0.3 @surface@, stop:0.7 @surface@, stop:1 @accent218@);
        border-bottom: 2px solid qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        border-radius: 8px;
        padding: 8px;
    }
    #sidebarAvatar {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        color: @bg@;
        border-radius: 12px;
        min-width: 36px;
        max-width: 36px;
        min-height: 36px;
        max-height: 36px;
        font-weight: bold;
        font-size: 14px;
    }
    #sidebar QPushButton {
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 9px 14px;
        text-align: left;
        color: @subtext@;
        font-size: 13px;
    }
    #sidebar QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent15@, stop:1 @accent10@);
        color: @text@;
        border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        padding-left: 11px;
    }
    #sidebar QPushButton:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent20@, stop:0.5 @sidebar_active@, stop:1 @accent10@);
        color: @accent@;
        font-weight: bold;
        border-left: 3px solid @accent@;
        padding-left: 11px;
    }
    #quitBtn {
        color: @red@ !important;
    }
    #quitBtn:hover {
        background: @red22@ !important;
    }
    #stopBtn {
        color: @red@ !important;
        border-color: @red@;
    }
    #stopBtn:hover {
        background: @red22@ !important;
    }
    #multiBtn {
        color: @subtext@;
        border: 1px solid @border@;
        border-radius: 8px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        font-weight: bold;
        padding: 6px 14px;
    }
    #multiBtn:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @green@, stop:1 @accent2@);
        color: @base@;
        border-color: @green@;
    }
    #navList {
        background: transparent;
        border: none;
        outline: 0;
    }
    QLineEdit#navFilter {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @border@);
        border: 1px solid @border2@;
        border-radius: 8px;
        padding: 6px 12px;
        color: @text@;
        font-size: 12px;
        selection-background-color: @accent@;
    }
    QLineEdit#navFilter:focus {
        border: 1px solid @accent@;
        background: @surface@;
    }
    #navList::item {
        padding: 8px 14px;
        border-radius: 8px;
        color: @subtext@;
        margin: 1px 4px;
    }
    #navList::item:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent10@, stop:1 transparent);
        color: @text@;
    }
    #navList::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent20@, stop:0.5 @sidebar_active@, stop:1 @accent10@);
        color: @accent@;
        font-weight: bold;
        border-right: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
    }

    /* ── Page area ────────────────────────────────────────────────── */
    #pageArea {
        background-color: @bg@;
    }
    #pageTitle {
        color: @text@;
        font-size: 22px;
        font-weight: bold;
        padding-bottom: 4px;
    }
    #metaLabel {
        color: @disabled@;
        font-size: 11px;
    }

    /* ── Status bar ───────────────────────────────────────────────── */
    #statusBar {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @crust@, stop:0.5 @surface@, stop:1 @crust@);
        color: @subtext@;
        border-top: 1px solid @border@;
        padding: 4px 12px;
        font-size: 12px;
    }

    /* ── Ask bar ──────────────────────────────────────────────────── */
    #askBar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface@, stop:1 @crust@);
        border-top: 1px solid @border@;
        padding: 6px;
    }
    QLineEdit#askInput {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @border@);
        border: 1px solid @border2@;
        border-radius: 8px;
        padding: 8px 14px;
        color: @text@;
        font-size: 13px;
        selection-background-color: @accent@;
    }
    QLineEdit#askInput:focus {
        border: 1px solid @accent@;
        background: @surface@;
    }

    /* ── Buttons ──────────────────────────────────────────────────── */
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @border@);
        border: 1px solid @border2@;
        border-radius: 8px;
        padding: 7px 18px;
        color: @text@;
        font-weight: 500;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @border2@, stop:1 @sidebar_active@);
        border-color: @accent40@;
    }
    QPushButton:disabled {
        background: @border@;
        border-color: @border@;
        color: @disabled@;
    }
    QPushButton:focus {
        border: 1px solid @accent@;
    }
    QPushButton#sendBtn {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        color: @bg@;
        font-weight: bold;
        border: none;
        padding: 8px 22px;
        border-radius: 8px;
        font-size: 13px;
    }
    QPushButton#sendBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accentcc@, stop:1 @accent2cc@);
    }
    QPushButton#sendBtn:disabled {
        background: @border@;
        color: @disabled@;
    }
    QPushButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @sidebar_active@, stop:1 @border@);
    }

    /* ── Text editors ─────────────────────────────────────────────── */
    QTextEdit, QPlainTextEdit {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface@, stop:1 @surface2@);
        border: 1px solid @border@;
        border-radius: 8px;
        color: @text@;
        padding: 10px;
        font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
        font-size: 12px;
        selection-background-color: @accent40@;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border: 1px solid @accent@;
    }

    /* ── List widgets ─────────────────────────────────────────────── */
    QListWidget {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 8px;
        color: @text@;
    }
    QListWidget::item {
        padding: 4px 8px;
        border-radius: 6px;
        margin: 1px 2px;
    }
    QListWidget::item:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent10@, stop:1 transparent);
    }
    QListWidget::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent20@, stop:1 @accent10@);
        color: @accent@;
    }

    /* ── Line edits ───────────────────────────────────────────────── */
    QLineEdit {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 8px;
        padding: 7px 12px;
        color: @text@;
        selection-background-color: @accent40@;
    }
    QLineEdit:focus {
        border: 1px solid @accent@;
    }

    /* ── Progress bars ────────────────────────────────────────────── */
    QProgressBar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @border@, stop:1 @surface@);
        border: none;
        border-radius: 5px;
        height: 8px;
        text-align: center;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent@, stop:0.5 @accent2@, stop:1 @accent@);
        border-radius: 5px;
    }

    /* ── Group boxes (cards) ──────────────────────────────────────── */
    QGroupBox {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        border: 1px solid @border@;
        border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        border-radius: 12px;
        margin-top: 20px;
        padding: 20px 16px 16px;
        font-weight: bold;
        color: @accent@;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
        color: @accent@;
    }

    /* ── Combo boxes ──────────────────────────────────────────────── */
    QComboBox {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @border@);
        border: 1px solid @border2@;
        border-radius: 8px;
        padding: 7px 12px;
        color: @text@;
        min-width: 100px;
    }
    QComboBox:hover {
        border-color: @accent40@;
    }
    QComboBox:focus {
        border: 1px solid @accent@;
    }
    QComboBox::drop-down {
        border: none;
        width: 26px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid @subtext@;
        margin-right: 8px;
    }
    QComboBox QAbstractItemView {
        background: @surface@;
        border: 1px solid @border2@;
        border-radius: 8px;
        color: @text@;
        selection-background-color: @accent20@;
        selection-color: @accent@;
        outline: none;
        padding: 4px;
    }

    /* ── Tabs ─────────────────────────────────────────────────────── */
    QTabWidget::pane {
        border: none;
        background: transparent;
    }
    QTabBar::tab {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        border: 1px solid @border@;
        border-bottom: 2px solid @border@;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 8px 18px;
        margin-right: 2px;
        color: @disabled@;
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @border@, stop:1 @bg@);
        color: @accent@;
        font-weight: bold;
        border-bottom: 2px solid @accent@;
    }
    QTabBar::tab:hover:!selected {
        color: @subtext@;
        background: @surface2@;
    }

    /* ── Scroll bars ──────────────────────────────────────────────── */
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 2px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background: @border2@;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: @accent40@;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
        border: none;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 8px;
        margin: 2px;
        border: none;
    }
    QScrollBar::handle:horizontal {
        background: @border2@;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background: @accent40@;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
        border: none;
    }

    /* ── Splitters ────────────────────────────────────────────────── */
    QSplitter::handle {
        background: @border@;
    }
    QSplitter::handle:horizontal { width: 2px; }
    QSplitter::handle:vertical { height: 2px; }
    QSplitter::handle:hover {
        background: @accent40@;
    }

    /* ── Sliders ──────────────────────────────────────────────────── */
    QSlider::groove:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @border@, stop:1 @surface@);
        height: 6px;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        width: 18px;
        height: 18px;
        margin: -6px 0;
        border-radius: 9px;
        border: 2px solid @bg@;
    }
    QSlider::handle:horizontal:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accentcc@, stop:1 @accent2cc@);
    }

    /* ── Checkboxes ───────────────────────────────────────────────── */
    QCheckBox { color: @text@; spacing: 8px; }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 2px solid @border2@;
        border-radius: 5px;
        background: @surface@;
    }
    QCheckBox::indicator:hover {
        border-color: @accent40@;
    }
    QCheckBox::indicator:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        border-color: @accent@;
    }

    /* ── Tooltips ─────────────────────────────────────────────────── */
    QToolTip {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        border: 1px solid @border2@;
        border-radius: 6px;
        color: @text@;
        padding: 6px 10px;
        font-size: 12px;
    }

    /* ── Tables ───────────────────────────────────────────────────── */
    QTableWidget {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 8px;
        color: @text@;
        gridline-color: @border@;
        selection-background-color: @accent20@;
        selection-color: @accent@;
        alternate-background-color: @accent08@;
    }
    QTableWidget::item {
        padding: 6px 10px;
        border-bottom: 1px solid @border@;
    }
    QTableWidget::item:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent08@, stop:1 transparent);
    }
    QTableCornerButton::section {
        background: @surface@;
        border: none;
        border-bottom: 2px solid @border@;
        border-right: 1px solid @border@;
    }
    QHeaderView::section {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        color: @subtext@;
        border: none;
        border-bottom: 2px solid @accent20@;
        border-right: 1px solid @border@;
        padding: 8px 10px;
        font-weight: bold;
        font-size: 12px;
    }
    QHeaderView::section:hover {
        background: @border@;
        color: @text@;
    }

    /* ── Context menus ────────────────────────────────────────────── */
    QMenu {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 @surface2@, stop:1 @surface@);
        border: 1px solid @border2@;
        border-radius: 10px;
        padding: 6px;
    }
    QMenu::item {
        padding: 8px 24px 8px 14px;
        border-radius: 6px;
        color: @text@;
    }
    QMenu::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent20@, stop:1 @accent10@);
        color: @accent@;
    }
    QMenu::item:disabled { color: @disabled@; }
    QMenu::separator {
        height: 1px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.2 @border@, stop:0.8 @border@, stop:1 transparent);
        margin: 4px 10px;
    }

    /* ── Dialogs ──────────────────────────────────────────────────── */
    QMessageBox, QDialog {
        background-color: @bg@;
        color: @text@;
    }
    QMessageBox QLabel { color: @text@; }

    /* ── Status bar (Qt widget) ───────────────────────────────────── */
    QStatusBar {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @crust@, stop:0.5 @surface@, stop:1 @crust@);
        color: @subtext@;
        border-top: 1px solid @border@;
    }
    QStatusBar::item { border: none; }

    /* ── Scroll areas ─────────────────────────────────────────────── */
    QScrollArea { background: transparent; border: none; }
    QScrollArea > QWidget > QWidget { background: transparent; }

    /* ── Spin boxes ───────────────────────────────────────────────── */
    QSpinBox {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 8px;
        padding: 5px 10px;
        color: @text@;
    }
    QSpinBox:focus {
        border: 1px solid @accent@;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        background: @border@;
        border: none;
        width: 18px;
        border-radius: 4px;
    }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {
        background: @accent20@;
    }

    /* ── Radio buttons ────────────────────────────────────────────── */
    QRadioButton { color: @text@; spacing: 8px; }
    QRadioButton::indicator {
        width: 16px;
        height: 16px;
        border: 2px solid @border2@;
        border-radius: 9px;
        background: @surface@;
    }
    QRadioButton::indicator:hover {
        border-color: @accent40@;
    }
    QRadioButton::indicator:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        border: 3px solid @bg@;
    }
    """)
    for key, val in t.items():
        raw = raw.replace(f"@{key}@", val)
    # ── Pre-compute alpha-enhanced variants ──────────────────────────
    # Qt uses #AARRGGBB format (alpha first), not #RRGGBBAA.
    accent = t.get("accent", "#89b4fa")
    accent2 = t.get("accent2", "#a6e3a1")
    red = t.get("red", "#f38ba8")
    rrggbb_a = accent.lstrip("#")
    rrggbb_a2 = accent2.lstrip("#")
    rrggbb_r = red.lstrip("#")
    # Accent variants: 08 (3%), 10 (6%), 15 (8%), 18 (9%), 20 (12%),
    # 25 (15%), 40 (25%), bb (73%), cc (80%)
    for suffix, alpha_pct in [
        ("08", 0.03), ("10", 0.06), ("15", 0.08), ("18", 0.09),
        ("20", 0.12), ("25", 0.15), ("40", 0.25), ("bb", 0.73), ("cc", 0.80),
    ]:
        alpha = max(1, min(255, int(alpha_pct * 255)))
        raw = raw.replace(f"@accent{suffix}@", f"#{alpha:02x}{rrggbb_a}")
    # Accent2 variants: 10 (6%), 18 (9%), 22 (13%), cc (80%)
    for suffix, alpha_pct in [("10", 0.06), ("18", 0.09), ("22", 0.13), ("cc", 0.80)]:
        alpha = max(1, min(255, int(alpha_pct * 255)))
        raw = raw.replace(f"@accent2{suffix}@", f"#{alpha:02x}{rrggbb_a2}")
    # Red variant: 22 (13%)
    for suffix, alpha_pct in [("22", 0.13)]:
        alpha = max(1, min(255, int(alpha_pct * 255)))
        raw = raw.replace(f"@red{suffix}@", f"#{alpha:02x}{rrggbb_r}")
    # Drop any leftover placeholders so incomplete user themes never emit
    # a literal '@x@' that makes Qt reject the entire stylesheet.
    raw = re.sub(r"@\w+@", "", raw)
    return raw


# ── Robust launch: find a Python that actually has PyQt6 ──────────
def _has_pyqt6(python: str) -> bool:
    try:
        r = subprocess.run(
            [python, "-c", "import PyQt6"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def _find_pyqt6_python() -> str | None:
    """Return a python executable (other than current) that can import PyQt6."""
    candidates = []
    # Windows: common install locations.
    if sys.platform == "win32":
        base = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates += [
            r"C:\Python314\python.exe",
            r"C:\Python313\python.exe",
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
            os.path.join(base, "Python314", "python.exe"),
            os.path.join(base, "Python313", "python.exe"),
            os.path.join(base, "Python312", "python.exe"),
            os.path.join(base, "Python311", "python.exe"),
        ]
    else:
        candidates += [
            "python3.14",
            "python3.13",
            "python3.12",
            "python3.11",
            "/usr/bin/python3",
            "/usr/local/bin/python3",
        ]
    for c in candidates:
        if c and c != sys.executable and os.path.isfile(c) and _has_pyqt6(c):
            return c
    return None


def _ensure_pyqt6() -> None:
    """If the current interpreter lacks PyQt6, re-exec under one that has it."""
    try:
        import PyQt6  # noqa: F401

        return
    except Exception:
        pass
    alt = _find_pyqt6_python()
    if alt:
        os.execv(alt, [alt, str(HERE / "virgo_desktop.py"), *sys.argv[1:]])
    # No alternative found — surface a clear error instead of a traceback.
    sys.stderr.write(
        "ERROR: PyQt6 is not installed in this Python environment.\n"
        "Install it with:  pip install pyqt6\n"
        "or run this script with a Python that has PyQt6.\n"
    )
    sys.exit(1)


# ── Ensure a PyQt6-capable interpreter, then import GUI deps ───────
_ensure_pyqt6()  # re-execs under a PyQt6 Python if needed

from PyQt6.QtCore import QCoreApplication, QSize, Qt, QTimer, pyqtSignal, qInstallMessageHandler
from PyQt6.QtCore import Q_ARG, QMetaObject, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

# ── Import virgo modules ─────────────────────────────────────────────
from virgo_desktop_pages import (
    AboutPage,
    ActivityFeedPage,
    AlertsPage,
    BenchmarkPage,
    ChatPage,
    DashboardPage,
    EventBusPage,
    DiagnosticsPage,
    FilesPage,
    LeaderboardPage,
    LogsPage,
    MascotChatPage,
    NetworkPage,
    NotificationsPage,
    PipelinePage,
    PluginsPage,
    ProcessMonitorPage,
    ScaffoldPage,
    SessionPage,
    SwarmPage,
    SettingsPage,
    ReconGraphPage,
    C2CommanderPage,
    AdversarialArenaPage,
    SonificationPage,
    DreamsPage,
    FlavorPage,
    GhostPage,
    ArchaeologyPage,
    EmpathyPage,
    AuditPage,
    MemesPage,
    StigmergyPage,
    DivergencePage,
)
# ── New feature pages (standalone modules, top-3 brainstorm build) ──
try:
    from virgo_model_manager import ModelManagerPage
except Exception:  # noqa: BLE001
    ModelManagerPage = None
try:
    from virgo_desktop_automation import DesktopAutomationPage
except Exception:  # noqa: BLE001
    DesktopAutomationPage = None
try:
    from virgo_desktop_sync import SyncPage
except Exception:  # noqa: BLE001
    SyncPage = None
try:
    from virgo_font_picker import FontPickerPage
except Exception:  # noqa: BLE001
    FontPickerPage = None

# New feature pages (pheromone, soundscape, empathy, ghost replay, DNA fingerprint, dream viz, swarm, plugin shell)
try:
    from virgo_desktop_pages import (
        PheromoneTrailPage,
        SoundscapePage,
        EmpathyUIPage,
        GhostReplayPage,
        DNAFingerprintPage,
        DreamVizPage,
        SwarmDashboardPage,
        PluginShellPage,
    )
except Exception as exc:  # noqa: BLE001
    print(f"virgo_desktop: new pages unavailable ({exc})")
    PheromoneTrailPage = SoundscapePage = EmpathyUIPage = None
    GhostReplayPage = DNAFingerprintPage = DreamVizPage = None
    SwarmDashboardPage = PluginShellPage = None

# Feature pages (diffusal, debate, selfheal)
try:
    from virgo_desktop_pages import DiffusalPage, DebatePage, SelfHealPage
except Exception as exc:  # noqa: BLE001
    print(f"virgo_desktop: feature pages unavailable ({exc})")
    DiffusalPage = DebatePage = SelfHealPage = None

# VibeVoice TTS page
try:
    from virgo_desktop_pages import VibeVoicePage
except Exception as exc:  # noqa: BLE001
    print(f"virgo_desktop: VibeVoice page unavailable ({exc})")
    VibeVoicePage = None


# ── Build-on-top feature pages ──
try:
    from virgo_agent_pages import (
        ArtifactsPage,
        BudgetPage,
        MemoryPage,
        RagPage,
        RunTimelinePage,
    )
except Exception as exc:  # noqa: BLE001
    print(f"virgo_desktop: agent pages unavailable ({exc})")
    ArtifactsPage = BudgetPage = MemoryPage = RagPage = RunTimelinePage = None

# Embedded web dashboard tab (requires PyQt6-WebEngine; optional).
# QtWebEngine demands AA_ShareOpenGLContexts be set before a QApplication
# exists — do it here (module level) so the import below succeeds.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
WebViewPage = None
try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    class WebViewPage(QWidget):
        """Embed the Virgo web dashboard (virgo serve) inside the app."""

        def __init__(self, url: str = "http://127.0.0.1:8765") -> None:
            super().__init__()
            self._url = url
            self._server_started = False
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            self.view = QWebEngineView()
            lay.addWidget(self.view)

        def on_activate(self) -> None:
            self._ensure_dashboard_server()
            if self.view.url().isEmpty():
                self.view.setUrl(QUrl(self._url))

        def _ensure_dashboard_server(self) -> None:
            """Auto-start `virgo serve` (port 8765) in a daemon thread if down."""
            if self._server_started:
                return
            self._server_started = True  # set first — avoid double-start races
            try:
                import socket

                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    probe.bind(("127.0.0.1", 8765))
                    free = True
                except OSError:
                    free = False  # something already listening
                finally:
                    probe.close()
                if not free:
                    return
                import threading

                threading.Thread(
                    target=self._run_server, name="virgo-dashboard", daemon=True
                ).start()
            except Exception as exc:  # noqa: BLE001
                print(f"virgo_desktop: could not auto-start dashboard server ({exc})")

        def _run_server(self) -> None:
            try:
                import server

                server.serve(
                    host=os.environ.get("VIRGO_DASH_HOST", "127.0.0.1"),
                    port=int(os.environ.get("VIRGO_DASH_PORT", "8765")),
                    token=os.environ.get("VIRGO_DASH_TOKEN", ""),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"virgo_desktop: dashboard server exited ({exc})")

except Exception as exc:  # noqa: BLE001
    print(f"virgo_desktop: web dashboard tab unavailable ({exc})")
    WebViewPage = None

# ── Constants ────────────────────────────────────────────────────────

APP_NAME = "Virgo Desktop"
APP_VERSION = "0.2.0"
WIDTH = 1100
HEIGHT = 720

# Emoji icons for the desktop GUI. PyQt6 renders these on Windows fine;
# the terminal-safe ASCII fallbacks in _console.icon() don't apply here.
DESKTOP_ICONS = {
    "pipeline": "\U0001f680",  # 🚀
    "chat": "\U0001f4ac",  # 💬
    "dashboard": "\U0001f5a5",  # 🖥
    "eventbus": "\U0001f4e1",  # 📡
    "files": "\U0001f4c1",  # 📁
    "network": "\U0001f310",  # 🌐
    "diagnostics": "\U0001f527",  # 🔧
    "alerts": "\U0001f514",  # 🔔
    "scaffold": "\U0001f4e6",  # 📦
    "sessions": "\U0001f4dc",  # 📜
    "swarm": "\u26a1",  # ⚡
    "logs": "\U0001f4dd",  # 📝
    "plugins": "\U0001f9e9",  # 🧩
    "settings": "\u2699",  # ⚙
    "about": "\u2139",  # ℹ
    "procs": "\U0001f4bb",  # 💻
    "bench": "\u23f1",  # ⏱
    "mascot_chat": "\U0001f43e",  # 🐾
    "activity_feed": "\U0001f4ca",  # 📊
    "leaderboard": "\U0001f3c6",  # 🏆
    "notifications": "\U0001f4e3",  # 📣
    "timeline": "\U0001f4c8",  # 📈
    "artifacts": "\U0001f5c3\ufe0f",  # 🗃️
    "memory": "\U0001f9e0",  # 🧠
    "budget": "\U0001f4b0",  # 💰
    "rag": "\U0001f50d",  # 🔍
    "webview": "\U0001f9ed",  # 🧭
    "models": "\U0001f916",  # 🤖
    "automation": "\U0001f5b1\ufe0f",  # 🖱️
    "sync": "\U0001f504",  # 🔄
    "fonts": "\U0001f520",  # 🔠
    "recon": "\U0001f50d",  # 🔍
    "c2": "\U0001f6e1",  # 🛡
    "arena": "\u2694",  # ⚔
    "sonification": "\U0001f3b5",  # 🎵
    "dreams": "\U0001f4ad",  # 💭
    "flavor": "\U0001f36e",  # 🍮
    "ghost": "\U0001f47b",  # 👻
    "archaeology": "\U0001f3d6",  # 🏖
    "empathy": "\u2764",  # ❤
    "audit": "\U0001f516",  # 🔗
    "memes": "\U0001f600",  # 😀
    "stigmergy": "\U0001f41d",  # 🐝
    "divergence": "\U0001f504",  # 🔄
    "diffusal": "\U0001f500",  # 🔀
    "debate": "\U0001f91d",  # 🤝
    "selfheal": "\U0001fa7a",  # 🩺
    "vibevoice": "\U0001f3a4",  # 🎤
}

# Sidebar layout: (page_id, label, emoji, group). Groups render as
# non-clickable section headers; filter box + drag-reorder still work.
SIDEBAR_ITEMS = [
    # ── Core ──
    ("pipeline", "Pipeline", DESKTOP_ICONS["pipeline"], "Core"),
    ("chat", "Chat", DESKTOP_ICONS["chat"], "Core"),
    ("dashboard", "Dashboard", DESKTOP_ICONS["dashboard"], "Core"),
    ("eventbus", "Event Bus", DESKTOP_ICONS["eventbus"], "Core"),
    # ── Agents ──
    ("sessions", "Sessions", DESKTOP_ICONS["sessions"], "Agents"),
    ("swarm", "Swarm", DESKTOP_ICONS["swarm"], "Agents"),
    ("bench", "Bench", DESKTOP_ICONS["bench"], "Agents"),
    ("timeline", "Run Timeline", DESKTOP_ICONS["timeline"], "Agents"),
    ("memory", "Memory", DESKTOP_ICONS["memory"], "Agents"),
    ("budget", "Budget", DESKTOP_ICONS["budget"], "Agents"),
    # ── System ──
    ("files", "Files", DESKTOP_ICONS["files"], "System"),
    ("network", "Network", DESKTOP_ICONS["network"], "System"),
    ("diagnostics", "Diagnostics", DESKTOP_ICONS["diagnostics"], "System"),
    ("alerts", "Alerts", DESKTOP_ICONS["alerts"], "System"),
    ("logs", "Logs", DESKTOP_ICONS["logs"], "System"),
    ("settings", "Settings", DESKTOP_ICONS["settings"], "System"),
    ("about", "About", DESKTOP_ICONS["about"], "System"),
]
# Pages accessible only via Ctrl+Shift+P command palette (not in sidebar).
_PALETTE_ONLY = {
    "scaffold", "models", "automation", "sync", "fonts", "webview",
    "recon", "c2", "arena", "sonification", "dreams", "flavor",
    "ghost", "archaeology", "empathy", "audit", "memes", "stigmergy",
    "divergence", "pheromone", "soundscape", "empathy_ui", "ghost_replay",
    "dna_fingerprint", "dream_viz", "swarm_dashboard", "plugin_shell",
    "mascot_chat", "activity_feed", "leaderboard", "notifications",
    "artifacts", "rag", "procs", "plugins",
    "diffusal", "debate", "selfheal", "vibevoice",
}


class SidebarButton(QPushButton):
    """A styled sidebar navigation button."""

    def __init__(self, text: str, icon_char: str = "") -> None:
        super().__init__()
        label = f"{icon_char}  {text}" if icon_char else text
        self.setText(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(42)
        self.setCheckable(True)


class NavList(QListWidget):
    """Reorderable sidebar navigation list (drag items to rearrange)."""

    reordered = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setMinimumWidth(120)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.reordered.emit()


class VirgoDesktopWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(WIDTH, HEIGHT)

        # Branded window icon (falls back silently if the asset is missing)
        import os

        from PyQt6.QtGui import QIcon

        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if getattr(sys, "frozen", False):
            _icon_path = os.path.join(getattr(sys, "_MEIPASS", ""), "logo.ico")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # ── Persisted UI config ──────────────────────────────────
        self._config = self._load_config()
        self.themes = all_themes()
        self._theme_mode = self._config.get("theme_mode", "system")  # system|dark|light|manual
        self._theme_name = self._config.get("theme_name", "mocha")
        # Honour .env theme preferences (written by the Settings page).
        try:
            env_path = HERE / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("VIRGO_THEME="):
                        val = line.split("=", 1)[1].strip()
                        if val in self.themes:
                            self._theme_name = val
                    elif line.startswith("VIRGO_THEME_MODE="):
                        self._theme_mode = line.split("=", 1)[1].strip()
        except Exception:
            pass
        if self._theme_name not in self.themes:
            self._theme_name = "mocha"
        self._custom_css = self._config.get("custom_css", "")
        self._sidebar_collapsed = bool(self._config.get("sidebar_collapsed", False))
        default_order = [pid for pid, _l, _e, _g in SIDEBAR_ITEMS]
        saved_order = self._config.get("sidebar_order", default_order)
        # Merge saved order with default order: keep saved positions for known
        # items, insert any new items (not in saved) at their default position.
        saved_set = set(saved_order)
        self.nav_order = [p for p in saved_order if p in default_order]
        inserted = set(self.nav_order)
        for p in default_order:
            if p not in inserted:
                # Insert at the correct default position
                default_idx = default_order.index(p)
                # Find where to insert: after all previously inserted items
                # that come before this one in the default order
                pos = 0
                for i, existing in enumerate(self.nav_order):
                    if default_order.index(existing) < default_idx:
                        pos = i + 1
                self.nav_order.insert(pos, p)
                inserted.add(p)
        self._nav_items: dict[str, QListWidgetItem] = {}
        self._popped: dict[str, PopOutWindow] = {}
        self.current_page = ""

        # ── Central widget + resizable splitter ──────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        root.addWidget(self.splitter, 1)

        # ── Ask Virgo global inline bar ──────────────────────────
        ask_bar = QWidget()
        ask_bar.setObjectName("askBar")
        ask_lay = QHBoxLayout(ask_bar)
        ask_lay.setContentsMargins(10, 6, 10, 6)
        ask_lay.setSpacing(8)
        ask_prompt = QLabel("💡")
        ask_prompt.setToolTip("Ask Virgo — sends to the Chat page")
        ask_lay.addWidget(ask_prompt)
        self.ask_input = QLineEdit()
        self.ask_input.setObjectName("askInput")
        self.ask_input.setPlaceholderText("Ask Virgo… (Enter sends to Chat)")
        self.ask_input.returnPressed.connect(self._ask_virgo)
        ask_lay.addWidget(self.ask_input, 1)
        ask_btn = QPushButton("Send")
        ask_btn.clicked.connect(self._ask_virgo)
        ask_lay.addWidget(ask_btn)
        root.addWidget(ask_bar)

        # ── Sidebar ──────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(2)

        header = QWidget()
        header.setObjectName("sidebarHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(10)
        avatar = QLabel("\U0001f6f8")  # 🛸
        avatar.setObjectName("sidebarAvatar")
        avatar.setFont(QFont("Segoe UI", 18))
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(avatar)
        title = QLabel("Virgo")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setObjectName("sidebarTitle")
        header_layout.addWidget(title, 1)
        collapse_btn = QPushButton("\u2630")  # ☰
        collapse_btn.setToolTip("Collapse / expand sidebar (Ctrl+B)")
        collapse_btn.setFixedSize(28, 28)
        collapse_btn.clicked.connect(self._toggle_sidebar)
        header_layout.addWidget(collapse_btn)
        sidebar_layout.addWidget(header)
        sidebar_layout.addSpacing(12)

        # Filter-as-you-type box (grouped nav needs search)
        self.nav_filter = QLineEdit()
        self.nav_filter.setObjectName("navFilter")
        self.nav_filter.setPlaceholderText("🔍  Filter pages…")
        self.nav_filter.setClearButtonEnabled(True)
        self.nav_filter.textChanged.connect(self._filter_nav)
        sidebar_layout.addWidget(self.nav_filter)

        self.nav_list = NavList()
        self.nav_list.setObjectName("navList")
        self.nav_list.currentItemChanged.connect(lambda cur, _prev: self._on_nav_selected(cur))
        self.nav_list.itemClicked.connect(self._on_nav_header_click)
        self.nav_list.reordered.connect(self._on_nav_reordered)
        self.nav_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.nav_list.customContextMenuRequested.connect(self._nav_context_menu)
        sidebar_layout.addWidget(self.nav_list, 1)

        quit_btn = QPushButton(f"{icon('exit')}  Quit")
        quit_btn.setObjectName("quitBtn")
        quit_btn.clicked.connect(self.close)
        sidebar_layout.addWidget(quit_btn)
        self.quit_btn = quit_btn
        self.sidebar_title = title

        self.splitter.addWidget(sidebar)

        # ── Page area ────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageArea")
        self.pages: dict[str, QWidget] = {}

        self._register(DashboardPage(), "dashboard")
        self._register(EventBusPage(), "eventbus")
        self._register(PipelinePage(), "pipeline")
        self._register(ChatPage(), "chat")
        self._register(FilesPage(), "files")
        self._register(NetworkPage(), "network")
        self._register(DiagnosticsPage(), "diagnostics")
        self._register(AlertsPage(), "alerts")
        self._register(ScaffoldPage(), "scaffold")
        self._register(SessionPage(), "sessions")
        self._register(SwarmPage(), "swarm")
        self._register(LogsPage(), "logs")
        self._register(PluginsPage(), "plugins")
        self._register(ProcessMonitorPage(), "procs")
        self._register(BenchmarkPage(), "bench")
        self._register(SettingsPage(), "settings")
        self._register(MascotChatPage(), "mascot_chat")
        self._register(ActivityFeedPage(), "activity_feed")
        self._register(LeaderboardPage(), "leaderboard")
        self._register(AboutPage(), "about")
        self._register(NotificationsPage(), "notifications")
        # ── New brainstorm features (top 3) ──
        if ModelManagerPage is not None:
            self._register(ModelManagerPage(), "models")
        if DesktopAutomationPage is not None:
            self._register(DesktopAutomationPage(), "automation")
        if SyncPage is not None:
            self._register(SyncPage(), "sync")
        if FontPickerPage is not None:
            self._register(FontPickerPage(), "fonts")
        # ── Build-on-top feature pages ──
        if RunTimelinePage is not None:
            self._register(RunTimelinePage(), "timeline")
        if ArtifactsPage is not None:
            self._register(ArtifactsPage(), "artifacts")
        if MemoryPage is not None:
            self._register(MemoryPage(), "memory")
        if BudgetPage is not None:
            self._register(BudgetPage(), "budget")
        if RagPage is not None:
            self._register(RagPage(), "rag")
        if WebViewPage is not None:
            self._register(WebViewPage(), "webview")
        # ── New pages (recon, C2, adversarial arena) ──
        self._register(ReconGraphPage(), "recon")
        self._register(C2CommanderPage(), "c2")
        self._register(AdversarialArenaPage(), "arena")

        # ── Experimental pages (brainstorm build) ──
        self._register(SonificationPage(), "sonification")
        self._register(DreamsPage(), "dreams")
        self._register(FlavorPage(), "flavor")
        self._register(GhostPage(), "ghost")
        self._register(ArchaeologyPage(), "archaeology")
        self._register(EmpathyPage(), "empathy")
        self._register(AuditPage(), "audit")
        self._register(MemesPage(), "memes")
        self._register(StigmergyPage(), "stigmergy")
        self._register(DivergencePage(), "divergence")

        # New feature pages (pheromone, soundscape, empathy, ghost replay, DNA fingerprint, dream viz, swarm, plugin shell)
        if PheromoneTrailPage is not None:
            self._register(PheromoneTrailPage(), "pheromone")
        if SoundscapePage is not None:
            self._register(SoundscapePage(), "soundscape")
        if EmpathyUIPage is not None:
            self._register(EmpathyUIPage(), "empathy_ui")
        if GhostReplayPage is not None:
            self._register(GhostReplayPage(), "ghost_replay")
        if DNAFingerprintPage is not None:
            self._register(DNAFingerprintPage(), "dna_fingerprint")
        if DreamVizPage is not None:
            self._register(DreamVizPage(), "dream_viz")
        if SwarmDashboardPage is not None:
            self._register(SwarmDashboardPage(), "swarm_dashboard")
        if PluginShellPage is not None:
            self._register(PluginShellPage(), "plugin_shell")

        # Feature pages (diffusal, debate, selfheal)
        if DiffusalPage is not None:
            self._register(DiffusalPage(), "diffusal")
        if DebatePage is not None:
            self._register(DebatePage(), "debate")
        if SelfHealPage is not None:
            self._register(SelfHealPage(), "selfheal")

        # VibeVoice TTS
        if VibeVoicePage is not None:
            self._register(VibeVoicePage(), "vibevoice")

        self.splitter.addWidget(self.stack)

        # ── Sidebar items ────────────────────────────────────────
        self._init_sidebar_items()
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        # ── Status bar ───────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("statusBar")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"Virgo Desktop  v{APP_VERSION} · ready")

        # ── Status bar widgets ──
        # Persona switcher
        self._persona_combo = QComboBox()
        self._persona_combo.setFixedWidth(140)
        self._persona_combo.currentIndexChanged.connect(self._on_persona_changed)
        self.status_bar.addPermanentWidget(self._persona_combo)
        self._populate_persona_combo()

        # Focus indicator
        self._focus_indicator = QLabel("")
        self._focus_indicator.setStyleSheet("color: #00e5a0; font-size: 11px; padding: 0 6px;")
        self.status_bar.addPermanentWidget(self._focus_indicator)

        # Theme indicator
        self._theme_indicator = QLabel("")
        self._theme_indicator.setStyleSheet("color: #8888bb; font-size: 11px; padding: 0 6px;")
        self.status_bar.addPermanentWidget(self._theme_indicator)

        # Chaos toggle
        self._chaos_btn = QPushButton("🎲")
        self._chaos_btn.setFixedWidth(32)
        self._chaos_btn.setToolTip("Toggle Chaos Mode")
        self._chaos_btn.clicked.connect(self._chaos_toggle_fast)
        self._chaos_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 14px; } QPushButton:hover { background: #252545; border-radius: 4px; }")
        self.status_bar.addPermanentWidget(self._chaos_btn)

        # Sound toggle
        self._sound_btn = QPushButton("🔊")
        self._sound_btn.setFixedWidth(32)
        self._sound_btn.setToolTip("Toggle Sound Effects")
        self._sound_btn.clicked.connect(self._sound_toggle_fast)
        self._sound_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 14px; } QPushButton:hover { background: #252545; border-radius: 4px; }")
        self.status_bar.addPermanentWidget(self._sound_btn)

        # ── Live status widgets (item: status bar) ───────────────
        # Ollama health dot (async via QNetworkAccessManager — never blocks UI)
        self._ollama_dot = QLabel("●")
        self._ollama_dot.setToolTip("Ollama: checking…")
        self._ollama_dot.setStyleSheet("color: #4a4a6a; font-size: 13px; padding: 0 4px;")
        self.status_bar.addPermanentWidget(self._ollama_dot)
        self._ollama_label = QLabel("ollama")
        self._ollama_label.setToolTip("Ollama runtime health")
        self._ollama_label.setStyleSheet("color: #8888bb; font-size: 11px; padding: 0 2px;")
        self.status_bar.addPermanentWidget(self._ollama_label)
        self._ollama_ok: bool | None = None
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest

            self._ollama_nam = QNetworkAccessManager(self)
            self._ollama_nam.finished.connect(self._on_ollama_reply)
        except Exception:
            self._ollama_nam = None

        # Budget burn
        self._budget_label = QLabel("💰 –")
        self._budget_label.setToolTip("Today's estimated spend / limit")
        self._budget_label.setStyleSheet("color: #8888bb; font-size: 11px; padding: 0 6px;")
        self.status_bar.addPermanentWidget(self._budget_label)

        # Pipeline state
        self._pipeline_label = QLabel("🚀 –")
        self._pipeline_label.setToolTip("Pipeline state")
        self._pipeline_label.setStyleSheet("color: #8888bb; font-size: 11px; padding: 0 6px;")
        self.status_bar.addPermanentWidget(self._pipeline_label)

        # Event bus state
        self._bus_label = QLabel("📡 –")
        self._bus_label.setToolTip("Event bus status")
        self._bus_label.setStyleSheet("color: #8888bb; font-size: 11px; padding: 0 6px;")
        self.status_bar.addPermanentWidget(self._bus_label)

        # Status bar refresh timer
        self._status_timer = QTimer()
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start()
        self._check_ollama()

        # ── System tray ──────────────────────────────────────────
        self._setup_tray()

        # ── Human-in-the-loop approval hook (agent tool gate) ────
        self._install_approval_hook()

        # ── Shortcuts ────────────────────────────────────────────
        self._setup_shortcuts()

        # ── Navigate to last-used page (or pipeline) ───────────────
        last = self._config.get("last_page", "pipeline")
        if last not in [p for p, _l, _e, _g in SIDEBAR_ITEMS]:
            last = "pipeline"
        self._navigate(last)

        # ── Theme (honours auto dark/light) ──────────────────────
        self.refresh_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self.refresh_theme)
        except Exception:
            pass

        # ── Auto-theme timer (switch by time of day) ─────────────
        self._auto_theme_timer = QTimer()
        self._auto_theme_timer.setInterval(60000)  # Check every minute
        self._auto_theme_timer.timeout.connect(self._check_auto_theme)
        self._auto_theme_timer.start()
        self._check_auto_theme()

        # ── Restore saved geometry + sidebar width ──────────────
        self._restore_geom()
        self._apply_sidebar_collapsed()

        # ── Ambient Mode (animated background overlay) ──
        self._ambient_widget: QWidget | None = None
        self._ambient_active = False
        self._ambient_timer: QTimer | None = None

        # ── Performance overlay (Ctrl+Shift+I) ──
        self._perf_overlay: QWidget | None = None
        self._perf_timer: QTimer | None = None

        # ── Soundscape mode ──
        self._soundscape_active = False
        self._soundscape_volume = 50

        # ── Animated boot screen ──
        self._show_boot_screen()

        # ── Crash recovery check ──
        self._check_crash_recovery()

    # ────────────────────────────────────────────────────────────────

    def _register(self, page: QWidget, name: str) -> None:
        self.pages[name] = page
        self.stack.addWidget(page)

    # ── Navigation ────────────────────────────────────────────────
    def _init_sidebar_items(self) -> None:
        """(Re)build the nav list from self.nav_order (grouped, registered-only)."""
        self.nav_list.clear()
        self._nav_items.clear()
        self._nav_headers: dict[str, QListWidgetItem] = {}
        saved = self._config.get("sidebar_collapsed_groups")
        if saved is None:
            # With only 17 items, all groups start expanded for easy discovery.
            self._group_collapsed = {"Core": False, "Agents": False, "System": False}
        else:
            self._group_collapsed = {g: (g in saved) for g in ("Core", "Agents", "System")}
        meta = {pid: (label, emoji, group) for pid, label, emoji, group in SIDEBAR_ITEMS}
        last_group = None
        for pid in self.nav_order:
            if pid not in self.pages:
                continue  # optional pages (e.g. webview w/o QtWebEngine) are skipped
            label, emoji, group = meta.get(pid, (pid, "•", "Other"))
            if group != last_group:
                arrow = "▸" if self._group_collapsed.get(group, False) else "▾"
                h = QListWidgetItem(f"  {arrow}  {group.upper()}")
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                h.setSizeHint(QSize(0, 24))
                f = h.font()
                f.setBold(True)
                f.setPointSize(8)
                h.setFont(f)
                h.setForeground(QBrush(QColor("#4a4a6a")))
                self.nav_list.addItem(h)
                self._nav_headers[group] = h
                last_group = group
            text = emoji if self._sidebar_collapsed else f"{emoji}  {label}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setSizeHint(QSize(0, 42))
            self.nav_list.addItem(item)
            self._nav_items[pid] = item
        self._filter_nav(self.nav_filter.text())

    def _on_nav_header_click(self, item: QListWidgetItem) -> None:
        """Click a group header to fold/unfold its pages."""
        group = next((g for g, h in self._nav_headers.items() if h is item), None)
        if group is None:
            return
        self._group_collapsed[group] = not self._group_collapsed.get(group, False)
        h = self._nav_headers[group]
        h.setText(f"  {'▸' if self._group_collapsed[group] else '▾'}  {group.upper()}")
        self._config["sidebar_collapsed_groups"] = [g for g, c in self._group_collapsed.items() if c]
        self._save_config()
        if not self.nav_filter.text().strip():
            self._apply_group_visibility()

    def _apply_group_visibility(self) -> None:
        """Show/hide page items per collapse state (used when the filter is empty)."""
        for pid, item in self._nav_items.items():
            group = next((g for p, _l, _e, g in SIDEBAR_ITEMS if p == pid), "")
            folded = self._group_collapsed.get(group, False) and not self._sidebar_collapsed
            item.setHidden(folded)
        for h in self._nav_headers.values():
            h.setHidden(self._sidebar_collapsed)

    def _on_nav_selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is None:
            return  # group header, not navigable
        self._navigate(pid)

    def _on_nav_reordered(self) -> None:
        self.nav_order = [
            self.nav_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.nav_list.count())
            if self.nav_list.item(i).data(Qt.ItemDataRole.UserRole) is not None
        ]
        self._config["sidebar_order"] = self.nav_order
        self._save_config()

    def _filter_nav(self, text: str) -> None:
        """Filter-as-you-type over sidebar pages; keeps group headers tidy."""
        q = text.strip().lower()
        self.nav_list.setDragEnabled(not q)
        if not q:
            self._apply_group_visibility()
            return
        visible_groups: set[str] = set()
        for pid, item in self._nav_items.items():
            label = next((l for p, l, _e, _g in SIDEBAR_ITEMS if p == pid), pid)
            show = q in label.lower() or q in pid
            item.setHidden(not show)
            if show:
                group = next((g for p, _l, _e, g in SIDEBAR_ITEMS if p == pid), "")
                visible_groups.add(group)
        for group, h in self._nav_headers.items():
            h.setHidden(group not in visible_groups)

    def _nav_context_menu(self, pos) -> None:
        item = self.nav_list.itemAt(pos)
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pop = menu.addAction("\U0001f5d7  Open in new window")
        if pop is not None:
            pop.triggered.connect(lambda checked=False, p=pid: self._pop_out(p))
        menu.exec(self.nav_list.mapToGlobal(pos))

    def _navigate(self, page_id: str) -> None:
        if page_id == self.current_page:
            return
        # Persist leaving page UI state
        if self.current_page:
            prev = self.pages.get(self.current_page)
            if hasattr(prev, "_save_splitter"):
                prev._save_splitter()
        item = self._nav_items.get(page_id)
        if item is not None:
            self.nav_list.setCurrentItem(item)
        self.stack.setCurrentWidget(self.pages[page_id])
        self.current_page = page_id
        try:
            from virgo_telemetry import track
            track("page_view", page_id=page_id)
        except Exception:
            pass
        self._config["last_page"] = page_id
        self._save_config()
        page = self.pages[page_id]
        if hasattr(page, "on_activate"):
            page.on_activate()

    def set_status(self, text: str) -> None:
        """Update the bottom status bar text."""
        self.status_bar.showMessage(text)

    def _ask_virgo(self) -> None:
        """Route the Ask Virgo bar text into the Chat page and fire it."""
        msg = self.ask_input.text().strip()
        if not msg:
            return
        self.ask_input.clear()
        try:
            from virgo_telemetry import track
            track("chat_send")
        except Exception:
            pass
        try:
            self._navigate("chat")
            page = self.pages.get("chat")
            if page is not None and hasattr(page, "msg_input") and hasattr(page, "_send"):
                page.msg_input.setText(msg)
                page._send()
        except Exception:
            pass

    # ── Sidebar collapse + resize ─────────────────────────────────
    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        self._apply_sidebar_collapsed()
        self._config["sidebar_collapsed"] = self._sidebar_collapsed
        self._save_config()

    def _apply_sidebar_collapsed(self) -> None:
        if self._sidebar_collapsed:
            widths = [56, max(240, self.width() - 56)]
        else:
            w = int(self._config.get("sidebar_width", 180))
            widths = [w, max(240, self.width() - w)]
        self.splitter.setSizes(widths)
        for pid, item in self._nav_items.items():
            label, emoji = next(((l, e) for p, l, e, _g in SIDEBAR_ITEMS if p == pid), (pid, "•"))
            item.setText(emoji if self._sidebar_collapsed else f"{emoji}  {label}")
        self._apply_group_visibility()
        for h in self._nav_headers.values():
            h.setHidden(self._sidebar_collapsed)
        self.nav_filter.setVisible(not self._sidebar_collapsed)
        self.sidebar_title.setVisible(not self._sidebar_collapsed)
        self.quit_btn.setText("\U0001f6f8" if self._sidebar_collapsed else f"{icon('exit')}  Quit")

    def _on_splitter_moved(self, *_args) -> None:
        if self._sidebar_collapsed:
            return
        self._config["sidebar_width"] = int(self.splitter.sizes()[0])
        self._save_config()

    # ── Multi-window pop-out ──────────────────────────────────────
    def _pop_out(self, page_id: str) -> None:
        if page_id in self._popped:
            self._popped[page_id].raise_()
            self._popped[page_id].activateWindow()
            return
        page = self.pages.get(page_id)
        if page is None:
            return
        win = PopOutWindow(page_id, page, self)
        self._popped[page_id] = win
        win.show()

    # ── Shortcuts ─────────────────────────────────────────────────
    def _setup_shortcuts(self) -> None:
        """Number keys 1-9 / 0 jump to sidebar pages (following order)."""
        for idx, page_id in enumerate(self.nav_order):
            if idx < 9:
                key = str(idx + 1)
            elif idx == 9:
                key = "0"
            else:
                break
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda pid=page_id: self._navigate(pid))

        # Ctrl+P / Ctrl+K quick page switcher
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._show_quick_switcher)
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._show_quick_switcher)
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(self._command_palette)
        # Ctrl+B toggle sidebar collapse
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._toggle_sidebar)
        # ? shortcuts overlay
        QShortcut(QKeySequence("?"), self).activated.connect(self._show_shortcuts_overlay)

        # Ctrl+Shift+I toggles the performance overlay
        QShortcut(QKeySequence("Ctrl+Shift+I"), self).activated.connect(self._toggle_perf_overlay)

    def _setup_tray(self) -> None:
        """Create system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._real_close = False
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(f"{APP_NAME}  v{APP_VERSION}")
        # Use the branded mark when available, otherwise a solid fallback
        import os

        _tray_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if getattr(sys, "frozen", False) and not os.path.exists(_tray_icon):
            _tray_icon = os.path.join(getattr(sys, "_MEIPASS", ""), "logo.ico")
        if os.path.exists(_tray_icon):
            self.tray.setIcon(QIcon(_tray_icon))
        else:
            from PyQt6.QtGui import QColor, QPixmap

            pm = QPixmap(16, 16)
            pm.fill(QColor("#00b4d8"))
            self.tray.setIcon(QIcon(pm))

        menu = QMenu()
        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(self.showNormal)
        chat_action = menu.addAction("Open Chat")
        chat_action.triggered.connect(lambda: (self.showNormal(), self._navigate("chat")))
        pipeline_action = menu.addAction("Run Pipeline")
        pipeline_action.triggered.connect(lambda: (self.showNormal(), self._navigate("pipeline")))
        agent_action = menu.addAction("Run Agent (live timeline)")
        agent_action.triggered.connect(lambda: (self.showNormal(), self._navigate("timeline")))
        swarm_action = menu.addAction("Launch Swarm")
        swarm_action.triggered.connect(lambda: (self.showNormal(), self._navigate("swarm")))
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.show()
        QTimer.singleShot(15000, self._check_updates)

    def _notify_tray(self, title: str, message: str, critical: bool = False) -> None:
        """Pop a system-tray notification when the tray is live."""
        try:
            tray = getattr(self, "tray", None)
            if tray is not None and tray.isVisible():
                ico = (
                    QSystemTrayIcon.MessageIcon.Critical
                    if critical
                    else QSystemTrayIcon.MessageIcon.Information
                )
                tray.showMessage(title, message, ico, 6000)
        except Exception:
            pass

    def _check_updates(self) -> None:
        """Check GitHub for a newer virgo-agent release; notify via tray."""
        try:
            import urllib.request

            req = urllib.request.Request(
                "https://api.github.com/repos/Aussielad89/virgo-agent/releases/latest",
                headers={"User-Agent": "Virgo-Desktop"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            latest = str(data.get("tag_name", "")).lstrip("v")
            if not latest:
                return
            current = tuple(int(p) for p in APP_VERSION.split(".") if p.isdigit())
            newest = tuple(int(p) for p in latest.split(".") if p.isdigit())
            if newest and newest > current:
                self._notify_tray("Virgo update available", f"{latest} — check GitHub")
        except Exception:
            pass

    def _quit(self) -> None:
        self._real_close = True
        self.close()

    # ── Human-in-the-loop approval (agent tool gate) ─────────────────
    def _install_approval_hook(self) -> None:
        """Register a dialog-based approval hook for risky agent tool calls.

        Agent runs execute on worker threads, so the dialog is marshalled
        back onto the GUI thread with a blocking queued invocation.
        """
        try:
            from approval import set_global_hook

            def _hook(tool: str, args: str, risk: int) -> bool:
                result = QMetaObject.invokeMethod(
                    self,
                    "_approval_dialog",
                    Qt.ConnectionType.BlockingQueuedConnection,
                    Q_ARG(str, tool),
                    Q_ARG(str, args[:200]),
                    Q_ARG(int, risk),
                )
                return bool(result)

            set_global_hook(_hook)
        except Exception as exc:  # pragma: no cover
            log.info("approval hook not installed (%s)", exc)

    @pyqtSlot(str, str, int, result=bool)
    def _approval_dialog(self, tool: str, args: str, risk: int) -> bool:
        """Modal approve/deny dialog shown on the GUI thread."""
        risk_names = {0: "unknown", 1: "safe", 2: "low", 3: "medium", 4: "high", 5: "critical"}
        label = risk_names.get(risk, str(risk))
        snippet = (args or "").replace("\n", " ")[:120]
        box = QMessageBox(self)
        box.setWindowTitle("Agent approval required")
        box.setText(f"Virgo wants to call tool: {tool}  (risk: {label})")
        box.setInformativeText(f"Arguments: {snippet}\n\nApprove this call?")
        approve = box.addButton("Approve", QMessageBox.ButtonRole.AcceptRole)
        deny = box.addButton("Deny", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(deny)
        box.exec()
        return box.clickedButton() is approve

    def notify(self, title: str, message: str) -> None:
        """Show a system tray notification (falls back to the status bar)."""
        if getattr(self, "tray", None) and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)
        else:
            self.set_status(f"{title}: {message}")
        self._toast(title, message)

    # ── Achievement / Toast system ────────────────────────────────────────
    _toasts: list[QFrame] = []

    def _toast(self, title: str, message: str, kind: str = "info") -> None:
        """Show a transient in-app toast with stacking and slide-in."""
        try:
            toast = QFrame(self)
            toast.setObjectName("toast")
            toast.setFrameShape(QFrame.Shape.StyledPanel)
            toast.setMinimumWidth(280)
            toast.setMaximumWidth(340)

            # Style by kind
            kind_styles = {
                "achievement": {
                    "bg": "#0a2a1a", "border": "#00e5a0",
                    "icon": "🏆", "title_color": "#00e5a0",
                },
                "success": {
                    "bg": "#0a1a3a", "border": "#7c6aff",
                    "icon": "✅", "title_color": "#7c6aff",
                },
                "error": {
                    "bg": "#2a0a1a", "border": "#ff5577",
                    "icon": "❌", "title_color": "#ff5577",
                },
                "warning": {
                    "bg": "#2a2a0a", "border": "#ffc53d",
                    "icon": "⚠️", "title_color": "#ffc53d",
                },
                "info": {
                    "bg": "#141428", "border": "#35356a",
                    "icon": "ℹ️", "title_color": "#e0e0ff",
                },
            }
            style = kind_styles.get(kind, kind_styles["info"])

            t_layout = QVBoxLayout(toast)
            t_layout.setContentsMargins(14, 10, 14, 10)
            t_layout.setSpacing(4)

            # Title row with icon
            title_row = QHBoxLayout()
            icon_lbl = QLabel(style["icon"])
            icon_lbl.setStyleSheet("font-size: 16px;")
            title_row.addWidget(icon_lbl)
            t_title = QLabel(f"<b>{title}</b>")
            t_title.setStyleSheet(f"color: {style['title_color']}; font-size: 13px;")
            title_row.addWidget(t_title, 1)
            t_layout.addLayout(title_row)

            t_msg = QLabel(message)
            t_msg.setStyleSheet("color: #8888bb; font-size: 12px;")
            t_msg.setWordWrap(True)
            t_layout.addWidget(t_msg)

            toast.setStyleSheet(
                f"QFrame#toast {{ background: {style['bg']}; "
                f"border: 1px solid {style['border']}; "
                f"border-radius: 10px; }}"
            )
            toast.adjustSize()

            # Stack: position based on existing toasts
            offset = 16 + (len(self._toasts) * (toast.height() + 10))
            x = self.width() - toast.width() - 16
            y = offset
            # Clamp to bottom of window
            if y + toast.height() > self.height() - 60:
                y = self.height() - toast.height() - 60
            toast.move(x, y)
            toast.show()
            self._toasts.append(toast)

            # Animate slide-in: start off-screen right, slide to position
            toast.move(self.width(), y)
            toast.show()

            # Slide animation using a timer
            target_x = x
            slide_steps = 6
            slide_interval = 20

            def _slide(step: int = 0) -> None:
                if step >= slide_steps:
                    toast.move(target_x, toast.y())
                    return
                progress = (step + 1) / slide_steps
                ease = 1 - (1 - progress) ** 2  # ease-out quad
                current_x = self.width() - (self.width() - target_x) * ease
                toast.move(int(current_x), toast.y())
                QTimer.singleShot(
                    slide_interval,
                    lambda s=step + 1: _slide(s),
                )

            # Start slide after layout settles
            QTimer.singleShot(10, _slide)

            # Auto-dismiss and shift remaining toasts up
            def _dismiss() -> None:
                try:
                    if toast in self._toasts:
                        self._toasts.remove(toast)
                    # Fade out by shrinking
                    toast.setMaximumHeight(0)
                    toast.setVisible(False)
                    toast.deleteLater()
                    # Shift remaining toasts up
                    self._reposition_toasts()
                except Exception:
                    pass

            duration = 5000 if kind == "achievement" else 3500
            QTimer.singleShot(duration, _dismiss)
        except Exception:
            pass

    def _reposition_toasts(self) -> None:
        """Reposition all visible toasts after one is dismissed."""
        y_offset = 16
        for t in list(self._toasts):
            try:
                if t and t.isVisible():
                    t.move(t.x(), y_offset)
                    y_offset += t.height() + 10
            except Exception:
                pass

    _achievement_levels = {
        "first_pipeline": ("First Pipeline!", "Ran your first pipeline — the journey begins", "achievement"),
        "pipeline_10": ("Pipeline Veteran", "Ran 10 pipelines total", "achievement"),
        "pipeline_50": ("Pipeline Master", "Ran 50 pipelines — you're a machine", "achievement"),
        "streak_3": ("On Fire!", "3-day streak", "achievement"),
        "streak_7": ("Unstoppable", "7-day streak!", "achievement"),
        "chat_100": ("Chatterbox", "Sent 100 chat messages", "achievement"),
        "swarm_first": ("Swarm Commander", "Launched your first swarm", "achievement"),
        "level_5": ("Level 5", "Reached level 5 XP", "achievement"),
        "level_10": ("Level 10", "Reached level 10 — legend", "achievement"),
    }
    _achievement_counts: dict[str, int] = {}
    _achievement_unlocked: set[str] = set()

    def _achievement_check(self, source: str, data: Any = None) -> None:
        """Check if a milestone has been reached and fire an achievement toast."""
        try:
            from virgo_leaderboard import get_stats
            stats = get_stats()

            total_pipelines = stats.get("total_sessions", 0)
            current_streak = stats.get("current_streak", 0)
            total_xp = stats.get("total_xp", 0)
            level = (total_xp // 100) + 1

            checks = []

            if source == "pipeline":
                checks.append(("first_pipeline", total_pipelines >= 1))
                checks.append(("pipeline_10", total_pipelines >= 10))
                checks.append(("pipeline_50", total_pipelines >= 50))
                checks.append(("streak_3", current_streak >= 3))
                checks.append(("streak_7", current_streak >= 7))
                checks.append(("level_5", level >= 5))
                checks.append(("level_10", level >= 10))

            elif source == "chat":
                self._achievement_counts["chat_messages"] = (
                    self._achievement_counts.get("chat_messages", 0) + 1
                )
                checks.append(("chat_100", self._achievement_counts["chat_messages"] >= 100))

            elif source == "swarm":
                checks.append(("swarm_first", True))

            for key, cond in checks:
                if cond and key not in self._achievement_unlocked:
                    self._achievement_unlocked.add(key)
                    info = self._achievement_levels.get(key)
                    if info:
                        self._show_achievement(info[0], info[1])

        except Exception:
            pass

    def _show_achievement(self, title: str, message: str) -> None:
        """Fire an achievement-style toast."""
        self._toast(f"🏆  {title}", message, kind="achievement")

    def _fuzzy_score(self, query: str, text: str) -> int:
        """Subsequence fuzzy score: higher is better, -1 means no match."""
        q = query.lower().replace(" ", "")
        t = text.lower()
        if not q:
            return 0
        if q in t:
            return 1000 - t.index(q)
        ti = 0
        score = 0
        streak = 0
        for ch in q:
            found = False
            while ti < len(t):
                if t[ti] == ch:
                    streak += 1
                    score += 1 + streak
                    ti += 1
                    found = True
                    break
                streak = 0
                ti += 1
            if not found:
                return -1
        return score

    def _show_quick_switcher(self) -> None:
        """Ctrl+P dialog: fuzzy-search sidebar pages, jump or pop out on Enter."""
        t = self.themes.get(getattr(self, "_active_theme", self._theme_name), self.themes["mocha"])
        dlg = QDialog(self)
        dlg.setWindowTitle("Jump to Page")
        dlg.resize(340, 380)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {t["bg"]}; }}
            QLineEdit {{
                background: {t["border"]};
                border: 1px solid {t["border2"]};
                border-radius: 6px; padding: 8px 12px;
                color: {t["text"]};
                font-size: 15px;
            }}
            QListWidget {{
                background: {t["surface"]};
                border: 1px solid {t["border"]};
                border-radius: 6px;
                color: {t["text"]};
            }}
            QListWidget::item {{
                padding: 6px 12px; border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background: {t["border2"]};
                color: {t["accent"]};
            }}
        """)
        layout = QVBoxLayout(dlg)
        inp = QLineEdit()
        inp.setPlaceholderText("Type page name (fuzzy)…")
        inp.setFocus()
        layout.addWidget(inp)
        lst = QListWidget()
        layout.addWidget(lst)

        entries = [(pid, label, emoji) for pid, label, emoji, _g in SIDEBAR_ITEMS]

        def _refresh(text: str) -> None:
            q = text.strip()
            if not q:
                scored = [(0, e) for e in entries]
            else:
                scored = [(self._fuzzy_score(q, e[1]), e) for e in entries]
                scored = [(s, e) for s, e in scored if s >= 0]
                scored.sort(key=lambda x: -x[0])
            lst.clear()
            for _s, (pid, label, emoji) in scored:
                item = QListWidgetItem(f"{emoji}  {label}")
                item.setData(Qt.ItemDataRole.UserRole, pid)
                lst.addItem(item)
            if lst.count():
                lst.setCurrentRow(0)

        def _go() -> None:
            cur = lst.currentItem()
            if cur:
                self._navigate(cur.data(Qt.ItemDataRole.UserRole))
            dlg.accept()

        def _pop() -> None:
            cur = lst.currentItem()
            if cur:
                self._pop_out(cur.data(Qt.ItemDataRole.UserRole))
            dlg.accept()

        inp.textChanged.connect(_refresh)
        lst.itemDoubleClicked.connect(lambda _: _go())
        inp.returnPressed.connect(_go)

        btn_row = QHBoxLayout()
        go_btn = QPushButton(f"{icon('open')}  Open")
        go_btn.setDefault(True)
        go_btn.clicked.connect(_go)
        pop_btn = QPushButton("\U0001f5d7  Pop out window")
        pop_btn.clicked.connect(_pop)
        btn_row.addWidget(go_btn)
        btn_row.addWidget(pop_btn)
        layout.addLayout(btn_row)
        _refresh("")
        dlg.exec()

    def _command_palette(self) -> None:
        """Ctrl+Shift+P — full-screen overlay command palette with categories."""
        t = self.themes.get(
            getattr(self, "_active_theme", self._theme_name), self.themes["mocha"]
        )

        # Build action list with categories
        categories = {
            "Navigation": [],
            "Actions": [],
            "Persona": [],
            "Focus": [],
            "Tools": [],
        }

        for pid, label, emoji, _g in SIDEBAR_ITEMS:
            categories["Navigation"].append(
                (f"{emoji}  Go to {label}", "page", lambda p=pid: self._navigate(p))
            )
        # Also include palette-only pages (hidden from sidebar, accessible here)
        _all_registered = set(self.pages.keys())
        for pid in sorted(_PALETTE_ONLY):
            if pid not in _all_registered:
                continue
            emoji = DESKTOP_ICONS.get(pid, "📄")
            categories["Navigation"].append(
                (f"{emoji}  {pid.replace('_', ' ').title()}", "page", lambda p=pid: self._navigate(p))
            )

        nav_actions = categories["Navigation"]
        act_actions = categories["Actions"]
        act_actions += [
            ("⚡  Toggle Theme", "cmd", lambda: self._cycle_theme()),
            ("💾  Export Chat", "cmd", lambda: self._route_to_page_action("chat", "_export")),
            ("📂  Files: refresh", "cmd", lambda: self._route_to_page_action("files", "on_activate")),
            ("🚀  Run Pipeline", "cmd", lambda: self._route_to_page_action("pipeline", "_run_pipeline")),
            ("🔄  Reload UI", "cmd", lambda: self._apply_style()),
            ("⚙️  Open Settings", "cmd", lambda: self._navigate("settings")),
            ("ℹ️  About", "cmd", lambda: self._navigate("about")),
            ("📋  Toggle sidebar", "cmd", lambda: self._toggle_sidebar()),
            ("📋  Prompt Library", "cmd", lambda: self._navigate("chat") or self._route_to_page_action("chat", "_show_prompt_lib")),
            ("📊  View Leaderboard", "cmd", lambda: self._navigate("leaderboard")),
            ("🐾  Mascot Chat", "cmd", lambda: self._navigate("mascot_chat")),
        ]

        persona_actions = categories["Persona"]
        for p_name in ("hacker", "poet", "pirate", "cybercat", "sage"):
            persona_actions.append(
                (f"🎨  Persona: {p_name.capitalize()}", "cmd",
                 lambda n=p_name: self._set_persona_fast(n))
            )

        focus_actions = categories["Focus"]
        for f_name in ("lofi", "synthwave", "ambient"):
            focus_actions.append(
                (f"🎧  Focus: {f_name.capitalize()}", "cmd",
                 lambda n=f_name: self._focus_fast(n))
            )
        focus_actions.append(("🔇  Focus: Stop", "cmd", lambda: self._focus_stop()))

        tools_actions = categories["Tools"]
        tools_actions += [
            ("🎲  Chaos: Toggle", "cmd", lambda: self._chaos_toggle_fast()),
            ("🔊  Sound: Toggle", "cmd", lambda: self._sound_toggle_fast()),
            ("🎉  Celebrate!", "cmd", lambda: self._show_celebration("success")),
        ]

        # Build-on-top commands
        act_actions += [
            ("📈  Run Agent (timeline)", "cmd", lambda: self._navigate("timeline")),
            ("📦  Artifacts", "cmd", lambda: self._navigate("artifacts")),
            ("🧠  Memory / profile", "cmd", lambda: self._navigate("memory")),
            ("💰  Budget", "cmd", lambda: self._navigate("budget")),
            ("🔍  Knowledge Base (RAG)", "cmd", lambda: self._navigate("rag")),
        ]
        if "webview" in self.pages:
            act_actions.append(("🌐  Web Dashboard tab", "cmd", lambda: self._navigate("webview")))

        flat_actions = []
        for cat_name, items in categories.items():
            if items:
                flat_actions.append((f"── {cat_name} ──", "header", None))
                flat_actions.extend(items)

        # Full-screen overlay dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Command Palette")
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        dlg.resize(520, 480)

        # Center on parent
        parent_rect = self.geometry()
        dlg.move(
            parent_rect.center().x() - dlg.width() // 2,
            parent_rect.center().y() - dlg.height() // 2 - 40,
        )

        overlay = QWidget(dlg)
        overlay.setGeometry(0, 0, dlg.width(), dlg.height())
        overlay.setStyleSheet(f"""
            background: {t.get("bg", "#1e1e2e")};
            border: 1px solid {t.get("border", "#313244")};
            border-radius: 12px;
        """)

        lo = QVBoxLayout(overlay)
        lo.setContentsMargins(16, 16, 16, 12)
        lo.setSpacing(8)

        # Search input (large, prominent)
        inp = QLineEdit()
        inp.setPlaceholderText("🔍  Type a command or page name…")
        inp.setStyleSheet(f"""
            QLineEdit {{
                background: {t.get("surface", "#181825")};
                border: 2px solid {t.get("accent", "#89b4fa")};
                border-radius: 8px; padding: 10px 14px;
                color: {t.get("text", "#cdd6f4")};
                font-size: 16px;
            }}
            QLineEdit:focus {{ border-color: {t.get("accent2", "#a6e3a1")}; }}
        """)
        inp.setFocus()
        dlg.setFocusProxy(inp)
        lo.addWidget(inp)

        # Results list
        lst = QListWidget()
        lst.setStyleSheet(f"""
            QListWidget {{
                background: {t.get("surface", "#181825")};
                border: 1px solid {t.get("border", "#313244")};
                border-radius: 8px;
                color: {t.get("text", "#cdd6f4")};
                font-size: 13px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-radius: 6px;
                margin: 1px 0;
            }}
            QListWidget::item:selected {{
                background: {t.get("border2", "#45475a")};
                color: {t.get("accent", "#89b4fa")};
            }}
            QListWidget::item:hover {{
                background: {t.get("border", "#313244")};
            }}
        """)
        lo.addWidget(lst, 1)

        # Footer hint
        footer = QLabel(
            "⏎  Execute   ·   ↑↓  Navigate   ·   Esc  Close"
        )
        footer.setStyleSheet(f"color: {t.get('disabled', '#6c7086')}; font-size: 11px; padding: 4px 2px;")
        lo.addWidget(footer)

        def _refresh(q: str) -> None:
            q = q.strip().lower()
            lst.clear()
            if not q:
                # Show all with headers
                for a in flat_actions:
                    item = QListWidgetItem(a[0])
                    if a[1] == "header":
                        item.setFlags(Qt.ItemFlag.NoItemFlags)
                        item.setForeground(QColor(t.get("disabled", "#6c7086")))
                        f = item.font()
                        f.setPointSize(9)
                        f.setBold(True)
                        item.setFont(f)
                    else:
                        item.setData(Qt.ItemDataRole.UserRole, a)
                    lst.addItem(item)
            else:
                scored = [
                    (self._fuzzy_score(q, a[0]), a)
                    for a in flat_actions if a[1] != "header"
                ]
                scored = [(s, a) for s, a in scored if s >= 0]
                scored.sort(key=lambda x: -x[0])
                for _s, a in scored:
                    item = QListWidgetItem(a[0])
                    item.setData(Qt.ItemDataRole.UserRole, a)
                    lst.addItem(item)
            if lst.count():
                # Skip headers when setting current row
                for i in range(lst.count()):
                    it = lst.item(i)
                    if it and it.flags() & Qt.ItemFlag.ItemIsSelectable:
                        lst.setCurrentRow(i)
                        break

        def _run() -> None:
            cur = lst.currentItem()
            if cur:
                data = cur.data(Qt.ItemDataRole.UserRole)
                if data and data[1] != "header":
                    _, _, cb = data
                    dlg.accept()
                    if cb:
                        cb()

        inp.textChanged.connect(_refresh)
        lst.itemDoubleClicked.connect(lambda _: _run())
        inp.returnPressed.connect(_run)

        # Keyboard nav: ↑↓ in list, Esc to close
        def _key_handler(event) -> None:
            if event.key() == Qt.Key.Key_Escape:
                dlg.reject()
            elif event.key() == Qt.Key.Key_Down:
                nxt = lst.currentRow() + 1
                while nxt < lst.count():
                    it = lst.item(nxt)
                    if it and it.flags() & Qt.ItemFlag.ItemIsSelectable:
                        lst.setCurrentRow(nxt)
                        break
                    nxt += 1
            elif event.key() == Qt.Key.Key_Up:
                prv = lst.currentRow() - 1
                while prv >= 0:
                    it = lst.item(prv)
                    if it and it.flags() & Qt.ItemFlag.ItemIsSelectable:
                        lst.setCurrentRow(prv)
                        break
                    prv -= 1
            else:
                super(QLineEdit, inp).keyPressEvent(event)

        inp.keyPressEvent = _key_handler  # type: ignore[assignment]
        _refresh("")
        dlg.exec()

    def _route_to_page_action(self, page_id: str, method: str) -> None:
        """Navigate to a page and call one of its methods if present."""
        self._navigate(page_id)
        page = self.pages.get(page_id)
        if page and hasattr(page, method):
            getattr(page, method)()

    def _cycle_theme(self) -> None:
        """Advance to the next available theme."""
        names = list(self.themes.keys())
        idx = names.index(getattr(self, "_active_theme", self._theme_name))
        nxt = names[(idx + 1) % len(names)]
        self._theme_name = nxt
        self._active_theme = nxt
        self._apply_style()
        self._save_theme_pref(nxt)

    # ── Status bar helpers ──────────────────────────────────────────

    def _check_auto_theme(self) -> None:
        """Auto-switch theme based on time of day."""
        try:
            from virgo_themes import get_suggested_theme
            suggested = get_suggested_theme()
            current = getattr(self, "_auto_theme_current", None)
            theme_map = {"mocha": "Mocha", "latte": "Latte", "nord": "Nord", "gruvbox": "Gruvbox"}
            target = theme_map.get(suggested, current)
            if target and target != current:
                self._auto_theme_current = target
                theme_key = {"Mocha": "mocha", "Latte": "latte", "Nord": "nord", "Gruvbox": "gruvbox"}.get(target, "mocha")
                self._set_theme(theme_key)
        except Exception:
            pass

    def _populate_persona_combo(self) -> None:
        """Fill the persona combo box from virgo_persona."""
        try:
            from virgo_persona import list_personas, current_persona_name
            self._persona_combo.blockSignals(True)
            self._persona_combo.clear()
            for p in list_personas():
                display = p.get("display_name", p["name"])
                self._persona_combo.addItem(display, p["name"])
            current = current_persona_name()
            idx = self._persona_combo.findData(current)
            if idx >= 0:
                self._persona_combo.setCurrentIndex(idx)
            self._persona_combo.blockSignals(False)
        except Exception:
            pass

    def _on_persona_changed(self, idx: int) -> None:
        """Handle persona combo change."""
        name = self._persona_combo.itemData(idx)
        if not name:
            return
        try:
            from virgo_persona import set_persona
            set_persona(name)
            self.status_bar.showMessage(f"Persona: {name}", 3000)
            self._update_status_bar_theme()
        except Exception:
            pass

    def _refresh_status_bar(self) -> None:
        """Periodic status bar refresh — focus, sound, styles."""
        # Update focus indicator
        try:
            import virgo_focus as fmod
            st = fmod.status()
            if st.get("active"):
                genre = st.get("genre_name", "?")
                mins = int(st.get("elapsed_minutes", 0))
                self._focus_indicator.setText(f"🎧 {genre} ({mins}m)")
            else:
                self._focus_indicator.setText("")
        except Exception:
            pass

        # Update sound button icon
        try:
            import virgo_soundpack as sp
            p = sp.get_pack()
            self._sound_btn.setText("🔇" if not p.get("active") else "🔊")
        except Exception:
            pass

        # Update chaos button
        try:
            import virgo_chaos as ch
            self._chaos_btn.setText("🎲" if ch.is_chaos_enabled() else "🎲")
            self._chaos_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; font-size: 14px; } QPushButton:hover { background: #252545; border-radius: 4px; }"
            )
        except Exception:
            pass

        # ── Live status widgets ──
        # Budget burn (local file read — fast, safe on UI thread)
        try:
            from budget import get_budget

            bt = get_budget()
            cost = sum(float(r.get("cost", 0.0)) for r in bt._records)
            lim = float(getattr(bt, "limit", 0.0) or 0.0)
            pct = int(cost / lim * 100) if lim > 0 else 0
            color = "#00e5a0" if pct < 70 else ("#ffc53d" if pct < 90 else "#ff5577")
            self._budget_label.setText(f"💰 ${cost:.2f} ({pct}%)")
            self._budget_label.setToolTip(f"Estimated spend ${cost:.2f} / limit ${lim:.2f}")
            self._budget_label.setStyleSheet(f"color: {color}; font-size: 11px; padding: 0 6px;")
        except Exception:
            pass

        # Pipeline state (reads the UI state file the pipeline writes)
        try:
            state_path = Path(__file__).parent / ".virgo_pipeline_ui.json"
            state = "idle"
            if state_path.exists():
                d = json.loads(state_path.read_text())
                state = str(d.get("state", d.get("status", "idle"))).lower()
            color = "#ffc53d" if state in ("running", "active", "busy") else "#4a4a6a"
            self._pipeline_label.setText(f"🚀 {state}")
            self._pipeline_label.setToolTip("Pipeline state (from .virgo_pipeline_ui.json)")
            self._pipeline_label.setStyleSheet(f"color: {color}; font-size: 11px; padding: 0 6px;")
        except Exception:
            pass

        # Event bus status
        try:
            from virgo_eventbus import get_bus

            s = get_bus().status()
            running = bool(s.get("running", s.get("active", False)))
            subs = s.get("listeners", s.get("sources", 0))
            color = "#00e5a0" if running else "#4a4a6a"
            self._bus_label.setText(f"📡 {'on' if running else 'off'}" + (f" · {subs}" if subs else ""))
            self._bus_label.setToolTip("Event bus status")
            self._bus_label.setStyleSheet(f"color: {color}; font-size: 11px; padding: 0 6px;")
        except Exception:
            pass

    def _check_ollama(self) -> None:
        """Fire an async GET to the Ollama API (non-blocking health probe)."""
        if self._ollama_nam is None:
            return
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtNetwork import QNetworkRequest

            req = QNetworkRequest(QUrl("http://localhost:11434/api/tags"))
            req.setTransferTimeout(2500)
            self._ollama_nam.get(req)
        except Exception:
            pass

    def _on_ollama_reply(self, reply) -> None:
        """Colour the Ollama health dot from the probe result."""
        try:
            err = reply.error()
            ok = err == reply.NetworkError.NoError
            self._ollama_ok = ok
            color = "#00e5a0" if ok else "#ff5577"
            self._ollama_dot.setStyleSheet(f"color: {color}; font-size: 13px; padding: 0 4px;")
            self._ollama_dot.setToolTip("Ollama: online" if ok else "Ollama: unreachable")
            self._ollama_label.setStyleSheet(
                f"color: {'#00e5a0' if ok else '#ff5577'}; font-size: 11px; padding: 0 2px;"
            )
        except Exception:
            pass
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass
        # Re-arm the probe every 10 s (separate slow timer)
        try:
            self._ollama_timer = QTimer()
            self._ollama_timer.setSingleShot(True)
            self._ollama_timer.setInterval(10000)
            self._ollama_timer.timeout.connect(self._check_ollama)
            self._ollama_timer.start()
        except Exception:
            pass

    def _update_status_bar_theme(self) -> None:
        """Update persona combo styling to match current persona."""
        try:
            from virgo_persona import get_persona
            p = get_persona()
            colors = p.get("theme_colors", {})
            primary = colors.get("primary", "cyan")
            style_map = {
                "green": "#00e5a0", "cyan": "#7c6aff", "magenta": "#ff77cc",
                "purple": "#b48aff", "blue": "#7c6aff", "pink": "#ff77cc",
                "gold": "#ffc53d", "orange": "#ff9944", "yellow": "#ffc53d",
                "bright_magenta": "#ff77cc", "bright_cyan": "#66ddff",
                "lime": "#00e5a0", "white": "#e0e0ff",
            }
            accent = style_map.get(primary, "#7c6aff")
            self._persona_combo.setStyleSheet(
                f"QComboBox {{ background: #1a1a36; border: 1px solid {accent}; "
                f"border-radius: 4px; padding: 2px 6px; color: {accent}; "
                f"font-size: 11px; }}"
            )
        except Exception:
            pass

    # ── Quick actions ────────────────────────────────────────────

    def _set_persona_fast(self, name: str) -> None:
        """Set persona from command palette."""
        try:
            from virgo_persona import set_persona, current_persona_name
            if current_persona_name() != name:
                set_persona(name)
                self._populate_persona_combo()
                self.status_bar.showMessage(f"Persona: {name}", 3000)
        except Exception:
            pass

    def _focus_fast(self, genre: str) -> None:
        """Start focus mode from command palette."""
        try:
            import virgo_focus as fmod
            fmod.start(genre)
            self._refresh_status_bar()
        except Exception:
            pass

    def _focus_stop(self) -> None:
        """Stop focus mode from command palette."""
        try:
            import virgo_focus as fmod
            fmod.stop()
            self._refresh_status_bar()
        except Exception:
            pass

    def _chaos_toggle_fast(self) -> None:
        """Toggle chaos mode."""
        try:
            import virgo_chaos as ch
            ch.toggle_chaos()
            enabled = ch.is_chaos_enabled()
            self._chaos_btn.setText("🎲" if enabled else "🎲")
            self.status_bar.showMessage(f"Chaos: {'ON' if enabled else 'OFF'}", 2000)
        except Exception:
            pass

    def _sound_toggle_fast(self) -> None:
        """Toggle sound effects."""
        try:
            import virgo_soundpack as sp
            st = sp.toggle()
            self._sound_btn.setText("🔇" if st.get("status") == "muted" else "🔊")
            self.status_bar.showMessage(f"Sound: {st['status'].upper()}", 2000)
        except Exception:
            pass

    def _show_celebration(self, style: str = "success") -> None:
        """Show a celebration overlay."""
        try:
            from virgo_celebrate import firework, banner, cheer_text
            text = cheer_text(style)
            art = firework(style)
            msg = f"<h2 style='color: #ffc53d;'>{text}</h2><pre style='color: #00e5a0; font-size: 12px;'>{art}</pre>"

            dlg = QDialog(self)
            dlg.setWindowTitle("🎉")
            dlg.resize(400, 300)
            dlg.setStyleSheet("background: #0d0d1a;")
            lo = QVBoxLayout(dlg)
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lo.addWidget(lbl)
            btn = QPushButton("Close")
            btn.clicked.connect(dlg.accept)
            btn.setStyleSheet("QPushButton { background: #1a1a36; border: 1px solid #35356a; border-radius: 6px; padding: 8px 24px; color: #e0e0ff; } QPushButton:hover { border-color: #7c6aff; }")
            lo.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
            dlg.exec()
        except Exception:
            pass

    # ── Achievement Toasts ───────────────────────────────────────

    def _show_achievement_toast(self, title: str, desc: str, xp: int) -> None:
        """Show a slide-in achievement toast notification."""
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle("")
            dlg.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            dlg.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            dlg.setStyleSheet("""
                QDialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a36, stop:1 #252545);
                    border: 1px solid #ffc53d; border-radius: 8px; }
            """)
            lo = QHBoxLayout(dlg)
            lo.setContentsMargins(12, 8, 12, 8)
            icon_lbl = QLabel("🏆")
            icon_lbl.setStyleSheet("font-size: 24px;")
            text_lbl = QLabel(f"<b style='color: #ffc53d;'>{title}</b><br>"
                              f"<span style='color: #8888bb;'>{desc}</span>"
                              f"<br><span style='color: #00e5a0;'>+{xp} XP</span>")
            text_lbl.setWordWrap(True)
            lo.addWidget(icon_lbl)
            lo.addWidget(text_lbl, 1)

            # Position in top-right of main window
            parent_rect = self.geometry()
            dlg.adjustSize()
            x = parent_rect.right() - dlg.width() - 20
            y = parent_rect.top() + 60
            dlg.move(x, y)
            dlg.show()

            # Auto close after 4 seconds
            QTimer.singleShot(4000, dlg.close)
        except Exception:
            pass

    def _show_shortcuts_overlay(self) -> None:
        """Show a dialog listing all keyboard shortcuts."""
        t = self.themes.get(getattr(self, "_active_theme", self._theme_name), self.themes["mocha"])
        lines = [
            ("Key", "Action"),
            ("", ""),
            ("1 – 9, 0", "Navigate sidebar pages (in order)"),
            ("Ctrl+P", "Quick page switcher (fuzzy)"),
            ("Ctrl+Shift+P", "Command palette (actions + pages)"),
            ("Ctrl+Shift+L", "Prompt library panel"),
            ("Ctrl+Shift+I", "Performance overlay"),
            ("Ctrl+B", "Collapse / expand sidebar"),
            ("Ctrl+F", "Search within chat log"),
            ("Ctrl+Return", "Send chat message"),
            ("Ctrl++ / Ctrl+-", "Zoom chat font"),
            ("?", "Show this help overlay"),
            ("Escape", "Close dialogs / overlays"),
            ("", ""),
            ("Drag sidebar items", "Reorder pages"),
            ("Drag sidebar edge", "Resize sidebar"),
            ("Right-click page", "Pop out page to a new window"),
        ]
        html = "<table style='width:100%; border-collapse:collapse;'>"
        for key, action in lines:
            if key == "":
                html += (
                    "<tr><td colspan='2' style='border-bottom:1px solid "
                    + t["border"]
                    + "'></td></tr>"
                )
            else:
                html += (
                    f"<tr><td style='padding:4px 12px; color:{t['accent']}; "
                    f"font-weight:bold; white-space:nowrap;'>{key}</td>"
                    f"<td style='padding:4px 12px; color:{t['text']};'>{action}</td></tr>"
                )
        html += "</table>"

        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.resize(440, 360)
        label = QLabel(html)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"background:{t['surface']}; color:{t['text']}; "
            f"border:1px solid {t['border']}; border-radius:8px; padding:16px;"
        )
        layout = QVBoxLayout(dlg)
        layout.addWidget(label)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setStyleSheet(
            f"background:{t['border']}; color:{t['text']}; "
            f"border:1px solid {t['border2']}; border-radius:6px; padding:6px 24px;"
        )
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        dlg.exec()

    def hideEvent(self, event) -> None:
        """Persist UI state when the window is hidden (minimised / tray)."""
        try:
            cur = self.pages.get(self.current_page)
            if hasattr(cur, "_save_splitter"):
                cur._save_splitter()
            self._save_geom()
        except Exception:
            pass
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        """Minimize to tray instead of quitting, unless a real quit was asked."""
        if getattr(self, "tray", None) and not self._real_close:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                "Running in the background. Right-click the tray icon to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        else:
            # Close any popped-out windows first.
            for win in list(self._popped.values()):
                try:
                    win.close()
                except Exception:
                    pass
            self._save_geom()
            event.accept()

    def _restore_geom(self) -> None:
        try:
            import json

            p = Path(__file__).parent / ".virgo_desktop_geom.json"
            if p.exists():
                d = json.loads(p.read_text())
                w = max(640, int(d.get("w", WIDTH)))
                h = max(480, int(d.get("h", HEIGHT)))
                x = int(d.get("x", 0))
                y = int(d.get("y", 0))
                screen = QApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    x = max(geo.left(), min(x, geo.right() - w))
                    y = max(geo.top(), min(y, geo.bottom() - h))
                    w = min(w, geo.width())
                    h = min(h, geo.height())
                self.resize(w, h)
                self.move(x, y)
        except Exception:
            self.resize(WIDTH, HEIGHT)

    def _check_voice_deps(self) -> None:
        """Check if voice dependencies are available."""
        import importlib
        for dep in ("edge-tts", "SpeechRecognition", "pyaudio"):
            try:
                importlib.import_module(dep)
            except ImportError:
                self.voice_label.setText(f"Voice: ❌ {dep} not installed")
                self.voice_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
                return
        self.voice_label.setText("Voice: ✅ All dependencies available")
        self.voice_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")

    def _check_license(self) -> None:
        """Check license status."""
        try:
            from assetbatch_pro.assetbatch_license import LicenseManager
        except ImportError:
            self.license_label.setText("License: ❌ assetbatch_pro not installed")
            self.license_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
            return
        license_manager = LicenseManager()
        if license_manager.is_licensed():
            self.license_label.setText("License: ✅ Valid")
            self.license_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        else:
            self.license_label.setText("License: ❌ Not verified (Trial Mode)")
            self.license_label.setStyleSheet("color: #f38ba8; font-size: 11px;")

    def _save_geom(self) -> None:
        try:
            import json

            p = Path(__file__).parent / ".virgo_desktop_geom.json"
            geo = self.geometry()
            p.write_text(
                json.dumps({"x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()})
            )
        except Exception:
            pass

    # ── Config persistence ───────────────────────────────────────
    def _load_config(self) -> dict:
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text())
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_config(self) -> None:
        try:
            CONFIG_PATH.write_text(json.dumps(self._config, indent=2))
        except Exception:
            pass

    # ── Theming ───────────────────────────────────────────────────
    def _current_theme(self) -> dict[str, str]:
        name = getattr(self, "_active_theme", self._theme_name)
        return self.themes.get(name, self.themes["mocha"])

    def _apply_style(self) -> None:
        """Build and apply the stylesheet (theme + custom CSS injection)."""
        t = self._current_theme()
        # Inject user font preferences (defaults if not configured).
        t = dict(t)
        t["ui_font_family"] = self._config.get(
            "ui_font_family", "'Segoe UI', 'SF Pro', sans-serif"
        )
        t["ui_font_size"] = str(self._config.get("ui_font_size", 13))
        ss = _build_stylesheet(t)
        if getattr(self, "_custom_css", ""):
            ss += "\n" + self._custom_css
        self.setStyleSheet(ss)
        # Update theme indicator
        if hasattr(self, "_theme_indicator"):
            theme_name = t.get("name", "Mocha")
            icon = "🌙" if self._active_theme in ("mocha", "nord", "gruvbox") else "☀️"
            self._theme_indicator.setText(f"{icon} {theme_name}")
        # Live-apply to any popped-out windows too.
        for win in getattr(self, "_popped", {}).values():
            try:
                win.setStyleSheet(ss)
            except Exception:
                pass

    def set_ui_font(self, family: str, size: int) -> None:
        """Change the global UI font family + base size and re-apply live."""
        self._config["ui_font_family"] = family
        self._config["ui_font_size"] = int(size)
        self._save_config()
        self._apply_style()

    def refresh_theme(self) -> None:
        """Resolve the active theme from the current mode and re-apply."""
        mode = getattr(self, "_theme_mode", "system")
        if mode == "system":
            try:
                scheme = QApplication.styleHints().colorScheme()
                self._active_theme = "latte" if scheme == Qt.ColorScheme.Light else "mocha"
            except Exception:
                self._active_theme = "mocha"
        elif mode == "light":
            self._active_theme = "latte"
        elif mode == "dark":
            self._active_theme = "mocha"
        else:  # manual
            self._active_theme = self._theme_name
        self._apply_style()

    def set_theme_mode(self, mode: str) -> None:
        """Set theme mode: system | dark | light | manual."""
        self._theme_mode = mode
        self.refresh_theme()
        self._save_theme_pref()

    def switch_theme(self, name: str) -> None:
        """Switch to a named theme (also flips mode to 'manual')."""
        if name not in self.themes:
            return
        self._theme_name = name
        self._theme_mode = "manual"
        self._active_theme = name
        self._apply_style()
        self._save_theme_pref()

    def set_custom_css(self, text: str) -> None:
        """Apply and persist user-injected Qt stylesheet overrides."""
        self._custom_css = text
        self._config["custom_css"] = text
        self._save_config()
        self._apply_style()

    def save_custom_theme(self, name: str, colors: dict[str, str]) -> None:
        """Persist a user-built theme and switch to it immediately."""
        key = name.strip().lower().replace(" ", "_") or "custom"
        colors = dict(colors)
        colors["name"] = name
        themes = load_user_themes()
        themes[key] = colors
        try:
            USER_THEMES_PATH.write_text(json.dumps(themes, indent=2))
        except Exception:
            return
        self.themes = all_themes()
        self.switch_theme(key)

    def _save_theme_pref(self) -> None:
        try:
            env_path = HERE / ".env"
            lines = env_path.read_text().splitlines() if env_path.exists() else []
            found_theme = found_mode = False
            for i, line in enumerate(lines):
                if line.startswith("VIRGO_THEME="):
                    lines[i] = f"VIRGO_THEME={self._theme_name}"
                    found_theme = True
                elif line.startswith("VIRGO_THEME_MODE="):
                    lines[i] = f"VIRGO_THEME_MODE={self._theme_mode}"
                    found_mode = True
            if not found_theme:
                lines.append(f"VIRGO_THEME={self._theme_name}")
            if not found_mode:
                lines.append(f"VIRGO_THEME_MODE={self._theme_mode}")
            env_path.write_text("\n".join(lines) + "\n")
        except Exception:
            pass


    def _check_crash_recovery(self) -> None:
        marker = Path(__file__).parent / ".virgo_last_crash"
        if not marker.exists():
            return
        try:
            report_path = marker.read_text(encoding="utf-8").strip()
        except Exception:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Crash Recovery")
        box.setText("Previous session ended unexpectedly.")
        box.setInformativeText(
            f"Crash report: {report_path}\n\n"
            "Restore last known good UI state (theme, page, sidebar)?"
        )
        restore = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Continue", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore)
        box.exec()
        if box.clickedButton() is restore:
            try:
                config_path = Path(__file__).parent / ".virgo_desktop_config.json"
                if config_path.exists():
                    data = json.loads(config_path.read_text())
                    if isinstance(data, dict):
                        if "theme_name" in data and data["theme_name"] in self.themes:
                            self._theme_name = data["theme_name"]
                            self._active_theme = data["theme_name"]
                        if "theme_mode" in data:
                            self._theme_mode = data["theme_mode"]
                        if "last_page" in data and data["last_page"] in self.pages:
                            self._navigate(data["last_page"])
                        if "sidebar_order" in data:
                            self.nav_order = [
                                p for p in data["sidebar_order"] if p in self.pages
                            ]
                            self._init_sidebar_items()
                        self._apply_style()
                        self._save_config()
            except Exception:
                pass
        try:
            marker.unlink()
        except Exception:
            pass


    # ── Animated Boot Screen (#10) ──────────────────────────────────────

    def _show_boot_screen(self) -> None:
        """Display a brief centered splash with Virgo logo text (no QGraphicsView)."""
        try:
            splash = QLabel(self)
            splash.setObjectName("bootSplash")
            splash.setAlignment(Qt.AlignmentFlag.AlignCenter)
            splash.setText(
                "<div style='text-align: center;'>"
                "<span style='font-size: 48px; color: #7c6aff;'>✦</span><br><br>"
                "<span style='font-size: 32px; font-weight: bold; color: #e0e0ff;'>VIRGO</span><br>"
                f"<span style='font-size: 14px; color: #8888bb;'>v{APP_VERSION}</span><br><br>"
                "<span style='font-size: 13px; color: #35356a;'>loading...</span>"
                "</div>"
            )
            splash.setStyleSheet(
                "QLabel { background: #08080f; border: none; }"
            )
            splash.setGeometry(0, 0, self.width(), self.height())
            splash.raise_()
            splash.show()

            def _dismiss() -> None:
                try:
                    splash.hide()
                    splash.deleteLater()
                except Exception:
                    pass

            QTimer.singleShot(1500, _dismiss)
        except Exception:
            pass

    # ── Ambient Mode (#8) ──────────────────────────────────────────────

    def _toggle_ambient(self) -> None:
        """Toggle ambient animated background (Matrix rain / starfield)."""
        self._ambient_active = not self._ambient_active
        if self._ambient_active:
            self._start_ambient()
        else:
            self._stop_ambient()

    def _start_ambient(self) -> None:
        """Create the ambient particle overlay."""
        try:
            if self._ambient_widget:
                self._ambient_widget.deleteLater()
            self._ambient_widget = QWidget(self.stack)
            self._ambient_widget.setGeometry(self.stack.rect())
            self._ambient_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._ambient_widget.setStyleSheet("background: transparent;")
            self._ambient_widget.lower()  # Behind page content
            self._ambient_widget.show()

            self._ambient_particles: list[dict] = []
            import random, math
            for _ in range(60):
                self._ambient_particles.append({
                    "x": random.randint(0, self._ambient_widget.width()),
                    "y": random.randint(-200, self._ambient_widget.height()),
                    "speed": random.uniform(1.0, 3.0),
                    "size": random.randint(1, 3),
                    "alpha": random.randint(30, 150),
                    "char": random.choice("0123456789ABCDEF"),
                })

            self._ambient_timer = QTimer()
            self._ambient_timer.setInterval(50)
            self._ambient_timer.timeout.connect(self._tick_ambient)
            self._ambient_timer.start()
        except Exception:
            pass

    def _tick_ambient(self) -> None:
        """Animate one frame of the Matrix rain particles."""
        w = self._ambient_widget
        if not w or not w.isVisible():
            return
        try:
            pm = QPixmap(w.size())
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setFont(QFont("Courier New", 11))
            for pt in self._ambient_particles:
                pt["y"] += pt["speed"]
                if pt["y"] > w.height() + 20:
                    pt["y"] = -20
                    pt["x"] = __import__("random").randint(0, w.width())
                color = QColor(137, 180, 250, pt["alpha"])
                p.setPen(color)
                p.drawText(int(pt["x"]), int(pt["y"]), pt["char"])
            p.end()
            w.setPixmap(pm)
        except Exception:
            pass

    def _stop_ambient(self) -> None:
        if self._ambient_timer:
            self._ambient_timer.stop()
        if self._ambient_widget:
            self._ambient_widget.deleteLater()
            self._ambient_widget = None

    def resizeEvent(self, event) -> None:
        """Keep ambient overlay sized to the stack widget."""
        super().resizeEvent(event)
        if self._ambient_widget:
            self._ambient_widget.setGeometry(self.stack.rect())

    # ── Performance Overlay (#15) ───────────────────────────────────────

    def _toggle_perf_overlay(self) -> None:
        """Ctrl+Shift+I toggle translucent performance HUD."""
        if self._perf_overlay and self._perf_overlay.isVisible():
            self._perf_overlay.hide()
            if self._perf_timer:
                self._perf_timer.stop()
            return

        if not self._perf_overlay:
            self._perf_overlay = QFrame(self)
            self._perf_overlay.setObjectName("perfOverlay")
            self._perf_overlay.setStyleSheet(
                "QFrame#perfOverlay { background: rgba(8, 8, 15, 220); "
                "border: 1px solid #252545; border-radius: 8px; }"
            )
            lo = QVBoxLayout(self._perf_overlay)
            lo.setContentsMargins(12, 8, 12, 8)
            lo.setSpacing(4)

            self._perf_labels: dict[str, QLabel] = {}
            for key, label in [
                ("fps", "FPS"), ("ram", "RAM (MB)"), ("cpu", "CPU %"),
                ("tokens", "Token speed"), ("uptime", "Uptime"),
            ]:
                row = QHBoxLayout()
                row.addWidget(QLabel(f"{label}:"))
                val = QLabel("—")
                val.setStyleSheet("color: #00e5a0; font-weight: bold;")
                row.addWidget(val, 1)
                lo.addLayout(row)
                self._perf_labels[key] = val

            lo.addWidget(QLabel("Ctrl+Shift+I to hide"))
            self._perf_overlay.adjustSize()

        self._perf_overlay.setFixedWidth(220)
        x = self.width() - self._perf_overlay.width() - 16
        y = 60
        self._perf_overlay.move(x, y)
        self._perf_overlay.show()
        self._perf_overlay.raise_()

        self._perf_timer = QTimer()
        self._perf_timer.setInterval(1000)
        self._perf_timer.timeout.connect(self._update_perf)
        self._perf_timer.start()
        self._update_perf()

    def _update_perf(self) -> None:
        """Refresh performance stats."""
        try:
            import psutil, time
            proc = psutil.Process()
            mem = proc.memory_info().rss / 1024 / 1024
            cpu = proc.cpu_percent(interval=0)
            uptime_sec = time.time() - psutil.boot_time()
            days, rem = divmod(int(uptime_sec), 86400)
            hours, rem = divmod(rem, 3600)
            mins = rem // 60
            uptime_str = f"{days}d {hours}h {mins}m"

            # Estimate FPS from refresh rate
            fps = self._perf_timer.interval() if self._perf_timer else 0
            if fps > 0:
                fps_str = f"{1000 / fps:.0f} (1s update)"
            else:
                fps_str = "—"

            self._perf_labels["fps"].setText(fps_str)
            self._perf_labels["ram"].setText(f"{mem:.1f}")
            self._perf_labels["cpu"].setText(f"{cpu:.1f}")
            self._perf_labels["tokens"].setText("N/A (pipeline)")
            self._perf_labels["uptime"].setText(uptime_str)
        except Exception:
            pass

    # ── Soundscape Mode (#11) ──────────────────────────────────────────

    def _toggle_soundscape(self) -> None:
        """Toggle ambient soundscape (looping nature/synth sounds)."""
        self._soundscape_active = not self._soundscape_active
        if self._soundscape_active:
            self._start_soundscape()
        else:
            self._stop_soundscape()
        self._update_sound_btn()

    def _start_soundscape(self) -> None:
        """Play ambient soundscape using winsound.Beep tones (no deps)."""
        try:
            self._soundscape_thread_running = True
            import threading
            self._sound_thread = threading.Thread(target=self._soundscape_loop, daemon=True)
            self._sound_thread.start()
        except Exception:
            pass

    def _soundscape_loop(self) -> None:
        """Generate a gentle ambient tone pattern via winsound."""
        import time, winsound, random
        base_freq = 220
        while getattr(self, "_soundscape_thread_running", False) and self._soundscape_active:
            try:
                freq = base_freq + random.randint(-30, 30)
                dur = random.randint(300, 800)
                winsound.Beep(freq, dur)
                time.sleep(random.uniform(0.5, 2.0))
            except Exception:
                time.sleep(1)

    def _stop_soundscape(self) -> None:
        self._soundscape_thread_running = False

    def _update_sound_btn(self) -> None:
        try:
            if self._soundscape_active:
                self._sound_btn.setText("🌿")
                self._sound_btn.setToolTip("Soundscape ON — click to stop")
            else:
                self._sound_btn.setText("🔊")
                self._sound_btn.setToolTip("Toggle Sound Effects")
        except Exception:
            pass


class PopOutWindow(QMainWindow):
    """A detached window that hosts one of the main pages."""

    def __init__(self, page_id: str, page: QWidget, parent: VirgoDesktopWindow) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.page = page
        self.main = parent
        label = next((l for pid, l, _e, _g in SIDEBAR_ITEMS if pid == page_id), page_id)
        self.setWindowTitle(f"Virgo · {label}")
        import os

        from PyQt6.QtGui import QIcon

        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        # Reparent the live page widget into this window.
        page.setParent(self)
        self.setCentralWidget(page)
        if hasattr(page, "on_activate"):
            try:
                page.on_activate()
            except Exception:
                pass
        self.resize(820, 600)

    def closeEvent(self, event) -> None:
        # Return the page to the main stack.
        self.page.setParent(self.main.stack)
        self.main.stack.addWidget(self.page)
        self.main.pages[self.page_id] = self.page
        if self.main.current_page == self.page_id:
            self.main.stack.setCurrentWidget(self.page)
        self.main._popped.pop(self.page_id, None)
        event.accept()


def _open_file(path: str) -> None:
    """Open a file with the OS default handler (cross-platform)."""
    import subprocess

    p = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", p], check=False)
        else:
            subprocess.run(["xdg-open", p], check=False)
    except Exception:
        pass


def _qt_message_handler(msgtype, context, msg: str) -> None:
    """Filter benign Qt noise.

    On Windows the system font is sized in pixels, so ``QFont.pointSize()``
    resolves to -1 and Qt logs a harmless
    ``QFont::setPointSize: Point size <= 0 (-1)`` warning for every widget.
    The fonts render correctly; we just suppress that one known-benign line.
    """
    if "setPointSize" in msg and "Point size <= 0" in msg:
        return
    try:
        print(msg)
    except Exception:
        pass


def main() -> None:
    qInstallMessageHandler(_qt_message_handler)
    # PyQt6 aborts the whole app (BEX64 0xc0000409) when a slot raises.
    # Print the traceback and keep running so one bad page can't kill Virgo.
    def _safe_excepthook(etype, val, tb) -> None:
        last_page = None
        try:
            app = QApplication.instance()
            if app is not None:
                win = app.activeWindow()
                if isinstance(win, VirgoDesktopWindow):
                    last_page = win.current_page
        except Exception:
            pass
        report_path = virgo_crash.record_crash(
            etype, val, tb,
            last_active_page=last_page,
            log_file=os.environ.get("VIRGO_LOG_FILE"),
        )
        try:
            box = QMessageBox()
            box.setWindowTitle("Oops")
            box.setIcon(QMessageBox.Icon.Critical)
            box.setText(
                f"An unexpected error occurred.\n\n"
                f"Crash report saved to:\n{report_path}"
            )
            box.exec()
        except Exception:
            pass
        sys.__excepthook__(etype, val, tb)
        try:
            from virgo_telemetry import track
            track("crash")
        except Exception:
            pass

    sys.excepthook = _safe_excepthook
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Virgo")
    window = VirgoDesktopWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    app.processEvents()  # ensure layout and paint events are flushed
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

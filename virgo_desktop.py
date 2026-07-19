"""
Virgo Desktop — polished PyQt6 GUI for virgo-agent.

Usage:
    virgo-desktop
    python -m virgo_desktop
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log, OUTDIR

# ── Theme system ────────────────────────────────────────────────────
THEMES: dict[str, dict[str, str]] = {
    "mocha": {
        "name": "Catppuccin Mocha",
        "bg": "#1e1e2e", "surface": "#181825", "crust": "#11111b",
        "border": "#313244", "border2": "#45475a",
        "text": "#cdd6f4", "subtext": "#a6adc8", "disabled": "#6c7086",
        "accent": "#89b4fa", "accent2": "#a6e3a1",
        "red": "#f38ba8", "yellow": "#f9e2af", "green": "#a6e3a1",
        "sidebar_active": "#45475a",
    },
    "latte": {
        "name": "Catppuccin Latte",
        "bg": "#eff1f5", "surface": "#e6e9ef", "crust": "#dce0e8",
        "border": "#ccd0da", "border2": "#bcc0cc",
        "text": "#4c4f69", "subtext": "#5c5f77", "disabled": "#9ca0b0",
        "accent": "#1e66f5", "accent2": "#40a02b",
        "red": "#d20f39", "yellow": "#df8e1d", "green": "#40a02b",
        "sidebar_active": "#ccd0da",
    },
    "nord": {
        "name": "Nord",
        "bg": "#2e3440", "surface": "#3b4252", "crust": "#434c5e",
        "border": "#4c566a", "border2": "#5e6a83",
        "text": "#eceff4", "subtext": "#d8dee9", "disabled": "#6c7086",
        "accent": "#88c0d0", "accent2": "#a3be8c",
        "red": "#bf616a", "yellow": "#ebcb8b", "green": "#a3be8c",
        "sidebar_active": "#4c566a",
    },
    "gruvbox": {
        "name": "Gruvbox Dark",
        "bg": "#282828", "surface": "#3c3836", "crust": "#504945",
        "border": "#665c54", "border2": "#7c6f64",
        "text": "#ebdbb2", "subtext": "#a89984", "disabled": "#6c7086",
        "accent": "#d79921", "accent2": "#689d6a",
        "red": "#cc241d", "yellow": "#d79921", "green": "#98971a",
        "sidebar_active": "#665c54",
    },
}


# ── User config + custom themes ───────────────────────────────────
CONFIG_PATH = HERE / ".virgo_desktop_config.json"
USER_THEMES_PATH = HERE / ".virgo_themes.json"

# Colour keys exposed in the in-app theme editor.
EDITABLE_THEME_KEYS = [
    ("bg", "Background"), ("surface", "Surface"), ("crust", "Crust"),
    ("border", "Border"), ("border2", "Border 2"), ("text", "Text"),
    ("subtext", "Subtext"), ("disabled", "Disabled"), ("accent", "Accent"),
    ("accent2", "Accent 2"), ("red", "Red"), ("yellow", "Yellow"),
    ("green", "Green"), ("sidebar_active", "Sidebar active"),
]


def load_user_themes() -> dict[str, dict[str, str]]:
    """Load user-saved custom themes from .virgo_themes.json."""
    if not USER_THEMES_PATH.exists():
        return {}
    try:
        data = json.loads(USER_THEMES_PATH.read_text())
        return {k: v for k, v in data.items() if isinstance(v, dict) and "bg" in v}
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
    QMainWindow, QWidget {
        background-color: @bg@;
        color: @text@;
        font-family: 'Segoe UI', 'SF Pro', sans-serif;
        font-size: 13px;
    }
    #sidebar {
        background-color: @surface@;
        border-right: 1px solid @border@;
    }
    #sidebarTitle {
        color: @accent@;
        padding: 0 4px;
    }
    #sidebarHeader {
        background-color: @surface@;
        border-bottom: 1px solid @border@;
        border-radius: 8px;
        padding: 6px;
    }
    #sidebarAvatar {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 @accent@, stop:1 @accent2@);
        color: @bg@;
        border-radius: 10px;
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
    }
    #sidebar QPushButton {
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 8px 12px;
        text-align: left;
        color: @subtext@;
        font-size: 13px;
    }
    #sidebar QPushButton:hover {
        background: @border@;
        color: @text@;
    }
    #sidebar QPushButton:checked {
        background: @sidebar_active@;
        color: @accent@;
        font-weight: bold;
    }
    #quitBtn {
        color: @red@ !important;
    }
    #quitBtn:hover {
        background: @red@22 !important;
    }
    #stopBtn {
        color: @red@ !important;
        border-color: @red@;
    }
    #stopBtn:hover {
        background: @red@22 !important;
    }
    #pageArea {
        background-color: @bg@;
    }
    #pageTitle {
        color: @text@;
        font-size: 20px;
        padding-bottom: 2px;
    }
    #metaLabel {
        color: @disabled@;
        font-size: 11px;
    }
    #statusBar {
        background: @surface@;
        color: @subtext@;
        border-top: 1px solid @border@;
        padding: 3px 10px;
        font-size: 12px;
    }
    QPushButton {
        background: @border@;
        border: 1px solid @border2@;
        border-radius: 6px;
        padding: 6px 16px;
        color: @text@;
    }
    QPushButton:hover {
        background: @border2@;
    }
    QPushButton#sendBtn {
        background: @accent@;
        color: @bg@;
        font-weight: bold;
        border: none;
        padding: 6px 18px;
    }
    QPushButton#sendBtn:hover {
        background: @accent@bb;
    }
    QPushButton:pressed {
        background: @sidebar_active@;
    }
    QTextEdit, QPlainTextEdit {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 6px;
        color: @text@;
        padding: 8px;
        font-family: 'Cascadia Code', 'Fira Code', monospace;
        font-size: 12px;
    }
    QListWidget {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 6px;
        color: @text@;
    }
    QListWidget::item:hover {
        background: @border@;
    }
    QListWidget::item:selected {
        background: @sidebar_active@;
        color: @accent@;
    }
    QLineEdit {
        background: @surface@;
        border: 1px solid @border@;
        border-radius: 6px;
        padding: 6px 10px;
        color: @text@;
    }
    QProgressBar {
        background: @border@;
        border: none;
        border-radius: 4px;
        height: 6px;
        text-align: center;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 @accent@, stop:1 @accent2@);
        border-radius: 4px;
    }
    QGroupBox {
        background-color: @surface@;
        border: 1px solid @border@;
        border-radius: 10px;
        margin-top: 18px;
        padding: 18px 14px 14px;
        font-weight: bold;
        color: @accent@;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }
    QComboBox {
        background: @border@;
        border: 1px solid @border2@;
        border-radius: 6px;
        padding: 6px 10px;
        color: @text@;
        min-width: 100px;
    }
    QComboBox:hover {
        border-color: @sidebar_active@;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid @subtext@;
        margin-right: 6px;
    }
    QComboBox QAbstractItemView {
        background: @surface@;
        border: 1px solid @border2@;
        border-radius: 4px;
        color: @text@;
        selection-background-color: @border2@;
        outline: none;
    }
    QTabWidget::pane { border: none; background: transparent; }
    QTabBar::tab {
        background: @surface@;
        border: 1px solid @border@;
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 6px 16px;
        margin-right: 2px;
        color: @disabled@;
    }
    QTabBar::tab:selected {
        background: @border@;
        color: @accent@;
        font-weight: bold;
    }
    QTabBar::tab:hover:!selected { color: @subtext@; }
    QScrollBar:vertical {
        background: @bg@; width: 10px; margin: 0; border: none;
    }
    QScrollBar::handle:vertical {
        background: @border2@; border-radius: 5px; min-height: 30px;
    }
    QScrollBar::handle:vertical:hover { background: @sidebar_active@; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0; border: none;
    }
    QScrollBar:horizontal {
        background: @bg@; height: 10px; border: none;
    }
    QScrollBar::handle:horizontal {
        background: @border2@; border-radius: 5px; min-width: 30px;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0; border: none;
    }
    QSplitter::handle {
        background: @border@;
    }
    QSplitter::handle:horizontal { width: 2px; }
    QSplitter::handle:vertical { height: 2px; }
    QSlider::groove:horizontal {
        background: @border@; height: 6px; border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: @accent@; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }
    QSlider::handle:horizontal:hover { background: @accent@bb; }
    QCheckBox { color: @text@; spacing: 6px; }
    QCheckBox::indicator {
        width: 16px; height: 16px;
        border: 1px solid @border2@; border-radius: 4px;
        background: @surface@;
    }
    QCheckBox::indicator:checked {
        background: @accent@; border-color: @accent@;
    }
    QToolTip {
        background: @border@; border: 1px solid @border2@;
        border-radius: 4px; color: @text@;
        padding: 4px 8px; font-size: 12px;
    }
    """)
    for key, val in t.items():
        raw = raw.replace(f"@{key}@", val)
    return raw


# ── Robust launch: find a Python that actually has PyQt6 ──────────
def _has_pyqt6(python: str) -> bool:
    try:
        r = subprocess.run(
            [python, "-c", "import PyQt6"],
            capture_output=True, text=True, timeout=20,
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
            "python3.14", "python3.13", "python3.12", "python3.11",
            "/usr/bin/python3", "/usr/local/bin/python3",
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

from PyQt6.QtCore import Qt, QTimer, qInstallMessageHandler, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QFont, QIcon, QPalette, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QSystemTrayIcon, QMenu, QStatusBar, QVBoxLayout, QWidget,
)

# ── Import virgo modules ─────────────────────────────────────────────
from _console import icon
from _log import log

from virgo_desktop_pages import (
    AboutPage,
    AlertsPage,
    ChatPage,
    DiagnosticsPage,
    LogsPage,
    NetworkPage,
    PipelinePage,
    PluginsPage,
    ScaffoldPage,
    SessionPage,
    SettingsPage,
    SwarmPage,
)

# ── Constants ────────────────────────────────────────────────────────

APP_NAME = "Virgo Desktop"
APP_VERSION = "0.2.0"
WIDTH = 1100
HEIGHT = 720

# Emoji icons for the desktop GUI. PyQt6 renders these on Windows fine;
# the terminal-safe ASCII fallbacks in _console.icon() don't apply here.
DESKTOP_ICONS = {
    "pipeline": "\U0001F680",      # 🚀
    "chat": "\U0001F4AC",          # 💬
    "network": "\U0001F310",       # 🌐
    "diagnostics": "\U0001F527",   # 🔧
    "alerts": "\U0001F514",        # 🔔
    "scaffold": "\U0001F4E6",      # 📦
    "sessions": "\U0001F4DC",      # 📜
    "swarm": "\u26A1",             # ⚡
    "logs": "\U0001F4DD",          # 📝
    "plugins": "\U0001F9E9",       # 🧩
    "settings": "\u2699",          # ⚙
    "about": "\u2139",             # ℹ
}

SIDEBAR_ITEMS = [
    ("pipeline", "Pipeline", DESKTOP_ICONS["pipeline"]),
    ("chat", "Chat", DESKTOP_ICONS["chat"]),
    ("network", "Network", DESKTOP_ICONS["network"]),
    ("diagnostics", "Diagnostics", DESKTOP_ICONS["diagnostics"]),
    ("alerts", "Alerts", DESKTOP_ICONS["alerts"]),
    ("scaffold", "Scaffolds", DESKTOP_ICONS["scaffold"]),
    ("sessions", "Sessions", DESKTOP_ICONS["sessions"]),
    ("swarm", "Swarm", DESKTOP_ICONS["swarm"]),
    ("logs", "Logs", DESKTOP_ICONS["logs"]),
    ("plugins", "Plugins", DESKTOP_ICONS["plugins"]),
    ("settings", "Settings", DESKTOP_ICONS["settings"]),
    ("about", "About", DESKTOP_ICONS["about"]),
]


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
        default_order = [pid for pid, _l, _e in SIDEBAR_ITEMS]
        saved_order = self._config.get("sidebar_order", default_order)
        self.nav_order = [p for p in saved_order if p in default_order]
        for p in default_order:
            if p not in self.nav_order:
                self.nav_order.append(p)
        self._nav_items: dict[str, QListWidgetItem] = {}
        self._popped: dict[str, "PopOutWindow"] = {}
        self.current_page = ""

        # ── Central widget + resizable splitter ──────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        root.addWidget(self.splitter, 1)

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
        avatar = QLabel("\U0001F6F8")  # 🛸
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

        self.nav_list = NavList()
        self.nav_list.setObjectName("navList")
        self.nav_list.currentItemChanged.connect(
            lambda cur, _prev: self._on_nav_selected(cur)
        )
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

        self._register(PipelinePage(), "pipeline")
        self._register(ChatPage(), "chat")
        self._register(NetworkPage(), "network")
        self._register(DiagnosticsPage(), "diagnostics")
        self._register(AlertsPage(), "alerts")
        self._register(ScaffoldPage(), "scaffold")
        self._register(SessionPage(), "sessions")
        self._register(SwarmPage(), "swarm")
        self._register(LogsPage(), "logs")
        self._register(PluginsPage(), "plugins")
        self._register(SettingsPage(), "settings")
        self._register(AboutPage(), "about")

        self.splitter.addWidget(self.stack)

        # ── Sidebar items ────────────────────────────────────────
        self._init_sidebar_items()
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        # ── Status bar ───────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("statusBar")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Virgo Desktop · checking LLM…")

        # ── System tray ──────────────────────────────────────────
        self._setup_tray()

        # ── Shortcuts ────────────────────────────────────────────
        self._setup_shortcuts()

        # ── Navigate to default ──────────────────────────────────
        self._navigate("pipeline")

        # ── Theme (honours auto dark/light) ──────────────────────
        self.refresh_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self.refresh_theme)
        except Exception:
            pass

        # ── Restore saved geometry + sidebar width ──────────────
        self._restore_geom()
        self._apply_sidebar_collapsed()

    # ────────────────────────────────────────────────────────────────

    def _register(self, page: QWidget, name: str) -> None:
        self.pages[name] = page
        self.stack.addWidget(page)

    # ── Navigation ────────────────────────────────────────────────
    def _init_sidebar_items(self) -> None:
        """(Re)build the nav list from self.nav_order."""
        self.nav_list.clear()
        self._nav_items.clear()
        meta = {pid: (label, emoji) for pid, label, emoji in SIDEBAR_ITEMS}
        for pid in self.nav_order:
            label, emoji = meta.get(pid, (pid, "•"))
            text = emoji if self._sidebar_collapsed else f"{emoji}  {label}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setSizeHint(QSize(0, 42))
            self.nav_list.addItem(item)
            self._nav_items[pid] = item

    def _on_nav_selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        self._navigate(pid)

    def _on_nav_reordered(self) -> None:
        self.nav_order = [
            self.nav_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.nav_list.count())
        ]
        self._config["sidebar_order"] = self.nav_order
        self._save_config()

    def _nav_context_menu(self, pos) -> None:
        item = self.nav_list.itemAt(pos)
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pop = menu.addAction("\U0001F5D7  Open in new window")
        if pop is not None:
            pop.triggered.connect(lambda checked=False, p=pid: self._pop_out(p))
        menu.exec(self.nav_list.mapToGlobal(pos))

    def _navigate(self, page_id: str) -> None:
        if page_id == self.current_page:
            return
        item = self._nav_items.get(page_id)
        if item is not None:
            self.nav_list.setCurrentItem(item)
        self.stack.setCurrentWidget(self.pages[page_id])
        self.current_page = page_id
        page = self.pages[page_id]
        if hasattr(page, "on_activate"):
            page.on_activate()

    def set_status(self, text: str) -> None:
        """Update the bottom status bar text."""
        self.status_bar.showMessage(text)

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
            label, emoji = next(
                ((l, e) for p, l, e in SIDEBAR_ITEMS if p == pid), (pid, "•")
            )
            item.setText(emoji if self._sidebar_collapsed else f"{emoji}  {label}")
        self.sidebar_title.setVisible(not self._sidebar_collapsed)
        self.quit_btn.setText(
            "\U0001F6F8" if self._sidebar_collapsed else f"{icon('exit')}  Quit"
        )

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

        # Ctrl+P quick page switcher
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._show_quick_switcher)
        # Ctrl+B toggle sidebar collapse
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._toggle_sidebar)
        # ? shortcuts overlay
        QShortcut(QKeySequence("?"), self).activated.connect(self._show_shortcuts_overlay)

    def _setup_tray(self) -> None:
        """Create system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._real_close = False
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(APP_NAME)
        # Use the branded mark when available, otherwise a solid fallback
        import os
        _tray_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if getattr(sys, "frozen", False) and not os.path.exists(_tray_icon):
            _tray_icon = os.path.join(getattr(sys, "_MEIPASS", ""), "logo.ico")
        if os.path.exists(_tray_icon):
            self.tray.setIcon(QIcon(_tray_icon))
        else:
            from PyQt6.QtGui import QPixmap, QColor
            pm = QPixmap(16, 16)
            pm.fill(QColor("#00b4d8"))
            self.tray.setIcon(QIcon(pm))

        menu = QMenu()
        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(self.showNormal)
        chat_action = menu.addAction("Open Chat")
        chat_action.triggered.connect(
            lambda: (self.showNormal(), self._navigate("chat"))
        )
        pipeline_action = menu.addAction("Run Pipeline")
        pipeline_action.triggered.connect(
            lambda: (self.showNormal(), self._navigate("pipeline"))
        )
        swarm_action = menu.addAction("Launch Swarm")
        swarm_action.triggered.connect(
            lambda: (self.showNormal(), self._navigate("swarm"))
        )
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _quit(self) -> None:
        self._real_close = True
        self.close()

    def notify(self, title: str, message: str) -> None:
        """Show a system tray notification (falls back to the status bar)."""
        if getattr(self, "tray", None) and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, 4000
            )
        else:
            self.set_status(f"{title}: {message}")

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
        t = self.themes.get(getattr(self, "_active_theme", self._theme_name),
                            self.themes["mocha"])
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

        entries = [(pid, label, emoji) for pid, label, emoji in SIDEBAR_ITEMS]

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
        pop_btn = QPushButton("\U0001F5D7  Pop out window")
        pop_btn.clicked.connect(_pop)
        btn_row.addWidget(go_btn)
        btn_row.addWidget(pop_btn)
        layout.addLayout(btn_row)
        _refresh("")
        dlg.exec()

    def _show_shortcuts_overlay(self) -> None:
        """Show a dialog listing all keyboard shortcuts."""
        t = self.themes.get(getattr(self, "_active_theme", self._theme_name),
                            self.themes["mocha"])
        lines = [
            ("Key", "Action"),
            ("", ""),
            ("1 – 9, 0", "Navigate sidebar pages (in order)"),
            ("Ctrl+P", "Quick page switcher (fuzzy)"),
            ("Ctrl+B", "Collapse / expand sidebar"),
            ("?", "Show this help overlay"),
            ("Escape", "Close dialogs"),
            ("", ""),
            ("Drag sidebar items", "Reorder pages"),
            ("Drag sidebar edge", "Resize sidebar"),
            ("Right-click page", "Pop out page to a new window"),
        ]
        html = "<table style='width:100%; border-collapse:collapse;'>"
        for key, action in lines:
            if key == "":
                html += ("<tr><td colspan='2' style='border-bottom:1px solid "
                         + t["border"] + "'></td></tr>")
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
                self.resize(d.get("w", WIDTH), d.get("h", HEIGHT))
                if d.get("x") is not None:
                    self.move(d["x"], d["y"])
        except Exception:
            pass

    def _save_geom(self) -> None:
        try:
            import json
            p = Path(__file__).parent / ".virgo_desktop_geom.json"
            geo = self.geometry()
            p.write_text(json.dumps({
                "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()
            }))
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
        ss = _build_stylesheet(t)
        if getattr(self, "_custom_css", ""):
            ss += "\n" + self._custom_css
        self.setStyleSheet(ss)

    def refresh_theme(self) -> None:
        """Resolve the active theme from the current mode and re-apply."""
        mode = getattr(self, "_theme_mode", "system")
        if mode == "system":
            try:
                scheme = QApplication.styleHints().colorScheme()
                self._active_theme = (
                    "latte" if scheme == Qt.ColorScheme.Light else "mocha"
                )
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


class PopOutWindow(QMainWindow):
    """A detached window that hosts one of the main pages."""

    def __init__(self, page_id: str, page: QWidget, parent: "VirgoDesktopWindow") -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.page = page
        self.main = parent
        label = next((l for pid, l, _e in SIDEBAR_ITEMS if pid == page_id), page_id)
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
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Virgo")
    window = VirgoDesktopWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

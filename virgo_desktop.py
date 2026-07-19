"""
Virgo Desktop — polished PyQt6 GUI for virgo-agent.

Usage:
    virgo-desktop
    python -m virgo_desktop
"""

from __future__ import annotations

import os
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

from PyQt6.QtCore import Qt, QTimer, qInstallMessageHandler
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


class VirgoDesktopWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(WIDTH, HEIGHT)

        # ── Central widget ─────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Sidebar ────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(2)

        # ── Branded header (avatar + title) ───────────────────
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
        title_font = QFont("Segoe UI", 15, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setObjectName("sidebarTitle")
        header_layout.addWidget(title)
        sidebar_layout.addWidget(header)
        sidebar_layout.addSpacing(12)

        self.nav_buttons: dict[str, SidebarButton] = {}
        self.current_page = ""

        for page_id, label, emoji in SIDEBAR_ITEMS:
            btn = SidebarButton(label, emoji)
            btn.clicked.connect(lambda checked=False, pid=page_id: self._navigate(pid))
            sidebar_layout.addWidget(btn)
            self.nav_buttons[page_id] = btn

        sidebar_layout.addStretch()

        quit_btn = QPushButton(f"{icon('exit')}  Quit")
        quit_btn.setObjectName("quitBtn")
        quit_btn.clicked.connect(self.close)
        sidebar_layout.addWidget(quit_btn)

        layout.addWidget(sidebar)

        # ── Page area ──────────────────────────────────────────────
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

        layout.addWidget(self.stack, 1)

        # ── Status bar ───────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("statusBar")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Virgo Desktop · checking LLM…")

        # ── System tray ───────────────────────────────────────────
        self._setup_tray()

        # ── Number-key navigation ─────────────────────────────────
        self._setup_shortcuts()

        # ── Navigate to default ───────────────────────────────────
        self._navigate("pipeline")

        # ── Stylesheet ────────────────────────────────────────────
        self._theme_name = "mocha"
        try:
            env_path = HERE / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("VIRGO_THEME="):
                        theme = line.split("=", 1)[1].strip()
                        if theme in THEMES:
                            self._theme_name = theme
        except Exception:
            pass
        self._apply_style()

        # ── Restore saved window geometry ────────────────────────
        self._restore_geom()

    # ────────────────────────────────────────────────────────────────

    def _register(self, page: QWidget, name: str) -> None:
        self.pages[name] = page
        self.stack.addWidget(page)

    def _navigate(self, page_id: str) -> None:
        if page_id == self.current_page:
            return
        for pid, btn in self.nav_buttons.items():
            btn.setChecked(pid == page_id)
        self.stack.setCurrentWidget(self.pages[page_id])
        self.current_page = page_id
        page = self.pages[page_id]
        if hasattr(page, "on_activate"):
            page.on_activate()

    def set_status(self, text: str) -> None:
        """Update the bottom status bar text."""
        self.status_bar.showMessage(text)

    def _setup_shortcuts(self) -> None:
        """Number keys 1-9 / 0 jump to sidebar pages."""
        for idx, (page_id, _label, _emoji) in enumerate(SIDEBAR_ITEMS):
            if idx < 9:
                key = str(idx + 1)
            elif idx == 9:
                key = "0"
            else:
                continue  # 11th+ page has no number key
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(
                lambda pid=page_id: self._navigate(pid)
            )

    def _setup_tray(self) -> None:
        """Create system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._real_close = False
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(APP_NAME)
        # Create a simple pixmap icon (16x16)
        pixmap = self.palette().color(QPalette.ColorRole.Window)
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

    def _apply_style(self) -> None:
        """Build and apply stylesheet from the active theme."""
        name = getattr(self, "_theme_name", "mocha")
        t = THEMES.get(name, THEMES["mocha"])
        self.setStyleSheet(_build_stylesheet(t))

    def switch_theme(self, name: str) -> None:
        """Switch the app to a different colour theme."""
        if name not in THEMES:
            return
        self._theme_name = name
        self._apply_style()
        # Persist to .env
        try:
            env_path = HERE / ".env"
            lines = env_path.read_text().splitlines() if env_path.exists() else []
            found = False
            for i, line in enumerate(lines):
                if line.startswith("VIRGO_THEME="):
                    lines[i] = f"VIRGO_THEME={name}"
                    found = True
                    break
            if not found:
                lines.append(f"VIRGO_THEME={name}")
            env_path.write_text("\n".join(lines) + "\n")
        except Exception:
            pass


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

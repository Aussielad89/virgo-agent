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
        """Apply dark theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', 'SF Pro', sans-serif;
                font-size: 13px;
            }
            #sidebar {
                background-color: #181825;
                border-right: 1px solid #313244;
            }
            #sidebarTitle {
                color: #89b4fa;
                padding: 0 4px;
            }
            #sidebarHeader {
                background-color: #181825;
                border-bottom: 1px solid #313244;
                border-radius: 8px;
                padding: 6px;
            }
            #sidebarAvatar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #89b4fa, stop:1 #a6e3a1);
                color: #1e1e2e;
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
                color: #a6adc8;
                font-size: 13px;
            }
            #sidebar QPushButton:hover {
                background: #313244;
                color: #cdd6f4;
            }
            #sidebar QPushButton:checked {
                background: #45475a;
                color: #89b4fa;
                font-weight: bold;
            }
            #quitBtn {
                color: #f38ba8 !important;
            }
            #quitBtn:hover {
                background: #45232e !important;
            }
            #stopBtn {
                color: #f38ba8 !important;
                border-color: #f38ba8;
            }
            #stopBtn:hover {
                background: #45232e !important;
            }
            #pageArea {
                background-color: #1e1e2e;
            }
            #pageTitle {
                color: #cdd6f4;
                font-size: 20px;
                padding-bottom: 2px;
            }
            #metaLabel {
                color: #6c7086;
                font-size: 11px;
            }
            #statusBar {
                background: #181825;
                color: #a6adc8;
                border-top: 1px solid #313244;
                padding: 3px 10px;
                font-size: 12px;
            }
            QPushButton {
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 16px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background: #45475a;
            }
            QPushButton:pressed {
                background: #585b70;
            }
            QTextEdit, QPlainTextEdit {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                color: #cdd6f4;
                padding: 8px;
                font-family: 'Cascadia Code', 'Fira Code', monospace;
                font-size: 12px;
            }
            QListWidget {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                color: #cdd6f4;
            }
            QListWidget::item:hover {
                background: #313244;
            }
            QListWidget::item:selected {
                background: #45475a;
                color: #89b4fa;
            }
            QLineEdit {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 6px 10px;
                color: #cdd6f4;
            }
            QProgressBar {
                background: #313244;
                border: none;
                border-radius: 4px;
                height: 6px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #89b4fa, stop:1 #a6e3a1);
                border-radius: 4px;
            }
            QGroupBox {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 10px;
                margin-top: 18px;
                padding: 18px 14px 14px;
                font-weight: bold;
                color: #89b4fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)


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

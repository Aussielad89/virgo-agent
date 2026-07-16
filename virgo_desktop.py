"""
Virgo Desktop — polished PyQt6 GUI for virgo-agent.

Usage:
    virgo-desktop
    python -m virgo_desktop
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QSystemTrayIcon, QMenu, QVBoxLayout, QWidget,
)

# ── Import virgo modules ─────────────────────────────────────────────
from _console import icon
from _log import log

# ── Pages ────────────────────────────────────────────────────────────
from virgo_desktop_pages import (
    AboutPage,
    AlertsPage,
    ChatPage,
    DiagnosticsPage,
    LogsPage,
    NetworkPage,
    PipelinePage,
    ScaffoldPage,
    SettingsPage,
)

# ── Constants ────────────────────────────────────────────────────────

APP_NAME = "Virgo Desktop"
APP_VERSION = "0.1.0"
WIDTH = 1100
HEIGHT = 720

SIDEBAR_ITEMS = [
    ("pipeline", "Pipeline", "run"),
    ("chat", "Chat", "chat"),
    ("network", "Network", "network"),
    ("diagnostics", "Diagnostics", "diagnostics"),
    ("alerts", "Alerts", "alert"),
    ("scaffold", "Scaffolds", "scaffold"),
    ("logs", "Logs", "log"),
    ("settings", "Settings", "settings"),
    ("about", "About", "info"),
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

        title = QLabel(f"{icon('virgo')}  Virgo")
        title_font = QFont("Segoe UI", 14, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(title)
        sidebar_layout.addSpacing(12)

        self.nav_buttons: dict[str, SidebarButton] = {}
        self.current_page = ""

        for page_id, label, ico in SIDEBAR_ITEMS:
            btn = SidebarButton(label, icon(ico) if icon(ico) != ico else "")
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
        self._register(LogsPage(), "logs")
        self._register(SettingsPage(), "settings")
        self._register(AboutPage(), "about")

        layout.addWidget(self.stack, 1)

        # ── System tray ───────────────────────────────────────────
        self._setup_tray()

        # ── Navigate to default ───────────────────────────────────
        self._navigate("pipeline")

        # ── Stylesheet ────────────────────────────────────────────
        self._apply_style()

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

    def _setup_tray(self) -> None:
        """Create system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
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
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        self.tray.setContextMenu(menu)
        self.tray.show()

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
                padding: 4px 8px;
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
            #pageArea {
                background-color: #1e1e2e;
            }
            QLabel {
                color: #cdd6f4;
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
                border: 1px solid #313244;
                border-radius: 8px;
                margin-top: 16px;
                padding: 16px 12px 12px;
                font-weight: bold;
                color: #89b4fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Virgo")
    window = VirgoDesktopWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

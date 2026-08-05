"""Font Picker page for Virgo Desktop.

Lets the user choose the global UI font family + base size and apply it live.
Reuses the existing theming hook (VirgoDesktopWindow.set_ui_font), so it slots
into the same config/stylesheet pipeline as the theme system. No new
persistence format — settings land in the same _config the app already saves.
"""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from virgo_desktop_pages import PageWidget

# Common, reliably-present Windows fonts (plus the app default).
_DEFAULT_FAMILIES = [
    "'Segoe UI', 'SF Pro', sans-serif",
    "Consolas, 'Cascadia Code', monospace",
    "Arial, sans-serif",
    "Courier New, monospace",
    "Georgia, serif",
    "Tahoma, sans-serif",
    "Verdana, sans-serif",
    "Times New Roman, serif",
]

# Pretty labels → CSS font-family string
_FONT_MAP = {
    "Segoe UI (default)": "'Segoe UI', 'SF Pro', sans-serif",
    "Consolas (mono)": "Consolas, 'Cascadia Code', monospace",
    "Arial": "Arial, sans-serif",
    "Courier New (mono)": "Courier New, monospace",
    "Georgia (serif)": "Georgia, serif",
    "Tahoma": "Tahoma, sans-serif",
    "Verdana": "Verdana, sans-serif",
    "Times New Roman (serif)": "Times New Roman, serif",
}


class FontPickerPage(PageWidget):
    """Pick the global UI font family and size; apply live."""

    def __init__(self) -> None:
        super().__init__("Font Picker", "Global UI typeface & size (live)")

        # ── Family ──
        fbox = QGroupBox("Font family")
        fl = QVBoxLayout(fbox)
        self.family_combo = QComboBox()
        self.family_combo.addItems(list(_FONT_MAP.keys()))
        self.family_combo.setCurrentIndex(0)
        fl.addWidget(self.family_combo)

        self.preview = QLabel("The quick brown fox jumps over the lazy dog — 1234567890")
        self.preview.setStyleSheet("padding: 8px; border: 1px solid #313244; border-radius: 6px;")
        fl.addWidget(self.preview)
        self._add(fbox)

        # ── Size ──
        sbox = QGroupBox("Base size")
        sl = QVBoxLayout(sbox)
        self.slider = QSlider()
        try:
            from PyQt6.QtCore import Qt
            self.slider.setOrientation(Qt.Orientation.Horizontal)
        except Exception:  # noqa: BLE001
            pass
        self.slider.setMinimum(9)
        self.slider.setMaximum(28)
        self.slider.setValue(15)
        self.size_label = QLabel("15 px")
        self.slider.valueChanged.connect(lambda v: self.size_label.setText(f"{v} px"))
        srow = QHBoxLayout()
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.size_label)
        sl.addLayout(srow)
        self._add(sbox)

        # ── Actions ──
        arow = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._apply)
        self.reset_btn = QPushButton("Reset to default")
        self.reset_btn.clicked.connect(self._reset)
        arow.addWidget(self.apply_btn)
        arow.addWidget(self.reset_btn)
        arow.addStretch()
        self.content.addLayout(arow)

        # Live preview update
        self.family_combo.currentTextChanged.connect(self._update_preview)
        self.slider.valueChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self) -> None:
        fam = _FONT_MAP[self.family_combo.currentText()]
        size = self.slider.value()
        # Strip quotes for QFont (CSS form is for the stylesheet).
        qfam = fam.split(",")[0].strip().strip("'").strip('"')
        self.preview.setFont(QFont(qfam, size))

    def _window(self):
        # Find the main window via the Qt object tree.
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.__class__.__name__ == "VirgoDesktopWindow":
                return w
        return None

    def _chat_page(self):
        win = self._window()
        if win is None:
            return None
        return win.pages.get("chat")

    def _apply(self) -> None:
        win = self._window()
        fam = _FONT_MAP[self.family_combo.currentText()]
        size = self.slider.value()
        if win is not None and hasattr(win, "set_ui_font"):
            win.set_ui_font(fam, size)
            # Also drive the chat message area so AI replies are readable.
            chat = self._chat_page()
            if chat is not None and hasattr(chat, "set_chat_font"):
                chat.set_chat_font(fam, size)
            self.preview.setText(f"Applied: {self.family_combo.currentText()} @ {size}px (UI + chat)")
        else:
            self.preview.setText("⚠ Could not reach main window to apply")

    def _reset(self) -> None:
        self.family_combo.setCurrentIndex(0)
        self.slider.setValue(15)
        self._apply()

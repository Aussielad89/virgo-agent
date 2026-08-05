"""Virgo Desktop pages — settings (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

def _live_ollama_models() -> list[str]:
    """Best-effort fetch of models currently pulled into Ollama."""
    import urllib.request

    try:
        raw = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3).read()
        data = json.loads(raw)
        return sorted(m["name"] for m in data.get("models", []))
    except Exception:
        return []


class SettingsPage(PageWidget):
    """Virgo environment configuration."""

    def __init__(self) -> None:
        super().__init__(
            "Settings",
            "Environment variables and configuration.",
        )

       # --- Wrap self.content in a QScrollArea ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        scroll_layout = QVBoxLayout(container)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(container)
        self.content.addWidget(scroll)

        self.content = scroll_layout
        # ------------------------------------------
        # ------------------------------------------

        self._fields: dict[str, QWidget] = {}
        self._model_keys = {"MODEL_PLANNER", "MODEL_GENERATOR", "MODEL_FIXER"}

        # Merge preferred + live Ollama models for the dropdowns.
        live = _live_ollama_models()
        model_choices = []
        for m in PREFERRED_MODELS + live:
            if m not in model_choices:
                model_choices.append(m)
        if not model_choices:
            model_choices = ["ornith:latest"]

        form = self._section("Environment")
        env_vars = {
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_API_KEY": "«redacted:sk-…»",
            "MODEL_PLANNER": "phi4-mini-reasoning:3.8b",
            "MODEL_GENERATOR": "qwen3.5:2b",
            "MODEL_FIXER": "ornith:latest",
            "LLM_TIMEOUT": "300",
            "VIRGO_LOG_LEVEL": "INFO",
            "WEBHOOK_URL": "http://localhost:8080/webhook",
        }

        env_path = HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()

        self._defaults = dict(env_vars)

        for key, val in env_vars.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(key), 1)
            if key in self._model_keys:
                combo = QComboBox()
                combo.setMinimumWidth(220)
                for choice in model_choices:
                    combo.addItem(choice)
                if val in model_choices:
                    combo.setCurrentText(val)
                else:
                    combo.addItem(val)
                    combo.setCurrentText(val)
                row.addWidget(combo, 2)
                form.layout().addLayout(row)  # type: ignore
                self._fields[key] = combo
            else:
                edit = QLineEdit(val)
                row.addWidget(edit, 2)
                form.layout().addLayout(row)  # type: ignore
                self._fields[key] = edit

        # ── Appearance: theme mode + theme ──────────────────────────────
        from virgo_desktop import EDITABLE_THEME_KEYS

        theme_section = self._section("Appearance")

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Theme mode:"))
        self.mode_combo = QComboBox()
        for mode, label in (
            ("system", "Auto (follow system)"),
            ("dark", "Dark"),
            ("light", "Light"),
            ("manual", "Manual pick"),
        ):
            self.mode_combo.addItem(label, mode)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        mode_row.addWidget(self.mode_combo, 1)
        theme_section.layout().addLayout(mode_row)  # type: ignore

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.currentIndexChanged.connect(self._on_theme_change)
        theme_row.addWidget(self.theme_combo, 1)
        theme_section.layout().addLayout(theme_row)  # type: ignore

        # ── Font family + size ───────────────────────────────────────
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font:"))
        self.font_combo = QComboBox()
        for fam in (
            "'Segoe UI', 'SF Pro', sans-serif",
            "Arial, sans-serif",
            "'Consolas', 'Courier New', monospace",
            "'Cascadia Code', monospace",
            "'Inter', sans-serif",
            "Tahoma, sans-serif",
            "Verdana, sans-serif",
        ):
            self.font_combo.addItem(fam)
        font_row.addWidget(self.font_combo, 2)
        font_row.addWidget(QLabel("Size:"))
        self.size_combo = QComboBox()
        for s in (11, 12, 13, 14, 15, 16, 18, 20, 22):
            self.size_combo.addItem(f"{s}px", s)
        font_row.addWidget(self.size_combo, 1)
        apply_font = QPushButton(f"{icon('ok')}  Apply font")
        apply_font.clicked.connect(self._apply_font)
        font_row.addWidget(apply_font)
        theme_section.layout().addLayout(font_row)  # type: ignore

        # ── Custom theme editor ─────────────────────────────────────────
        editor = self._section("Custom theme editor")
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.theme_name_edit = QLineEdit()
        self.theme_name_edit.setPlaceholderText("My theme")
        name_row.addWidget(self.theme_name_edit, 1)
        editor.layout().addLayout(name_row)  # type: ignore

        self._color_btns: dict[str, QPushButton] = {}
        self._editor_colors: dict[str, str] = {}
        grid = QGridLayout()
        for i, (key, nice) in enumerate(EDITABLE_THEME_KEYS):
            lbl = QLabel(nice)
            btn = QPushButton()
            btn.setFixedSize(34, 20)
            btn.clicked.connect(lambda _checked=False, k=key: self._pick_color(k))
            row, col = divmod(i, 2)
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(btn, row, col * 2 + 1)
            self._color_btns[key] = btn
        editor.layout().addLayout(grid)  # type: ignore

        save_theme_btn = QPushButton(f"{icon('save')}  Save as new theme")
        save_theme_btn.clicked.connect(self._save_custom_theme)
        editor.layout().addWidget(save_theme_btn)  # type: ignore

        # ── Custom CSS injection ─────────────────────────────────────────
        css_section = self._section("Custom CSS (advanced)")
        self.css_edit = QPlainTextEdit()
        self.css_edit.setPlaceholderText(
            "Paste Qt stylesheet overrides, e.g.\nQPushButton { border-radius: 12px; }"
        )
        self.css_edit.setMaximumHeight(120)
        css_section.layout().addWidget(self.css_edit)  # type: ignore
        css_row = QHBoxLayout()
        apply_css = QPushButton(f"{icon('ok')}  Apply CSS")
        apply_css.clicked.connect(self._apply_css)
        reset_css = QPushButton(f"{icon('refresh')}  Reset CSS")
        reset_css.clicked.connect(self._reset_css)
        css_row.addWidget(apply_css)
        css_row.addWidget(reset_css)
        css_section.layout().addLayout(css_row)  # type: ignore

        # ── Raw .env editor ──────────────────────────────────────────────
        env_section = self._section(".env editor (raw)")
        self.env_edit = QPlainTextEdit()
        self.env_edit.setPlaceholderText("KEY=value per line…")
        self.env_edit.setMaximumHeight(140)
        env_path = HERE / ".env"
        if env_path.exists():
            self.env_edit.setPlainText(env_path.read_text(encoding="utf-8", errors="replace"))
        env_section.layout().addWidget(self.env_edit)  # type: ignore
        env_row = QHBoxLayout()
        save_env = QPushButton(f"{icon('save')}  Save .env")
        save_env.clicked.connect(self._save_env)
        env_row.addWidget(save_env)
        env_section.layout().addLayout(env_row)  # type: ignore

        # ── Backup & Restore ──────────────────────────────────────────
        backup_section = self._section("Backup & Restore")
        backup_row = QHBoxLayout()
        backup_btn = QPushButton("💾  Backup now")
        backup_btn.clicked.connect(self._do_backup)
        restore_btn = QPushButton("♻  Restore from file…")
        restore_btn.clicked.connect(self._do_restore)
        backup_row.addWidget(backup_btn)
        backup_row.addWidget(restore_btn)
        backup_section.layout().addLayout(backup_row)  # type: ignore
        self.backup_status = QLabel("")
        self.backup_status.setWordWrap(True)
        backup_section.layout().addWidget(self.backup_status)  # type: ignore

        btn_row = QHBoxLayout()
        save_btn = QPushButton(f"{icon('save')}  Save")
        save_btn.clicked.connect(self._save)
        test_btn = QPushButton(f"{icon('web')}  Test connection")
        test_btn.clicked.connect(self._test_connection)
        reset_btn = QPushButton(f"{icon('refresh')}  Reset")
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(test_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        self.content.addLayout(btn_row)

        self.save_status = QLabel("")
        self._add(self.save_status)

    def _save(self) -> None:
        values: dict[str, str] = {}
        for key, widget in self._fields.items():
            values[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
        # Basic validation for URL-like fields.
        for key in ("LLM_BASE_URL", "WEBHOOK_URL"):
            v = values.get(key, "")
            if v and "://" not in v:
                self.save_status.setText(f"{icon('error')} {key} must be a URL (http://…)")
                return
        env_path = HERE / ".env"
        lines = [f"# Virgo Desktop — saved {__import__('datetime').datetime.now()}\n"]
        for key, value in values.items():
            lines.append(f"{key}={value}\n")
        env_path.write_text("".join(lines), encoding="utf-8")
        self.save_status.setText(f"{icon('ok')} Saved to .env")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def _save_env(self) -> None:
        env_path = HERE / ".env"
        env_path.write_text(self.env_edit.toPlainText(), encoding="utf-8")
        self.save_status.setText(f"{icon('ok')} Raw .env saved")

    def _do_backup(self) -> None:
        try:
            import virgo_backup

            path = virgo_backup.backup()
            self.backup_status.setText(f"{icon('ok')} Backup saved: {path}")
        except Exception as exc:
            self.backup_status.setText(f"{icon('error')} Backup failed: {exc}")

    def _do_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Virgo backup", str(HERE), "Virgo backups (*.zip)"
        )
        if not path:
            return
        try:
            import virgo_backup

            count = virgo_backup.restore(path)
            self.backup_status.setText(f"{icon('ok')} Restored {count} file(s) from {path}")
        except Exception as exc:
            self.backup_status.setText(f"{icon('error')} Restore failed: {exc}")

    def _test_connection(self) -> None:
        base = ""
        for key, widget in self._fields.items():
            if key == "LLM_BASE_URL":
                base = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
        if not base:
            self.save_status.setText(f"{icon('error')} No LLM_BASE_URL set")
            return
        self.save_status.setText("Testing connection…")
        try:
            import json as _json
            import urllib.request

            url = base.rstrip("/") + "/api/tags"
            raw = urllib.request.urlopen(url, timeout=5).read()
            data = _json.loads(raw)
            n = len(data.get("models", []))
            self.save_status.setText(f"{icon('ok')} Ollama reachable — {n} model(s)")
        except Exception as exc:
            self.save_status.setText(f"{icon('error')} Connection failed: {exc}")

    def _reset(self) -> None:
        for key, widget in self._fields.items():
            val = self._defaults.get(key, "")
            if isinstance(widget, QComboBox):
                if widget.findText(val) == -1:
                    widget.addItem(val)
                widget.setCurrentText(val)
            else:
                widget.setText(val)
        self.save_status.setText("Defaults restored — click Save to persist")

    def _apply_font(self) -> None:
        w = self.window()
        family = self.font_combo.currentText()
        size = self.size_combo.currentData() or 13
        try:
            w.set_ui_font(family, int(size))
            self.save_status.setText(f"{icon('ok')} Font applied: {family} @ {size}px")
        except Exception as exc:
            self.save_status.setText(f"{icon('error')} Font apply failed: {exc}")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def on_activate(self) -> None:
        """Sync the appearance controls with the window's current state."""
        w = self.window()
        mode = getattr(w, "_theme_mode", "system")
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self._populate_themes()
        active = getattr(w, "_active_theme", w._theme_name)
        tidx = self.theme_combo.findData(active)
        if tidx >= 0:
            self.theme_combo.setCurrentIndex(tidx)
        self.theme_combo.setEnabled(mode == "manual")
        self._refresh_theme_editor()
        self.css_edit.setPlainText(getattr(w, "_custom_css", "") or "")
        # Sync font controls with saved config.
        fam = w._config.get("ui_font_family", "'Segoe UI', 'SF Pro', sans-serif")
        fidx = self.font_combo.findText(fam)
        if fidx >= 0:
            self.font_combo.setCurrentIndex(fidx)
        else:
            self.font_combo.addItem(fam)
            self.font_combo.setCurrentText(fam)
        sz = int(w._config.get("ui_font_size", 13))
        sidx = self.size_combo.findData(sz)
        if sidx >= 0:
            self.size_combo.setCurrentIndex(sidx)

    def _populate_themes(self) -> None:
        self.theme_combo.clear()
        for key, t in self.window().themes.items():
            self.theme_combo.addItem(t["name"], key)

    def _on_mode_change(self, idx: int) -> None:
        mode = self.mode_combo.itemData(idx)
        if not mode:
            return
        w = self.window()
        w.set_theme_mode(mode)
        self.theme_combo.setEnabled(mode == "manual")
        active = getattr(w, "_active_theme", w._theme_name)
        tidx = self.theme_combo.findData(active)
        if tidx >= 0:
            self.theme_combo.setCurrentIndex(tidx)
        self.save_status.setText(f"Theme mode: {self.mode_combo.currentText()}")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def _on_theme_change(self, idx: int) -> None:
        if self.mode_combo.currentData() != "manual":
            return
        name = self.theme_combo.itemData(idx)
        if not name:
            return
        w = self.window()
        if hasattr(w, "switch_theme"):
            w.switch_theme(name)
        self.save_status.setText(f"Theme switched to {self.theme_combo.currentText()}")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def _refresh_theme_editor(self) -> None:
        t = self.window()._current_theme()
        for key, btn in self._color_btns.items():
            col = t.get(key, "#000000")
            self._editor_colors[key] = col
            btn.setStyleSheet(
                f"background-color: {col}; border: 1px solid #00000055; border-radius: 4px;"
            )

    def _pick_color(self, key: str) -> None:
        from PyQt6.QtGui import QColor

        cur = self._editor_colors.get(key, "#000000")
        dlg = QColorDialog(self)
        dlg.setCurrentColor(QColor(cur))
        if dlg.exec():
            col = dlg.currentColor().name()
            self._editor_colors[key] = col
            self._color_btns[key].setStyleSheet(
                f"background-color: {col}; border: 1px solid #00000055; border-radius: 4px;"
            )

    def _save_custom_theme(self) -> None:
        name = self.theme_name_edit.text().strip()
        if not name:
            self.save_status.setText(f"{icon('warn')} Enter a theme name first")
            return
        w = self.window()
        w.save_custom_theme(name, dict(self._editor_colors))
        self._populate_themes()
        tidx = self.theme_combo.findData(name.strip().lower().replace(" ", "_"))
        if tidx >= 0:
            self.theme_combo.setCurrentIndex(tidx)
        self.save_status.setText(f"{icon('ok')} Saved theme '{name}'")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def _apply_css(self) -> None:
        w = self.window()
        w.set_custom_css(self.css_edit.toPlainText())
        self.save_status.setText(f"{icon('ok')} Custom CSS applied")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

    def _reset_css(self) -> None:
        self.css_edit.clear()
        w = self.window()
        w.set_custom_css("")
        self.save_status.setText(f"{icon('ok')} Custom CSS cleared")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))


# ═══════════════════════════════════════════════════════════════════════
# About page
# ═══════════════════════════════════════════════════════════════════════


class AboutPage(PageWidget):
    """About Virgo Desktop."""

    def __init__(self) -> None:
        super().__init__(
            "About",
            "",
        )

        try:
            from virgo_desktop import APP_VERSION
        except Exception:
            APP_VERSION = "0.2.0"

        about_text = QLabel(
            f"<h2>Virgo Desktop {APP_VERSION}</h2>"
            f"<p>A multi-agent pipeline framework with a polished PyQt6 GUI — "
            f"featuring an animated pipeline graph, thermal model bench, "
            f"recon dashboard with attack surface map, swarm visualizer, "
            f"live system health monitoring, and more.</p>"
            f"<hr>"
            f"<p><b>Pages (19 total):</b> Pipeline · Chat · Dashboard · "
            f"Mascot Chat · Activity Feed · Leaderboard · Files · "
            f"Network/Recon · System Health · Alerts · Scaffolds · "
            f"Sessions · Swarm · Logs · Plugins · Procs · Bench · "
            f"Settings · About</p>"
            f"<hr>"
            f"<p><b>Key Shortcuts:</b></p>"
            f"<p>"
            f"1–9 / 0 — Switch pages · "
            f"Ctrl+P — Quick page switcher · "
            f"Ctrl+Shift+P — Command palette · "
            f"Ctrl+Shift+L — Prompt library · "
            f"Ctrl+Shift+I — Performance overlay · "
            f"Ctrl+B — Toggle sidebar · "
            f"? — Show all shortcuts"
            f"</p>"
            f"<hr>"
            f"<p><b>Integrations:</b> Ollama (local LLM) · "
            f"crawl4ai (web crawling) · mem0 (persistent memory) · "
            f"psutil (system stats) · PyQt6 6.11</p>"
            f"<hr>"
            f"<p>Built with PyQt6 · MIT License</p>"
            f"<p><a href='https://github.com/Aussielad89/virgo-agent' "
            f"style='color: #89b4fa;'>github.com/Aussielad89/virgo-agent</a></p>"
        )
        about_text.setWordWrap(True)
        about_text.setTextFormat(Qt.TextFormat.RichText)
        self._add(about_text)


# ═══════════════════════════════════════════════════════════════════════
# Live Dashboard Page
# ═══════════════════════════════════════════════════════════════════════



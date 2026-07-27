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
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

HERE = Path(__file__).parent
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


class PipelinePage(PageWidget):
    """Visual Pipeline Graph — animated DAG with live stats and split-view log."""

    def __init__(self) -> None:
        super().__init__(
            "Pipeline",
            "Write → Test → Fix loop with animated graph & live metrics.",
        )
        self._process: subprocess.Popen | None = None
        self._running = False
        self._elapsed = 0.0
        self._iter_count = 0
        self._token_count = 0

        # ── Goal input ──
        goal_group = self._section("Goal")
        goal_row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText(
            "e.g. build a web scraper that fetches Hacker News headlines"
        )
        self.goal_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        goal_row.addWidget(self.goal_input, 1)
        self.run_btn = QPushButton("▶  Run")
        self.run_btn.setStyleSheet(
            "QPushButton { background: #a6e3a1; color: #1e1e2e; font-weight: bold; "
            "border: none; border-radius: 6px; padding: 6px 18px; }"
            "QPushButton:hover { background: #89d89e; }"
            "QPushButton:disabled { background: #313244; color: #6c7086; }"
        )
        self.run_btn.clicked.connect(self._run_pipeline)
        goal_row.addWidget(self.run_btn)
        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_pipeline)
        goal_row.addWidget(self.stop_btn)
        goal_group.layout().addLayout(goal_row)  # type: ignore
        self._add(goal_group)

        # ── Options bar ──
        opt_row = QHBoxLayout()
        self.use_llm = QPushButton("🧠  LLM: ON")
        self.use_llm.setCheckable(True)
        self.use_llm.setChecked(True)
        self.use_llm.clicked.connect(self._toggle_llm)
        self.use_llm.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 4px 12px; color: #cdd6f4; font-size: 11px; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        opt_row.addWidget(self.use_llm)
        opt_row.addWidget(QLabel("Iterations:"))
        self.iter_input = QLineEdit("5")
        self.iter_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 4px; padding: 3px 6px; color: #cdd6f4; max-width: 50px; }"
        )
        self.iter_input.setFixedWidth(50)
        opt_row.addWidget(self.iter_input)
        opt_row.addStretch()
        self.content.addLayout(opt_row)

        # ── Animated Pipeline Graph ──
        dag_group = self._section("Pipeline Graph")
        self._status_label = QLabel("● Idle")
        self._status_label.setStyleSheet("color: #6c7086; font-size: 12px; padding: 2px 0;")
        dag_group.layout().addWidget(self._status_label)  # type: ignore

        self._phases = ["discover", "plan", "generate", "test", "fix"]
        self._phase_status: dict[str, str] = dict.fromkeys(self._phases, "idle")
        self._dag_scene = QGraphicsScene()
        self._dag_view = QGraphicsView(self._dag_scene)
        self._dag_view.setMinimumHeight(160)
        self._dag_view.setMaximumHeight(200)
        self._dag_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dag_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dag_view.setStyleSheet("border: 1px solid #313244; border-radius: 6px; background: #11111b;")
        self._dag_view.setRenderHint(  # type: ignore[arg-type]
            self._dag_view.renderHints() |
            QPainter.RenderHint.Antialiasing
        )
        dag_group.layout().addWidget(self._dag_view)  # type: ignore
        self._build_animated_dag()
        # Click phase to re-run
        self._dag_view.mousePressEvent = self._dag_clicked  # type: ignore
        self._add(dag_group)

        # ── Split view: log (left) + live stats (right) ──
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Log pane
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_layout.addWidget(QLabel("📋  Output Log"))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Pipeline output will appear here...")
        self.output.setStyleSheet(
            "QPlainTextEdit { background: #11111b; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; font-size: 12px; }"
        )
        log_layout.addWidget(self.output, 1)
        self._splitter.addWidget(log_widget)

        # Stats pane
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        stats_layout.setContentsMargins(8, 0, 0, 0)
        stats_layout.setSpacing(6)
        stats_layout.addWidget(QLabel("📊  Live Stats"))

        self._stat_labels = {}
        for key, label, color in [
            ("phase", "Phase", "#89b4fa"),
            ("elapsed", "Elapsed", "#a6e3a1"),
            ("iterations", "Iterations", "#f9e2af"),
            ("tokens", "Tokens", "#f5c2e7"),
            ("lines", "Log lines", "#a6adc8"),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label}:"))
            val = QLabel("—")
            val.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")
            row.addWidget(val, 1)
            stats_layout.addLayout(row)
            self._stat_labels[key] = val

        # Mini progress
        stats_layout.addSpacing(8)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background: #313244; border: none; border-radius: 4px; "
            "height: 8px; text-align: center; font-size: 10px; color: #a6adc8; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #89b4fa, stop:1 #a6e3a1); border-radius: 4px; }"
        )
        stats_layout.addWidget(self._progress)

        # Export button
        export_btn = QPushButton("💾  Export graph")
        export_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 12px; color: #cdd6f4; font-size: 11px; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        export_btn.clicked.connect(self._export_dag)
        stats_layout.addWidget(export_btn)

        # ── Recipe Book (#13) ──
        stats_layout.addSpacing(6)
        recipe_label = QLabel("📖  Recipes")
        recipe_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f9e2af;")
        stats_layout.addWidget(recipe_label)
        recipe_row = QHBoxLayout()
        self._recipe_combo = QComboBox()
        self._recipe_combo.setStyleSheet(
            "QComboBox { background: #181825; border: 1px solid #313244; "
            "border-radius: 4px; padding: 3px 6px; color: #cdd6f4; font-size: 11px; }"
        )
        self._recipe_combo.currentIndexChanged.connect(self._load_recipe)
        recipe_row.addWidget(self._recipe_combo, 1)
        save_recipe_btn = QPushButton("💾 Save")
        save_recipe_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; padding: 3px 8px; color: #cdd6f4; font-size: 10px; }"
            "QPushButton:hover { border-color: #f9e2af; }"
        )
        save_recipe_btn.clicked.connect(self._save_recipe)
        recipe_row.addWidget(save_recipe_btn)
        del_recipe_btn = QPushButton("✕")
        del_recipe_btn.setFixedWidth(24)
        del_recipe_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #f38ba8; font-size: 12px; }"
        )
        del_recipe_btn.clicked.connect(self._delete_recipe)
        recipe_row.addWidget(del_recipe_btn)
        stats_layout.addLayout(recipe_row)
        self._refresh_recipes()

        stats_layout.addStretch()

        self._splitter.addWidget(stats_widget)
        self._splitter.setSizes([400, 200])

        self._add(self._splitter)
        self._restore_splitter()

        # ── Timers ──
        self._timer = QTimer()
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_process)

        self._anim_timer = QTimer()
        self._anim_timer.setInterval(400)
        self._anim_timer.timeout.connect(self._animate_dag)

        self._elapsed_timer = QTimer()
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._log_line_count = 0

    # ── Helpers ──────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        self.goal_input.setFocus()

    def _toggle_llm(self) -> None:
        self.use_llm.setText(f"🧠  LLM: {'ON' if self.use_llm.isChecked() else 'OFF'}")

    def _restore_splitter(self) -> None:
        try:
            p = HERE / ".virgo_pipeline_ui.json"
            if p.exists():
                d = json.loads(p.read_text())
                sizes = d.get("splitter")
                if sizes and len(sizes) == self._splitter.count():
                    self._splitter.setSizes([int(s) for s in sizes])
        except Exception:
            pass

    def _save_splitter(self) -> None:
        try:
            p = HERE / ".virgo_pipeline_ui.json"
            d = {}
            if p.exists():
                try:
                    d = json.loads(p.read_text())
                except Exception:
                    d = {}
            d["splitter"] = list(self._splitter.sizes())
            p.write_text(json.dumps(d))
        except Exception:
            pass

    # ── Animated DAG ─────────────────────────────────────────────────────

    def _build_animated_dag(self) -> None:
        """Draw phase nodes with glow-friendly rectangles + arrows."""
        self._dag_scene.clear()
        self._dag_nodes: dict[str, QGraphicsRectItem] = {}
        self._dag_glows: dict[str, QGraphicsEllipseItem] = {}
        n = len(self._phases)
        node_w, node_h, gap = 130, 52, 36
        total_w = n * node_w + (n - 1) * gap
        y = 30
        x0 = 20
        glow_colors = {
            "idle": QColor(69, 71, 90, 0),
            "running": QColor(249, 226, 175, 60),
            "done": QColor(166, 227, 161, 40),
            "failed": QColor(243, 139, 168, 50),
        }
        fill_colors = {
            "idle": "#45475a",
            "running": "#f9e2af",
            "done": "#a6e3a1",
            "failed": "#f38ba8",
        }

        for i, phase in enumerate(self._phases):
            x = x0 + i * (node_w + gap)

            # Glow circle behind node
            glow = QGraphicsEllipseItem(
                x - 8, y - 8, node_w + 16, node_h + 16,
            )
            glow.setBrush(QBrush(glow_colors["idle"]))
            glow.setPen(QPen(Qt.PenStyle.NoPen))
            self._dag_scene.addItem(glow)
            self._dag_glows[phase] = glow

            # Node rect
            rect = QGraphicsRectItem(x, y, node_w, node_h)
            rect.setBrush(QBrush(QColor(fill_colors["idle"])))
            rect.setPen(QPen(QColor("#1e1e2e"), 2))
            rect.setFlags(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
            rect.setData(0, phase)
            self._dag_scene.addItem(rect)
            self._dag_nodes[phase] = rect

            # Phase label
            display_name = {"discover": "Discover", "plan": "Plan", "generate": "Generate",
                            "test": "Test", "fix": "Fix"}.get(phase, phase.upper())
            txt = QGraphicsTextItem(display_name, rect)
            txt.setPos(x + 12, y + 16)
            txt.setDefaultTextColor(QColor("#1e1e2e"))
            font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            txt.setFont(font)

            # Arrow between nodes
            if i < n - 1:
                ax = x + node_w + 4
                arrow = self._dag_scene.addLine(
                    ax, y + node_h / 2, ax + gap - 8, y + node_h / 2,
                    QPen(QColor("#6c7086"), 2),
                )
                # Arrowhead
                head = self._dag_scene.addPolygon(
                    QPolygonF([
                        QPointF(ax + gap - 4, y + node_h / 2 - 5),
                        QPointF(ax + gap - 4, y + node_h / 2 + 5),
                        QPointF(ax + gap + 4, y + node_h / 2),
                    ]),
                    QPen(Qt.PenStyle.NoPen),
                    QBrush(QColor("#6c7086")),
                )

        self._dag_scene.setSceneRect(0, 0, total_w + 60, 120)
        self._dag_view.setSceneRect(0, 0, total_w + 60, 120)

    def _animate_dag(self) -> None:
        """Pulse glow on the running phase node."""
        for phase, status in self._phase_status.items():
            glow = self._dag_glows.get(phase)
            if not glow:
                continue
            if status == "running":
                # Pulse alpha: alternate between 40 and 80
                cur = glow.brush().color().alpha()
                new_alpha = 40 if cur >= 70 else 80
                glow.setBrush(QBrush(QColor(249, 226, 175, new_alpha)))
            else:
                alpha = {"done": 30, "failed": 40, "idle": 0}.get(status, 0)
                if glow.brush().color().alpha() != alpha:
                    glow.setBrush(QBrush(QColor(
                        249 if status == "running" else (
                            166 if status == "done" else 243
                        ),
                        226 if status == "running" else (
                            227 if status == "done" else 139
                        ),
                        175 if status == "running" else (
                            161 if status == "done" else 168
                        ),
                        alpha,
                    )))

    def _update_dag(self, phase: str, status: str) -> None:
        if phase not in self._phase_status:
            return
        self._phase_status[phase] = status
        colors = {"idle": "#45475a", "running": "#f9e2af", "done": "#a6e3a1", "failed": "#f38ba8"}
        node = self._dag_nodes.get(phase)
        if node:
            node.setBrush(QBrush(QColor(colors.get(status, "#45475a"))))

    def _dag_clicked(self, event) -> None:  # type: ignore[override]
        item = self._dag_view.itemAt(event.pos())
        phase = None
        if item is not None:
            phase = item.data(0)
        if phase:
            self._rerun_phase(phase)
        QGraphicsView.mousePressEvent(self._dag_view, event)

    def _rerun_phase(self, phase: str) -> None:
        goal = self.goal_input.text().strip()
        if not goal:
            self.output.appendPlainText("⚠️  Enter a goal first.")
            return
        self.output.appendPlainText(f"▶  Re-running phase: {phase}")
        self._update_dag(phase, "running")
        args = [
            sys.executable, str(HERE / "cli.py"), "run",
            "--goal", goal, "--phase", phase,
            "--max-iterations", self.iter_input.text() or "5",
        ]
        if self.use_llm.isChecked():
            args.append("--llm")
        try:
            subprocess.run(
                args,
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._update_dag(phase, "done")
            self.output.appendPlainText(f"✅ Phase {phase} complete")
        except Exception as exc:
            self._update_dag(phase, "failed")
            self.output.appendPlainText(f"❌ Phase {phase} failed: {exc}")

    def _export_dag(self) -> None:
        from PyQt6.QtGui import QImage, QPainter
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DAG", str(HERE / "pipeline_graph.png"), "PNG (*.png)"
        )
        if not path:
            return
        try:
            scene = self._dag_scene
            img = QImage(int(scene.width()), int(scene.height()), QImage.Format.Format_ARGB32)
            img.fill(QColor("#1e1e2e"))
            painter = QPainter(img)
            scene.render(painter)
            painter.end()
            img.save(path)
            self.output.appendPlainText(f"✅ DAG exported → {path}")
        except Exception as exc:
            self.output.appendPlainText(f"❌ Export failed: {exc}")

    def _phase_from_line(self, line: str) -> str | None:
        low = line.lower()
        for kw, phase in (
            ("discover", "discover"), ("plan", "plan"),
            ("generat", "generate"), ("test", "test"), ("fix", "fix"),
        ):
            if kw in low and ("phase" in low or "→" in low or "running" in low or "starting" in low or kw == low.strip()):
                return phase
        # Also match iteration counters like "[1/5]"
        import re
        m = re.search(r"\[(\d+)/(\d+)\]", low)
        if m:
            self._iter_count = int(m.group(1))
            self._stat_labels["iterations"].setText(f"{m.group(1)}/{m.group(2)}")
        return None

    # ── Pipeline execution ──────────────────────────────────────────────

    def _run_pipeline(self) -> None:
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._status_label.setText("🟡 Running...")
        self._elapsed = 0.0
        self._iter_count = 0
        self._token_count = 0
        self._log_line_count = 0
        self.output.clear()
        for p in self._phases:
            self._update_dag(p, "idle")
        self._anim_timer.start()
        self._elapsed_timer.start()

        args = [
            sys.executable, str(HERE / "cli.py"), "run",
            "--goal", self.goal_input.text().strip(),
            "--max-iterations", self.iter_input.text() or "5",
        ]
        if self.use_llm.isChecked():
            args.append("--llm")

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._timer.start()

    def _stop_pipeline(self) -> None:
        if self._process:
            self._process.kill()
            self._process = None
        self._cleanup_run("Stopped")

    def _poll_process(self) -> None:
        if not self._process:
            self._timer.stop()
            return
        if self._process.stdout:
            line = self._process.stdout.readline()
            if line:
                self.output.appendPlainText(line.rstrip())
                self._log_line_count += 1
                self._stat_labels["lines"].setText(str(self._log_line_count))
                # Token estimation
                self._token_count += len(line.split())
                self._stat_labels["tokens"].setText(str(self._token_count))
                # Phase detection
                ph = self._phase_from_line(line)
                if ph:
                    self._update_dag(ph, "running")
                    self._stat_labels["phase"].setText(ph.capitalize())
        if self._process.poll() is not None:
            if self._process.stdout:
                for line in self._process.stdout:
                    self.output.appendPlainText(line.rstrip())
            rc = self._process.returncode
            self._process = None
            final = "failed" if rc not in (0, None) else "done"
            for p in self._phases:
                if self._phase_status.get(p) == "running":
                    self._update_dag(p, final)
                elif self._phase_status.get(p) == "idle":
                    self._update_dag(p, "done" if final == "done" else "idle")
            self._cleanup_run(f"Exit code {rc}")
            w = self.window()
            if hasattr(w, "_achievement_check"):
                w._achievement_check("pipeline", rc)
            _beep("error" if rc not in (0, None) else "done")

    def _cleanup_run(self, msg: str) -> None:
        self._timer.stop()
        self._anim_timer.stop()
        self._elapsed_timer.stop()
        self._running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._status_label.setText(f"● {msg}")

    def _tick_elapsed(self) -> None:
        self._elapsed += 1
        mins, secs = divmod(int(self._elapsed), 60)
        self._stat_labels["elapsed"].setText(f"{mins:02d}:{secs:02d}")

    # ── Recipe Book (#13) ───────────────────────────────────────────────
    _RECIPES_DIR = Path(__file__).parent / ".virgo_recipes"

    def _refresh_recipes(self) -> None:
        """Reload pipeline recipes into the combo box."""
        self._RECIPES_DIR.mkdir(exist_ok=True)
        self._recipe_combo.blockSignals(True)
        self._recipe_combo.clear()
        self._recipe_combo.addItem("(select recipe)")
        self._recipe_combo.addItem("💾  Save current as…")
        for pf in sorted(self._RECIPES_DIR.glob("*.json")):
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                name = data.get("name", pf.stem)
                tags = data.get("tags", "")
                label = f"{name}" + (f"  [{tags}]" if tags else "")
                self._recipe_combo.addItem(label)
                self._recipe_combo.setItemData(
                    self._recipe_combo.count() - 1, str(pf), Qt.ItemDataRole.UserRole,
                )
            except Exception:
                pass
        self._recipe_combo.blockSignals(False)

    def _load_recipe(self, idx: int) -> None:
        """Load a recipe into the pipeline inputs."""
        if idx <= 0:
            return
        if idx == 1:
            # "Save current as…" selected
            self._save_recipe_dialog()
            return
        path = self._recipe_combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.goal_input.setText(data.get("goal", ""))
            self.iter_input.setText(str(data.get("iterations", 5)))
            self.use_llm.setChecked(data.get("use_llm", True))
            self.output.appendPlainText(f"📖  Loaded recipe: {data.get('name', 'Unnamed')}")
        except Exception:
            pass
        # Reset combo to first item
        self._recipe_combo.blockSignals(True)
        self._recipe_combo.setCurrentIndex(0)
        self._recipe_combo.blockSignals(False)

    def _save_recipe(self) -> None:
        """Quick-save from the Save button."""
        self._save_recipe_dialog()

    def _save_recipe_dialog(self) -> None:
        """Dialog to save current pipeline config as a recipe."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Save Pipeline Recipe")
        dlg.resize(360, 200)
        dlg.setStyleSheet("QDialog { background: #1e1e2e; }")
        lo = QVBoxLayout(dlg)
        lo.setSpacing(10)

        name_inp = QLineEdit()
        name_inp.setPlaceholderText("Recipe name…")
        name_inp.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        lo.addWidget(QLabel("Name:"))
        lo.addWidget(name_inp)

        tags_inp = QLineEdit()
        tags_inp.setPlaceholderText("Tags (comma-separated, e.g. web,api)")
        tags_inp.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        lo.addWidget(QLabel("Tags:"))
        lo.addWidget(tags_inp)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Save")
        ok_btn.setStyleSheet(
            "QPushButton { background: #a6e3a1; color: #1e1e2e; font-weight: bold; "
            "border: none; border-radius: 6px; padding: 6px 16px; }"
        )
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 16px; color: #cdd6f4; }"
        )
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lo.addLayout(btn_row)

        if not dlg.exec():
            return
        name = name_inp.text().strip()
        if not name:
            return
        tags = tags_inp.text().strip()
        slug = name.lower().replace(" ", "_").replace("/", "_")
        payload = {
            "name": name,
            "goal": self.goal_input.text().strip(),
            "iterations": int(self.iter_input.text() or "5"),
            "use_llm": self.use_llm.isChecked(),
            "tags": tags,
        }
        dest = self._RECIPES_DIR / f"{slug}.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._refresh_recipes()
        self.output.appendPlainText(f"📖  Saved recipe: {name}")

    def _delete_recipe(self) -> None:
        """Delete the currently selected recipe."""
        idx = self._recipe_combo.currentIndex()
        if idx <= 1:
            return
        path = self._recipe_combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if path:
            Path(path).unlink(missing_ok=True)
            self._refresh_recipes()
            self.output.appendPlainText(f"🗑️  Deleted recipe")


# ═══════════════════════════════════════════════════════════════════════
# Chat page
# ═══════════════════════════════════════════════════════════════════════


def _strip_think(text: str) -> str:
    """Remove  blocks and surrounding whitespace from model output."""
    import re

    return re.sub(r"\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL)


_CHAT_HISTORY_DIR = HERE / ".virgo_chat_history"


def _md_to_html(text: str) -> str:
    """Convert basic markdown to safe HTML for the chat log."""
    import re

    # Escape HTML entities first, then apply markdown rules.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Code blocks (```...```) — protect from other rules
    code_blocks: list[tuple[str, str]] = []

    def _save_code(m: re.Match) -> str:
        code_blocks.append((m.group(1) or "", m.group(2)))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(
        r"```(\w*)[^\S\n]*\n(.*?)```",
        lambda m: _save_code(m),
        text,
        flags=re.DOTALL,
    )

    # Inline code `` `...` `` — protect from other rules
    inline_codes: list[str] = []

    def _save_inline(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", lambda m: _save_inline(m), text)

    # Headings
    text = re.sub(r"^### (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic *text* or _text_ (single, not double)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)

    # Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Unordered lists
    lines = text.split("\n")
    in_list = False
    result: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if m:
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{m.group(2)}</li>")
        else:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append(line)
    if in_list:
        result.append("</ul>")
    text = "\n".join(result)

    # Ordered lists
    lines = text.split("\n")
    in_list = False
    result = []
    for line in lines:
        m = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
        if m:
            if not in_list:
                result.append("<ol>")
                in_list = True
            result.append(f"<li>{m.group(2)}</li>")
        else:
            if in_list:
                result.append("</ol>")
                in_list = False
            result.append(line)
    if in_list:
        result.append("</ol>")
    text = "\n".join(result)

    # Newlines → <br> (not inside block elements)
    text = text.replace("\n", "<br>")

    # Restore code blocks — with language badge + copy button
    for i, (lang, code) in enumerate(code_blocks):
        escaped = code.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        text = text.replace(
            f"\x00CODEBLOCK{i}\x00",
            f"<div style='background:#1e1e2e; border:1px solid #313244; "
            f"border-radius:6px; margin:8px 0; overflow:hidden;'>"
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:center; padding:4px 10px; background:#181825; "
            f"border-bottom:1px solid #313244; font-size:11px; color:#6c7086;'>"
            f"<span>{lang or 'code'}</span>"
            f"<a href='copy:{i}' style='color:#89b4fa; text-decoration:none;' "
            f"onclick='navigator.clipboard.writeText(\"{escaped}\")'>Copy</a>"
            f"</div>"
            f"<pre style='margin:0; padding:10px; font-size:12px;'><code>{code}</code></pre>"
            f"</div>",
        )

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", f"<code>{code}</code>")

    return text


def _chat_session_path(prefix: str = "chat") -> Path:
    """Return a unique path for a new chat history file."""
    from datetime import datetime

    _CHAT_HISTORY_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CHAT_HISTORY_DIR / f"{prefix}_{ts}.json"


def _load_recent_chat() -> tuple[list[dict[str, str]], str, str] | None:
    """Load the most recent chat session. Returns (messages, model, session_id) or None."""
    if not _CHAT_HISTORY_DIR.exists():
        return None
    sessions = sorted(_CHAT_HISTORY_DIR.glob("chat_*.json"), reverse=True)
    if not sessions:
        return None
    try:
        data = json.loads(sessions[0].read_text())
        msgs = data.get("messages", [])
        model = data.get("model", "")
        sid = data.get("session_id", "")
        return (msgs, model, sid) if msgs else None
    except Exception:
        return None


class _StopStream(Exception):
    """Raised inside the stream writer to abort an in-flight reply."""


class _ImageDropHandler(QObject):
    """Event filter that accepts image drops onto a QTextEdit."""

    def __init__(self, target: QTextEdit, callback):
        super().__init__(target)
        self._cb = callback
        target.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.DragEnter:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if url.isLocalFile() and self._is_image(url.toLocalFile()):
                        event.acceptProposedAction()
                        return True
            return False
        if t == QEvent.Type.Drop:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if url.isLocalFile():
                        p = url.toLocalFile()
                        if self._is_image(p):
                            self._cb(p)
                event.acceptProposedAction()
                return True
            return False
        return super().eventFilter(obj, event)

    @staticmethod
    def _is_image(path: str) -> bool:
        return path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


class ChatPage(PageWidget):
    """Interactive streaming chat with Virgo (local LLM)."""

    def __init__(self) -> None:
        super().__init__(
            "Chat",
            "Talk to Virgo — powered by your local LLM. Type /help for commands.",
        )

        # ── Model switcher + stop (top bar) ──
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        try:
            live = _live_ollama_models()
        except Exception:
            live = []
        choices = []
        for m in PREFERRED_MODELS + live:
            if m not in choices:
                choices.append(m)
        if not choices:
            choices = ["ornith:latest"]
        default_model = os.environ.get("MODEL_GENERATOR", "phi4-mini-reasoning:3.8b")
        for m in choices:
            self.model_combo.addItem(m)
        if default_model not in choices:
            self.model_combo.addItem(default_model)
        self.model_combo.setCurrentText(default_model)
        self._current_model = default_model
        model_row.addWidget(self.model_combo, 1)

        # Persona selector
        model_row.addWidget(QLabel("Persona:"))
        self.persona_combo = QComboBox()
        from cli import VIRGO_RESEARCH_PROMPT, VIRGO_SYSTEM_PROMPT

        self._personas = {
            "Default": VIRGO_SYSTEM_PROMPT,
            "Researcher": VIRGO_RESEARCH_PROMPT,
            "Concise": "You are Virgo. Reply in the fewest words possible.",
            "Teacher": "You are Virgo. Explain concepts step by step with examples.",
            "Sarcastic": "You are Virgo. Be witty and sarcastic but still correct.",
            "Coder": "You are Virgo. Focus on production-ready code, minimal prose.",
        }
        for name in self._personas:
            self.persona_combo.addItem(name)
        self.persona_combo.setCurrentText("Default")
        self.persona_combo.setMinimumWidth(110)
        self._persona = self._personas["Default"]
        self.persona_combo.currentTextChanged.connect(self._on_persona)
        model_row.addWidget(self.persona_combo)

        self.stop_btn = QPushButton(f"{icon('error')}  Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop)
        model_row.addWidget(self.stop_btn)
        self.content.addLayout(model_row)
        # Connect only after the initial value is set, so it doesn't fire.
        self.model_combo.currentTextChanged.connect(self._switch_model)

        # ── Action toolbar ──
        toolbar = QHBoxLayout()
        self.export_btn = QPushButton(f"{icon('save')}  Export")
        self.export_btn.clicked.connect(self._export)
        self.copy_btn = QPushButton(f"{icon('file')}  Copy reply")
        self.copy_btn.clicked.connect(self._copy_reply)
        self.regen_btn = QPushButton(f"{icon('refresh')}  Regenerate")
        self.regen_btn.clicked.connect(self._regenerate)
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.regen_btn)
        self.branch_btn = QPushButton(f"{icon('refresh')}  Branch")
        self.branch_btn.setToolTip("Fork the conversation from the last message")
        self.branch_btn.clicked.connect(self._branch_from)
        toolbar.addWidget(self.branch_btn)
        self.speak_btn = QPushButton(f"{icon('audio')}  Speak")
        self.speak_btn.setToolTip("Read last reply aloud")
        self.speak_btn.clicked.connect(self._speak_reply)
        self.mic_btn = QPushButton(f"{icon('mic')}  Mic")
        self.mic_btn.setToolTip("Speak into your microphone")
        self.mic_btn.clicked.connect(self._mic_input)
        self.voice_mode = QPushButton(f"{icon('audio')}  Voice mode")
        self.voice_mode.setCheckable(True)
        self.voice_mode.setToolTip("Toggle: recognized speech auto-sends")
        toolbar.addWidget(self.speak_btn)
        toolbar.addWidget(self.mic_btn)
        toolbar.addWidget(self.voice_mode)
        self.prompt_btn = QPushButton(f"{icon('file')}  Prompts")
        self.prompt_btn.setToolTip("Save / load prompt templates")
        self.prompt_btn.clicked.connect(self._show_prompt_lib)
        toolbar.addWidget(self.prompt_btn)
        self.copy_md_btn = QPushButton(f"{icon('file')}  Copy MD")
        self.copy_md_btn.setToolTip("Copy full chat as Markdown to clipboard")
        self.copy_md_btn.clicked.connect(self._copy_markdown)
        toolbar.addWidget(self.copy_md_btn)
        self.split_btn = QPushButton(f"{icon('ok')}  Split view")
        self.split_btn.setToolTip("Toggle side-by-side comparison view")
        self.split_btn.setCheckable(True)
        self.split_btn.clicked.connect(self._toggle_split)
        toolbar.addWidget(self.split_btn)
        self.ab_btn = QPushButton(f"{icon('compare')}  A/B")
        self.ab_btn.setToolTip("Compare two models on the same prompt, scored")
        self.ab_btn.clicked.connect(self._ab_compare)
        toolbar.addWidget(self.ab_btn)
        toolbar.addStretch()
        self.content.addLayout(toolbar)

        # Image gallery strip (collects images referenced in chat)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(64, 64))
        self.gallery.setMaximumHeight(80)
        self.gallery.setFlow(QListWidget.Flow.LeftToRight)
        self.gallery.setWrapping(False)
        self.gallery.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.gallery.itemDoubleClicked.connect(self._open_gallery_image)
        self.gallery.setVisible(False)
        self.content.addWidget(self.gallery)

        # ── Options row: temperature + token estimate ──
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("Temp:"))
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setMinimum(0)
        self.temp_slider.setMaximum(20)  # 0.0–2.0 in steps of 0.1
        self.temp_slider.setValue(7)
        self._temperature = 0.7
        self.temp_slider.setFixedWidth(120)
        self.temp_slider.valueChanged.connect(self._on_temp)
        opts_row.addWidget(self.temp_slider)
        self.temp_label = QLabel("0.7")
        opts_row.addWidget(self.temp_label)
        opts_row.addSpacing(12)
        self.token_label = QLabel("tokens: —")
        self.token_label.setObjectName("metaLabel")
        opts_row.addWidget(self.token_label)
        self._stream_chars = 0
        self._stream_t0 = 0.0
        opts_row.addStretch()
        self.content.addLayout(opts_row)

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Start a conversation...")
        self.chat_log.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_log.customContextMenuRequested.connect(self._chat_context_menu)
        self._drop_handler = _ImageDropHandler(self.chat_log, self._handle_image_drop)
        self._add(self.chat_log)

        self._cancel = False
        self._last_user = ""
        self._last_reply = ""

        input_row = QHBoxLayout()
        self.attach_btn = QPushButton(f"{icon('file')}  Attach")
        self.attach_btn.setToolTip("Attach a file or photo")
        self.attach_btn.clicked.connect(self._attach)
        input_row.addWidget(self.attach_btn)
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Message Virgo, or /help for commands...")
        self.msg_input.returnPressed.connect(self._send)
        self._slash_commands = [
            ("/help", "Show available commands"),
            ("/tools", "List available tools"),
            ("/clear", "Clear the chat history"),
            ("/read <path>", "Read a file into context"),
            ("/web <url>", "Fetch a web page"),
            ("/py <code>", "Run a Python snippet"),
        ]
        self.msg_input.textChanged.connect(self._update_token_count)
        self.msg_input.textChanged.connect(self._on_input_typed)
        self.msg_input.installEventFilter(self)
        input_row.addWidget(self.msg_input, 1)
        self.send_btn = QPushButton(f"{icon('send')}  Send")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        self.multi_btn = QPushButton("M")
        self.multi_btn.setToolTip("Multi-model: send to several models at once")
        self.multi_btn.setCheckable(True)
        self.multi_btn.setFixedWidth(32)
        self.multi_btn.setObjectName("multiBtn")
        self.multi_btn.clicked.connect(self._toggle_multi)
        input_row.addWidget(self.multi_btn)
        self._multi_models: list[str] = []
        self._slash_popup: QListWidget | None = None
        self.content.addLayout(input_row)

        # Ctrl+Enter / Ctrl+Return sends the message.
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._send)

        # Font zoom
        for seq, delta in (("Ctrl++", 1), ("Ctrl+=", 1), ("Ctrl+-", -1)):
            QShortcut(QKeySequence(seq), self).activated.connect(lambda d=delta: self._zoom_font(d))
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(lambda: self._zoom_font(0))
        self._chat_font_size = 13
        # Chat search
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._show_search)

        # LLM client (lazy, set on first activate)
        self._client = None
        self._client_checked = False
        self._history: list[dict[str, str]] = []
        self._busy = False
        self._session_id = __import__("uuid").uuid4().hex[:12]

        # Restore previous chat session if available
        prev = _load_recent_chat()
        if prev:
            msgs, model, sid = prev
            self._history[:] = msgs
            self._session_id = sid or self._session_id
            if model:
                self.chat_log.append(f"<i>[Restored previous chat — {model}]</i>")
            self.chat_log.append("<i>Type /clear to start fresh, or continue below.</i>")
            for msg in msgs:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    self.chat_log.append(f"<b>You:</b> {content}")
                elif role == "assistant":
                    self._append_assistant(content)
                elif role == "system":
                    self.chat_log.append(f"<i>[System: {content[:100]}…]</i>")

        if not prev:
            # Banner
            self.chat_log.append(
                "<i>Virgo chat — local LLM. Commands: /help, /tools, /clear, "
                "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;. "
                "Use Attach to send files or photos.</i>"
            )

        # ── Prompt Library side panel (lazy-built) ──
        self._setup_prompt_panel()

    def _attach(self) -> None:
        """Open a file picker and attach selected files / photos to the chat."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files or photos",
            "",
            "All files (*);;"
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg);;"
            "Text (*.txt *.md *.py *.json *.csv *.log *.yaml *.yml *.toml *.ini)",
        )
        for path in files:
            if path:
                self._attach_one(path)

    def _attach_one(self, path: str) -> None:
        p = Path(path)
        ext = p.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"):
            url = QUrl.fromLocalFile(str(p)).toString()
            self.chat_log.append(f"<i>You attached a photo:</i><br><img src='{url}' width='240'>")
            self._history.append({"role": "user", "content": f"[User attached photo: {p.name}]"})
            return
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.chat_log.append(f"<i>[Could not read {p.name}: {exc}]</i>")
            return
        shown = text if len(text) <= 8000 else text[:8000] + "\n…(truncated)"
        self.chat_log.append(
            f"<i>You attached <b>{p.name}</b> ({len(text)} chars):</i><br>"
            f"<pre>{self._escape(shown)}</pre>"
        )
        self._history.append(
            {
                "role": "user",
                "content": f"[Attached file {p.name}]\n```\n{shown}\n```",
            }
        )

    @staticmethod
    def _escape(s: str) -> str:
        """Escape text for safe insertion into a rich-text chat log."""
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def on_activate(self) -> None:
        self.msg_input.setFocus()
        if not self._client_checked:
            self._client_checked = True
            self._init_client()

    def _init_client(self) -> None:
        """Connect to the local LLM (same client the agent runtime uses)."""
        try:
            import main

            # Load saved .env so the Settings dropdown models take effect.
            env_path = HERE / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        os.environ[k.strip()] = v.strip()
            chat_model = os.environ.get("MODEL_GENERATOR", "phi4-mini-reasoning:3.8b")
            self._client = main.get_client(model=chat_model)
            self.chat_log.append(f"<i>[LLM connected — {chat_model}]</i>")
            win = self.window()
            if hasattr(win, "set_status"):
                win.set_status(f"Model: {chat_model} · Connected")
        except Exception as exc:
            self._client = None
            self.chat_log.append(f"<i>[No LLM detected ({exc}) — running in echo mode]</i>")
            win = self.window()
            if hasattr(win, "set_status"):
                win.set_status("No LLM detected · echo mode")

    def _send(self) -> None:
        if self._busy:
            return
        msg = self.msg_input.text().strip()
        self._last_user = msg
        if not msg:
            return
        self.msg_input.clear()
        self.chat_log.append(f"<b>You:</b> {msg}")
        self._busy = True

        # Slash commands handled locally (no model call).
        low = msg.lower()
        if low in ("/help", "/?"):
            self._append_assistant(self._help_text())
            self._busy = False
            return
        if low == "/tools":
            self._append_assistant(self._tools_text())
            self._busy = False
            return
        if low == "/clear":
            self._history.clear()
            self.chat_log.clear()
            self.chat_log.append("<i>[Chat history cleared]</i>")
            self._busy = False
            return
        if low.startswith("/read "):
            self._run_tool("read", {"path": msg[len("/read ") :].strip()})
            self._busy = False
            return
        if low.startswith("/web "):
            self._run_tool("web", {"url": msg[len("/web ") :].strip()})
            self._busy = False
            return
        if low.startswith("/py "):
            self._run_tool("py", {"code": msg[len("/py ") :].strip()})
            self._busy = False
            return

        if self._client is None:
            self._append_assistant(f"(echo) You said: {msg}")
            self._busy = False
            return

        self._history.append({"role": "user", "content": msg})

        if self._multi_models and len(self._multi_models) > 1:
            self.chat_log.append(f"<i>[Sending to {len(self._multi_models)} models...]</i>")
            self._cancel = False
            self.stop_btn.setVisible(True)
            self.stop_btn.setEnabled(True)
            for model in self._multi_models:
                threading.Thread(target=self._multi_stream, args=(msg, model), daemon=True).start()
            return

        self.chat_log.append("<i>Virgo is thinking...</i>")
        self._cancel = False
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        # Stream the reply off the GUI thread, then render it.
        threading.Thread(target=self._stream_reply, args=(msg,), daemon=True).start()

    def _build_system(self, user_msg: str) -> str:
        """Compose the system prompt for one turn, injecting RAG context.

        The persona (self._persona) is the base prompt; if a knowledge-base
        passage is relevant to the user's message we append it. Falls back to
        the persona alone when the KB is empty or no match is found.
        """
        system = self._persona
        try:
            from _rag import kb_context

            rag = kb_context(user_msg, top_k=3)
            if rag:
                system = f"{system}\n\n{rag}"
        except Exception:
            pass  # RAG is best-effort; never break chat on its failure
        return system

    def _stream_reply(self, msg: str) -> None:

        messages = [{"role": "system", "content": self._build_system(msg)}] + self._history
        # Forward streamed tokens into the chat box live (and keep the full text).
        collector = _GuiStream(self)
        old_stdout = sys.stdout
        sys.stdout = collector
        stopped = False
        try:
            reply = self._client.chat_stream(
                messages, temperature=self._temperature, max_tokens=2048, role="agent"
            )
        except _StopStream:
            stopped = True
            reply = ""
        except Exception as exc:
            reply = f"(LLM error: {exc})"
        finally:
            sys.stdout = old_stdout

        # User hit Stop — discard the partial reply, don't touch history.
        if stopped or self._cancel:
            QMetaObject.invokeMethod(self, "_finish_stop", Qt.ConnectionType.QueuedConnection)
            return

        # Ensure the final text is the collected reply (in case streaming
        # wrote partial chunks, the client returns the full string).
        if not reply:
            reply = collector.text
        # Schedule the final render on the GUI thread (cross-thread safe).
        QMetaObject.invokeMethod(
            self,
            "_render_reply",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, reply or "(empty response)"),
            Q_ARG(bool, collector._started),
        )

    def _stop(self) -> None:
        """Request cancellation of the in-flight stream."""
        if not self._busy:
            return
        self._cancel = True
        self.stop_btn.setEnabled(False)

    @pyqtSlot()
    def _finish_stop(self) -> None:
        self.chat_log.append("<i>(stopped by user)</i>")
        self.stop_btn.setVisible(False)
        self._cancel = False
        self._busy = False

    def _on_temp(self, val: int) -> None:
        self._temperature = val / 10.0
        self.temp_label.setText(f"{self._temperature:.1f}")

    def _update_token_count(self) -> None:
        text = self.msg_input.text()
        est = len(text) // 4 or 0
        self.token_label.setText(f"~{est} tokens (input)")

    def _on_input_typed(self, text: str) -> None:
        """Show the slash-command popup when the input starts with '/'."""
        if text.startswith("/") and " " not in text:
            self._show_slash_popup(text)
        elif self._slash_popup and self._slash_popup.isVisible():
            self._slash_popup.hide()

    def _show_slash_popup(self, prefix: str) -> None:
        if self._slash_popup is None:
            self._slash_popup = QListWidget()
            self._slash_popup.setParent(self)
            self._slash_popup.setWindowFlags(Qt.WindowType.Popup)
            self._slash_popup.itemClicked.connect(lambda _: self._slash_accept())
            t = self.window().themes.get(getattr(self.window(), "_active_theme", "mocha"), {})
            bg = t.get("surface", "#181825")
            fg = t.get("text", "#cdd6f4")
            self._slash_popup.setStyleSheet(
                f"QListWidget{{background:{bg};border:1px solid #45475a;"
                f"border-radius:6px;color:{fg};padding:4px;}}"
                f"QListWidget::item{{padding:4px 8px;border-radius:4px;}}"
                f"QListWidget::item:selected{{background:#45475a;color:#89b4fa;}}"
            )
        q = prefix[1:].lower()
        self._slash_popup.clear()
        for cmd, desc in self._slash_commands:
            if not q or cmd[1:].lower().startswith(q):
                item = QListWidgetItem(f"{cmd}  —  {desc}")
                item.setData(Qt.ItemDataRole.UserRole, cmd)
                self._slash_popup.addItem(item)
        if not self._slash_popup.count():
            self._slash_popup.hide()
            return
        self._slash_popup.setCurrentRow(0)
        # Position above the input box
        pos = self.msg_input.mapToGlobal(self.msg_input.rect().bottomLeft())
        self._slash_popup.move(pos.x(), pos.y() + 4)
        self._slash_popup.setMinimumWidth(self.msg_input.width())
        self._slash_popup.setVisible(True)

    def _slash_accept(self) -> None:
        if not self._slash_popup or not self._slash_popup.isVisible():
            return
        item = self._slash_popup.currentItem()
        if item:
            cmd = item.data(Qt.ItemDataRole.UserRole)
            # Keep arg placeholder (e.g. /read <path>) but strip the <...>
            base = cmd.split(" <")[0]
            self.msg_input.setText(base + (" " if "<" in cmd else ""))
            self.msg_input.setFocus()
        self._slash_popup.hide()

    def _on_persona(self, name: str) -> None:
        self._persona = self._personas.get(name, self._personas["Default"])
        self.chat_log.append(f"<i>[Persona: {name}]</i>")

    def _switch_model(self, model: str) -> None:
        """Reconnect the chat client to a different local model."""
        if not model or self._busy:
            return
        self._current_model = model
        try:
            import main

            self._client = main.get_client(model=model)
            self.chat_log.append(f"<i>[Switched model — {model}]</i>")
            win = self.window()
            if hasattr(win, "set_status"):
                win.set_status(f"Model: {model} · Connected")
        except Exception as exc:
            self._client = None
            self.chat_log.append(f"<i>[Model switch failed ({exc}) — echo mode]</i>")

    def _ab_compare(self) -> None:
        """Send the current prompt to two models and score both replies."""
        prompt = self.msg_input.text().strip()
        if not prompt:
            self.chat_log.append("<i>[Enter a prompt to A/B test]</i>")
            return
        models = [self._current_model] + [
            m for m in (self._multi_models or []) if m != self._current_model
        ][:1]
        if len(models) < 2:
            models = [self._current_model, "ornith:latest"]
        self.chat_log.append(f"<i>[A/B comparing {models[0]} vs {models[1]}…]</i>")
        for model in models:
            try:
                import main

                cli = main.get_client(model=model)
                reply = main.complete(cli, prompt, model=model)
            except Exception as exc:
                reply = f"(error: {exc})"
            score = self._score_reply(prompt, reply)
            self.chat_log.append(f"<b>[{model}] — score {score:.2f}</b><br>{_md_to_html(reply)}")
        self._save_chat()

    @staticmethod
    def _score_reply(prompt: str, reply: str) -> float:
        """Heuristic quality score: length + overlap with prompt keywords."""
        import re as _re

        words = _re.findall(r"\w+", reply.lower())
        if not words:
            return 0.0
        pwords = set(_re.findall(r"\w+", prompt.lower()))
        overlap = len([w for w in words if w in pwords]) / max(1, len(pwords))
        length_ok = min(1.0, len(words) / 150.0)
        return round((0.6 * length_ok + 0.4 * overlap) * 10, 2)

    def _toggle_multi(self) -> None:
        """Open a dialog to select models for multi-model chat."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Multi-model — select models")
        dlg.resize(300, 350)
        dlg.setStyleSheet("QDialog { background: #1e1e2e; }")
        lo = QVBoxLayout(dlg)
        lo.addWidget(QLabel("<b style='color:#cdd6f4;'>Select 2+ models:</b>"))

        checks: list[tuple[QCheckBox, str]] = []
        for m in getattr(self, "_available_models", []) or [
            self.model_combo.itemText(i) for i in range(self.model_combo.count())
        ]:
            if not m:
                continue
            cb = QCheckBox(m)
            cb.setStyleSheet("color:#cdd6f4;")
            cb.setChecked(m in self._multi_models)
            lo.addWidget(cb)
            checks.append((cb, m))

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; border-radius:6px; padding:6px 16px;"
        )
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background:#313244; color:#cdd6f4; border-radius:6px; padding:6px 16px;"
        )
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lo.addLayout(btn_row)

        if dlg.exec():
            self._multi_models = [m for cb, m in checks if cb.isChecked()]
            self.multi_btn.setChecked(bool(self._multi_models))
            if self._multi_models:
                self.multi_btn.setText(f"M ({len(self._multi_models)})")
                self.chat_log.append(f"<i>[Multi-mode: {', '.join(self._multi_models)}]</i>")
            else:
                self.multi_btn.setText("M")

    def _multi_stream(self, msg: str, model: str) -> None:
        """Send to a single model in multi-mode."""
        import main

        try:
            client = main.get_client(model=model)
            system = self._build_system(msg)
            msgs = [{"role": "system", "content": system}] + self._history
            reply = client.chat_stream(msgs, temperature=self._temperature, max_tokens=2048)
        except Exception as exc:
            reply = f"(error: {exc})"

        # Append model's response to chat log (cross-thread safe).
        QMetaObject.invokeMethod(
            self,
            "_append_multi_reply",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, model),
            Q_ARG(str, reply or "(empty)"),
        )

    @pyqtSlot(str, str)
    def _append_multi_reply(self, model: str, reply: str) -> None:
        self.chat_log.append(f"<hr><b>{model}</b><br>{reply}")
        self._history.append({"role": "assistant", "content": f"[{model}] {reply}"})
        if all(f"[{m}]" in str(self._history) for m in self._multi_models):
            self._busy = False
            self.stop_btn.setVisible(False)

    @pyqtSlot()
    def _stream_start(self) -> None:
        """Replace the 'thinking...' placeholder with the live reply line."""
        self._stream_chars = 0
        self._stream_t0 = __import__("time").time()
        cursor = self.chat_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText("<b>Virgo:</b> ")
        self.chat_log.moveCursor(cursor.MoveOperation.End)

    @pyqtSlot(str)
    def _stream_chunk(self, chunk: str) -> None:
        """Append one streamed chunk to the live reply line."""
        self.chat_log.insertHtml(self._escape(chunk))
        self.chat_log.verticalScrollBar().setValue(self.chat_log.verticalScrollBar().maximum())
        # Live token-rate estimate
        self._stream_chars += len(chunk)
        elapsed = __import__("time").time() - self._stream_t0
        if elapsed > 0.3:
            tps = (self._stream_chars / 4) / elapsed
            self.token_label.setText(f"~{tps:.1f} tok/s · {self._stream_chars // 4} tok")

    @pyqtSlot(str, bool)
    def _render_reply(self, reply: str, streamed: bool = False) -> None:
        reply = _strip_think(reply)
        self._last_reply = reply
        est = (len(reply) + len(self._last_user)) // 4
        self.token_label.setText(f"~{est} tokens")
        if streamed:
            # Replace the streamed plain-text with full markdown rendering.
            cursor = self.chat_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertHtml(_md_to_html(reply))
            self.chat_log.moveCursor(cursor.MoveOperation.End)
        else:
            # Replace the trailing "thinking..." line with the real reply.
            cursor = self.chat_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText("")  # clear the empty block left behind
            self.chat_log.append("")  # re-add a clean paragraph
            self._append_assistant(reply)
        self._history.append({"role": "assistant", "content": reply})

        # Detect local image paths in the reply and add to gallery.
        import re

        for m in re.findall(
            r"(?:!\[[^\]]*\]\(([^)]+)\)|`?([\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp))`?)",
            reply,
            re.IGNORECASE,
        ):
            cand = m[0] or m[1]
            if cand and not cand.startswith("http"):
                self._add_to_gallery(cand)
        from cli import _CHAT_TOOLS, _parse_tool_calls, _run_chat_tool  # lazy import (safe)

        for tname, tkwargs in _parse_tool_calls(reply):
            if tname in _CHAT_TOOLS:
                try:
                    out = _run_chat_tool(tname, tkwargs)
                except Exception as exc:
                    out = f"(tool error: {exc})"
                self._append_assistant(f"[tool {tname}] {out[:800]}")
                self._history.append({"role": "system", "content": f"[tool {tname}] {out}"})
            else:
                self._append_assistant(f"[tool {tname}] not allowed")

        self.stop_btn.setVisible(False)
        self._busy = False
        self._save_chat()

    def _show_search(self) -> None:
        """Open a small search bar to find text in the chat log."""
        if getattr(self, "_search_bar", None) is None:
            self._search_bar = QLineEdit()
            self._search_bar.setPlaceholderText("Search chat… (Enter = next, Shift+Enter = prev)")
            self._search_bar.returnPressed.connect(lambda: self._search_next(False))
            self._search_bar.setObjectName("searchBar")
            self.content.addWidget(self._search_bar)
        self._search_bar.setVisible(True)
        self._search_bar.setFocus()
        self._search_bar.selectAll()
        self._search_bar.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """ChatPage-level key handling: slash popup nav + search bar."""
        t = event.type()
        # Chat search bar: Shift+Enter = previous match
        if obj is getattr(self, "_search_bar", None) and t == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_Return
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._search_next(True)
                return True
        # Slash popup keyboard nav (typed in msg_input)
        popup = getattr(self, "_slash_popup", None)
        if obj is getattr(self, "msg_input", None) and popup and popup.isVisible():
            if t == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Down:
                    popup.setCurrentRow(min(popup.currentRow() + 1, popup.count() - 1))
                    return True
                if key == Qt.Key.Key_Up:
                    popup.setCurrentRow(max(popup.currentRow() - 1, 0))
                    return True
                if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return):
                    self._slash_accept()
                    return True
                if key == Qt.Key.Key_Escape:
                    popup.hide()
                    return True
        return super().eventFilter(obj, event)

    def _search_next(self, backward: bool) -> bool:
        bar = getattr(self, "_search_bar", None)
        if not bar or not bar.isVisible():
            return False
        needle = bar.text()
        if not needle:
            return False
        cur = self.chat_log.textCursor()
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = cur.isNull() and self.chat_log.document().find(needle, 0, flags) or cur
        if found.isNull() or not found.selectedText():
            found = self.chat_log.document().find(needle, cur, flags)
        if found.isNull():
            # Wrap around
            new_cur = self.chat_log.textCursor()
            new_cur.movePosition(
                new_cur.MoveOperation.End if backward else new_cur.MoveOperation.Start
            )
            found = self.chat_log.document().find(needle, new_cur, flags)
        if not found.isNull() and found.selectedText():
            self.chat_log.setTextCursor(found)
            bar.setStyleSheet("")
            return True
        bar.setStyleSheet("border: 1px solid #f38ba8;")
        return False

    def _branch_from(self) -> None:
        """Fork the conversation: keep history up to the last user message."""
        # Find the last user message index in history
        last_user = -1
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i]["role"] == "user":
                last_user = i
                break
        if last_user < 0:
            self.chat_log.append("<i>[Nothing to branch from]</i>")
            return
        branch = self._history[: last_user + 1]
        # Start a fresh branch in a new session id
        self._history[:] = branch
        self._session_id = __import__("uuid").uuid4().hex[:12]
        self.chat_log.append(f"<hr><i>[Branched — new session {self._session_id}]</i><hr>")
        self._save_chat()
        self.msg_input.setFocus()

    def _append_assistant(self, text: str) -> None:
        self.chat_log.append(f"<b>Virgo:</b> {_md_to_html(text)}")

    def _copy_reply(self) -> None:
        """Copy Virgo's last reply to the clipboard."""
        text = getattr(self, "_last_reply", "")
        if not text:
            self.chat_log.append("<i>[No reply to copy yet]</i>")
            return
        QApplication.clipboard().setText(text)
        self.chat_log.append("<i>[Copied last reply to clipboard]</i>")

    def _copy_markdown(self) -> None:
        """Copy the entire conversation as Markdown to the clipboard."""
        if not self._history:
            self.chat_log.append("<i>[Nothing to copy yet]</i>")
            return
        md_lines = []
        for msg in self._history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                md_lines.append(f"**You:** {content}")
            elif role == "assistant":
                md_lines.append(f"**Virgo:** {content}")
            else:
                md_lines.append(f"*{role}:* {content}")
            md_lines.append("")
        QApplication.clipboard().setText("\n".join(md_lines))
        self.chat_log.append("<i>[Copied full chat as Markdown]</i>")

    def _zoom_font(self, delta: int) -> None:
        """Zoom chat font: +1 / -1 step, or 0 to reset."""
        if delta == 0:
            self._chat_font_size = 13
        else:
            self._chat_font_size = max(9, min(24, self._chat_font_size + delta))
        self.chat_log.setStyleSheet(f"QTextEdit {{ font-size: {self._chat_font_size}px; }}")
        if delta != 0:
            self.chat_log.append(f"<i>[Font size: {self._chat_font_size}px]</i>")

    def _toggle_split(self) -> None:
        """Toggle a side-by-side comparison view (second chat log)."""
        if self.split_btn.isChecked():
            if not hasattr(self, "_split_log"):
                self._split_log = QTextEdit()
                self._split_log.setReadOnly(True)
                self._split_log.setPlaceholderText(
                    "Comparison pane — paste or compare output here."
                )
                self._split_log.setStyleSheet(f"font-size: {self._chat_font_size}px;")
                self.content.addWidget(self._split_log)
            self._split_log.setVisible(True)
            self.chat_log.append("<i>[Split view ON]</i>")
        else:
            if hasattr(self, "_split_log"):
                self._split_log.setVisible(False)
            self.chat_log.append("<i>[Split view OFF]</i>")

    def _regenerate(self) -> None:
        """Re-ask the last user message, dropping the previous reply."""
        if self._busy:
            return
        user = getattr(self, "_last_user", "")
        if not user:
            self.chat_log.append("<i>[Nothing to regenerate]</i>")
            return
        # Drop the trailing assistant + tool/system turn for a clean re-ask.
        while self._history and self._history[-1]["role"] in ("assistant", "system"):
            self._history.pop()
        self.msg_input.setText(user)
        self._send()

    def _export(self) -> None:
        """Save the conversation to Markdown, JSON, or plain text."""
        from datetime import datetime

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export chat",
            "virgo-chat.md",
            "Markdown (*.md);;JSON (*.json);;Text (*.txt)",
        )
        if not path:
            return
        if path.endswith(".json"):
            payload = {
                "exported": datetime.now().isoformat(),
                "messages": self._history,
            }
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            Path(path).write_text(self.chat_log.toPlainText(), encoding="utf-8")
        self.chat_log.append(f"<i>[Exported to {Path(path).name}]</i>")

    def _save_chat(self) -> None:
        """Persist the current conversation to a JSON file."""
        if not self._history:
            return
        payload = {
            "session_id": self._session_id,
            "model": self._current_model,
            "messages": self._history,
        }
        path = _chat_session_path()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ── Prompt Library (side panel) ─────────────────────────────────────
    _PROMPTS_DIR = Path(__file__).parent / ".virgo_prompts"

    def _setup_prompt_panel(self) -> None:
        """Build the docked prompt library panel alongside the chat area."""
        self._prompt_panel = QWidget()
        self._prompt_panel.setObjectName("promptPanel")
        self._prompt_panel.setStyleSheet(
            "#promptPanel { background: #181825; border-left: 1px solid #313244; }"
        )
        self._prompt_panel.setMinimumWidth(280)
        self._prompt_panel.setMaximumWidth(400)
        self._prompt_panel.setVisible(False)

        p_layout = QVBoxLayout(self._prompt_panel)
        p_layout.setContentsMargins(10, 10, 10, 10)
        p_layout.setSpacing(6)

        # ── Header ──
        header_row = QHBoxLayout()
        title = QLabel("📋  Prompt Library")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        header_row.addWidget(title)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #6c7086; font-size: 14px; }"
            "QPushButton:hover { color: #f38ba8; }"
        )
        close_btn.clicked.connect(lambda: self._toggle_prompt_panel(False))
        header_row.addWidget(close_btn)
        p_layout.addLayout(header_row)

        # ── Search ──
        self._prompt_search = QLineEdit()
        self._prompt_search.setPlaceholderText("Search prompts...")
        self._prompt_search.setStyleSheet(
            "QLineEdit { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; font-size: 12px; }"
        )
        self._prompt_search.textChanged.connect(self._filter_prompt_list)
        p_layout.addWidget(self._prompt_search)

        # ── Category tabs ──
        cat_row = QHBoxLayout()
        cat_row.setSpacing(4)
        self._cat_buttons: dict[str, QPushButton] = {}
        for cat in ("All", "General", "Code", "Debug", "Custom"):
            btn = QPushButton(cat)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { background: #11111b; border: 1px solid #313244; "
                "border-radius: 4px; padding: 2px 8px; color: #6c7086; "
                "font-size: 11px; }"
                "QPushButton:checked { background: #313244; color: #89b4fa; "
                "border-color: #89b4fa; }"
                "QPushButton:hover { color: #cdd6f4; }"
            )
            btn.clicked.connect(lambda checked=False, c=cat: self._select_prompt_category(c))
            cat_row.addWidget(btn)
            self._cat_buttons[cat] = btn
        cat_row.addStretch()
        p_layout.addLayout(cat_row)
        self._cat_buttons["All"].setChecked(True)
        self._prompt_category = "All"

        # ── Prompt list ──
        self._prompt_list = QListWidget()
        self._prompt_list.setStyleSheet(
            "QListWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; font-size: 12px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #11111b; }"
            "QListWidget::item:hover { background: #313244; }"
            "QListWidget::item:selected { background: #45475a; color: #89b4fa; }"
        )
        self._prompt_list.itemDoubleClicked.connect(self._load_selected_prompt)
        p_layout.addWidget(self._prompt_list, 1)

        # ── Save row ──
        save_row = QHBoxLayout()
        self._prompt_name_input = QLineEdit()
        self._prompt_name_input.setPlaceholderText("New prompt name...")
        self._prompt_name_input.setStyleSheet(
            "QLineEdit { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; padding: 4px 8px; color: #cdd6f4; font-size: 12px; }"
        )
        save_row.addWidget(self._prompt_name_input, 1)
        save_btn = QPushButton("💾")
        save_btn.setFixedSize(30, 30)
        save_btn.setToolTip("Save current input as a prompt")
        save_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background: #45475a; }"
        )
        save_btn.clicked.connect(self._save_prompt_from_panel)
        save_row.addWidget(save_btn)
        p_layout.addLayout(save_row)

        # ── Category chooser for save ──
        cat_save_row = QHBoxLayout()
        cat_save_row.addWidget(QLabel("Category:"))
        self._prompt_cat_combo = QComboBox()
        self._prompt_cat_combo.addItems(["General", "Code", "Debug", "Custom"])
        self._prompt_cat_combo.setStyleSheet(
            "QComboBox { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; padding: 3px 6px; color: #cdd6f4; font-size: 11px; }"
        )
        cat_save_row.addWidget(self._prompt_cat_combo, 1)
        cat_save_row.addStretch()
        p_layout.addLayout(cat_save_row)

        # Insert the panel into the parent layout (next to chat area)
        parent_layout = self.content.layout() if self.content.layout() else None
        if parent_layout:
            # We need to insert it after the chat log. Since we can't easily
            # restructure, we'll add it as the last widget in content.
            pass
        self.content.addWidget(self._prompt_panel)

        # Load prompts
        self._refresh_prompt_list()

        # ── Keyboard shortcut ──
        self._prompt_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self._prompt_shortcut.activated.connect(self._toggle_prompt_panel)

        # ── Prompt panel timer (auto-refresh) ──
        self._prompt_timer = QTimer()
        self._prompt_timer.setInterval(3000)
        self._prompt_timer.timeout.connect(self._refresh_prompt_list)
        self._prompt_timer.start()

    def _toggle_prompt_panel(self, show: bool | None = None) -> None:
        """Show or hide the prompt library side panel."""
        if show is None:
            show = not self._prompt_panel.isVisible()
        self._prompt_panel.setVisible(show)
        if show:
            self._refresh_prompt_list()
            self._prompt_search.setFocus()

    def _refresh_prompt_list(self) -> None:
        """Reload prompts from disk into the list (preserving filter)."""
        self._PROMPTS_DIR.mkdir(exist_ok=True)
        self._all_prompts: list[dict] = []
        for pf in sorted(self._PROMPTS_DIR.glob("*.json")):
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                data["_path"] = str(pf)
                self._all_prompts.append(data)
            except Exception:
                pass
        self._filter_prompt_list()

    def _filter_prompt_list(self) -> None:
        """Apply search + category filter and refresh the list widget."""
        self._prompt_list.clear()
        query = self._prompt_search.text().strip().lower()
        for data in getattr(self, "_all_prompts", []):
            name = data.get("name", "").lower()
            text = data.get("text", "").lower()
            cat = data.get("category", "General")
            if self._prompt_category != "All" and cat != self._prompt_category:
                continue
            if query and query not in name and query not in text:
                continue
            display = data.get("name", "Unnamed")
            icon_str = {"General": "📝", "Code": "💻", "Debug": "🐛", "Custom": "⭐"}.get(cat, "📄")
            item = QListWidgetItem(f"{icon_str}  {display}")
            item.setData(Qt.ItemDataRole.UserRole, data.get("_path", ""))
            self._prompt_list.addItem(item)

    def _select_prompt_category(self, cat: str) -> None:
        """Switch active category filter."""
        self._prompt_category = cat
        for name, btn in self._cat_buttons.items():
            btn.setChecked(name == cat)
        self._filter_prompt_list()

    def _load_selected_prompt(self, item: QListWidgetItem) -> None:
        """Load the selected prompt into the chat input."""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.msg_input.setText(data.get("text", ""))
            self.msg_input.setFocus()
        except Exception:
            pass

    def _save_prompt_from_panel(self) -> None:
        """Save the current chat input as a new prompt."""
        name = self._prompt_name_input.text().strip()
        text = self.msg_input.text().strip()
        if not name or not text:
            self.chat_log.append("<i>[Enter a name and some text to save a prompt]</i>")
            return
        cat = self._prompt_cat_combo.currentText()
        slug = name.lower().replace(" ", "_").replace("/", "_")
        payload = {"name": name, "text": text, "category": cat}
        dest = self._PROMPTS_DIR / f"{slug}.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._prompt_name_input.clear()
        self._refresh_prompt_list()
        self.chat_log.append(f"<i>[Saved prompt: {name}]</i>")

    def _show_prompt_lib(self) -> None:
        """Toggle the prompt panel (replaces old dialog)."""
        self._toggle_prompt_panel()
        if self._prompt_panel.isVisible():
            # Hides the prompt panel - if user was expecting dialog, toggle on
            pass

    def _speak_reply(self) -> None:
        """Read the last assistant reply aloud via edge-tts."""
        text = getattr(self, "_last_reply", "")
        if not text:
            self.chat_log.append("<i>[No reply to speak]</i>")
            return
        self.speak_btn.setEnabled(False)
        threading.Thread(target=self._speak_async, args=(text,), daemon=True).start()

    def _speak_async(self, text: str) -> None:
        try:
            import asyncio
            import tempfile

            import edge_tts

            communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            path = tmp.name
            tmp.close()
            asyncio.run(communicate.save(path))
            os.startfile(path)  # Windows default player
        except Exception as exc:
            QMetaObject.invokeMethod(
                self,
                "_append_log",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, f"<i>[TTS error: {exc}]</i>"),
            )
        finally:
            QMetaObject.invokeMethod(
                self,
                "_enable_btn",
                Qt.ConnectionType.QueuedConnection,
            )

    def _mic_input(self) -> None:
        """Transcribe microphone input and fill the message box."""
        self.mic_btn.setEnabled(False)
        threading.Thread(target=self._mic_async, daemon=True).start()

    def _mic_async(self) -> None:
        try:
            import speech_recognition as sr

            r = sr.Recognizer()
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.3)
                audio = r.listen(source, timeout=5, phrase_time_limit=15)
            text = r.recognize_google(audio)
            err = ""
        except ImportError:
            text = ""
            err = "speech_recognition not installed"
        except sr.WaitTimeoutError:
            text = ""
            err = "No speech detected"
        except Exception as exc:
            text = ""
            err = str(exc)
        QMetaObject.invokeMethod(
            self,
            "_mic_done",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, text),
            Q_ARG(str, err),
        )

    @pyqtSlot(str, str)
    def _mic_done(self, text: str, err: str) -> None:
        self.mic_btn.setEnabled(True)
        if text:
            self.msg_input.setText(text)
            self.msg_input.setFocus()
            if self.voice_mode.isChecked():
                self._send()
        elif err:
            self.chat_log.append(f"<i>[Mic: {err}]</i>")

    @pyqtSlot()
    def _enable_btn(self) -> None:
        self.speak_btn.setEnabled(True)

    @pyqtSlot(str)
    def _append_log(self, html: str) -> None:
        self.chat_log.append(html)

    def _handle_image_drop(self, path: str) -> None:
        """Insert a dropped image into the chat log and history."""
        self.chat_log.append(f"<b>You:</b> <img src='file:///{path}' width='400'><br>")
        self._history.append({"role": "user", "content": f"[image: {path}]"})
        self._save_chat()
        self._last_user = f"[image: {path}]"
        self._add_to_gallery(path)

    def _add_to_gallery(self, path: str) -> None:
        """Add an image thumbnail to the gallery strip (files only)."""
        from PyQt6.QtGui import QIcon, QPixmap

        p = Path(path)
        if not p.exists() or not p.is_file():
            return
        try:
            pm = QPixmap(str(p)).scaled(
                64,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item = QListWidgetItem(QIcon(pm), p.name)
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self.gallery.addItem(item)
            self.gallery.setVisible(True)
        except Exception:
            pass

    def _open_gallery_image(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            import webbrowser

            webbrowser.open(f"file:///{path}")

    def _chat_context_menu(self, pos) -> None:
        """Right-click on chat log: edit & resend last user message."""
        menu = self.chat_log.createStandardContextMenu()
        if self._last_user:
            act = menu.addAction(f"{icon('edit')}  Edit & Resend")
            act.triggered.connect(self._edit_last_message)
        menu.exec(self.chat_log.viewport().mapToGlobal(pos))

    def _edit_last_message(self) -> None:
        """Load the last user message into input for editing + resend."""
        text = self._last_user
        # Strip HTML tags for editing
        import re

        text = re.sub(r"<[^>]+>", "", text)
        self.msg_input.setText(text)
        self.msg_input.setFocus()

    def _load_history(self, msgs: list[dict], model: str = "", sid: str = "") -> None:
        self._history[:] = list(msgs)
        self._current_model = model or self._current_model
        self._session_id = sid or self._session_id
        self.model_combo.setCurrentText(self._current_model)
        for m in self._history:
            role = m.get("role", "?")
            content = m.get("content", "")
            if role == "user":
                self.chat_log.append(f"<b>You:</b> {content[:200]}")
            elif role == "assistant":
                self.chat_log.append(f"<b>Virgo:</b> {_md_to_html(content[:500])}")
            else:
                self.chat_log.append(f"<i>[{role}]: {content[:200]}</i>")
        self.chat_log.append(f"<i>— Loaded {len(msgs)} messages from {sid or 'session'} —</i>")
        self._save_chat()

    @staticmethod
    def _help_text() -> str:
        return (
            "Commands: /help, /tools, /clear, "
            "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;. "
            "Otherwise just chat — the model can call tools via "
            "[[virgo.read path=...]] etc."
        )

    @staticmethod
    def _tools_text() -> str:
        return (
            "Safe local tools: read &lt;path&gt; · write &lt;path&gt; &lt;text&gt; · "
            "web &lt;url&gt; · py &lt;code&gt;. The model may also invoke them "
            "with [[virgo.&lt;tool&gt; ...]] calls."
        )


class PluginsPage(PageWidget):
    """Browse, create, and manage virgo plugins."""

    def __init__(self) -> None:
        super().__init__(
            "Plugins",
            "Dynamic tool plugins loaded from plugins/ and ~/.virgo/plugins/.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
            QPushButton(f"{icon('run')}  Reload enabled", clicked=self._reload_all),
            QPushButton(f"{icon('file')}  New plugin", clicked=self._new_plugin),
        )

        self.list = QListWidget()
        self.list.setMinimumHeight(200)
        self._add(self.list)

        self._add_row(
            QPushButton(f"{icon('file')}  Open", clicked=self._open),
            QPushButton(f"{icon('refresh')}  Toggle enable", clicked=self._toggle),
            QPushButton(f"{icon('delete')}  Delete", clicked=self._delete),
        )

        self.status = QLabel("No plugins found.")
        self._add(self.status)

        self._enabled: set[str] = set()

    def on_activate(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        try:
            from plugins import discover

            files = discover()
        except Exception as exc:
            self.status.setText(f"Error: {exc}")
            return
        if not files:
            self.status.setText("No plugins in plugins/ or ~/.virgo/plugins/")
            return
        for f in files:
            item = QListWidgetItem(f"{f.parent.name}/{f.name}")
            item.setData(256, str(f))  # Qt.UserRole
            self.list.addItem(item)
            self._enabled.add(str(f))
        self.status.setText(f"{len(files)} plugin(s)")

    def _reload_all(self) -> None:
        try:
            from plugins import discover, load_path
            from tools import ToolRegistry

            reg = ToolRegistry()
            loaded = 0
            for f in discover():
                if str(f) in self._enabled:
                    load_path(f, reg)
                    loaded += 1
            self.status.setText(f"Reloaded {loaded} enabled plugin(s)")
        except Exception as exc:
            self.status.setText(f"Reload error: {exc}")

    def _selected(self) -> str | None:
        it = self.list.currentItem()
        return it.data(256) if it else None

    def _open(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        from virgo_desktop import _open_file

        _open_file(p)

    def _toggle(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        if p in self._enabled:
            self._enabled.discard(p)
            self.status.setText(f"Disabled {Path(p).name}")
        else:
            self._enabled.add(p)
            self.status.setText(f"Enabled {Path(p).name}")

    def _delete(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        try:
            Path(p).unlink()
            self.status.setText(f"Deleted {Path(p).name}")
        except Exception as exc:
            self.status.setText(f"Delete failed: {exc}")
        self._refresh()

    def _new_plugin(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("New plugin")
        dlg.resize(540, 440)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("File name (e.g. my_tool.py):"))
        name_edit = QLineEdit("my_tool.py")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("Code:"))
        code_edit = QPlainTextEdit()
        code_edit.setPlainText(
            "def register(registry):\n"
            "    from tools import Tool\n"
            "    def run(query: str) -> str:\n"
            '        return f"echo: {query}"\n'
            '    registry.register(Tool(name="my tool", fn=run,\n'
            '                             description="Example plugin tool"))\n'
        )
        layout.addWidget(code_edit, 1)
        btns = QHBoxLayout()
        ok = QPushButton("Create")
        cancel = QPushButton("Cancel")
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        def do_create() -> None:
            name = name_edit.text().strip()
            if not name.endswith(".py"):
                name += ".py"
            try:
                from plugins import create_plugin

                create_plugin(name, code_edit.toPlainText())
                self.status.setText(f"Created {name}")
                dlg.accept()
                self._refresh()
            except Exception as exc:
                self.status.setText(f"Create failed: {exc}")

        ok.clicked.connect(do_create)
        cancel.clicked.connect(dlg.reject)
        dlg.exec()


class McpPage(PageWidget):
    """Configure Virgo as an MCP server and connect to external MCP servers."""

    def __init__(self) -> None:
        super().__init__(
            "MCP",
            "Expose Virgo tools to MCP hosts, or connect to external MCP servers.",
        )

        # ── Expose Virgo (server mode) ──
        srv = self._section("Expose Virgo (act as MCP server)")
        srv.layout().addWidget(
            QLabel(  # type: ignore
                "Register this in your MCP host (Claude Desktop, Cursor, etc.):"
            )
        )
        self.config_view = QPlainTextEdit()
        self.config_view.setReadOnly(True)
        self.config_view.setMaximumHeight(150)
        try:
            cfg = {
                "mcpServers": {
                    "virgo": {
                        "command": sys.executable,
                        "args": [str(HERE / "mcp_server.py")],
                    }
                }
            }
            self.config_view.setPlainText(json.dumps(cfg, indent=2))
            from mcp_server import PROTOCOL_VERSION, SERVER_INFO, _build_registry

            reg = _build_registry()
            info = (
                f"Protocol {PROTOCOL_VERSION} · {SERVER_INFO['name']} "
                f"v{SERVER_INFO['version']} · {len(reg.list())} tool(s) exposed"
            )
        except Exception as exc:
            info = f"Could not build registry: {exc}"
        srv.layout().addWidget(self.config_view)  # type: ignore
        copy_row = QHBoxLayout()
        copy_row.addWidget(QPushButton(f"{icon('file')}  Copy config", clicked=self._copy_config))
        copy_row.addStretch()
        srv.layout().addLayout(copy_row)  # type: ignore
        srv.layout().addWidget(QLabel(info))  # type: ignore

        # ── Connect to MCP servers (client mode) ──
        cli = self._section("Connect to MCP servers")
        cli.layout().addWidget(
            QLabel(  # type: ignore
                "Discovered from .mcp.json / claude_desktop_config.json / ~/.gemini"
            )
        )
        self.server_list = QListWidget()
        self.server_list.setMinimumHeight(120)
        self.server_list.currentItemChanged.connect(self._on_select_server)
        cli.layout().addWidget(self.server_list)  # type: ignore
        self.server_status = QLabel("No servers discovered yet.")
        cli.layout().addWidget(self.server_status)  # type: ignore
        self.tools_view = QPlainTextEdit()
        self.tools_view.setReadOnly(True)
        self.tools_view.setMaximumHeight(130)
        cli.layout().addWidget(self.tools_view)  # type: ignore

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh_servers)
        )
        ctrl_row.addWidget(QPushButton(f"{icon('file')}  Add server", clicked=self._add_server))
        ctrl_row.addWidget(QPushButton(f"{icon('run')}  Test selected", clicked=self._test_server))
        ctrl_row.addStretch()
        cli.layout().addLayout(ctrl_row)  # type: ignore

        self._servers: dict[str, list[str]] = {}

    def on_activate(self) -> None:
        self._refresh_servers()

    def _copy_config(self) -> None:
        QApplication.clipboard().setText(self.config_view.toPlainText())
        self.server_status.setText("Config copied to clipboard.")

    def _refresh_servers(self) -> None:
        self.server_list.clear()
        self._servers = {}
        try:
            from mcp_bridge import discover_mcp_servers

            specs = discover_mcp_servers()
        except Exception as exc:
            self.server_status.setText(f"Error: {exc}")
            return
        if not specs:
            self.server_status.setText("No MCP servers discovered.")
            return
        for name, cmd in specs.items():
            item = QListWidgetItem(f"{name}  —  {' '.join(cmd)}")
            item.setData(256, name)  # Qt.UserRole
            self.server_list.addItem(item)
            self._servers[name] = cmd
        self.server_status.setText(f"{len(specs)} server(s) discovered.")

    def _add_server(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Add MCP server")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Name:"))
        name_edit = QLineEdit("myserver")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("Command (e.g. python server.py --port 8080):"))
        cmd_edit = QLineEdit()
        layout.addWidget(cmd_edit)
        btns = QHBoxLayout()
        ok = QPushButton("Add")
        cancel = QPushButton("Cancel")
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        def do_add() -> None:
            name = name_edit.text().strip()
            cmd = cmd_edit.text().strip().split()
            if not name or not cmd:
                return
            cfg_path = HERE / ".mcp.json"
            data: dict[str, Any] = {"mcpServers": {}}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text())
                    data.setdefault("mcpServers", {})
                except Exception:
                    pass
            data["mcpServers"][name] = {"command": cmd[0], "args": cmd[1:]}
            cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            dlg.accept()
            self._refresh_servers()

        ok.clicked.connect(do_add)
        cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _selected_server(self) -> str | None:
        it = self.server_list.currentItem()
        return it.data(256) if it else None

    def _on_select_server(self, current, _prev) -> None:
        name = self._selected_server()
        if name and name in self._servers:
            self.server_status.setText(f"{name}: {' '.join(self._servers[name])}")

    def _test_server(self) -> None:
        name = self._selected_server()
        if not name or name not in self._servers:
            self.server_status.setText("Select a discovered server first.")
            return
        cmd = self._servers[name]
        self.tools_view.clear()
        self.server_status.setText(f"Testing {name}...")
        try:
            from mcp_bridge import McpServer

            srv = McpServer(name, cmd)
            if srv.start(timeout=15):
                tools = srv.list_tool_specs()
                self.tools_view.setPlainText(
                    "\n".join(f"- {t.get('name')}: {t.get('description', '')}" for t in tools)
                )
                self.server_status.setText(f"{name}: {len(tools)} tool(s) reachable")
                srv.stop()
            else:
                self.server_status.setText(f"{name}: could not start / unreachable")
        except Exception as exc:
            self.server_status.setText(f"Test failed: {exc}")


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


# ═══════════════════════════════════════════════════════════════════════
# Network Scanner page
# ═══════════════════════════════════════════════════════════════════════


class NetworkPage(PageWidget):
    """Recon Dashboard + Attack Surface Map — device discovery, port scan, topology."""

    def __init__(self) -> None:
        super().__init__(
            "Recon",
            "Device discovery, port scanning & attack surface visualization.",
        )

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Target:"))
        self.subnet_input = QLineEdit("192.168.1.0/24")
        self.subnet_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        self.subnet_input.setFixedWidth(150)
        ctrl_row.addWidget(self.subnet_input)
        self.scan_btn = QPushButton("🔍  Scan")
        self.scan_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        self.scan_btn.clicked.connect(self._scan)
        ctrl_row.addWidget(self.scan_btn)
        self.auto_cb = QCheckBox("Auto (30s)")
        self.auto_cb.setStyleSheet("color: #a6adc8;")
        self.auto_cb.toggled.connect(self._toggle_auto)
        ctrl_row.addWidget(self.auto_cb)
        self.export_btn = QPushButton("💾  Export")
        self.export_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 10px; color: #cdd6f4; font-size: 11px; }"
        )
        self.export_btn.clicked.connect(self._export)
        ctrl_row.addWidget(self.export_btn)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Tab widget: Devices | Topology | Port Scanner ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #313244; border-radius: 6px; "
            "background: #1e1e2e; }"
            "QTabBar::tab { background: #181825; border: 1px solid #313244; "
            "border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; "
            "padding: 6px 14px; margin-right: 2px; color: #6c7086; }"
            "QTabBar::tab:selected { background: #313244; color: #89b4fa; font-weight: bold; }"
            "QTabBar::tab:hover { color: #cdd6f4; }"
        )

        # ── Tab 1: Recon Dashboard (device cards / table) ──
        dev_tab = QWidget()
        dev_lo = QVBoxLayout(dev_tab)
        dev_lo.setContentsMargins(8, 8, 8, 8)

        self._device_table = QTableWidget(0, 5)
        self._device_table.setHorizontalHeaderLabels(["IP", "Hostname", "MAC", "Vendor", "Status"])
        self._device_table.setAlternatingRowColors(True)
        self._device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._device_table.verticalHeader().setVisible(False)
        self._device_table.horizontalHeader().setStretchLastSection(True)
        self._device_table.setColumnWidth(0, 130)
        self._device_table.setColumnWidth(1, 150)
        self._device_table.setColumnWidth(2, 140)
        self._device_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: none; border-radius: 6px; "
            "color: #cdd6f4; gridline-color: #313244; font-size: 12px; }"
            "QTableWidget::item { padding: 4px 8px; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 6px; color: #a6adc8; font-weight: bold; }"
        )
        dev_lo.addWidget(self._device_table)

        self._device_count = QLabel("0 devices")
        self._device_count.setStyleSheet("color: #a6adc8; font-size: 12px; padding: 2px;")
        dev_lo.addWidget(self._device_count)
        self._tabs.addTab(dev_tab, "📋  Devices")

        # ── Tab 2: Attack Surface Map (topology graph) ──
        topo_tab = QWidget()
        topo_lo = QVBoxLayout(topo_tab)
        topo_lo.setContentsMargins(8, 8, 8, 8)

        self._topo_scene = QGraphicsScene()
        self._topo_view = QGraphicsView(self._topo_scene)
        self._topo_view.setMinimumHeight(300)
        self._topo_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._topo_view.setStyleSheet("background: #11111b; border: none; border-radius: 6px;")
        topo_lo.addWidget(self._topo_view)

        topo_info = QLabel("Devices discovered by scan appear as nodes. Edges show connectivity.")
        topo_info.setStyleSheet("color: #6c7086; font-size: 11px; padding: 2px;")
        topo_lo.addWidget(topo_info)
        self._tabs.addTab(topo_tab, "🗺️  Topology")

        # ── Tab 3: Port Scanner ──
        port_tab = QWidget()
        port_lo = QVBoxLayout(port_tab)
        port_lo.setContentsMargins(8, 8, 8, 8)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Host:"))
        self.port_host = QLineEdit("localhost")
        self.port_host.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        self.port_host.setFixedWidth(150)
        port_row.addWidget(self.port_host)
        port_row.addWidget(QLabel("Ports:"))
        self.port_range = QLineEdit("80,443,22,8080,11434,5432,3306")
        self.port_range.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        port_row.addWidget(self.port_range, 1)

        self.port_scan_btn = QPushButton("🔍  Scan ports")
        self.port_scan_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #f38ba8; }"
        )
        self.port_scan_btn.clicked.connect(self._scan_ports)
        port_row.addWidget(self.port_scan_btn)
        port_lo.addLayout(port_row)

        self.port_results = QListWidget()
        self.port_results.setStyleSheet(
            "QListWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; }"
            "QListWidget::item { padding: 4px 8px; }"
        )
        port_lo.addWidget(self.port_results, 1)
        self._tabs.addTab(port_tab, "🔌  Ports")

        self._add(self._tabs)

        # ── Status bar ──
        self._status = QLabel("Ready. Enter a subnet and scan.")
        self._status.setStyleSheet("color: #6c7086; font-size: 12px;")
        self.content.addWidget(self._status)

        # ── State ──
        self._devices: list[dict] = []
        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._scan)

    # ── Recon scan ──────────────────────────────────────────────────────

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._scan()
            self._timer.start()
        else:
            self._timer.stop()

    def _scan(self) -> None:
        self._status.setText("Scanning...")
        self.scan_btn.setEnabled(False)

        def _run() -> None:
            devices = []
            try:
                from virgo_network_scanner import scan_subnet
                raw = scan_subnet(self.subnet_input.text())
                for d in (raw or []):
                    if hasattr(d, "_asdict"):
                        devices.append(d._asdict())
                    elif isinstance(d, dict):
                        devices.append(d)
                    else:
                        devices.append({"ip": str(d), "hostname": "", "mac": "", "vendor": "", "status": "up"})
            except Exception as exc:
                devices = [{"ip": f"Error: {exc}", "hostname": "", "mac": "", "vendor": "", "status": "error"}]
            QMetaObject.invokeMethod(
                self, "_show_results", Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, devices),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(list)
    def _show_results(self, devices: list[dict]) -> None:
        self._devices = devices
        self._device_table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            ip = d.get("ip", "?")
            host = d.get("hostname", "") or d.get("host", "")
            mac = d.get("mac", "")
            vendor = d.get("vendor", "")
            status = d.get("status", "up")

            ip_item = QTableWidgetItem(ip)
            ip_item.setForeground(QColor("#89b4fa"))
            self._device_table.setItem(row, 0, ip_item)
            self._device_table.setItem(row, 1, QTableWidgetItem(host))
            self._device_table.setItem(row, 2, QTableWidgetItem(mac))
            self._device_table.setItem(row, 3, QTableWidgetItem(vendor))

            st_item = QTableWidgetItem(status)
            st_item.setForeground(QColor("#a6e3a1" if status == "up" else "#f38ba8"))
            self._device_table.setItem(row, 4, st_item)

        self._device_count.setText(f"{len(devices)} device(s)")
        self._status.setText(f"Found {len(devices)} device(s)")
        self.scan_btn.setEnabled(True)
        self._build_topology()

    # ── Attack Surface Map (topology) ──────────────────────────────────

    def _build_topology(self) -> None:
        """Render discovered devices as a visual network graph."""
        self._topo_scene.clear()
        if not self._devices:
            txt = self._topo_scene.addText("No devices — run a scan first")
            txt.setDefaultTextColor(QColor("#6c7086"))
            return

        import math
        n = len(self._devices)
        cx, cy, radius = 250, 180, 140
        node_w, node_h = 100, 36

        self._topo_nodes: list[dict] = []
        for i, d in enumerate(self._devices):
            angle = (2 * math.pi * i) / n - math.pi / 2
            x = cx + radius * math.cos(angle) - node_w // 2
            y = cy + radius * math.sin(angle) - node_h // 2

            # Node rect
            ip = d.get("ip", f"device_{i}")
            rect = QGraphicsRectItem(x, y, node_w, node_h)
            rect.setBrush(QBrush(QColor("#181825")))
            rect.setPen(QPen(QColor("#89b4fa"), 1.5))
            rect.setFlags(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
            self._topo_scene.addItem(rect)

            # IP label
            label = QGraphicsTextItem(ip, rect)
            label.setPos(x + 6, y + 8)
            label.setDefaultTextColor(QColor("#cdd6f4"))
            f = QFont("Segoe UI", 8, QFont.Weight.Bold)
            label.setFont(f)

            self._topo_nodes.append({"rect": rect, "ip": ip})

        # Draw edges between consecutive devices (star topology)
        for i in range(n - 1):
            n1 = self._topo_nodes[i]
            n2 = self._topo_nodes[i + 1]
            r1 = n1["rect"]
            r2 = n2["rect"]
            x1 = r1.rect().center().x() + r1.pos().x()
            y1 = r1.rect().center().y() + r1.pos().y()
            x2 = r2.rect().center().x() + r2.pos().x()
            y2 = r2.rect().center().y() + r2.pos().y()
            self._topo_scene.addLine(x1, y1, x2, y2, QPen(QColor("#45475a"), 1, Qt.PenStyle.DashLine))

        self._topo_scene.setSceneRect(0, 0, 500, 400)

    # ── Port scanner ────────────────────────────────────────────────────

    def _scan_ports(self) -> None:
        host = self.port_host.text().strip()
        ports: list[int] = []
        for part in self.port_range.text().split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-")
                ports.extend(range(int(a), int(b) + 1))
            elif part.isdigit():
                ports.append(int(part))
        if not host or not ports:
            return
        self.port_scan_btn.setEnabled(False)
        self.port_results.clear()

        def _run() -> None:
            import socket
            open_ports: list[int] = []
            for port in ports:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.5)
                        if s.connect_ex((host, port)) == 0:
                            open_ports.append(port)
                except Exception:
                    pass
            QMetaObject.invokeMethod(
                self, "_show_ports", Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, open_ports), Q_ARG(list, ports),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(list, list)
    def _show_ports(self, open_ports: list, all_ports: list) -> None:
        self.port_results.clear()
        for port in all_ports:
            is_open = int(port) in open_ports
            item = QListWidgetItem(f"  {'🔓' if is_open else '🔒'}  Port {port}  {'OPEN' if is_open else 'closed'}")
            if is_open:
                item.setForeground(QColor("#a6e3a1"))
            else:
                item.setForeground(QColor("#6c7086"))
            self.port_results.addItem(item)
        self.port_scan_btn.setEnabled(True)
        self._status.setText(f"Port scan: {len(open_ports)}/{len(all_ports)} open")

    def _export(self) -> None:
        if not self._devices:
            self._status.setText("Nothing to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export devices", "network-scan.csv", "CSV (*.csv)"
        )
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ip", "hostname", "mac", "vendor", "status"])
            w.writeheader()
            w.writerows(self._devices)
        self._status.setText(f"Exported {len(self._devices)} device(s)")


# ═══════════════════════════════════════════════════════════════════════
# Diagnostics page
# ═══════════════════════════════════════════════════════════════════════


class DiagnosticsPage(PageWidget):
    """Live system health — CPU, RAM, disk, network, services, processes."""

    def __init__(self) -> None:
        super().__init__(
            "System Health",
            "Live CPU, memory, disk, network & service monitoring.",
        )

        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        ctrl_row.addWidget(refresh_btn)
        self._auto_cb = QCheckBox("Auto (5s)")
        self._auto_cb.setStyleSheet("color: #a6adc8;")
        self._auto_cb.toggled.connect(self._toggle_auto)
        ctrl_row.addWidget(self._auto_cb)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Stats grid: CPU, RAM, DISK ──
        gauges = QHBoxLayout()
        gauges.setSpacing(16)
        self._gauges: dict[str, QProgressBar] = {}
        for name, icon, color in [
            ("CPU", "⚡", "#89b4fa"),
            ("RAM", "🅂", "#a6e3a1"),
            ("DISK C:", "💾", "#f9e2af"),
        ]:
            box = QWidget()
            box.setStyleSheet(
                "background: #181825; border: 1px solid #313244; "
                "border-radius: 8px; padding: 12px;"
            )
            bl = QVBoxLayout(box)
            bl.setSpacing(6)
            bl.addWidget(QLabel(f"{icon}  {name}"))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFixedHeight(22)
            bar.setStyleSheet(f"""
                QProgressBar {{ background: #11111b; border: none; border-radius: 4px;
                    text-align: center; color: #cdd6f4; font-size: 11px; }}
                QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}
            """)
            bl.addWidget(bar)
            gauges.addWidget(box, 1)
            self._gauges[name] = bar
        self.content.addLayout(gauges)

        # ── Network + Services row ──
        info_row = QHBoxLayout()
        info_row.setSpacing(16)

        # Network panel
        net_group = self._section("Network")
        self._net_labels: list[QLabel] = []
        self._net_container = QVBoxLayout()
        net_group.layout().addLayout(self._net_container)  # type: ignore
        info_row.addWidget(net_group, 1)

        # Services panel
        svc_group = self._section("Services")
        self._svc_labels: dict[str, QLabel] = {}
        for svc in ["Ollama", "Ollama Models"]:
            row = QHBoxLayout()
            lbl = QLabel(f"  ○  {svc}")
            lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
            row.addWidget(lbl)
            self._svc_labels[svc] = lbl
            svc_group.layout().addLayout(row)  # type: ignore
        info_row.addWidget(svc_group, 1)
        self.content.addLayout(info_row)

        # ── Process table ──
        proc_group = self._section("Top Processes")
        self._proc_table = QTableWidget(0, 4)
        self._proc_table.setHorizontalHeaderLabels(["PID", "Name", "Mem %", "CPU %"])
        self._proc_table.setAlternatingRowColors(True)
        self._proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proc_table.verticalHeader().setVisible(False)
        self._proc_table.horizontalHeader().setStretchLastSection(True)
        self._proc_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: none; border-radius: 6px; "
            "color: #cdd6f4; gridline-color: #313244; font-size: 11px; }"
            "QTableWidget::item { padding: 2px 6px; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 4px; color: #a6adc8; font-weight: bold; }"
        )
        self._proc_table.setMinimumHeight(200)
        proc_group.layout().addWidget(self._proc_table)  # type: ignore
        self._add(proc_group)

        # ── Last update timestamp ──
        self._ts_label = QLabel("")
        self._ts_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.content.addWidget(self._ts_label)

        self._refresh()

    def on_activate(self) -> None:
        if self._auto_cb.isChecked():
            self._timer.start()

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._refresh()
            self._timer.start()
        else:
            self._timer.stop()

    def _refresh(self) -> None:
        """Fetch latest stats and update all widgets."""
        try:
            from virgo_diagnostics import get_system_stats
            stats = get_system_stats()

            # CPU gauge
            cpu_pct = stats.get("cpu", {}).get("percent", 0) or 0
            self._gauges["CPU"].setValue(int(cpu_pct))
            freq = stats.get("cpu", {}).get("freq_mhz")
            freq_str = f" @ {freq}MHz" if freq else ""
            self._gauges["CPU"].setFormat(f"CPU  {cpu_pct:.0f}%  ({stats['cpu'].get('count', '?')} cores{freq_str})")

            # RAM gauge
            mem = stats.get("memory", {})
            if mem:
                self._gauges["RAM"].setValue(int(mem["percent"]))
                self._gauges["RAM"].setFormat(f"RAM  {mem['percent']:.0f}%  ({mem['used_gb']}/{mem['total_gb']} GB)")

            # Disk gauge
            disks = stats.get("disk", [])
            if disks:
                d = disks[0]
                self._gauges["DISK C:"].setValue(int(d["percent"]))
                self._gauges["DISK C:"].setFormat(f"{d['mount']}  {d['percent']:.0f}%  ({d['used_gb']}/{d['total_gb']} GB)")

            # Network
            for i in reversed(range(self._net_container.count())):
                w = self._net_container.itemAt(i)
                if w and w.widget():
                    w.widget().deleteLater()
            for iface in stats.get("network", [])[:5]:
                lbl = QLabel(f"  🌐  {iface['interface']}:  {iface['ip']}")
                lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
                self._net_container.addWidget(lbl)
            if not stats.get("network"):
                self._net_container.addWidget(QLabel("  (no network info)"))

            # Services
            services = stats.get("services", {})
            for svc, lbl in self._svc_labels.items():
                if svc == "Ollama":
                    status = services.get("Ollama", "unknown")
                    icon = "🟢" if status == "running" else ("🟡" if status == "checking" else "🔴")
                    lbl.setText(f"  {icon}  Ollama: {status}")
                elif svc == "Ollama Models":
                    models = stats.get("ollama", {}).get("models", [])
                    count = stats.get("ollama", {}).get("model_count", 0)
                    lbl.setText(f"  🧠  {count} model(s): {', '.join(models[:3])}{'...' if count > 3 else ''}")

            # Processes
            self._proc_table.setRowCount(0)
            for proc in stats.get("processes", [])[:10]:
                r = self._proc_table.rowCount()
                self._proc_table.insertRow(r)
                self._proc_table.setItem(r, 0, QTableWidgetItem(str(proc["pid"])))
                self._proc_table.setItem(r, 1, QTableWidgetItem(proc["name"]))
                mt = QTableWidgetItem(f"{proc['mem_pct']:.1f}")
                mt.setForeground(QColor("#a6e3a1"))
                self._proc_table.setItem(r, 2, mt)
                ct = QTableWidgetItem(f"{proc['cpu_pct']:.1f}")
                ct.setForeground(QColor("#89b4fa"))
                self._proc_table.setItem(r, 3, ct)

            self._ts_label.setText(f"Last updated: {stats['timestamp']}")

        except Exception as exc:
            self._ts_label.setText(f"Error: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# Alerts page
# ═══════════════════════════════════════════════════════════════════════


class AlertsPage(PageWidget):
    """Alert evaluation and history."""

    def __init__(self) -> None:
        super().__init__(
            "Alerts",
            "Threshold-based alert evaluation from diagnostics & network data.",
        )

        self._add_row(
            QPushButton(f"{icon('run')}  Evaluate Alerts", clicked=self._evaluate),
            QPushButton(f"{icon('fix')}  Run Fixer", clicked=self._run_fixer),
            QPushButton(f"{icon('delete')}  Clear Alerts", clicked=self._clear),
        )
        self.auto_cb = QCheckBox("Auto (30s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        self._add_row(self.auto_cb)

        self.alerts_list = QListWidget()
        self._add(self.alerts_list)
        self.status = QLabel("No alerts evaluated yet.")

        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._evaluate)

        self._add(self.status)

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._evaluate()
            self._timer.start()
        else:
            self._timer.stop()

    def _run_fixer(self) -> None:
        self.status.setText("Running fixer...")
        try:
            from virgo_fixer import fix_all

            fix_all()
            self.status.setText(f"{icon('ok')} Fixer finished")
        except Exception as exc:
            self.status.setText(f"Fixer error: {exc}")
        self._evaluate()

    def _evaluate(self) -> None:
        self.alerts_list.clear()
        self.status.setText("Evaluating...")

        def _run() -> None:
            try:
                from virgo_alerts import check_thresholds

                check_thresholds()
            except Exception as exc:
                lines = [f"Error: {exc}"]
            else:
                lines = []
                alert_path = OUTDIR / "ALERTS_TRIGGERED.txt"
                if alert_path.exists():
                    lines = alert_path.read_text().strip().split("\n")
                if not lines:
                    lines = ["System clear — no alerts triggered."]
            QMetaObject.invokeMethod(
                self,
                "_show_alerts",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, "\n".join(lines)),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(str)
    def _show_alerts(self, text: str) -> None:
        self.alerts_list.clear()
        for line in text.split("\n"):
            self.alerts_list.addItem(line)
        self.status.setText(
            f"{self.alerts_list.count()} alert(s)" if self.alerts_list.count() else "No alerts"
        )

    def _clear(self) -> None:
        self.alerts_list.clear()
        self.status.setText("Cleared")
        alert_path = OUTDIR / "ALERTS_TRIGGERED.txt"
        if alert_path.exists():
            alert_path.unlink()


# ═══════════════════════════════════════════════════════════════════════
# Scaffold page
# ═══════════════════════════════════════════════════════════════════════


class ScaffoldPage(PageWidget):
    """Project scaffold generator."""

    def __init__(self) -> None:
        super().__init__(
            "Scaffolds",
            "Generate project skeletons from templates.",
        )

        # Template selector
        self._add_row(QLabel(f"{icon('info')} Select a scaffold:"))
        self.scaffold_combo = QComboBox()
        self.scaffold_combo.setMinimumWidth(250)
        self._populate_scaffolds()
        self._add_row(self.scaffold_combo)

        # Output dir
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output directory:"))
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("./my-project")
        output_row.addWidget(self.output_dir, 1)
        self.content.addLayout(output_row)

        # Project name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Project name:"))
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("my-project")
        name_row.addWidget(self.project_name, 1)
        self.content.addLayout(name_row)

        self._add_row(
            QPushButton(f"{icon('run')}  Generate", clicked=self._generate),
        )

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(200)
        self._add(self.output)

    def _populate_scaffolds(self) -> None:
        try:
            from virgo_scaffold import list_scaffolds

            for s in list_scaffolds():
                self.scaffold_combo.addItem(s.get("name", "?"), s.get("id", ""))
        except Exception:
            self.scaffold_combo.addItems(
                ["fastapi-crud", "cli-app", "flask-app", "python-lib", "agent-tool"]
            )

    def _generate(self) -> None:
        scaffold = self.scaffold_combo.currentText()
        out_dir = self.output_dir.text().strip() or f"./{scaffold}_output"
        name = self.project_name.text().strip() or scaffold

        self.output.clear()
        self.output.appendPlainText(f"Generating '{scaffold}' → {out_dir}...")

        def _run() -> None:
            try:
                from virgo_scaffold import generate_scaffold

                result = generate_scaffold(scaffold, out_dir, project_name=name)
                self.output.appendPlainText(json.dumps(result, indent=2))
                base = Path(out_dir)
                if base.exists():
                    files = [str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()]
                    self.output.appendPlainText("\nFiles:\n" + "\n".join(files))
                self.output.appendPlainText(f"\n{icon('ok')} Done!")
            except Exception as exc:
                self.output.appendPlainText(f"Error: {exc}")

        threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# Sessions / Replay page
# ═══════════════════════════════════════════════════════════════════════


class SessionPage(PageWidget):
    """Browse and replay saved pipeline sessions."""

    def __init__(self) -> None:
        super().__init__(
            "Sessions",
            "Browse and replay pipeline / swarm runs, or load chat history.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
        )

        self.tabs = QTabWidget()
        self.pipeline_list = QListWidget()
        self.pipeline_list.setMinimumHeight(180)
        self.pipeline_list.currentItemChanged.connect(self._on_pipeline_select)
        self.tabs.addTab(self.pipeline_list, "Pipeline")

        self.chat_list = QListWidget()
        self.chat_list.setMinimumHeight(180)
        self.chat_list.currentItemChanged.connect(self._on_chat_select)
        self.tabs.addTab(self.chat_list, "Chat")
        self._add(self.tabs)

        # Agent memory explorer tab
        self.memory_list = QListWidget()
        self.memory_list.setMinimumHeight(180)
        self.tabs.addTab(self.memory_list, "Memory")
        self.memory_list.currentItemChanged.connect(self._on_memory_select)
        self._add(self.tabs)

        # Detail panel
        detail = self._section("Detail")
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(140)
        detail.layout().addWidget(self.detail_text)  # type: ignore

        self._add_row(
            QPushButton(f"{icon('run')}  Replay", clicked=self._replay),
            QPushButton(f"{icon('file')}  Open JSON", clicked=self._open_json),
            QPushButton(f"{icon('delete')}  Delete", clicked=self._delete),
        )

        self.status = QLabel("No sessions yet.")
        self._add(self.status)
        self._sessions: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._chat_sessions: list[dict[str, Any]] = []
        self._current_chat: dict[str, Any] | None = None

    def _delete(self) -> None:
        if self.tabs.currentIndex() == 1:
            # Chat session deletion
            if not self._current_chat:
                self.status.setText("Select a chat session first.")
                return
            path = self._current_chat.get("path", "")
            try:
                if path and Path(path).exists():
                    Path(path).unlink()
                self.status.setText(f"Deleted '{self._current_chat.get('name', '')}'")
            except Exception as exc:
                self.status.setText(f"Delete failed: {exc}")
            self._refresh()
            return
        # Pipeline session deletion (existing logic)
        if not self._current:
            self.status.setText("Select a session first.")
            return
        name = self._current.get("name", "")
        path = self._current.get("path", "")
        try:
            import shutil

            if path and Path(path).exists():
                Path(path).unlink()
            mem_dir = HERE / ".virgo_memory"
            for cand in (mem_dir / f"{name}.json", mem_dir / name):
                if cand.exists():
                    if cand.is_dir():
                        shutil.rmtree(cand)
                    else:
                        cand.unlink()
            self.status.setText(f"Deleted '{name}'")
        except Exception as exc:
            self.status.setText(f"Delete failed: {exc}")
        self._refresh()

    def on_activate(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        """Reload both pipeline and chat session lists."""
        # ── Pipeline sessions ──
        self.pipeline_list.clear()
        self._current = None
        try:
            from memory import list_sessions

            sessions = list_sessions()
        except Exception as exc:
            self.status.setText(f"Error: {exc}")
            return
        self._sessions = sessions
        for s in sessions:
            label = s.get("name", "?")
            goal = (s.get("goal") or "").strip()
            if goal:
                label += f"  —  {goal[:60]}"
            phase = s.get("phase")
            if phase:
                label += f"  [{phase}]"
            item = QListWidgetItem(label)
            item.setData(256, s)
            self.pipeline_list.addItem(item)

        # ── Chat sessions ──
        self.chat_list.clear()
        self._current_chat = None
        chat_dir = HERE / ".virgo_chat_history"
        self._chat_sessions = []
        if chat_dir.exists():
            for fp in sorted(chat_dir.glob("chat_*.json"), reverse=True):
                try:
                    data = json.loads(fp.read_text())
                    msgs = data.get("messages", [])
                    sid = data.get("session_id", "")[:8]
                    model = data.get("model", "?")
                    label = f"{fp.stem}  [{model}]  ({len(msgs)} msgs)"
                    entry = {
                        "name": fp.stem,
                        "path": str(fp),
                        "session_id": sid,
                        "model": model,
                        "messages": len(msgs),
                    }
                    item = QListWidgetItem(label)
                    item.setData(256, entry)
                    self.chat_list.addItem(item)
                    self._chat_sessions.append(entry)
                except Exception:
                    pass

        pipe_count = len(self._sessions)
        chat_count = len(self._chat_sessions)
        self.status.setText(f"{pipe_count} pipeline / {chat_count} chat session(s)")

        # ── Agent memory (experience.jsonl) ──
        self.memory_list.clear()
        self._memories = []
        mem_file = HERE / ".virgo_memory" / "experience.jsonl"
        if mem_file.exists():
            for i, line in enumerate(mem_file.read_text().splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    entry = {"raw": line[:200]}
                label = (
                    entry.get("goal")
                    or entry.get("task")
                    or entry.get("prompt")
                    or entry.get("raw")
                    or f"entry {i}"
                )
                if isinstance(label, str):
                    label = label[:70]
                item = QListWidgetItem(f"#{i}  {label}")
                item.setData(256, entry)
                self.memory_list.addItem(item)
                self._memories.append(entry)

    def _on_memory_select(self, current, _prev) -> None:
        if not current:
            return
        entry = current.data(256)
        self.detail_text.setPlainText(json.dumps(entry, indent=2)[:2000])

    def _on_pipeline_select(self, current, _prev) -> None:
        if not current:
            return
        self._current = current.data(256)
        if not self._current:
            return
        s = self._current
        lines = [
            f"Name:      {s.get('name', '?')}",
            f"Goal:      {s.get('goal', '')}",
            f"Phase:     {s.get('phase', '')}",
            f"Passed:    {s.get('loop_passed', 'n/a')}",
            f"Iteration: {s.get('iteration', 0)}",
            f"Generated: {s.get('generated', 0)} file(s)",
            f"Modified:  {s.get('modified', '')}",
            f"Path:      {s.get('path', '')}",
        ]
        self.detail_text.setPlainText("\n".join(lines))

    def _on_chat_select(self, current, _prev) -> None:
        if not current:
            return
        self._current_chat = current.data(256)
        if not self._current_chat:
            return
        c = self._current_chat
        lines = [
            f"Session:   {c.get('name', '?')}",
            f"Model:     {c.get('model', '?')}",
            f"Messages:  {c.get('messages', 0)}",
            f"Path:      {c.get('path', '')}",
        ]
        # Preview first few messages
        try:
            data = json.loads(Path(c["path"]).read_text())
            for m in data.get("messages", [])[:4]:
                role = m.get("role", "?")
                content = m.get("content", "")[:80]
                lines.append(f"  [{role}] {content}")
        except Exception:
            pass
        self.detail_text.setPlainText("\n".join(lines))

    def _replay(self) -> None:
        if self.tabs.currentIndex() == 1:
            self._load_chat_into_chat()
            return
        if not self._current:
            self.status.setText("Select a session first.")
            return
        name = self._current.get("name", "")
        self.status.setText(f"Replaying '{name}'...")
        subprocess.Popen(
            [sys.executable, str(HERE / "cli.py"), "replay", name],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self.status.setText(f"Launched replay for '{name}' in a new process.")

    def _load_chat_into_chat(self) -> None:
        """Load the selected chat session into ChatPage."""
        if not self._current_chat:
            self.status.setText("Select a chat session first.")
            return
        path = self._current_chat.get("path", "")
        try:
            data = json.loads(Path(path).read_text())
            msgs = data.get("messages", [])
            model = data.get("model", "")
            sid = data.get("session_id", "")
            # Find ChatPage and load
            w = self.window()
            if not w:
                self.status.setText("Cannot access main window.")
                return
            cp = getattr(w, "pages", {}).get("chat")
            if cp and hasattr(cp, "_load_history"):
                cp._load_history(msgs, model, sid)
                if hasattr(w, "_navigate"):
                    w._navigate("chat")
                self.status.setText(f"Loaded '{self._current_chat.get('name', '')}' into Chat.")
            else:
                self.status.setText("Chat page not found or lacks _load_history.")
        except Exception as exc:
            self.status.setText(f"Load failed: {exc}")

    def _open_json(self) -> None:
        if self.tabs.currentIndex() == 1:
            if self._current_chat:
                from virgo_desktop import _open_file

                _open_file(self._current_chat.get("path", ""))
                self.status.setText(f"Opened {self._current_chat.get('path', '')}")
            return
        if not self._current:
            self.status.setText("Select a session first.")
            return
        path = self._current.get("path", "")
        if path and Path(path).exists():
            from virgo_desktop import _open_file

            _open_file(path)
            self.status.setText(f"Opened {path}")
        else:
            self.status.setText("Session file not found.")


# ═══════════════════════════════════════════════════════════════════════
# Swarm / delegation page
# ═══════════════════════════════════════════════════════════════════════


class SwarmPage(PageWidget):
    """Agent Swarm Visualizer — live agent cards with real-time status."""

    def __init__(self) -> None:
        super().__init__(
            "Swarm",
            "Launch a multi-agent swarm with live visual feedback",
        )

        # ── Goal input ──
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("Goal:"))
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. build a REST API and a CLI that consumes it")
        self.goal_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        goal_row.addWidget(self.goal_input, 1)
        self.content.addLayout(goal_row)

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        self.launch_btn = QPushButton("🚀  Launch Swarm")
        self.launch_btn.clicked.connect(self._launch)
        self.stop_swarm_btn = QPushButton("⏹  Stop")
        self.stop_swarm_btn.setObjectName("stopBtn")
        self.stop_swarm_btn.setVisible(False)
        self.stop_swarm_btn.clicked.connect(self._stop_swarm)
        self.llm_toggle = QPushButton("🧠  LLM: ON")
        self.llm_toggle.setCheckable(True)
        self.llm_toggle.setChecked(True)
        self.llm_toggle.clicked.connect(lambda: self.llm_toggle.setText(
            f"🧠  LLM: {'ON' if self.llm_toggle.isChecked() else 'OFF'}"
        ))
        ctrl_row.addWidget(self.launch_btn)
        ctrl_row.addWidget(self.stop_swarm_btn)
        ctrl_row.addWidget(self.llm_toggle)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Agent cards container (scrollable) ──
        self._cards_widget = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)

        scroll = QWidget()
        scroll_layout = QVBoxLayout(scroll)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(self._cards_widget)
        scroll_layout.addStretch()
        self._add(scroll)

        # ── Status bar ──
        self._status_bar = QLabel("Ready. Enter a goal and launch.")
        self._status_bar.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 4px 0;"
        )
        self.content.addWidget(self._status_bar)

        # ── State ──
        self._running = False
        self._proc: subprocess.Popen | None = None
        self._agent_cards: dict[str, "AgentCard"] = {}
        self._card_container = self._cards_layout

    def on_activate(self) -> None:
        self.goal_input.setFocus()

    def _launch(self) -> None:
        if self._running:
            return
        goal = self.goal_input.text().strip()
        if not goal:
            self._status_bar.setText("⚠️  Enter a goal first.")
            return

        # Load saved .env
        env_path = HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ[k.strip()] = v.strip()

        # Clear previous cards
        self._clear_cards()

        self._status_bar.setText(f"🚀  Launching swarm: {goal}")
        self._running = True
        self.launch_btn.setEnabled(False)
        self.stop_swarm_btn.setVisible(True)

        args = [
            sys.executable,
            str(HERE / "cli.py"),
            "swarm",
            "--goal",
            goal,
        ]
        if self.llm_toggle.isChecked():
            args.append("--llm")

        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

        # Poll for agent updates from stdout
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(300)
        self._poll_timer.timeout.connect(self._refresh_cards)
        self._poll_timer.start()

    def _stop_swarm(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._status_bar.setText("⏹  Swarm stopped.")
        self._cleanup_done()

    def _read_output(self) -> None:
        """Read swarm output and detect agent activity."""
        try:
            for line in iter(self._proc.stdout.readline, ""):  # type: ignore
                if not line:
                    break
                self._parse_line(line.rstrip())
            self._proc.wait()  # type: ignore
        except Exception:
            pass
        finally:
            QMetaObject.invokeMethod(
                self, "_cleanup_done", Qt.ConnectionType.QueuedConnection,
            )

    def _parse_line(self, line: str) -> None:
        """Parse subprocess output to detect agent starts/completions."""
        low = line.lower()
        detailed = line[:80]

        # Detect agent starts
        if "[agent:" in low or "spawning" in low:
            name = self._extract_name(line) or f"agent-{len(self._agent_cards)}"
            QMetaObject.invokeMethod(
                self, "_add_agent_card", Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, name), Q_ARG(str, "running"),
                Q_ARG(str, detailed),
            )
        # Detect agent completions
        elif "done" in low or "finished" in low or "completed" in low:
            name = self._extract_name(line)
            if name and name in self._agent_cards:
                QMetaObject.invokeMethod(
                    self, "_update_card", Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, name), Q_ARG(str, "done"),
                    Q_ARG(str, detailed),
                )
            elif self._agent_cards:
                # Mark the last running card as done
                last = list(self._agent_cards.keys())[-1]
                QMetaObject.invokeMethod(
                    self, "_update_card", Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, last), Q_ARG(str, "done"),
                    Q_ARG(str, detailed),
                )
        # Detect errors
        elif "error" in low or "traceback" in low or "failed" in low:
            name = self._extract_name(line)
            if name and name in self._agent_cards:
                QMetaObject.invokeMethod(
                    self, "_update_card", Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, name), Q_ARG(str, "error"),
                    Q_ARG(str, detailed),
                )

    @staticmethod
    def _extract_name(line: str) -> str | None:
        """Try to extract an agent name from an output line."""
        import re
        m = re.search(r"\[agent:\s*(\w+)\]", line, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"(agent[\d_]+)", line, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def _clear_cards(self) -> None:
        while self._card_container.count():
            item = self._card_container.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._agent_cards.clear()

    @pyqtSlot(str, str, str)
    def _add_agent_card(self, name: str, status: str, detail: str) -> None:
        if name in self._agent_cards:
            self._update_card(name, status, detail)
            return
        card = AgentCard(name, status, detail)
        self._agent_cards[name] = card
        self._card_container.addWidget(card)

    @pyqtSlot(str, str, str)
    def _update_card(self, name: str, status: str, detail: str) -> None:
        card = self._agent_cards.get(name)
        if card:
            card.set_status(status, detail)

    def _refresh_cards(self) -> None:
        """Animate running cards with a pulsing dot indicator."""
        for card in self._agent_cards.values():
            card.tick()

    @pyqtSlot()
    def _cleanup_done(self) -> None:
        if hasattr(self, "_poll_timer"):
            self._poll_timer.stop()
        self._running = False
        self.launch_btn.setEnabled(True)
        self.stop_swarm_btn.setVisible(False)
        self._status_bar.setText("✅  Swarm finished.")
        # Mark any still-running cards as done
        for name, card in self._agent_cards.items():
            if card._card_status == "running":
                card.set_status("done", "Swarm completed")
        w = self.window()
        if hasattr(w, "notify"):
            w.notify("Swarm", f"Finished — {self.goal_input.text()[:60]}")


class AgentCard(QWidget):
    """An individual agent card showing status, current tool, and tokens."""

    def __init__(self, name: str, status: str = "running", detail: str = "") -> None:
        super().__init__()
        self._card_status = status
        self._tick = 0
        self.setStyleSheet("""
            AgentCard {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Status icon
        self._icon = QLabel("●")
        self._icon.setStyleSheet("font-size: 18px; color: #f9e2af;")
        self._icon.setFixedWidth(20)
        layout.addWidget(self._icon)

        # Name + detail
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #cdd6f4;"
        )
        info_col.addWidget(self._name_label)
        self._detail_label = QLabel(detail or "Running...")
        self._detail_label.setStyleSheet("font-size: 11px; color: #6c7086;")
        info_col.addWidget(self._detail_label)
        layout.addLayout(info_col, 1)

        # Mini stats
        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(
            "font-size: 11px; color: #a6adc8; padding: 2px 8px;"
            "background: #11111b; border-radius: 4px;"
        )
        layout.addWidget(self._stats_label)

        self.set_status(status, detail)

    def set_status(self, status: str, detail: str = "") -> None:
        self._card_status = status
        colors = {
            "running": "#f9e2af",
            "done": "#a6e3a1",
            "error": "#f38ba8",
            "idle": "#6c7086",
        }
        icons = {
            "running": "●",
            "done": "✓",
            "error": "✗",
            "idle": "○",
        }
        c = colors.get(status, "#6c7086")
        self._icon.setText(icons.get(status, "●"))
        self._icon.setStyleSheet(f"font-size: 18px; color: {c};")
        border_c = {"running": "#f9e2af", "done": "#a6e3a1", "error": "#f38ba8"}.get(status, "#313244")
        self.setStyleSheet(f"""
            AgentCard {{
                background: #181825;
                border: 1px solid {border_c};
                border-radius: 8px;
            }}
        """)
        if detail:
            self._detail_label.setText(detail)
        if status == "running":
            self._stats_label.setText("● running")
        elif status == "done":
            self._stats_label.setText("✅ complete")
        elif status == "error":
            self._stats_label.setText("❌ failed")

    def tick(self) -> None:
        """Animate the running indicator."""
        if self._card_status == "running":
            self._tick += 1
            dots = "." * ((self._tick // 4) % 4)
            self._stats_label.setText(f"● running{dots}")


# ═══════════════════════════════════════════════════════════════════════
# Logs page
# ═══════════════════════════════════════════════════════════════════════


class LogsPage(PageWidget):
    """Virgo application logs."""

    def __init__(self) -> None:
        super().__init__(
            "",
            "Recent virgo log output.",
        )

        self.level_combo = QComboBox()
        self.level_combo.addItems(["ALL", "INFO", "WARN", "ERROR", "DEBUG"])
        self.level_combo.setCurrentText("ALL")
        self.level_combo.currentTextChanged.connect(lambda _: self._refresh())
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("regex filter (empty = all)…")
        self.filter_input.textChanged.connect(lambda _: self._refresh())
        self.tail_chk = QCheckBox("Tail follow")
        self.tail_chk.setChecked(True)
        self.tail_chk.stateChanged.connect(lambda _: self._refresh())
        self._add_row(
            QLabel("Level:"),
            self.level_combo,
            QLabel("Filter:"),
            self.filter_input,
            self.tail_chk,
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
            QPushButton(f"{icon('delete')}  Clear", clicked=self._clear_logs),
        )

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(1000)
        self._add(self.log_output)

        # Auto-refresh timer
        self._timer = QTimer()
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        log_file = OUTDIR / "virgo.log"
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8", errors="replace")
            lines = text.strip().split("\n")[-200:]
            lvl = self.level_combo.currentText()
            if lvl != "ALL":
                lines = [l for l in lines if lvl in l.upper()]
            # Regex filter
            pat = self.filter_input.text().strip()
            if pat:
                try:
                    rx = re.compile(pat, re.IGNORECASE)
                    lines = [l for l in lines if rx.search(l)]
                except re.error:
                    lines = [l for l in lines if pat.lower() in l.lower()]
            self.log_output.setPlainText("\n".join(lines))
            if self.tail_chk.isChecked():
                self.log_output.verticalScrollBar().setValue(
                    self.log_output.verticalScrollBar().maximum()
                )

    def _clear_logs(self) -> None:
        log_file = OUTDIR / "virgo.log"
        if log_file.exists():
            log_file.write_text("")
        self.log_output.clear()


# ═══════════════════════════════════════════════════════════════════════
# Process monitor page
# ═══════════════════════════════════════════════════════════════════════


class ProcessMonitorPage(PageWidget):
    """Show running python/ollama processes with a kill button."""

    def __init__(self) -> None:
        super().__init__("Procs", "Running python / ollama processes")
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["PID", "Name", "CPU %", "Kill"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 80)
        self._table.setColumnWidth(1, 260)
        self._table.setColumnWidth(2, 80)
        self._add(self._table)

        row = QHBoxLayout()
        row.addWidget(QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh))
        self.auto_chk = QCheckBox("Auto (2s)")
        self.auto_chk.stateChanged.connect(self._toggle_auto)
        row.addWidget(self.auto_chk)
        row.addStretch()
        self.content.addLayout(row)

        self._timer = QTimer()
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)

    def _toggle_auto(self, state: int) -> None:
        if state:
            self._timer.start()
        else:
            self._timer.stop()

    def on_activate(self) -> None:
        self._refresh()

    def _list_procs(self) -> list[tuple[int, str, str]]:
        procs: list[tuple[int, str, str]] = []
        try:
            import psutil

            for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
                name = (p.info.get("name") or "").lower()
                if "python" in name or "ollama" in name:
                    procs.append(
                        (
                            p.info["pid"],
                            p.info.get("name") or "?",
                            f"{p.info.get('cpu_percent') or 0:.1f}",
                        )
                    )
        except Exception:
            # Fallback: tasklist (Windows)
            try:
                out = subprocess.run(
                    ["tasklist", "/FO", "CSV"], capture_output=True, text=True, timeout=15
                ).stdout
                for line in out.splitlines()[1:]:
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2 and (
                        "python" in parts[0].lower() or "ollama" in parts[0].lower()
                    ):
                        procs.append((int(parts[1]), parts[0], "—"))
            except Exception:
                pass
        return procs

    def _refresh(self) -> None:
        procs = self._list_procs()
        self._table.setRowCount(len(procs))
        for r, (pid, name, cpu) in enumerate(procs):
            self._table.setItem(r, 0, QTableWidgetItem(str(pid)))
            self._table.setItem(r, 1, QTableWidgetItem(name))
            self._table.setItem(r, 2, QTableWidgetItem(cpu))
            btn = QPushButton("Kill")
            btn.clicked.connect(lambda _checked, p=pid: self._kill(p))
            self._table.setCellWidget(r, 3, btn)

    def _kill(self, pid: int) -> None:
        try:
            import psutil

            psutil.Process(pid).terminate()
        except Exception:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# Benchmark page
# ═══════════════════════════════════════════════════════════════════════

_BENCH_PROMPT = "Write a Python function that returns the nth Fibonacci number using memoization."


class BenchmarkPage(PageWidget):
    """Multi-Model Thermal Dashboard — compare every Ollama model on the same prompt."""

    def __init__(self) -> None:
        super().__init__(
            "Thermal Bench",
            "Run all Ollama models on one prompt — compare speed & quality",
        )

        # ── Prompt input ──
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt:"))
        self._prompt_input = QLineEdit()
        self._prompt_input.setText("Explain Python decorators in one paragraph.")
        self._prompt_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        prompt_row.addWidget(self._prompt_input, 1)
        self.content.addLayout(prompt_row)

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        self._run_all_btn = QPushButton("🔥  Run all models")
        self._run_all_btn.clicked.connect(self._run_all)
        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_all)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        ctrl_row.addWidget(self._run_all_btn)
        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addWidget(self._status_label)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Results table (color-coded heatmap) ──
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            "Model", "Latency", "Tokens", "Tok/s", "Quality", "Status", "Preview"
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 80)
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; gridline-color: #313244; font-size: 12px; }"
            "QTableWidget::item { padding: 4px 8px; }"
            "QTableView::item:selected { background: #45475a; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 6px; color: #a6adc8; font-weight: bold; }"
        )
        self._table.itemDoubleClicked.connect(self._show_full_output)
        self._add(self._table)

        # ── Full output viewer (expandable) ──
        self._output_view = QPlainTextEdit()
        self._output_view.setReadOnly(True)
        self._output_view.setMaximumHeight(200)
        self._output_view.setVisible(False)
        self._add(self._output_view)

        # ── State ──
        self._running: set[str] = set()
        self._results: dict[str, dict] = {}
        self._cancelled = False
        self._bench_prompt = _BENCH_PROMPT

    def _run_all(self) -> None:
        """Kick off benchmarks on every available model in parallel."""
        prompt = self._prompt_input.text().strip() or self._bench_prompt
        models = _live_ollama_models()
        if not models:
            # If Ollama is unreachable, use the preferred list so the page
            # is still useful.
            models = PREFERRED_MODELS[:]

        self._table.setRowCount(0)
        self._results.clear()
        self._running = set(models)
        self._cancelled = False
        self._run_all_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._output_view.setVisible(False)
        self._status_label.setText(f"Running {len(models)} model(s)...")

        for model in models:
            threading.Thread(
                target=self._bench_one,
                args=(model, prompt),
                daemon=True,
            ).start()

    def _stop_all(self) -> None:
        self._cancelled = True
        self._stop_btn.setVisible(False)
        self._run_all_btn.setEnabled(True)
        self._status_label.setText("Cancelled.")
        self._running.clear()

    def _bench_one(self, model: str, prompt: str) -> None:
        """Benchmark a single model against Ollama and update the table."""
        import time
        import urllib.request

        t0 = time.time()
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 256},
                }).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            dt = time.time() - t0
            text = resp.get("response", "")
            toks = resp.get("eval_count", 0) or len(text.split())
            tok_s = round(toks / dt, 1) if dt > 0 else 0
            quality = self._score_output(prompt, text)
            QMetaObject.invokeMethod(
                self,
                "_add_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, model),
                Q_ARG(str, f"{dt:.2f}s"),
                Q_ARG(str, str(toks)),
                Q_ARG(str, f"{tok_s:.1f}"),
                Q_ARG(str, f"{quality}/10"),
                Q_ARG(str, "✅ Done"),
                Q_ARG(str, text[:80].replace("\n", " ")),
            )
        except Exception as exc:
            QMetaObject.invokeMethod(
                self,
                "_add_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, model),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, f"❌ {exc!s:.50}"),
                Q_ARG(str, ""),
            )

    @pyqtSlot(str, str, str, str, str, str, str)
    def _add_result(
        self, model: str, lat: str, toks: str,
        tps: str, qual: str, status: str, preview: str,
    ) -> None:
        _color = QColor
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Colour-code latency (green < 5s, yellow < 20s, red >= 20s)
        try:
            lat_val = float(lat.rstrip("s"))
            if lat_val < 5:
                bg = _color("#1a3a2a")
            elif lat_val < 20:
                bg = _color("#3a3a1a")
            else:
                bg = _color("#3a1a1a")
        except Exception:
            bg = _color("#1e1e2e")

        items = [
            (model, _color("#89b4fa")),
            (lat, _color("#cdd6f4")),
            (toks, _color("#a6adc8")),
            (tps, _color("#a6e3a1")),
            (qual, _color("#f5c2e7")),
            (status, _color("#a6adc8")),
            (preview, _color("#6c7086")),
        ]
        for col, (text, fg) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(fg)
            item.setBackground(bg)
            self._table.setItem(row, col, item)

        self._results[model] = {
            "latency": lat, "tokens": toks, "tok_s": tps,
            "quality": qual, "output": preview,
        }

        self._running.discard(model)
        if not self._running and not self._cancelled:
            self._run_all_btn.setEnabled(True)
            self._stop_btn.setVisible(False)
            # Rank by quality then speed
            ranked = sorted(
                self._results.items(),
                key=lambda kv: (
                    float(kv[1]["quality"].split("/")[0]) if kv[1]["quality"] != "—" else 0,
                    -float(kv[1]["latency"].rstrip("s")) if kv[1]["latency"] != "—" else 0,
                ),
                reverse=True,
            )
            self._status_label.setText(
                f"Done — best: {ranked[0][0]} ({ranked[0][1]['quality']}, "
                f"{ranked[0][1]['latency']})"
                if ranked else "Done."
            )

    @staticmethod
    def _score_output(prompt: str, output: str) -> int:
        """Heuristic quality: keyword relevance + structure."""
        import re
        if not output:
            return 0
        pwords = set(re.findall(r"\w+", prompt.lower()))
        owords = re.findall(r"\w+", output.lower())
        if not owords:
            return 0
        overlap = len([w for w in owords if w in pwords]) / max(1, len(pwords))
        length_bonus = min(1.0, len(owords) / 100.0)
        score = int(round((overlap * 0.5 + length_bonus * 0.5) * 10))
        return max(0, min(10, score))

    def _show_full_output(self, item: QTableWidgetItem) -> None:
        """Double-click a row to see the full output."""
        row = item.row()
        model_item = self._table.item(row, 0)
        if not model_item:
            return
        model = model_item.text()
        result = self._results.get(model)
        if not result:
            return
        self._output_view.setPlainText(
            f"Model: {model}\n"
            f"Latency: {result['latency']}  |  Tokens: {result['tokens']}  "
            f"|  Tok/s: {result['tok_s']}  |  Quality: {result['quality']}\n"
            f"{'─' * 60}\n"
            f"Full output:\n{result.get('_full', '(not stored)')}"
        )
        self._output_view.setVisible(True)


# ═══════════════════════════════════════════════════════════════════════
# Settings page
# ═══════════════════════════════════════════════════════════════════════

# Preferred local models (benchmarked on this machine). The Settings page
# merges these with whatever Ollama currently has pulled.
PREFERRED_MODELS: list[str] = [
    "phi4-mini-reasoning:3.8b",
    "qwen3.5:2b",
    "llama3.2:latest",
    "gemma3:4b",
    "deepseek-r1:1.5b",
    "ornith:latest",
]


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


class DashboardPage(PageWidget):
    """Live cyberpunk dashboard — system stats, persona, mascot, achievements."""

    def __init__(self) -> None:
        super().__init__("Dashboard", "Live system overview")
        self._timer = QTimer()
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)

        # ── Widget selector (#18) ──
        self._widget_toggles: dict[str, QPushButton] = {}
        self._widget_visible: dict[str, bool] = {
            "persona": True, "system": True, "mascot": True,
            "achievements": True, "activity": True, "actions": True,
        }
        widget_row = QHBoxLayout()
        widget_row.setSpacing(4)
        for w_id, w_label, w_emoji in [
            ("persona", "Badge", "🎭"), ("system", "System", "⚡"),
            ("mascot", "Mascot", "🐾"), ("achievements", "XP", "🏆"),
            ("activity", "Activity", "📋"), ("actions", "Actions", "🚀"),
        ]:
            btn = QPushButton(w_emoji if len(w_emoji) > 1 else w_label)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { background: #181825; border: 1px solid #313244; "
                "border-radius: 4px; padding: 2px 8px; color: #6c7086; font-size: 10px; }"
                "QPushButton:checked { background: #313244; color: #89b4fa; border-color: #89b4fa; }"
            )
            btn.clicked.connect(lambda checked=False, wid=w_id: self._toggle_widget(wid))
            widget_row.addWidget(btn)
            self._widget_toggles[w_id] = btn
        widget_row.addStretch()
        self.content.addLayout(widget_row)

        self._all_widgets: dict[str, QWidget] = {}

        # ── Persona badge ──
        self._persona_badge = QLabel("Persona: Hacker")
        self._persona_badge.setObjectName("dw_persona")
        self._persona_badge.setStyleSheet("font-size: 14px; font-weight: bold; color: #89b4fa; padding: 4px;")
        self._add(self._persona_badge)

        # ── System stats row ──
        stats_group = self._section("System")
        stats_group.setObjectName("dw_system")
        self._stats_labels = {}
        for name, icon_c in [("CPU", "⚡"), ("RAM", "🅂"), ("DISK", "💾")]:
            row = QHBoxLayout()
            label = QLabel(f"{icon_c}  {name}")
            label.setStyleSheet("font-size: 13px; min-width: 100px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFixedHeight(18)
            bar.setStyleSheet("""
                QProgressBar { background: #313244; border: none; border-radius: 4px; text-align: center; color: #cdd6f4; font-size: 11px; }
                QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #89b4fa, stop:1 #a6e3a1); border-radius: 4px; }
            """)
            row.addWidget(label)
            row.addWidget(bar, 1)
            stats_group.layout().addLayout(row)
            self._stats_labels[name] = bar
        self._add(stats_group)

        # ── Mascot + Achievements row ──
        mid_row = QHBoxLayout()
        mid_row.setSpacing(20)

        # Mascot panel
        mascot_group = self._section("Sidekick")
        mascot_group.setObjectName("dw_mascot")
        self._mascot_art = QLabel("(mascot ascii)")
        self._mascot_art.setStyleSheet("font-family: 'Courier New', monospace; font-size: 12px; color: #f5c2e7; padding: 8px; background: #181825; border-radius: 6px;")
        self._mascot_name = QLabel("")
        self._mascot_action = QLabel("")
        self._mascot_action.setStyleSheet("color: #6c7086; font-style: italic;")
        mascot_vbox = QVBoxLayout()
        mascot_vbox.addWidget(self._mascot_art)
        mascot_vbox.addWidget(self._mascot_name)
        mascot_vbox.addWidget(self._mascot_action)
        mascot_vbox.addStretch()
        mascot_group.layout().addLayout(mascot_vbox)
        mid_row.addWidget(mascot_group, 1)

        # Achievements panel
        ach_group = self._section("Achievements")
        ach_group.setObjectName("dw_achievements")
        self._ach_level = QLabel("Level 1")
        self._ach_level.setStyleSheet("font-size: 14px; font-weight: bold; color: #f9e2af;")
        self._ach_xp = QLabel("0 XP")
        self._ach_xp.setStyleSheet("color: #a6adc8;")
        self._ach_bar = QProgressBar()
        self._ach_bar.setRange(0, 100)
        self._ach_bar.setValue(0)
        self._ach_bar.setFixedHeight(12)
        self._ach_bar.setTextVisible(False)
        self._ach_bar.setStyleSheet("""
            QProgressBar { background: #313244; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f9e2af, stop:1 #a6e3a1); border-radius: 3px; }
        """)
        self._ach_unlocked = QLabel("0 / 0 unlocked")
        self._ach_unlocked.setStyleSheet("color: #6c7086; font-size: 11px;")
        ach_vbox = QVBoxLayout()
        ach_vbox.addWidget(self._ach_level)
        ach_vbox.addWidget(self._ach_xp)
        ach_vbox.addWidget(self._ach_bar)
        ach_vbox.addWidget(self._ach_unlocked)
        ach_vbox.addStretch()
        ach_group.layout().addLayout(ach_vbox)
        mid_row.addWidget(ach_group, 1)
        self.content.addLayout(mid_row)

        # ── Activity feed ──
        activity_group = self._section("Recent Activity")
        activity_group.setObjectName("dw_activity")
        self._activity_log = QTextEdit()
        self._activity_log.setReadOnly(True)
        self._activity_log.setMaximumHeight(120)
        self._activity_log.setStyleSheet("font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 11px; background: #181825; border: 1px solid #313244; border-radius: 4px; color: #a6adc8;")
        activity_group.layout().addWidget(self._activity_log)
        self._add(activity_group)

        # ── Quick actions ──
        actions_group = self._section("Quick Actions")
        actions_group.setObjectName("dw_actions")
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        for label_text, callback in [
            ("🚀  Run Pipeline", self._run_pipeline),
            ("🌐  Network Scan", self._run_network_scan),
            ("🎭  Switch Persona", self._switch_persona),
            ("🧠  Focus Mode", self._toggle_focus),
        ]:
            btn = QPushButton(label_text)
            btn.setStyleSheet("""
                QPushButton { background: #313244; border: 1px solid #45475a; border-radius: 6px; padding: 10px 16px; font-size: 12px; color: #cdd6f4; }
                QPushButton:hover { background: #45475a; border-color: #89b4fa; }
            """)
            btn.clicked.connect(callback)
            actions_row.addWidget(btn)
        actions_row.addStretch()
        actions_group.layout().addLayout(actions_row)
        self._add(actions_group)

        # ── Focus mode status ──
        self._focus_label = QLabel("")
        self._focus_label.setStyleSheet("color: #89b4fa; font-size: 11px; padding: 2px;")
        self._add(self._focus_label)

    def on_activate(self) -> None:
        self._refresh()
        self._timer.start()

    def _refresh(self) -> None:
        """Refresh all dashboard widgets."""
        self._refresh_stats()
        self._refresh_persona()
        self._refresh_mascot()
        self._refresh_achievements()
        self._refresh_activity()
        self._refresh_focus()

    def _refresh_stats(self) -> None:
        """Update CPU/RAM/disk progress bars."""
        try:
            import psutil
            # First call to cpu_percent returns 0 on some systems; a second
            # call with interval=0 returns the real reading from the first sample.
            psutil.cpu_percent(interval=0.05)
            cpu = psutil.cpu_percent(interval=0.3)
            self._stats_labels["CPU"].setValue(int(cpu))
            self._stats_labels["CPU"].setFormat(f"CPU  {cpu:.0f}%")

            ram = psutil.virtual_memory()
            self._stats_labels["RAM"].setValue(int(ram.percent))
            used_gb = ram.used / 1024**3
            total_gb = ram.total / 1024**3
            self._stats_labels["RAM"].setFormat(f"RAM  {ram.percent:.0f}%  ({used_gb:.1f}/{total_gb:.1f} GB)")

            disk = psutil.disk_usage("/")
            self._stats_labels["DISK"].setValue(int(disk.percent))
            used_d = disk.used / 1024**3
            total_d = disk.total / 1024**3
            self._stats_labels["DISK"].setFormat(f"DISK  {disk.percent:.0f}%  ({used_d:.1f}/{total_d:.1f} GB)")
        except Exception:
            for name in self._stats_labels:
                self._stats_labels[name].setValue(0)
                self._stats_labels[name].setFormat(f"{name}  ---")

    def _refresh_persona(self) -> None:
        """Update persona badge."""
        try:
            from virgo_persona import current_persona_name, get_persona
            name = current_persona_name()
            p = get_persona()
            display = p.get("display_name", name)
            style = p.get("response_style", "")
            self._persona_badge.setText(f"🎭  Persona: {display}  ({style})")
        except Exception:
            pass

    def _refresh_mascot(self) -> None:
        """Update mascot display."""
        try:
            from virgo_mascot import (
                current_mascot_name, get_mascot, idle_action, mascot_ascii,
            )
            name = current_mascot_name()
            m = get_mascot()
            display = m.get("display", name)
            ascii_str = mascot_ascii(name) or ""
            action = idle_action()
            self._mascot_art.setText(ascii_str)
            self._mascot_name.setText(f"✦  {display}  —  {action}")
        except Exception:
            self._mascot_art.setText("(mascot not available)")
            self._mascot_name.setText("")
            self._mascot_action.setText("")

    def _refresh_achievements(self) -> None:
        """Update achievement progress."""
        try:
            from virgo_achievements import get_achievements
            system = get_achievements()
            stats = system.get_stats()
            level = stats.get("level", 1)
            xp = stats.get("total_xp", 0)
            unlocked = stats.get("unlocked_count", 0)
            total = stats.get("registered_count", 0)
            xp_next = stats.get("next_level_xp", 50)
            # Progress towards next level
            prev_xp = _xp_for_level(level - 1) if level > 1 else 0
            progress = ((xp - prev_xp) / (xp_next - prev_xp)) * 100 if xp_next > prev_xp else 0
            self._ach_level.setText(f"Level {level}")
            self._ach_xp.setText(f"{xp} XP  ({unlocked}/{total} achievements)")
            self._ach_bar.setValue(min(100, int(progress)))
            self._ach_unlocked.setText(f"Next level: {xp_next - xp} XP needed")
        except Exception:
            pass

    def _refresh_activity(self) -> None:
        """Update activity feed from log."""
        try:
            from virgo_heatmap import _load_activity_log
            entries = _load_activity_log()[-10:]
            if entries:
                lines = []
                for e in reversed(entries):
                    ts = e.get("timestamp", "")
                    if ts and len(ts) > 11:
                        ts = ts[11:19]
                    ev = e.get("event", "")
                    dt = e.get("detail", "")[:40]
                    lines.append(f"[{ts}] {ev}  {dt}")
                self._activity_log.setText("\n".join(lines))
            else:
                self._activity_log.setText("No activity yet. Run some tasks!")
        except Exception:
            self._activity_log.setText("Activity feed unavailable")

    def _refresh_focus(self) -> None:
        """Update focus mode status."""
        try:
            import virgo_focus as fmod
            st = fmod.status()
            if st.get("active"):
                genre = st.get("genre_name", "?")
                mins = int(st.get("elapsed_minutes", 0))
                self._focus_label.setText(f"🎧  Focus Mode: {genre}  ({mins}m elapsed)")
                self._focus_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            else:
                self._focus_label.setText("")
        except Exception:
            self._focus_label.setText("")

    def _run_pipeline(self) -> None:
        subprocess.Popen([sys.executable, os.path.join(str(HERE), "cli.py"), "run", "--goal", "auto-fix"])

    def _run_network_scan(self) -> None:
        subprocess.Popen([sys.executable, os.path.join(str(HERE), "virgo_network_scanner.py")])

    def _switch_persona(self) -> None:
        """Quick cycle through personas."""
        try:
            from virgo_persona import current_persona_name, list_personas, set_persona
            current = current_persona_name()
            personas = [p["name"] for p in list_personas()]
            idx = (personas.index(current) + 1) % len(personas) if current in personas else 0
            new_name = personas[idx]
            set_persona(new_name)
            self._refresh_persona()
        except Exception:
            pass

    def _toggle_focus(self) -> None:
        """Toggle focus mode on/off."""
        try:
            import virgo_focus as fmod
            st = fmod.status()
            if st.get("active"):
                fmod.stop()
            else:
                fmod.start("lofi")
            self._refresh_focus()
        except Exception:
            pass

    # ── Widget toggle (#18) ──

    def _toggle_widget(self, widget_id: str) -> None:
        """Show/hide a dashboard widget section."""
        self._widget_visible[widget_id] = not self._widget_visible.get(widget_id, True)
        # Find the widget by scrolling through children
        for child in self.findChildren(QWidget):
            obj_name = child.objectName()
            if obj_name == f"dw_{widget_id}":
                child.setVisible(self._widget_visible[widget_id])
                break
        # Update toggle button
        btn = self._widget_toggles.get(widget_id)
        if btn:
            btn.setChecked(self._widget_visible[widget_id])


def _xp_for_level(level: int) -> int:
    """Calculate XP needed to reach a given level."""
    return level * level * 50  # level^2 * 50


class FilesPage(PageWidget):
    """File browser — tree view of the workspace."""

    def __init__(self) -> None:
        super().__init__("Files", "Browse and open project files")

        self._model = QFileSystemModel()
        root = str(HERE)
        self._model.setRootPath(root)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self._model)
        self.tree.setRootIndex(self._model.index(root))
        self.tree.setAnimated(True)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 280)
        self.tree.setIndentation(16)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.doubleClicked.connect(self._open_file)
        self._add(self.tree)
        self.content.addStretch(1)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(200)
        self._add(self.preview)

        # ── Git panel ──
        git_group = self._section("Git")
        git_row = QHBoxLayout()
        status_btn = QPushButton(f"{icon('refresh')}  Status")
        status_btn.clicked.connect(self._git_status)
        commit_btn = QPushButton(f"{icon('save')}  Commit")
        commit_btn.clicked.connect(self._git_commit)
        push_btn = QPushButton(f"{icon('upload')}  Push")
        push_btn.clicked.connect(self._git_push)
        git_row.addWidget(status_btn)
        git_row.addWidget(commit_btn)
        git_row.addWidget(push_btn)
        git_row.addStretch()
        git_group.layout().addLayout(git_row)  # type: ignore
        self.git_output = QPlainTextEdit()
        self.git_output.setReadOnly(True)
        self.git_output.setMaximumHeight(120)
        self.git_output.setPlaceholderText("Git status will appear here…")
        git_group.layout().addWidget(self.git_output)  # type: ignore
        self._add(git_group)

    def _git_run(self, args: list[str]) -> str:
        try:
            res = subprocess.run(
                ["git"] + args, cwd=str(HERE), capture_output=True, text=True, timeout=30
            )
            return (res.stdout + res.stderr).strip() or "(no output)"
        except Exception as exc:
            return f"git error: {exc}"

    def _git_status(self) -> None:
        self.git_output.setPlainText(self._git_run(["status", "--short"]))

    def _git_commit(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Git Commit", "Commit message:")
        if ok and text.strip():
            out = self._git_run(["add", "-A"])
            out += "\n" + self._git_run(["commit", "-m", text.strip()])
            self.git_output.setPlainText(out)
        elif ok:
            self.git_output.setPlainText("Empty message — commit skipped.")

    def _git_push(self) -> None:
        self.git_output.setPlainText(self._git_run(["push"]))

    def _open_file(self, idx: QModelIndex) -> None:
        path = Path(self._model.filePath(idx))
        if path.is_dir():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            self.preview.setPlainText(text[:5000])
            if len(text) > 5000:
                self.preview.append(f"\n\n[... truncated — file is {path.stat().st_size:,} bytes]")
        except Exception as e:
            self.preview.setPlainText(f"Error reading {path.name}: {e}")


class ActivityFeedPage(PageWidget):
    """Detailed, filterable activity log with search and pagination."""

    def __init__(self) -> None:
        super().__init__("Activity Log", "Detailed, filterable activity feed")

        self._page_size = 20
        self._current_page = 0
        self._all_entries: list[dict] = []

        # ── Filter row ──
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "Pipeline", "Scan", "Search", "Persona", "Focus", "Mascot"])
        self._filter_combo.setStyleSheet(
            "QComboBox { background: #313244; border: 1px solid #45475a; border-radius: 6px; "
            "padding: 6px 10px; color: #cdd6f4; } "
            "QComboBox:hover { border-color: #89b4fa; } "
            "QComboBox::drop-down { border: none; }"
        )
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(QLabel("Filter:"))
        filter_row.addWidget(self._filter_combo)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search...")
        self._search_input.setStyleSheet(
            "QLineEdit { background: #313244; border: 1px solid #45475a; border-radius: 6px; "
            "padding: 6px 10px; color: #cdd6f4; } "
            "QLineEdit:focus { border-color: #89b4fa; }"
        )
        self._search_input.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._search_input, 1)

        self.content.addLayout(filter_row)

        # ── Table ──
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Time", "Event", "Detail"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 100)
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: 1px solid #313244; border-radius: 6px; "
            "color: #cdd6f4; gridline-color: #313244; font-size: 12px; } "
            "QTableWidget::item { padding: 4px 8px; } "
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 6px; color: #a6adc8; font-weight: bold; }"
        )
        self._add(self._table)

        # ── Pagination row ──
        pagination_row = QHBoxLayout()
        pagination_row.setSpacing(8)

        self._prev_btn = QPushButton("<  Prev")
        self._prev_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 8px 14px; color: #cdd6f4; } "
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        self._prev_btn.clicked.connect(self._prev_page)

        self._page_label = QLabel("Page 1/1")
        self._page_label.setStyleSheet("color: #a6adc8; font-size: 13px;")

        self._next_btn = QPushButton("Next  >")
        self._next_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 8px 14px; color: #cdd6f4; } "
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        self._next_btn.clicked.connect(self._next_page)

        pagination_row.addWidget(self._prev_btn)
        pagination_row.addWidget(self._page_label)
        pagination_row.addWidget(self._next_btn)
        pagination_row.addStretch()
        self.content.addLayout(pagination_row)

        # ── Action buttons ──
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 8px 14px; color: #cdd6f4; } "
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        refresh_btn.clicked.connect(self._refresh)

        clear_btn = QPushButton("Clear Log")
        clear_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 8px 14px; color: #cdd6f4; } "
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        clear_btn.clicked.connect(self._clear_log)

        action_row.addWidget(refresh_btn)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        self.content.addLayout(action_row)

        # ── Auto-refresh timer ──
        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)

    def on_activate(self) -> None:
        """Start auto-refresh when page becomes visible."""
        self._refresh()
        self._timer.start()

    def _refresh(self) -> None:
        """Load activity entries and render current page."""
        try:
            from virgo_heatmap import _load_activity_log
            self._all_entries = _load_activity_log()
        except Exception:
            self._all_entries = []
        self._current_page = 0
        self._render()

    def _on_filter_changed(self) -> None:
        """Re-render when filter or search text changes."""
        self._current_page = 0
        self._render()

    def _filtered_entries(self) -> list[dict]:
        """Return entries matching current filter + search."""
        entries = self._all_entries
        selected = self._filter_combo.currentText()
        if selected != "All":
            entries = [e for e in entries if e.get("event", "").lower() == selected.lower()]
        query = self._search_input.text().strip().lower()
        if query:
            entries = [
                e for e in entries
                if query in e.get("event", "").lower()
                or query in e.get("detail", "").lower()
            ]
        return entries

    def _render(self) -> None:
        """Fill the table with the current page of filtered entries."""
        entries = self._filtered_entries()
        total = len(entries)
        total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        self._current_page = min(self._current_page, total_pages - 1)
        self._current_page = max(self._current_page, 0)

        start = self._current_page * self._page_size
        end = start + self._page_size
        page_entries = list(reversed(entries))[start:end]

        self._table.setRowCount(len(page_entries))
        for row, e in enumerate(page_entries):
            ts = e.get("timestamp", "")
            if ts and len(ts) > 11:
                ts = ts[11:19]
            ev = e.get("event", "")
            dt = e.get("detail", "")

            time_item = QTableWidgetItem(ts)
            event_item = QTableWidgetItem(ev)
            detail_item = QTableWidgetItem(dt)

            time_item.setForeground(QBrush(QColor("#a6adc8")))
            event_item.setForeground(QBrush(QColor("#89b4fa")))

            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, event_item)
            self._table.setItem(row, 2, detail_item)

        self._page_label.setText(f"Page {self._current_page + 1}/{total_pages}")
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < total_pages - 1)

    def _prev_page(self) -> None:
        """Go to previous page."""
        if self._current_page > 0:
            self._current_page -= 1
            self._render()

    def _next_page(self) -> None:
        """Go to next page."""
        entries = self._filtered_entries()
        total_pages = max(1, (len(entries) + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._render()

    def _clear_log(self) -> None:
        """Clear the activity log."""
        try:
            from virgo_heatmap import _save_activity_log
            _save_activity_log([])
        except Exception:
            pass
        self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# Mascot Chat Page
# ═══════════════════════════════════════════════════════════════════════


class MascotChatPage(PageWidget):
    """Chat with your mascot sidekick — ASCII art, chat log, and action buttons."""

    def __init__(self) -> None:
        super().__init__("Mascot Chat", "Talk to your sidekick")

        # ── Mascot display section ──
        mascot_section = self._section("Sidekick")
        self._mascot_art = QLabel()
        self._mascot_art.setStyleSheet(
            "font-family: 'Courier New', monospace; font-size: 13px; color: #f5c2e7;"
        )
        self._mascot_name = QLabel()
        mascot_section.layout().addWidget(self._mascot_art)
        mascot_section.layout().addWidget(self._mascot_name)
        self._add(mascot_section)

        # ── Chat log ──
        self._chat_log = QTextEdit()
        self._chat_log.setReadOnly(True)
        self._chat_log.setMinimumHeight(200)
        self._add(self._chat_log)

        # ── Input row ──
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Talk to your mascot...")
        self._input.returnPressed.connect(self._send_message)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_message)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(send_btn)
        self.content.addLayout(input_row)

        # ── Action buttons ──
        actions_row = QHBoxLayout()
        for text, cb in [
            ("Tell Joke", self._tell_joke),
            ("Cheer Me Up", self._cheer_up),
            ("Change Mascot", self._cycle_mascot),
            ("Pet Mascot", self._pet_mascot),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(
                "QPushButton { background: #313244; border: 1px solid #45475a; "
                "border-radius: 6px; padding: 8px 14px; color: #cdd6f4; } "
                "QPushButton:hover { border-color: #89b4fa; }"
            )
            btn.clicked.connect(cb)
            actions_row.addWidget(btn)
        actions_row.addStretch()
        self.content.addLayout(actions_row)

        self._refresh_mascot()

    def on_activate(self) -> None:
        self._refresh_mascot()

    # ── helpers ──

    def _refresh_mascot(self) -> None:
        """Update mascot ASCII art and name display."""
        try:
            from virgo_mascot import (
                current_mascot_name,
                get_mascot,
                idle_action,
                mascot_ascii,
            )

            name = current_mascot_name()
            m = get_mascot()
            display = m.get("display", name)
            ascii_str = mascot_ascii(name) or ""
            action = idle_action()
            self._mascot_art.setText(ascii_str)
            self._mascot_name.setText(f"✦  {display}  —  {action}")
        except Exception:
            self._mascot_art.setText("(mascot module not available)")
            self._mascot_name.setText("")

    def _send_message(self) -> None:
        """Send the current input text to the mascot for a reply."""
        text = self._input.text().strip()
        if not text:
            return
        self._chat_log.append(f"You: {text}")
        self._input.clear()

        try:
            from virgo_mascot import (
                current_mascot_name,
                idle_action,
                react,
                speak,
            )

            name = current_mascot_name()

            # Simple response logic based on keywords
            lower = text.lower()
            if any(w in lower for w in ["joke", "funny", "laugh"]):
                from virgo_chaos import random_joke

                response = f"*tells a joke*\n{random_joke()}"
            elif any(w in lower for w in ["sad", "down", "cheer", "happy"]):
                response = react("pipeline", "success") if name else "You've got this!"
            elif any(w in lower for w in ["who", "what are you"]):
                from virgo_mascot import get_mascot

                m = get_mascot()
                response = f"I'm {m.get('display', name)}, your Virgo sidekick! 🐾"
            elif any(w in lower for w in ["hello", "hi", "hey"]):
                response = react("pipeline", "success") if name else "Hey there! 👋"
            elif any(w in lower for w in ["bye", "goodbye"]):
                response = react("pipeline", "fail") if name else "See ya! 👋"
            else:
                response = speak(text)

            self._chat_log.append(f"{name}: {response}")
        except Exception as e:
            self._chat_log.append(f"Sidekick: (error: {e})")

        # Scroll to bottom
        self._chat_log.verticalScrollBar().setValue(
            self._chat_log.verticalScrollBar().maximum()
        )

    def _tell_joke(self) -> None:
        self._input.setText("tell me a joke")
        self._send_message()

    def _cheer_up(self) -> None:
        try:
            from virgo_celebrate import cheer_text

            from virgo_mascot import cheer

            msg = cheer_text("success")
            self._chat_log.append(f"✨ {msg}")
            self._chat_log.append(f"🌟 {cheer()}")
        except Exception:
            self._chat_log.append("🌟 You're doing great!")

    def _cycle_mascot(self) -> None:
        try:
            from virgo_mascot import (
                current_mascot_name,
                list_mascots,
                set_mascot,
            )

            current = current_mascot_name()
            mascots = [m["tag"] for m in list_mascots()]
            idx = (
                (mascots.index(current) + 1) % len(mascots)
                if current in mascots
                else 0
            )
            new_name = mascots[idx]
            set_mascot(new_name)
            self._refresh_mascot()
            self._chat_log.append(f"🔄 Switched to {new_name}!")
        except Exception:
            pass

    def _pet_mascot(self) -> None:
        try:
            from virgo_mascot import current_mascot_name, idle_action

            action = idle_action()
            self._chat_log.append(f"*pets the {current_mascot_name()}*")
            self._chat_log.append(f"{current_mascot_name()}: {action}")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Leaderboard Page
# ═══════════════════════════════════════════════════════════════════════


class LeaderboardPage(PageWidget):
    """XP stats, streaks, session history, and activity heatmap."""

    def __init__(self) -> None:
        super().__init__("Leaderboard", "XP, streaks & session history")

        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)

        # ── Stats section ──
        stats_group = self._section("Stats")
        self._level_label = QLabel("Level: —")
        self._level_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #cdd6f4;"
        )
        self._xp_label = QLabel("XP: —")
        self._xp_label.setStyleSheet("font-size: 14px; color: #a6adc8;")
        self._streak_label = QLabel("Streak: —")
        self._streak_label.setStyleSheet("font-size: 14px; color: #a6adc8;")
        self._sessions_label = QLabel("Sessions: —")
        self._sessions_label.setStyleSheet("font-size: 14px; color: #a6adc8;")

        self._xp_bar = QProgressBar()
        self._xp_bar.setRange(0, 100)
        self._xp_bar.setValue(0)
        self._xp_bar.setTextVisible(True)
        self._xp_bar.setFixedHeight(20)
        self._xp_bar.setStyleSheet(
            "QProgressBar { background: #313244; border: none; border-radius: 4px;"
            " text-align: center; color: #cdd6f4; font-size: 11px; }"
            " QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #89b4fa, stop:1 #a6e3a1); border-radius: 4px; }"
        )
        self._xp_bar.setFormat("XP to next level: %p%")

        stats_group.layout().addWidget(self._level_label)
        stats_group.layout().addWidget(self._xp_label)
        stats_group.layout().addWidget(self._streak_label)
        stats_group.layout().addWidget(self._sessions_label)
        stats_group.layout().addWidget(self._xp_bar)
        self._add(stats_group)

        # ── Daily Quests (#20) ──
        quests_group = self._section("Daily Quests")
        quests_group.setStyleSheet(
            "QGroupBox { background-color: #181825; border: 1px solid #313244; "
            "border-radius: 8px; margin-top: 16px; padding: 14px 12px 10px; "
            "font-weight: bold; color: #f9e2af; }"
        )
        self._quest_layout = QVBoxLayout()
        self._quest_labels: list[tuple[QLabel, QLabel, QLabel]] = []
        for quest in self._load_quests():
            row = QHBoxLayout()
            icon = QLabel(quest.get("icon", "📋"))
            icon.setFixedWidth(24)
            name_lbl = QLabel(quest["name"])
            name_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
            prog_lbl = QLabel(f"0/{quest['target']}")
            prog_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
            xp_lbl = QLabel(f"+{quest['xp']} XP")
            xp_lbl.setStyleSheet("color: #a6e3a1; font-size: 11px; font-weight: bold;")
            row.addWidget(icon)
            row.addWidget(name_lbl, 1)
            row.addWidget(prog_lbl)
            row.addSpacing(8)
            row.addWidget(xp_lbl)
            self._quest_layout.addLayout(row)
            self._quest_labels.append((name_lbl, prog_lbl, xp_lbl))
        self._quest_layout.addStretch()
        quests_group.layout().addLayout(self._quest_layout)
        self._add(quests_group)

        # ── Recent Sessions section ──
        history_group = self._section("Recent Sessions")
        self._history_table = QTableWidget()
        self._history_table.setColumnCount(3)
        self._history_table.setHorizontalHeaderLabels(["Date", "XP", "Goal"])
        self._history_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._history_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: 1px solid #45475a;"
            " border-radius: 6px; gridline-color: #313244; color: #cdd6f4;"
            " font-size: 12px; }"
            " QTableWidget::item { padding: 4px 8px; }"
            " QHeaderView::section { background: #181825; color: #a6adc8;"
            " border: none; padding: 6px; font-weight: bold; }"
            " QTableWidget::item:alternate { background: #1a1a2e; }"
        )
        self._history_table.setMinimumHeight(160)
        history_group.layout().addWidget(self._history_table)
        self._add(history_group)

        # ── Daily XP (last 7 days) section ──
        daily_group = self._section("Daily XP (last 7 days)")
        self._daily_widgets: list[tuple[QLabel, QProgressBar]] = []
        for day_offset in range(7):
            row = QHBoxLayout()
            name_label = QLabel()
            name_label.setFixedWidth(60)
            name_label.setStyleSheet("font-size: 13px; color: #cdd6f4;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFixedHeight(18)
            bar.setStyleSheet(
                "QProgressBar { background: #313244; border: none;"
                " border-radius: 4px; text-align: right;"
                " color: #a6adc8; font-size: 11px; padding-right: 6px; }"
                " QProgressBar::chunk { background: #89b4fa;"
                " border-radius: 4px; }"
            )
            row.addWidget(name_label)
            row.addWidget(bar, 1)
            daily_group.layout().addLayout(row)
            self._daily_widgets.append((name_label, bar))
        self._add(daily_group)

        # ── Action buttons ──
        action_row = QHBoxLayout()
        reset_btn = QPushButton("Reset Data")
        reset_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a;"
            " border-radius: 6px; padding: 8px 14px; color: #cdd6f4; }"
            " QPushButton:hover { border-color: #89b4fa; }"
        )
        reset_btn.clicked.connect(self._reset_data)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a;"
            " border-radius: 6px; padding: 8px 14px; color: #cdd6f4; }"
            " QPushButton:hover { border-color: #89b4fa; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        auto_chk = QCheckBox("Auto-refresh")
        auto_chk.setStyleSheet("color: #a6adc8;")
        auto_chk.toggled.connect(self._toggle_auto_refresh)
        action_row.addWidget(reset_btn)
        action_row.addWidget(refresh_btn)
        action_row.addWidget(auto_chk)
        action_row.addStretch()
        self.content.addLayout(action_row)

        self._refresh()

    def on_activate(self) -> None:
        self._refresh()

    # ── helpers ──

    def _refresh(self) -> None:
        """Reload stats, history, and daily XP from virgo_leaderboard."""
        try:
            from virgo_leaderboard import get_history, get_stats

            stats = get_stats()
            history = get_history(days=7)

            self._update_stats(stats)
            self._update_history(history)
            self._update_daily(stats)
            self._update_quests(stats)
        except Exception:
            self._level_label.setText("Level: — (module unavailable)")
            self._history_table.setRowCount(0)

    def _update_stats(self, stats: dict) -> None:
        """Update the stats labels and XP bar."""
        total_xp = stats.get("total_xp", 0)
        total_sessions = stats.get("total_sessions", 0)
        pass_rate = stats.get("pass_rate", 0)
        streak = stats.get("current_streak", 0)
        longest = stats.get("longest_streak", 0)

        # Rough level = floor(total_xp / 100) + 1
        level = (total_xp // 100) + 1
        xp_in_level = total_xp % 100

        self._level_label.setText(f"Level: {level}")
        self._xp_label.setText(f"XP: {total_xp}")
        self._streak_label.setText(
            f"Streak: {streak} day(s)  (longest: {longest})"
        )
        self._sessions_label.setText(
            f"Sessions: {total_sessions}  ({pass_rate}% pass rate)"
        )
        self._xp_bar.setValue(xp_in_level)
        self._xp_bar.setFormat(f"Level {level}  —  {xp_in_level}/100 XP")

    def _update_history(self, history: list[dict]) -> None:
        """Populate the session history table."""
        self._history_table.setRowCount(len(history))
        for row_idx, h in enumerate(history):
            date = str(h.get("date", ""))
            xp = h.get("xp", 0)
            goal = str(h.get("goal", ""))
            passed = h.get("passed", False)

            prefix = "✓ " if passed else "✗ "
            date_item = QTableWidgetItem(f"{prefix}{date}")
            xp_item = QTableWidgetItem(f"+{xp} XP")
            goal_item = QTableWidgetItem(goal)

            color = "#a6e3a1" if passed else "#f38ba8"
            date_item.setForeground(QBrush(QColor(color)))
            xp_item.setForeground(QBrush(QColor("#f5c2e7")))

            self._history_table.setItem(row_idx, 0, date_item)
            self._history_table.setItem(row_idx, 1, xp_item)
            self._history_table.setItem(row_idx, 2, goal_item)

        self._history_table.resizeColumnsToContents()

    def _update_daily(self, stats: dict) -> None:
        """Update the daily XP progress bars for the last 7 days."""
        try:
            from virgo_leaderboard import _load

            data = _load()
        except Exception:
            data = {}

        daily_xp = data.get("daily_xp", {}) if isinstance(data, dict) else {}
        if not daily_xp:
            for name_label, bar in self._daily_widgets:
                name_label.setText("—")
                bar.setValue(0)
                bar.setFormat("")
            return

        xp_values = list(daily_xp.values())
        max_xp = max(xp_values) if xp_values else 1

        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC).date()
        for i, (name_label, bar) in enumerate(self._daily_widgets):
            day = today - timedelta(days=6 - i)
            key = day.strftime("%Y-%m-%d")
            day_name = day.strftime("%a")
            val = daily_xp.get(key, 0)
            pct = int(val / max_xp * 100) if max_xp else 0
            name_label.setText(day_name)
            bar.setValue(pct)
            bar.setFormat(f"{val} XP" if val else "")

    def _reset_data(self) -> None:
        """Reset all leaderboard data."""
        try:
            from virgo_leaderboard import reset

            reset()
            self._refresh()
        except Exception:
            pass

    def _toggle_auto_refresh(self, checked: bool) -> None:
        """Start/stop auto-refresh timer."""
        if checked:
            self._timer.start()
        else:
            self._timer.stop()

    # ── Daily Quests (#20) ──────────────────────────────────────────────
    _QUESTS_CACHE: list[dict] | None = None

    def _load_quests(self) -> list[dict]:
        """Load daily quest definitions (cached)."""
        if self._QUESTS_CACHE is not None:
            return self._QUESTS_CACHE
        quests = [
            {"id": "run_pipeline", "name": "Run a Pipeline", "icon": "🚀",
             "target": 1, "xp": 25},
            {"id": "scan_network", "name": "Scan a Subnet", "icon": "🌐",
             "target": 1, "xp": 20},
            {"id": "chat_messages", "name": "Send 5 Chat Messages", "icon": "💬",
             "target": 5, "xp": 15},
            {"id": "earn_xp", "name": "Earn 100 XP", "icon": "⭐",
             "target": 100, "xp": 50},
            {"id": "check_achievements", "name": "View Achievements", "icon": "🏆",
             "target": 1, "xp": 10},
        ]
        # Load any user-defined quests from disk
        quests_dir = Path(__file__).parent / ".virgo_quests"
        quests_dir.mkdir(exist_ok=True)
        for pf in sorted(quests_dir.glob("*.json")):
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                quests.append(data)
            except Exception:
                pass
        self._QUESTS_CACHE = quests
        return quests

    def _update_quests(self, stats: dict) -> None:
        """Refresh daily quest progress from current stats."""
        total_xp = stats.get("total_xp", 0)
        total_sessions = stats.get("total_sessions", 0)
        # Reset daily progress at midnight tracking
        quests = self._load_quests()
        for i, quest in enumerate(quests):
            if i >= len(self._quest_labels):
                break
            name_lbl, prog_lbl, xp_lbl = self._quest_labels[i]
            qid = quest["id"]
            target = quest["target"]
            # Map quest IDs to progress
            if qid == "run_pipeline":
                progress = min(total_sessions, target)
            elif qid == "earn_xp":
                progress = min(total_xp, target)
            else:
                progress = 0  # Tracked externally
            completed = progress >= target
            prog_lbl.setText(f"{progress}/{target}")
            if completed:
                name_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px; text-decoration: line-through;")
                prog_lbl.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            else:
                name_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
                prog_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")

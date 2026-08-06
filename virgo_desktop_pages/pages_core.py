"""Virgo Desktop pages — core (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

from .pages_settings import _live_ollama_models

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

        # Auto focus-mode: starts lofi once a run exceeds 2 minutes.
        self._focus_timer = QTimer()
        self._focus_timer.setInterval(5000)
        self._focus_timer.timeout.connect(self._focus_check)
        self._focus_started = False
        self._run_started: float | None = None

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

    def run_with_goal(self, goal: str, max_iter: str = "5", use_llm: bool = True) -> None:
        """Public entry point for the command center / tray: run the pipeline."""
        if self._running:
            return
        if goal:
            self.goal_input.setText(goal)
        self.iter_input.setText(max_iter)
        self.use_llm.setChecked(use_llm)
        self._run_pipeline()

    def stop(self) -> None:
        """Public stop for the command center / tray."""
        self._stop_pipeline()

    @property
    def is_running(self) -> bool:
        return bool(self._running or self._process)

    def _run_pipeline(self) -> None:
        try:
            from virgo_telemetry import track
            track("pipeline_run", page_id="pipeline", success=False)
        except Exception:
            pass
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

        # Focus mode: track the run start so _focus_check can kick in later.
        import time  # noqa: PLC0415 — lazy import

        self._run_started = time.monotonic()
        self._focus_started = False
        self._focus_timer.start()

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
            goal = self.goal_input.text().strip() or "pipeline"
            if hasattr(w, "_notify_tray"):
                if rc not in (0, None):
                    w._notify_tray("Pipeline failed", f"'{goal}' exited with code {rc}", critical=True)
                else:
                    w._notify_tray("Pipeline finished", f"'{goal}' completed successfully")
            _beep("error" if rc not in (0, None) else "done")

    def _focus_check(self) -> None:
        """Auto-start focus mode (lofi) once a run has been going > 2 minutes."""
        if self._focus_started:
            return
        try:
            import time  # noqa: PLC0415 — lazy import

            elapsed = time.monotonic() - self._run_started if self._run_started else 0.0
            if elapsed <= 120:
                return
            try:
                import virgo_focus  # noqa: PLC0415 — lazy import

                virgo_focus.start("lofi")
            except Exception:  # noqa: BLE001
                pass  # focus mode is best-effort; never break the run
            self._focus_started = True
        except Exception:  # noqa: BLE001
            pass

    def _cleanup_run(self, msg: str) -> None:
        try:
            from virgo_telemetry import track
            success = msg in ("done",) or msg.startswith("Exit code 0")
            track("pipeline_run", page_id="pipeline", success=success)
        except Exception:
            pass
        self._timer.stop()
        self._anim_timer.stop()
        self._elapsed_timer.stop()
        self._focus_timer.stop()
        if self._focus_started:
            try:
                import virgo_focus  # noqa: PLC0415 — lazy import

                virgo_focus.stop()
            except Exception:  # noqa: BLE001
                pass  # focus mode is best-effort
            self._focus_started = False
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

    # Auto-link plain URLs that aren't already markdown links.
    url_re = re.compile(r'(?<!href=")(?<!src=")\b(https?://[^\s<]+)')
    text = url_re.sub(r'<a href="\1">\1</a>', text)

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


def _prompt_slug(name: str) -> str:
    """Convert a prompt name into a safe filesystem slug."""
    slug = re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")
    return slug or "prompt"


def _load_prompt_file(path: Path) -> dict | None:
    """Load a prompt JSON file, returning it with its path attached."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["_path"] = str(path)
        return data
    except Exception:
        return None


def _write_prompt_file(prompts_dir: Path, name: str, text: str, category: str) -> Path:
    """Persist a prompt as a JSON file in the library directory."""
    prompts_dir.mkdir(exist_ok=True)
    dest = prompts_dir / f"{_prompt_slug(name)}.json"
    dest.write_text(
        json.dumps({"name": name, "text": text, "category": category}, indent=2),
        encoding="utf-8",
    )
    return dest


def _find_prompt_vars(text: str) -> list[str]:
    """Return unique {{placeholder}} names from a prompt, in order."""
    seen: list[str] = []
    for m in re.finditer(r"\{\{\s*([a-zA-Z0-9_ -]+?)\s*\}\}", text):
        var = m.group(1).strip()
        if var not in seen:
            seen.append(var)
    return seen


def _fill_prompt_vars(text: str, values: dict[str, str]) -> str:
    """Replace {{placeholders}} with the given values (unknown ones kept)."""

    def _sub(m: re.Match) -> str:
        return values.get(m.group(1).strip(), m.group(0))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_ -]+?)\s*\}\}", _sub, text)


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
        toolbar.setSpacing(6)

        # Chat actions
        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self._export)
        self.copy_btn = QPushButton("Copy reply")
        self.copy_btn.clicked.connect(self._copy_reply)
        self.regen_btn = QPushButton("Regenerate")
        self.regen_btn.clicked.connect(self._regenerate)
        self.branch_btn = QPushButton("Branch")
        self.branch_btn.setToolTip("Fork the conversation from the last message")
        self.branch_btn.clicked.connect(self._branch_from)
        for w in (self.export_btn, self.copy_btn, self.regen_btn, self.branch_btn):
            toolbar.addWidget(w)

        toolbar.addWidget(self._toolbar_sep())

        # Voice
        self.speak_btn = QPushButton("Speak")
        self.speak_btn.setToolTip("Read last reply aloud")
        self.speak_btn.clicked.connect(self._speak_reply)
        self.mic_btn = QPushButton("Mic")
        self.mic_btn.setToolTip("Speak into your microphone")
        self.mic_btn.clicked.connect(self._mic_input)
        self.voice_mode = QPushButton("Voice mode")
        self.voice_mode.setCheckable(True)
        self.voice_mode.setToolTip("Toggle: recognized speech auto-sends")
        for w in (self.speak_btn, self.mic_btn, self.voice_mode):
            toolbar.addWidget(w)

        toolbar.addWidget(self._toolbar_sep())

        # Memory / history
        self.prompt_btn = QPushButton("Prompts")
        self.prompt_btn.setToolTip("Save / load prompt templates")
        self.prompt_btn.clicked.connect(self._show_prompt_lib)
        self.history_btn = QPushButton("History")
        self.history_btn.setToolTip("Browse / load / delete past chat sessions")
        self.history_btn.clicked.connect(self._browse_history)
        self.copy_md_btn = QPushButton("Copy MD")
        self.copy_md_btn.setToolTip("Copy full chat as Markdown to clipboard")
        self.copy_md_btn.clicked.connect(self._copy_markdown)
        for w in (self.prompt_btn, self.history_btn, self.copy_md_btn):
            toolbar.addWidget(w)

        toolbar.addWidget(self._toolbar_sep())

        # Advanced
        self.split_btn = QPushButton("Split view")
        self.split_btn.setToolTip("Toggle side-by-side comparison view")
        self.split_btn.setCheckable(True)
        self.split_btn.clicked.connect(self._toggle_split)
        self.ab_btn = QPushButton("A/B")
        self.ab_btn.setToolTip("Compare two models on the same prompt, scored")
        self.ab_btn.clicked.connect(self._ab_compare)
        for w in (self.split_btn, self.ab_btn):
            toolbar.addWidget(w)

        toolbar.addStretch()
        self.content.addLayout(toolbar)

        self._check_voice_deps()

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

        self.chat_log = QTextBrowser()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Start a conversation...")
        self.chat_log.setOpenExternalLinks(True)
        self.chat_log.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_log.customContextMenuRequested.connect(self._chat_context_menu)
        self._drop_handler = _ImageDropHandler(self.chat_log, self._handle_image_drop)
        self._add(self.chat_log)

        self._cancel = False
        self._last_user = ""
        self._last_reply = ""
        self._search_context = ""  # top web results for follow-up questions

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
            ("/search <query>", "Search local memory and the web"),
            ("/mem [query]", "Show recalled memory (or recall for a query)"),
            ("/remember", "Save the last exchange to experience memory"),
            ("/remember <note>", "Save a note to persistent memory"),
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
                    self.chat_log.append(
                        f"<div style='background:#313244; border:1px solid #45475a; border-radius:10px; "
                        f"margin:6px 0 6px auto; padding:10px 14px; max-width:85%; text-align:right;'>"
                        f"<b style='color:#a6e3a1; font-size:12px;'>You</b>"
                        f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'>{self._escape(content)}</div>"
                        f"</div>"
                    )
                elif role == "assistant":
                    self._append_assistant(content)
                elif role == "system":
                    self.chat_log.append(f"<i>[System: {content[:100]}…]</i>")

        if not prev:
            # Banner
            self.chat_log.append(
                "<i>Virgo chat — local LLM. Commands: /help, /tools, /clear, "
                "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;, "
                "/search &lt;query&gt; (memory + web), /mem, /remember &lt;note&gt;. "
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
        self.chat_log.append(
            f"<div style='background:#313244; border:1px solid #45475a; border-radius:10px; "
            f"margin:6px 0 6px auto; padding:10px 14px; max-width:85%; text-align:right;'>"
            f"<b style='color:#a6e3a1; font-size:12px;'>You</b>"
            f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'>{self._escape(msg)}</div>"
            f"</div>"
        )
        self._busy = True
        try:
            from virgo_telemetry import track
            track("chat_send", page_id="chat")
        except Exception:
            pass

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
            self._search_context = ""
            self.chat_log.clear()
            self.chat_log.append("<i>[Chat history cleared]</i>")
            self._busy = False
            return
        if low.startswith("/read "):
            try:
                from virgo_telemetry import track
                track("tool_run", tool_id="read", success=False)
            except Exception:
                pass
            self._run_tool("read", {"path": msg[len("/read ") :].strip()})
            self._busy = False
            return
        if low.startswith("/web "):
            try:
                from virgo_telemetry import track
                track("tool_run", tool_id="web", success=False)
            except Exception:
                pass
            self._run_tool("web", {"url": msg[len("/web ") :].strip()})
            self._busy = False
            return
        if low.startswith("/py "):
            try:
                from virgo_telemetry import track
                track("tool_run", tool_id="py", success=False)
            except Exception:
                pass
            self._run_tool("py", {"code": msg[len("/py ") :].strip()})
            self._busy = False
            return
        if low.startswith("/search "):
            query = msg[len("/search ") :].strip()
            self._local_memory_search(query)
            self._web_search_start(query)
            self._busy = False
            return
        if low == "/mem" or low.startswith("/mem "):
            self._show_memory(msg[len("/mem") :].strip())
            self._busy = False
            return
        if low.startswith("/remember "):
            self._remember_note(msg[len("/remember ") :].strip())
            self._busy = False
            return
        if low == "/remember":
            self._remember_last_exchange()
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
        """Compose the system prompt for one turn, injecting context.

        Layers, in order: the persona, knowledge-base RAG, experience memory
        (lessons from past agent runs), recalled past chat sessions, and any
        active web search results. Every source is best-effort; a failure in
        one never breaks the chat.
        """
        system = self._persona
        try:
            from _rag import kb_context

            rag = kb_context(user_msg, top_k=3)
            if rag:
                system = f"{system}\n\n{rag}"
        except Exception:
            pass  # RAG is best-effort; never break chat on its failure

        # Experience memory — lessons from past agent runs and /remember.
        try:
            from experience import get_memory

            mem = get_memory().format_for_prompt(user_msg, k=3)
            if mem and "PAST EXPERIENCE: (none)" not in mem:
                system = f"{system}\n\n{mem}"
        except Exception:
            pass

        # Past chat sessions — keyword recall from saved conversations.
        try:
            past = self._recall_chat_history(user_msg, k=3)
            if past:
                system = f"{system}\n\nPAST CONVERSATIONS:\n" + "\n".join(past)
        except Exception:
            pass

        # Active web search results (set by /search) for follow-ups.
        if getattr(self, "_search_context", ""):
            system = f"{system}\n\nWEB SEARCH RESULTS:\n{self._search_context}"
        return system

    def _web_search_start(self, query: str) -> None:
        """Kick off a web search on a worker thread."""
        if not query:
            self.chat_log.append("<i>Usage: /search &lt;query&gt;</i>")
            return
        self.chat_log.append(f"<i>[Searching the web for: {query}…]</i>")
        threading.Thread(target=self._web_search_worker, args=(query,), daemon=True).start()

    def _web_search_worker(self, query: str) -> None:
        """Run the DuckDuckGo search off the GUI thread."""
        try:
            from virgo_web_search import web_search

            res = web_search(query)
        except Exception as exc:
            res = {"status": "error", "message": str(exc)}
        QMetaObject.invokeMethod(
            self,
            "_render_search",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, query),
            Q_ARG(str, json.dumps(res)),
        )

    @pyqtSlot(str, str)
    def _render_search(self, query: str, payload: str) -> None:
        """Render search results as clickable cards and keep them as context."""
        try:
            res = json.loads(payload)
        except Exception:
            res = {"status": "error", "message": payload}
        if res.get("status") == "error":
            self.chat_log.append(f"<i>[Search failed: {res.get('message')}]</i>")
            return
        results = res.get("results", [])
        if not results:
            self.chat_log.append(f"<i>[No results for: {query}]</i>")
            return
        cards = []
        context_lines = []
        for i, r in enumerate(results[:5], 1):
            url = str(r.get("url", ""))
            title = str(r.get("title", f"Result {i}"))
            snippet = str(r.get("snippet", ""))[:220]
            cards.append(
                f"<div style='border:1px solid #313244; border-radius:6px; margin:6px 0;"
                f"padding:6px 10px; background:#181825;'>"
                f"<b>{i}. {self._escape(title)}</b><br>"
                f"<a href='{self._escape(url)}' style='color:#89b4fa;'>"
                f"{self._escape(url[:90])}</a><br>"
                f"<span style='color:#a6adc8; font-size:12px;'>{self._escape(snippet)}</span>"
                f"</div>"
            )
            context_lines.append(f"{i}. {title} — {url}\n   {snippet}")
        self.chat_log.append(f"<b>Web search: {self._escape(query)}</b>")
        self.chat_log.append("".join(cards))
        # Keep the top results so follow-up questions can use them.
        self._search_context = "\n\n".join(context_lines[:5])
        self._history.append({"role": "user", "content": f"search: {query}"})
        self._history.append({"role": "assistant", "content": self._search_context})
        self.chat_log.append(
            "<i>[Results saved as context — ask a follow-up and Virgo can use them]</i>"
        )

    def _remember_last_exchange(self) -> None:
        """Save the last user/reply exchange into experience memory."""
        if not self._last_user or not self._last_reply:
            self.chat_log.append("<i>[Nothing to remember yet]</i>")
            return
        try:
            from experience import get_memory

            get_memory().add(
                goal=self._last_user[:200],
                approach="chat",
                tools_used=["chat"],
                outcome=self._last_reply[:300],
                success=True,
                lesson="",
            )
            self.chat_log.append("<i>[Saved last exchange to experience memory]</i>")
        except Exception as exc:
            self.chat_log.append(f"<i>[Could not save memory: {exc}]</i>")

    def _remember_note(self, note: str) -> None:
        """Persist a free-form note into unified memory (/remember <note>)."""
        if not note:
            self.chat_log.append("<i>Usage: /remember &lt;note&gt;</i>")
            return
        try:
            from memory_store import get_unified

            get_unified().remember(
                goal=note[:500],
                approach="user chat note",
                tools_used=[],
                outcome=note,
                success=True,
                lesson=note,
                task_type="chat",
            )
            self.chat_log.append(f"<i>[Remembered: {self._escape(note)}]</i>")
        except Exception as exc:  # noqa: BLE001
            self.chat_log.append(f"<i>[Could not remember note: {exc}]</i>")

    def _local_memory_search(self, query: str) -> None:
        """Search the local knowledge base (RAG) for memory hits (/search)."""
        if not query:
            self.chat_log.append("<i>Usage: /search &lt;query&gt;</i>")
            return
        try:
            from local_rag import get_rag

            rag = get_rag()
            search = getattr(rag, "search", None)
            hits = search(query) if callable(search) else rag.query(query, k=3)
            hits = [h for h in (hits or []) if h]
            if not hits:
                self.chat_log.append("<i>No memory hits for that query.</i>")
                return
            for h in hits[:3]:
                text = str(h.get("text", "") if isinstance(h, dict) else h)
                score = self._memory_hit_score(query, text)
                self.chat_log.append(f"🎯 {score:.2f} — {text[:120]}")
        except Exception as exc:  # noqa: BLE001
            self.chat_log.append(f"<i>[Memory search failed: {exc}]</i>")

    @staticmethod
    def _memory_hit_score(query: str, text: str) -> float:
        """Recall-weighted token overlap, mirroring local_rag's scorer."""
        q_tokens = set(re.findall(r"[a-zA-Z0-9_]{3,}", (query or "").lower()))
        doc_tokens = set(re.findall(r"[a-zA-Z0-9_]{3,}", (text or "").lower()))
        if not q_tokens or not doc_tokens:
            return 0.0
        return len(q_tokens & doc_tokens) / len(q_tokens)

    def _show_memory(self, query: str = "") -> None:
        """Show memory stats and optionally recall relevant experiences."""
        try:
            from experience import get_memory

            mem = get_memory()
            stats = mem.stats()
            lines = [
                f"{stats['count']} experience(s) stored, "
                f"{stats['successes']} successful, "
                f"{stats['with_embeddings']} embedded."
            ]
            if query:
                for e in mem.recall_semantic(query, k=5):
                    g = str(e.get("goal", ""))[:100]
                    o = str(e.get("outcome", ""))[:120]
                    lines.append(f"• {g} → {o}")
            else:
                for e in mem.all()[-5:]:
                    g = str(e.get("goal", ""))[:100]
                    lines.append(f"• {g}")
            self.chat_log.append("<i>Memory:</i><br>" + "<br>".join(lines))
        except Exception as exc:
            self.chat_log.append(f"<i>[Memory unavailable: {exc}]</i>")

    _MEM_STOPWORDS = frozenset(
        {
            "this", "that", "with", "from", "have", "will", "your", "what",
            "when", "were", "been", "they", "them", "their", "then", "than",
            "here", "there", "would", "could", "should", "which", "while",
            "about", "after", "before", "being", "where", "these", "those",
            "some", "such", "into", "over", "also", "because", "other",
            "more", "most", "very", "just", "like",
        }
    )

    def _recall_chat_history(self, query: str, k: int = 3) -> list[str]:
        """Find relevant Q&A pairs from past saved chat sessions.

        Scans the newest session files, ranks user/assistant pairs by keyword
        overlap with the query, and returns the top-k as prompt text.
        """
        if not _CHAT_HISTORY_DIR.exists():
            return []
        q_kw = {
            t for t in re.findall(r"[a-zA-Z]{4,}", query.lower())
            if t not in self._MEM_STOPWORDS
        }
        if not q_kw:
            return []
        scored: list[tuple[float, str]] = []
        for f in sorted(_CHAT_HISTORY_DIR.glob("chat_*.json"), reverse=True)[:40]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            msgs = data.get("messages", [])
            for i, m in enumerate(msgs):
                if m.get("role") != "user":
                    continue
                q = str(m.get("content", ""))
                nxt = msgs[i + 1] if i + 1 < len(msgs) else {}
                a = str(nxt.get("content", "")) if nxt.get("role") == "assistant" else ""
                if not q:
                    continue
                kw = {
                    t for t in re.findall(r"[a-zA-Z]{4,}", q.lower())
                    if t not in self._MEM_STOPWORDS
                }
                inter = len(q_kw & kw)
                if not inter:
                    continue
                score = inter / max(1, len(q_kw | kw))
                label = (
                    f"[{data.get('model', 'past session')}] "
                    f"Q: {q[:120]}\nA: {a[:200]}"
                )
                scored.append((score, label))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [label for _score, label in scored[:k]]

    def _stream_reply(self, msg: str) -> None:
        self._maybe_summarize()
        messages = [{"role": "system", "content": self._build_system(msg)}] + self._history
        # Forward streamed tokens into the chat box live (and keep the full text).
        collector = _GuiStream(self)
        old_stdout = sys.stdout
        sys.stdout = collector
        stopped = False
        try:
            reply = self._chat_with_fallback(messages, role="agent")
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

    @staticmethod
    def _count_tokens(text: str) -> int:
        return len(text) // 4

    def _maybe_summarize(self) -> None:
        if os.environ.get("AUTO_SUMMARIZE", "1") not in ("1", "true", "yes"):
            return
        context_window = int(os.environ.get("CONTEXT_WINDOW", "4096"))
        threshold = int(context_window * 0.75)
        total = sum(self._count_tokens(m.get("content", "")) for m in self._history)
        if total <= threshold:
            return
        split = max(1, len(self._history) // 2)
        old = self._history[:split]
        keep = self._history[split:]
        parts = []
        for m in old:
            role = m.get("role", "?")
            content = m.get("content", "")[:150]
            parts.append(f"{role}: {content}")
        summary = "; ".join(parts)
        summary_msg = {"role": "system", "content": f"[Earlier conversation summary: {summary}]"}
        self._history[:] = [summary_msg] + keep
        self.chat_log.append("<i>[Context window full — older messages summarized]</i>")

    def _chat_with_fallback(self, messages, role="agent"):
        import time as _time

        models = [self._current_model] + list(__import__("main").FALLBACK_MODELS)
        models = [m for m in models if m]
        if not models:
            c = self._client
            kwargs = {"temperature": self._temperature, "max_tokens": 2048}
            if hasattr(c, "chat_stream"):
                return c.chat_stream(messages, **kwargs)
            return c.chat(messages, **kwargs)
        last_exc = None
        for i, model in enumerate(models):
            try:
                if i > 0:
                    _time.sleep(2)
                    self._show_fallback_banner(model)
                if i == 0:
                    c = self._client
                else:
                    import main
                    c = main.get_client(model=model)
                kwargs = {"temperature": self._temperature, "max_tokens": 2048}
                if hasattr(c, "chat_stream"):
                    return c.chat_stream(messages, **kwargs)
                return c.chat(messages, **kwargs)
            except Exception as exc:
                last_exc = exc
                if i == len(models) - 1:
                    raise
                continue
        raise last_exc or RuntimeError("All fallback models failed")

    def _show_fallback_banner(self, model: str) -> None:
        self.chat_log.append(
            f"<div style='background:#f9e2af; color:#1e1e2e; border-radius:6px; "
            f"padding:6px 10px; margin:6px 0;'><b>⚠️ Fallback model: {model}</b></div>"
        )

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
                try:
                    from virgo_telemetry import track
                    track("tool_run", tool_id=tname, success=True)
                except Exception:
                    pass
            else:
                self._append_assistant(f"[tool {tname}] not allowed")
                try:
                    from virgo_telemetry import track
                    track("tool_run", tool_id=tname, success=False)
                except Exception:
                    pass

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

    @staticmethod
    def _toolbar_sep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("background: #45475a; min-width: 1px; max-width: 1px; margin: 2px 4px;")
        return sep

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
        html = _md_to_html(text)
        self.chat_log.append(
            f"<div style='background:#181825; border:1px solid #313244; border-radius:10px; "
            f"margin:6px 0 6px 0; padding:10px 14px;'>"
            f"<b style='color:#89b4fa; font-size:12px;'>Virgo</b>"
            f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'>{html}</div>"
            f"</div>"
        )

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

    def set_chat_font(self, family: str, size: int) -> None:
        """Apply a readable font (family + size) to the chat message area.

        Used by the global Font Picker so AI replies are comfortable to read.
        Family is the CSS form (e.g. \"'Segoe UI', sans-serif\"); we strip the
        first quoted token for the QFont used by appended HTML content.
        """
        self._chat_font_family = family
        self._chat_font_size = max(9, min(28, int(size)))
        qfam = family.split(",")[0].strip().strip("'").strip('"')
        self.chat_log.setFont(QFont(qfam, self._chat_font_size))
        self.chat_log.setStyleSheet(
            f"QTextEdit {{ font-family: {family}; font-size: {self._chat_font_size}px; }}"
        )
        if hasattr(self, "_split_log"):
            self._split_log.setFont(QFont(qfam, self._chat_font_size))
            self._split_log.setStyleSheet(
                f"font-family: {family}; font-size: {self._chat_font_size}px;"
            )

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
        export_btn = QPushButton("⇪")
        export_btn.setFixedSize(24, 24)
        export_btn.setToolTip("Export all prompts to one JSON file")
        export_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #6c7086; font-size: 14px; }"
            "QPushButton:hover { color: #a6e3a1; }"
        )
        export_btn.clicked.connect(self._export_prompts)
        header_row.addWidget(export_btn)
        import_btn = QPushButton("⤓")
        import_btn.setFixedSize(24, 24)
        import_btn.setToolTip("Import prompts from a JSON file")
        import_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #6c7086; font-size: 14px; }"
            "QPushButton:hover { color: #f9e2af; }"
        )
        import_btn.clicked.connect(self._import_prompts)
        header_row.addWidget(import_btn)
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
        self._prompt_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._prompt_list.customContextMenuRequested.connect(self._prompt_context_menu)
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
            data = _load_prompt_file(pf)
            if data is not None:
                self._all_prompts.append(data)
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
        """Load the selected prompt into the chat input, filling {{variables}}."""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            text = data.get("text", "")
            vars_ = _find_prompt_vars(text)
            if vars_:
                from PyQt6.QtWidgets import QInputDialog

                values: dict[str, str] = {}
                for v in vars_:
                    val, ok = QInputDialog.getText(
                        self, "Prompt variable", f"Value for {{{{v}}}}:"
                    )
                    if not ok:
                        return
                    values[v] = val
                text = _fill_prompt_vars(text, values)
            self.msg_input.setText(text)
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
        dest = self._PROMPTS_DIR / f"{_prompt_slug(name)}.json"
        existed = dest.exists()
        _write_prompt_file(self._PROMPTS_DIR, name, text, cat)
        self._prompt_name_input.clear()
        self._refresh_prompt_list()
        verb = "Overwrote" if existed else "Saved"
        self.chat_log.append(f"<i>[{verb} prompt: {name}]</i>")

    def _show_prompt_lib(self) -> None:
        """Toggle the prompt panel (replaces old dialog)."""
        self._toggle_prompt_panel()
        if self._prompt_panel.isVisible():
            # Hides the prompt panel - if user was expecting dialog, toggle on
            pass

    # ── Prompt management: right-click menu ────────────────────────────
    def _prompt_context_menu(self, pos) -> None:
        """Right-click menu for a prompt: edit, duplicate, or delete."""
        item = self._prompt_list.itemAt(pos)
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path:
            return
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        act_edit = menu.addAction("\u270f\ufe0f  Edit")
        act_dup = menu.addAction("\U0001f4c4  Duplicate")
        menu.addSeparator()
        act_del = menu.addAction("\U0001f5d1\ufe0f  Delete")
        chosen = menu.exec(self._prompt_list.viewport().mapToGlobal(pos))
        if chosen is act_edit:
            self._edit_prompt_from_menu(path)
        elif chosen is act_dup:
            self._duplicate_prompt(path)
        elif chosen is act_del:
            self._delete_prompt(path)

    def _edit_prompt_from_menu(self, path: str) -> None:
        """Load a saved prompt's contents back into the editor for changes."""
        data = _load_prompt_file(path)
        if data is None:
            return
        self._prompt_name_input.setText(str(data.get("name", "")))
        self._prompt_cat_combo.setCurrentText(str(data.get("category", "General")))
        self.msg_input.setText(str(data.get("text", "")))
        self.msg_input.setFocus()
        self.chat_log.append("<i>[Edit mode — adjust and hit \U0001f48e to save]</i>")

    def _duplicate_prompt(self, path: str) -> None:
        """Save a copy of a prompt with a ' (copy)' suffix."""
        data = _load_prompt_file(path)
        if data is None:
            return
        name = f"{data.get('name', 'prompt')} (copy)"
        _write_prompt_file(
            self._PROMPTS_DIR,
            name,
            str(data.get("text", "")),
            str(data.get("category", "General")),
        )
        self._refresh_prompt_list()
        self.chat_log.append(f"<i>[Duplicated prompt: {name}]</i>")

    def _delete_prompt(self, path: str) -> None:
        """Delete a saved prompt after confirmation."""
        from PyQt6.QtWidgets import QMessageBox

        name = Path(path).stem
        ans = QMessageBox.question(
            self,
            "Delete prompt",
            f"Delete prompt '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            Path(path).unlink()
        except Exception as exc:
            self.chat_log.append(f"<i>[Could not delete prompt: {exc}]</i>")
            return
        self._refresh_prompt_list()
        self.chat_log.append(f"<i>[Deleted prompt: {name}]</i>")

    # ── Prompt import / export ──────────────────────────────────────────
    def _export_prompts(self) -> None:
        """Write every prompt to a single JSON file for backup or sharing."""
        if not getattr(self, "_all_prompts", []):
            self.chat_log.append("<i>[No prompts to export]</i>")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export prompts",
            str(HERE / "virgo_prompts_export.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        payload = {
            "prompts": [
                {
                    "name": d.get("name", ""),
                    "text": d.get("text", ""),
                    "category": d.get("category", "General"),
                }
                for d in self._all_prompts
            ]
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.chat_log.append(
            f"<i>[Exported {len(payload['prompts'])} prompts to {Path(path).name}]</i>"
        )

    def _import_prompts(self) -> None:
        """Load prompts from an exported JSON file into the library."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import prompts", str(HERE), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self.chat_log.append(f"<i>[Import failed: {exc}]</i>")
            return
        items = data.get("prompts", data) if isinstance(data, dict) else data
        count = 0
        for p in items if isinstance(items, list) else []:
            name = str(p.get("name", "")).strip()
            text = str(p.get("text", "")).strip()
            if not name or not text:
                continue
            cat = str(p.get("category", "General"))
            if cat not in ("General", "Code", "Debug", "Custom"):
                cat = "General"
            dest = self._PROMPTS_DIR / f"{_prompt_slug(name)}.json"
            n = 1
            while dest.exists():
                dest = self._PROMPTS_DIR / f"{_prompt_slug(name)}_{n}.json"
                n += 1
            dest.write_text(
                json.dumps({"name": name, "text": text, "category": cat}, indent=2),
                encoding="utf-8",
            )
            count += 1
        self._refresh_prompt_list()
        self.chat_log.append(f"<i>[Imported {count} prompts from {Path(path).name}]</i>")

    # ── Chat history browser ─────────────────────────────────────────────
    def _browse_history(self) -> None:
        """Open a dialog to browse, load, or delete past chat sessions."""
        from PyQt6.QtWidgets import QMessageBox

        dlg = QDialog(self)
        dlg.setWindowTitle("Chat history")
        dlg.resize(580, 430)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Past sessions (newest first). Double-click to load."))
        lst = QListWidget()
        if _CHAT_HISTORY_DIR.exists():
            sessions = sorted(_CHAT_HISTORY_DIR.glob("chat_*.json"), reverse=True)
        else:
            sessions = []
        for f in sessions:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            msgs = data.get("messages", [])
            model = data.get("model", "")
            it = QListWidgetItem(
                f"{f.name}  ·  {len(msgs)} msgs  ·  {model}"
            )
            it.setData(Qt.ItemDataRole.UserRole, str(f))
            lst.addItem(it)
        if lst.count() == 0:
            lst.addItem("No saved sessions yet.")
        lay.addWidget(lst, 1)
        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load")
        del_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")
        load_btn.clicked.connect(lambda: self._load_history_item(lst.currentItem(), dlg))
        del_btn.clicked.connect(lambda: self._delete_history_item(lst, dlg))
        close_btn.clicked.connect(dlg.accept)
        lst.itemDoubleClicked.connect(lambda it: self._load_history_item(it, dlg))
        btn_row.addWidget(load_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        dlg.exec()

    def _load_history_item(self, item: QListWidgetItem | None, dlg: QDialog) -> None:
        """Load the selected history session into the chat and close the dialog."""
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if path:
            self._load_history_path(path)
            dlg.accept()

    def _delete_history_item(self, lst: QListWidget, dlg: QDialog) -> None:
        """Delete a saved chat session after confirmation."""
        from PyQt6.QtWidgets import QMessageBox

        item = lst.currentItem()
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path:
            return
        ans = QMessageBox.question(
            dlg,
            "Delete session",
            f"Delete {Path(path).name} permanently?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            Path(path).unlink()
        except Exception as exc:
            QMessageBox.warning(dlg, "Delete failed", str(exc))
            return
        lst.takeItem(lst.row(item))
        self.chat_log.append(f"<i>[Deleted session {Path(path).name}]</i>")

    def _load_history_path(self, path: str) -> None:
        """Replace the current conversation with a saved session."""
        if not path or not Path(path).exists():
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        msgs = data.get("messages", [])
        sid = data.get("session_id", "")
        self._history[:] = msgs
        if sid:
            self._session_id = sid
        self.chat_log.clear()
        for msg in msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self.chat_log.append(
                    f"<div style='background:#313244; border:1px solid #45475a; border-radius:10px; "
                    f"margin:6px 0 6px auto; padding:10px 14px; max-width:85%; text-align:right;'>"
                    f"<b style='color:#a6e3a1; font-size:12px;'>You</b>"
                    f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'>{self._escape(content)}</div>"
                    f"</div>"
                )
            elif role == "assistant":
                self._append_assistant(content)
            elif role == "system":
                self.chat_log.append(f"<i>[System: {content[:100]}…]</i>")
        self.chat_log.append(f"<i>[Loaded session {Path(path).name}]</i>")

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
    def _check_voice_deps(self) -> None:
        """Disable voice/mic buttons if required packages are missing."""
        tts_ok = True
        stt_ok = True
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            tts_ok = False
        try:
            import speech_recognition  # noqa: F401
            import pyaudio  # noqa: F401
        except ImportError:
            stt_ok = False
        if not tts_ok:
            self.speak_btn.setEnabled(False)
            self.speak_btn.setToolTip("Install edge-tts to enable speech: pip install edge-tts")
        if not stt_ok:
            self.mic_btn.setEnabled(False)
            self.mic_btn.setToolTip("Install SpeechRecognition + pyaudio to enable mic: pip install SpeechRecognition pyaudio")

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
        self.chat_log.append(
            f"<div style='background:#313244; border:1px solid #45475a; border-radius:10px; "
            f"margin:6px 0 6px auto; padding:10px 14px; max-width:85%; text-align:right;'>"
            f"<b style='color:#a6e3a1; font-size:12px;'>You</b>"
            f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'><img src='file:///{path}' width='400'></div>"
            f"</div>"
        )
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
                self.chat_log.append(
                    f"<div style='background:#313244; border:1px solid #45475a; border-radius:10px; "
                    f"margin:6px 0 6px auto; padding:10px 14px; max-width:85%; text-align:right;'>"
                    f"<b style='color:#a6e3a1; font-size:12px;'>You</b>"
                    f"<div style='color:#cdd6f4; margin-top:4px; line-height:1.5;'>{self._escape(content[:200])}</div>"
                    f"</div>"
                )
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
            "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;, "
            "/search &lt;query&gt; (memory + web), /mem, /remember &lt;note&gt;. "
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



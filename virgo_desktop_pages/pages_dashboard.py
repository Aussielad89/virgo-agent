"""Virgo Desktop pages — dashboard (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

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

        # ── Pipeline command center (runs the real PipelinePage) ──
        pipe_group = self._section("Pipeline Command Center")
        prow = QHBoxLayout()
        prow.setSpacing(8)
        prow.addWidget(QLabel("Goal:"))
        self.pipe_goal = QLineEdit("auto-fix")
        self.pipe_goal.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        self.pipe_run = QPushButton("▶  Run")
        self.pipe_run.clicked.connect(self._run_pipeline)
        self.pipe_stop = QPushButton("⏹  Stop")
        self.pipe_stop.setEnabled(False)
        self.pipe_stop.clicked.connect(self._stop_pipeline_cmd)
        prow.addWidget(self.pipe_goal, 1)
        prow.addWidget(self.pipe_run)
        prow.addWidget(self.pipe_stop)
        pipe_group.layout().addLayout(prow)
        self.pipe_status = QLabel("● Idle")
        self.pipe_status.setStyleSheet("color: #6c7086; font-size: 11px; padding: 2px;")
        pipe_group.layout().addWidget(self.pipe_status)
        self._add(pipe_group)

        # ── Command center: jump-to nav row ──
        jump_row = QHBoxLayout()
        jump_row.setSpacing(8)
        for label_text, target in [
            ("💬  Chat", "chat"), ("⚡  Swarm", "swarm"), ("⏱  Bench", "bench"),
            ("🧠  Memory", "memory"), ("💰  Budget", "budget"), ("🔍  Knowledge Base", "rag"),
        ]:
            btn = QPushButton(label_text)
            btn.setStyleSheet(
                "QPushButton { background: #181825; border: 1px solid #313244; border-radius: 6px; "
                "padding: 8px 14px; font-size: 11px; color: #a6adc8; }"
                "QPushButton:hover { background: #313244; border-color: #89b4fa; color: #cdd6f4; }"
            )
            btn.clicked.connect(
                lambda checked=False, t=target: self._jump_to(t)
            )
            jump_row.addWidget(btn)
        jump_row.addStretch()
        self.content.addLayout(jump_row)

        # ── Live command-center strip (Ollama / bus / pipeline) ──
        self._live_label = QLabel("● ollama …  📡 …  🚀 …")
        self._live_label.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 2px;")
        self._add(self._live_label)

        # ── Focus mode status ──
        self._focus_label = QLabel("")
        self._focus_label.setStyleSheet("color: #89b4fa; font-size: 11px; padding: 2px;")
        self._add(self._focus_label)

    def _jump_to(self, page_id: str) -> None:
        """Navigate the main window to *page_id* (command-center quick jump)."""
        try:
            win = self.window()
            if win is not None and hasattr(win, "_navigate"):
                win._navigate(page_id)
        except Exception:
            pass

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
        self._refresh_live()
        self._refresh_pipeline_ui()

    def _refresh_live(self) -> None:
        """Update the command-center live strip (Ollama, event bus, pipeline)."""
        try:
            parts: list[str] = []
            # Ollama
            try:
                import urllib.request

                req = urllib.request.Request(
                    "http://localhost:11434/api/tags",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    ok = resp.status == 200
                parts.append("● <span style='color:#a6e3a1'>ollama</span>" if ok else "● <span style='color:#f38ba8'>ollama</span>")
            except Exception:
                parts.append("● <span style='color:#f38ba8'>ollama</span>")
            # Event bus
            try:
                from virgo_eventbus import get_bus
                s = get_bus().status()
                running = bool(s.get("running", s.get("active", False)))
                col = "#a6e3a1" if running else "#6c7086"
                parts.append(f"<span style='color:{col}'>📡 {'on' if running else 'off'}</span>")
            except Exception:
                parts.append("📡 ?")
            # Pipeline
            try:
                state_path = HERE / ".virgo_pipeline_ui.json"
                state = "idle"
                if state_path.exists():
                    import json as _json
                    d = _json.loads(state_path.read_text(encoding="utf-8"))
                    state = str(d.get("state", d.get("status", "idle"))).lower()
                col = "#f9e2af" if state in ("running", "active", "busy") else "#6c7086"
                parts.append(f"<span style='color:{col}'>🚀 {state}</span>")
            except Exception:
                parts.append("🚀 ?")
            self._live_label.setText("   ".join(parts))
        except Exception:
            pass

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
        """Command-center run: drive the real PipelinePage (goal + live DAG)."""
        p = self._pipeline_page()
        if p is None:
            self.pipe_status.setText("Pipeline page unavailable")
            return
        p.run_with_goal(self.pipe_goal.text().strip())
        self._jump_to("pipeline")

    def _stop_pipeline_cmd(self) -> None:
        p = self._pipeline_page()
        if p is not None:
            p.stop()

    def _pipeline_page(self):
        w = self.window()
        if w is None:
            return None
        return getattr(w, "pages", {}).get("pipeline")

    def _refresh_pipeline_ui(self) -> None:
        p = self._pipeline_page()
        running = bool(p is not None and p.is_running)
        self.pipe_run.setEnabled(not running)
        self.pipe_stop.setEnabled(running)
        self.pipe_status.setText("🟡 Running…" if running else "● Idle")

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



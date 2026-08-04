"""Virgo Desktop pages — agents (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

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




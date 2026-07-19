"""
Virgo Desktop pages — each page is a QWidget plugged into the main window.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QMetaObject, pyqtSlot, Q_ARG, QUrl
from PyQt6.QtGui import QFont, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget, QFileDialog,
    QSlider, QCompleter, QCheckBox, QDialog,
)

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log, OUTDIR


# ═══════════════════════════════════════════════════════════════════════
# Helper: page wrapper with title bar
# ═══════════════════════════════════════════════════════════════════════

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
        self.content.addWidget(gb)
        return gb


# ═══════════════════════════════════════════════════════════════════════
# Pipeline page
# ═══════════════════════════════════════════════════════════════════════

class PipelinePage(PageWidget):
    """Run the pipeline and watch real-time output."""

    def __init__(self) -> None:
        super().__init__(
            "Pipeline",
            "Write → Test → Fix loop with live output.",
        )
        self._process: subprocess.Popen | None = None
        self._running = False

        # Goal input
        goal_group = self._section("Goal")
        goal_row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. build a web scraper that fetches Hacker News headlines")
        goal_row.addWidget(self.goal_input, 1)
        self.run_btn = QPushButton(f"{icon('run')}  Run")
        self.run_btn.clicked.connect(self._run_pipeline)
        goal_row.addWidget(self.run_btn)
        self.stop_btn = QPushButton(f"{icon('stop')}  Stop")
        self.stop_btn.clicked.connect(self._stop_pipeline)
        self.stop_btn.setEnabled(False)
        goal_row.addWidget(self.stop_btn)
        goal_group.layout().addLayout(goal_row)  # type: ignore

        # Options row
        opt_row = QHBoxLayout()
        self.use_llm = QPushButton(f"{icon('llm')}  LLM: ON")
        self.use_llm.setCheckable(True)
        self.use_llm.setChecked(True)
        self.use_llm.clicked.connect(self._toggle_llm)
        opt_row.addWidget(self.use_llm)

        self.iter_label = QLabel("Max iterations:")
        opt_row.addWidget(self.iter_label)
        self.iter_input = QLineEdit("5")
        self.iter_input.setFixedWidth(50)
        opt_row.addWidget(self.iter_input)
        opt_row.addStretch()
        goal_group.layout().addLayout(opt_row)  # type: ignore

        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self._add(self.progress)

        # Splitter: log output + status
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Pipeline output will appear here...")
        splitter.addWidget(self.output)

        status_group = self._section("Status")
        self.status_label = QLabel("Idle")
        status_group.layout().addWidget(self.status_label)  # type: ignore
        self._add(splitter)

        # Timer for polling subprocess
        self._timer = QTimer()
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_process)

    def on_activate(self) -> None:
        self.goal_input.setFocus()

    def _toggle_llm(self) -> None:
        self.use_llm.setText(f"{icon('llm')}  LLM: {'ON' if self.use_llm.isChecked() else 'OFF'}")

    def _run_pipeline(self) -> None:
        goal = self.goal_input.text().strip()
        if not goal:
            self.output.appendPlainText(f"{icon('warn')} Please enter a goal first.")
            return

        self.output.clear()
        self._running = True
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # indeterminate
        self.status_label.setText("Running...")

        args = [
            sys.executable, str(HERE / "cli.py"),
            "run",
            "--goal", goal,
            "--max-iterations", self.iter_input.text() or "5",
        ]
        if self.use_llm.isChecked():
            args.append("--llm")

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._timer.start()

    def _stop_pipeline(self) -> None:
        if self._process:
            self._process.kill()
            self._process = None
        self._running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.status_label.setText("Stopped")

    def _poll_process(self) -> None:
        if not self._process:
            self._timer.stop()
            return
        if self._process.stdout:
            line = self._process.stdout.readline()
            if line:
                self.output.appendPlainText(line.rstrip())
        if self._process.poll() is not None:
            # Drain remaining output
            if self._process.stdout:
                for line in self._process.stdout:
                    self.output.appendPlainText(line.rstrip())
            self._timer.stop()
            self._running = False
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.progress.setVisible(False)
            rc = self._process.returncode
            self.status_label.setText(f"Finished (exit code {rc})")
            self._process = None


# ═══════════════════════════════════════════════════════════════════════
# Chat page
# ═══════════════════════════════════════════════════════════════════════

def _strip_think(text: str) -> str:
    """Remove  blocks and surrounding whitespace from model output."""
    import re
    return re.sub(r'\s*<think>.*?</think>\s*', '', text, flags=re.DOTALL)


class _StopStream(Exception):
    """Raised inside the stream writer to abort an in-flight reply."""


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
        toolbar.addStretch()
        self.content.addLayout(toolbar)

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
        opts_row.addStretch()
        self.content.addLayout(opts_row)

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Start a conversation...")
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
        completer = QCompleter(
            ["/help", "/tools", "/clear", "/read ", "/web ", "/py "], self.msg_input
        )
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.msg_input.setCompleter(completer)
        input_row.addWidget(self.msg_input, 1)
        self.send_btn = QPushButton(f"{icon('send')}  Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        self.content.addLayout(input_row)

        # Ctrl+Enter / Ctrl+Return sends the message.
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._send)

        # LLM client (lazy, set on first activate)
        self._client = None
        self._client_checked = False
        self._history: list[dict[str, str]] = []
        self._busy = False

        # Banner
        self.chat_log.append(
            "<i>Virgo chat — local LLM. Commands: /help, /tools, /clear, "
            "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;. "
            "Use Attach to send files or photos.</i>"
        )

    def _attach(self) -> None:
        """Open a file picker and attach selected files / photos to the chat."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Attach files or photos", "",
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
            self.chat_log.append(
                f"<i>You attached a photo:</i><br><img src='{url}' width='240'>"
            )
            self._history.append(
                {"role": "user", "content": f"[User attached photo: {p.name}]"}
            )
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
        self._history.append({
            "role": "user",
            "content": f"[Attached file {p.name}]\n```\n{shown}\n```",
        })

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
            self.chat_log.append(
                f"<i>[LLM connected — {chat_model}]</i>"
            )
            win = self.window()
            if hasattr(win, "set_status"):
                win.set_status(f"Model: {chat_model} · Connected")
        except Exception as exc:
            self._client = None
            self.chat_log.append(
                f"<i>[No LLM detected ({exc}) — running in echo mode]</i>"
            )
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
            self._run_tool("read", {"path": msg[len("/read "):].strip()})
            self._busy = False
            return
        if low.startswith("/web "):
            self._run_tool("web", {"url": msg[len("/web "):].strip()})
            self._busy = False
            return
        if low.startswith("/py "):
            self._run_tool("py", {"code": msg[len("/py "):].strip()})
            self._busy = False
            return

        if self._client is None:
            self._append_assistant(f"(echo) You said: {msg}")
            self._busy = False
            return

        self._history.append({"role": "user", "content": msg})
        self.chat_log.append("<i>Virgo is thinking...</i>")
        self._cancel = False
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        # Stream the reply off the GUI thread, then render it.
        threading.Thread(target=self._stream_reply, args=(msg,), daemon=True).start()

    def _stream_reply(self, msg: str) -> None:
        from cli import VIRGO_SYSTEM_PROMPT, _parse_tool_calls  # lazy import (safe)

        messages = [{"role": "system", "content": VIRGO_SYSTEM_PROMPT}] + self._history
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
            QMetaObject.invokeMethod(
                self, "_finish_stop", Qt.ConnectionType.QueuedConnection
            )
            return

        # Ensure the final text is the collected reply (in case streaming
        # wrote partial chunks, the client returns the full string).
        if not reply:
            reply = collector.text
        # Schedule the final render on the GUI thread (cross-thread safe).
        QMetaObject.invokeMethod(
            self, "_render_reply", Qt.ConnectionType.QueuedConnection,
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
            self.chat_log.append(
                f"<i>[Model switch failed ({exc}) — echo mode]</i>"
            )

    @pyqtSlot()
    def _stream_start(self) -> None:
        """Replace the 'thinking...' placeholder with the live reply line."""
        cursor = self.chat_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText("<b>Virgo:</b> ")
        self.chat_log.moveCursor(cursor.MoveOperation.End)

    @pyqtSlot(str)
    def _stream_chunk(self, chunk: str) -> None:
        """Append one streamed chunk to the live reply line."""
        self.chat_log.insertPlainText(chunk)
        self.chat_log.verticalScrollBar().setValue(
            self.chat_log.verticalScrollBar().maximum()
        )

    @pyqtSlot(str, bool)
    def _render_reply(self, reply: str, streamed: bool = False) -> None:
        reply = _strip_think(reply)
        self._last_reply = reply
        est = (len(reply) + len(self._last_user)) // 4
        self.token_label.setText(f"~{est} tokens")
        if not streamed:
            # Replace the trailing "thinking..." line with the real reply.
            cursor = self.chat_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText("")  # clear the empty block left behind
            self.chat_log.append("")  # re-add a clean paragraph
            self._append_assistant(reply)
        self._history.append({"role": "assistant", "content": reply})

        # Agentic tool-use: run any [[virgo.<tool>]] calls the model emitted.
        from cli import _run_chat_tool, _CHAT_TOOLS, _parse_tool_calls  # lazy import (safe)
        for tname, tkwargs in _parse_tool_calls(reply):
            if tname in _CHAT_TOOLS:
                try:
                    out = _run_chat_tool(tname, tkwargs)
                except Exception as exc:
                    out = f"(tool error: {exc})"
                self._append_assistant(f"[tool {tname}] {out[:800]}")
                self._history.append(
                    {"role": "system", "content": f"[tool {tname}] {out}"}
                )
            else:
                self._append_assistant(f"[tool {tname}] not allowed")

        self.stop_btn.setVisible(False)
        self._busy = False

    def _run_tool(self, name: str, kwargs: dict[str, str]) -> None:
        from cli import _run_chat_tool  # lazy import (safe)
        try:
            out = _run_chat_tool(name, kwargs)
        except Exception as exc:
            out = f"(tool error: {exc})"
        self._append_assistant(f"[tool {name}] {out[:800]}")

    def _append_assistant(self, text: str) -> None:
        self.chat_log.append(f"<b>Virgo:</b> {text}")

    def _copy_reply(self) -> None:
        """Copy Virgo's last reply to the clipboard."""
        text = getattr(self, "_last_reply", "")
        if not text:
            self.chat_log.append("<i>[No reply to copy yet]</i>")
            return
        QApplication.clipboard().setText(text)
        self.chat_log.append("<i>[Copied last reply to clipboard]</i>")

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
            self, "Export chat", "virgo-chat.md",
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
            "    registry.register(Tool(name=\"my tool\", fn=run,\n"
            "                             description=\"Example plugin tool\"))\n"
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
        srv.layout().addWidget(QLabel(  # type: ignore
            "Register this in your MCP host (Claude Desktop, Cursor, etc.):"
        ))
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
            from mcp_server import _build_registry, PROTOCOL_VERSION, SERVER_INFO
            reg = _build_registry()
            info = (f"Protocol {PROTOCOL_VERSION} · {SERVER_INFO['name']} "
                    f"v{SERVER_INFO['version']} · {len(reg.list())} tool(s) exposed")
        except Exception as exc:
            info = f"Could not build registry: {exc}"
        srv.layout().addWidget(self.config_view)  # type: ignore
        copy_row = QHBoxLayout()
        copy_row.addWidget(
            QPushButton(f"{icon('file')}  Copy config", clicked=self._copy_config)
        )
        copy_row.addStretch()
        srv.layout().addLayout(copy_row)  # type: ignore
        srv.layout().addWidget(QLabel(info))  # type: ignore

        # ── Connect to MCP servers (client mode) ──
        cli = self._section("Connect to MCP servers")
        cli.layout().addWidget(QLabel(  # type: ignore
            "Discovered from .mcp.json / claude_desktop_config.json / ~/.gemini"
        ))
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
        ctrl_row.addWidget(
            QPushButton(f"{icon('file')}  Add server", clicked=self._add_server)
        )
        ctrl_row.addWidget(
            QPushButton(f"{icon('run')}  Test selected", clicked=self._test_server)
        )
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
                    "\n".join(
                        f"- {t.get('name')}: {t.get('description', '')}" for t in tools
                    )
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

    def __init__(self, page: "ChatPage") -> None:
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
                self._buf = combined[-len(partial):] + self._buf
                combined = combined[:-len(partial)]
                break

        # Strip fully closed think blocks (preserve surrounding whitespace)
        result = re.sub(r'\s*<think>.*?</think>\s*', '', combined, flags=re.DOTALL)
        return result

    def flush(self) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Network Scanner page
# ═══════════════════════════════════════════════════════════════════════

class NetworkPage(PageWidget):
    """Network discovery and device scanning."""

    def __init__(self) -> None:
        super().__init__(
            "Network",
            "Discover devices on your local subnet.",
        )

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel(f"{icon('info')} Subnet:"))
        self.subnet_input = QLineEdit("192.168.1.0/24")
        self.subnet_input.setFixedWidth(160)
        target_row.addWidget(self.subnet_input)
        self.scan_btn = QPushButton(f"{icon('run')}  Scan")
        self.scan_btn.clicked.connect(self._scan)
        target_row.addWidget(self.scan_btn)
        self.auto_cb = QCheckBox("Auto (30s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        target_row.addWidget(self.auto_cb)
        self.export_btn = QPushButton(f"{icon('save')}  Export CSV")
        self.export_btn.clicked.connect(self._export)
        target_row.addWidget(self.export_btn)
        target_row.addStretch()
        self.content.addLayout(target_row)

        self.results_list = QListWidget()
        self._add(self.results_list)

        self.status = QLabel("Ready")
        self._add(self.status)

        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._scan)

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._scan()
            self._timer.start()
        else:
            self._timer.stop()

    def _scan(self) -> None:
        self.status.setText("Scanning...")
        self.scan_btn.setEnabled(False)

        def _run() -> None:
            text = ""
            try:
                from virgo_network_scanner import scan_subnet
                devices = scan_subnet(self.subnet_input.text())
                text = "\n".join(str(d) for d in (devices or []))
            except Exception as exc:
                text = f"Error: {exc}"
            QMetaObject.invokeMethod(
                self, "_show_results", Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, text),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(str)
    def _show_results(self, text: str) -> None:
        self.results_list.clear()
        for line in text.strip().split("\n"):
            if line:
                self.results_list.addItem(line)
        self.status.setText(f"{self.results_list.count()} device(s)")
        self.scan_btn.setEnabled(True)

    def _export(self) -> None:
        if self.results_list.count() == 0:
            self.status.setText("Nothing to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export devices", "network-scan.csv", "CSV (*.csv)"
        )
        if not path:
            return
        rows = [self.results_list.item(i).text() for i in range(self.results_list.count())]
        Path(path).write_text("\n".join(rows), encoding="utf-8")
        self.status.setText(f"Exported {len(rows)} device(s)")


# ═══════════════════════════════════════════════════════════════════════
# Diagnostics page
# ═══════════════════════════════════════════════════════════════════════

class DiagnosticsPage(PageWidget):
    """System health diagnostics."""

    def __init__(self) -> None:
        super().__init__(
            "Diagnostics",
            "CPU, memory, disk, and service health checks.",
        )

        self._add_row(
            QPushButton(f"{icon('run')}  Run Full Diagnostics", clicked=self._run_diag),
            QPushButton(f"{icon('save')}  Export JSON", clicked=self._export),
        )
        self.auto_cb = QCheckBox("Auto (60s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        self._add_row(self.auto_cb)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(500)
        self._add(self.output)

        self._timer = QTimer()
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self._run_diag)

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._run_diag()
            self._timer.start()
        else:
            self._timer.stop()

    def _run_diag(self) -> None:
        self.output.clear()
        self.output.appendPlainText("Running system diagnostics...\n")

        def _run() -> None:
            import io
            try:
                from virgo_diagnostics import run_full_diagnostics
                buf = io.StringIO()
                old = sys.stdout
                sys.stdout = buf
                try:
                    run_full_diagnostics()
                finally:
                    sys.stdout = old
                text = buf.getvalue()
            except Exception as exc:
                text = f"Error: {exc}"
            QMetaObject.invokeMethod(
                self, "_append_diag", Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, text),
            )

        threading.Thread(target=_run, daemon=True).start()

    def _export(self) -> None:
        text = self.output.toPlainText().strip()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export diagnostics", "diagnostics.json", "JSON (*.json)"
        )
        if not path:
            return
        import re as _re
        # Best-effort: store the raw log; attempt to parse key/value lines.
        try:
            data = dict(_re.findall(r"^([\w\s]+):\s*(.+)$", text, _re.MULTILINE))
        except Exception:
            data = {"raw": text}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @pyqtSlot(str)
    def _append_diag(self, text: str) -> None:
        self.output.appendPlainText(text)


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
                self, "_show_alerts", Qt.ConnectionType.QueuedConnection,
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
            self.scaffold_combo.addItems(["fastapi-crud", "cli-app", "flask-app", "python-lib", "agent-tool"])

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
            "Inspect and replay saved pipeline / swarm sessions.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
        )
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("type to filter sessions…")
        self.search_input.textChanged.connect(lambda _: self._refresh())
        search_row.addWidget(self.search_input, 1)
        self.content.addLayout(search_row)

        self.session_list = QListWidget()
        self.session_list.setMinimumHeight(220)
        self.session_list.currentItemChanged.connect(self._on_select)
        self._add(self.session_list)

        # Detail panel
        detail = self._section("Session detail")
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(160)
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

    def _delete(self) -> None:
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
        self.session_list.clear()
        self._current = None
        try:
            from memory import list_sessions
            sessions = list_sessions()
        except Exception as exc:
            self.status.setText(f"Error: {exc}")
            return
        self._sessions = sessions

        if not sessions:
            self.status.setText("No sessions found in .virgo_memory/")
            return

        q = self.search_input.text().strip().lower()
        shown = 0
        for s in sessions:
            label = s.get("name", "?")
            goal = (s.get("goal") or "").strip()
            if goal:
                label += f"  —  {goal[:60]}"
            phase = s.get("phase")
            if phase:
                label += f"  [{phase}]"
            if q and q not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(256, s)  # Qt.UserRole
            self.session_list.addItem(item)
            shown += 1
        self.status.setText(f"{shown}/{len(sessions)} session(s)")

    def _on_select(self, current, _prev) -> None:
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

    def _replay(self) -> None:
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

    def _open_json(self) -> None:
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
    """Launch a multi-agent delegation (swarm) run."""

    def __init__(self) -> None:
        super().__init__(
            "",
            "Give a goal and Virgo figures out the rest.",
        )

        goal_group = self._section("Goal")
        goal_row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. build a REST API and a CLI that consumes it")
        goal_row.addWidget(self.goal_input, 1)
        goal_group.layout().addLayout(goal_row)  # type: ignore

        # LLM toggle (default ON)
        opt_row = QHBoxLayout()
        self.use_llm = QPushButton(f"{icon('llm')}  LLM: ON")
        self.use_llm.setCheckable(True)
        self.use_llm.setChecked(True)
        self.use_llm.clicked.connect(self._toggle_llm)
        opt_row.addWidget(self.use_llm)
        opt_row.addStretch()
        goal_group.layout().addLayout(opt_row)  # type: ignore

        self._add_row(
            QPushButton(f"{icon('run')}  Launch swarm", clicked=self._launch),
        )

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Swarm output will appear here...")
        self._add(self.output)

        self._running = False

    def on_activate(self) -> None:
        self.goal_input.setFocus()

    def _toggle_llm(self) -> None:
        self.use_llm.setText(f"{icon('llm')}  LLM: {'ON' if self.use_llm.isChecked() else 'OFF'}")

    def _launch(self) -> None:
        if self._running:
            return
        goal = self.goal_input.text().strip()
        if not goal:
            self.output.appendPlainText(f"{icon('warn')} Enter a goal.")
            return
        # Load saved .env so the Settings model dropdowns drive the swarm.
        env_path = HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ[k.strip()] = v.strip()

        self.output.clear()
        self.output.appendPlainText(f"{icon('run')}  Launching swarm: {goal}")
        self._running = True

        args = [
            sys.executable, str(HERE / "cli.py"),
            "swarm",
            "--goal", goal,
            "--llm",
        ]

        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self) -> None:
        try:
            for line in iter(self._proc.stdout.readline, ""):  # type: ignore
                if not line:
                    break
                QMetaObject.invokeMethod(
                    self, "_append_output", Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, line.rstrip()),
                )
            self._proc.wait()
        except Exception as exc:
            QMetaObject.invokeMethod(
                self, "_append_output", Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, f"(error: {exc})"),
            )
        finally:
            QMetaObject.invokeMethod(
                self, "_set_done", Qt.ConnectionType.QueuedConnection,
            )

    @pyqtSlot(str)
    def _append_output(self, line: str) -> None:
        self.output.appendPlainText(line)
        self.output.verticalScrollBar().setValue(
            self.output.verticalScrollBar().maximum()
        )

    @pyqtSlot()
    def _set_done(self) -> None:
        from cli import icon as _icon
        self.output.appendPlainText(f"\n{_icon('done')}  Swarm finished.")
        self._running = False


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
        self._add_row(
            QLabel("Level:"),
            self.level_combo,
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
            self.log_output.setPlainText("\n".join(lines))

    def _clear_logs(self) -> None:
        log_file = OUTDIR / "virgo.log"
        if log_file.exists():
            log_file.write_text("")
        self.log_output.clear()


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
        raw = urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=3
        ).read()
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
        env_path.write_text("".join(lines))
        self.save_status.setText(f"{icon('ok')} Saved to .env")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))

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
            f"<p>A polished GUI for the <b>virgo-agent</b> framework — "
            f"multi-agent state machine with diagnostics, network scanning, "
            f"alerting, web search, project scaffolding, and system monitoring.</p>"
            f"<hr>"
            f"<p><b>Agent Runtime:</b> ReAct loop with tool use, evaluation, "
            f"and experience memory.</p>"
            f"<p><b>Pipeline:</b> Discover → Plan → Generate → Critic → "
            f"Test/Fix loop.</p>"
            f"<p><b>System:</b> Diagnostics, alerts, network scanning, "
            f"auto-remediation, webhooks.</p>"
            f"<hr>"
            f"<p><b>Shortcuts:</b> 1–9 / 0 switch pages · Ctrl+Enter sends "
            f"chat · Esc/close minimizes to tray.</p>"
            f"<hr>"
            f"<p>Built with PyQt6 · MIT License</p>"
            f"<p><a href='https://github.com/Aussielad89/virgo-agent' "
            f"style='color: #89b4fa;'>github.com/Aussielad89/virgo-agent</a></p>"
        )
        about_text.setWordWrap(True)
        about_text.setTextFormat(Qt.TextFormat.RichText)
        self._add(about_text)

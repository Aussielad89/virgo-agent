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

from PyQt6.QtCore import Qt, QTimer, QMetaObject, pyqtSlot, Q_ARG
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
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
            "",
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

class ChatPage(PageWidget):
    """Interactive streaming chat with Virgo (local LLM)."""

    def __init__(self) -> None:
        super().__init__(
            "",
            "Talk to Virgo — powered by your local LLM. Type /help for commands.",
        )

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Start a conversation...")
        self._add(self.chat_log)

        input_row = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Message Virgo, or /help for commands...")
        self.msg_input.returnPressed.connect(self._send)
        input_row.addWidget(self.msg_input, 1)
        self.send_btn = QPushButton(f"{icon('send')}  Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        self.content.addLayout(input_row)

        # LLM client (lazy, set on first activate)
        self._client = None
        self._client_checked = False
        self._history: list[dict[str, str]] = []
        self._busy = False

        # Banner
        self.chat_log.append(
            "<i>Virgo chat — local LLM. Commands: /help, /tools, /clear, "
            "/read &lt;path&gt;, /web &lt;url&gt;, /py &lt;code&gt;</i>"
        )

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
                        os.environ.setdefault(k.strip(), v.strip())
            chat_model = os.environ.get("MODEL_GENERATOR", "phi4-mini-reasoning:3.8b")
            self._client = main.get_client(model=chat_model)
            self.chat_log.append(
                f"<i>[LLM connected — {chat_model}]</i>"
            )
        except Exception as exc:
            self._client = None
            self.chat_log.append(
                f"<i>[No LLM detected ({exc}) — running in echo mode]</i>"
            )

    def _send(self) -> None:
        if self._busy:
            return
        msg = self.msg_input.text().strip()
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
        # Stream the reply off the GUI thread, then render it.
        threading.Thread(target=self._stream_reply, args=(msg,), daemon=True).start()

    def _stream_reply(self, msg: str) -> None:
        from cli import VIRGO_SYSTEM_PROMPT, _parse_tool_calls  # lazy import (safe)

        messages = [{"role": "system", "content": VIRGO_SYSTEM_PROMPT}] + self._history
        # Forward streamed tokens into the chat box live (and keep the full text).
        collector = _GuiStream(self)
        old_stdout = sys.stdout
        sys.stdout = collector
        try:
            reply = self._client.chat_stream(
                messages, temperature=0.7, max_tokens=2048, role="agent"
            )
        except Exception as exc:
            reply = f"(LLM error: {exc})"
        finally:
            sys.stdout = old_stdout

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
            "",
            "Discover devices on your local subnet.",
        )

        self._add_row(
            QLabel(f"{icon('info')} Target subnet:"),
        )
        target_row = QHBoxLayout()
        self.subnet_input = QLineEdit("192.168.1.0/24")
        self.subnet_input.setFixedWidth(160)
        target_row.addWidget(self.subnet_input)
        self.scan_btn = QPushButton(f"{icon('run')}  Scan")
        self.scan_btn.clicked.connect(self._scan)
        target_row.addWidget(self.scan_btn)
        target_row.addStretch()
        self.content.addLayout(target_row)

        self.results_list = QListWidget()
        self._add(self.results_list)

        self.status = QLabel("Ready")
        self._add(self.status)

    def _scan(self) -> None:
        self.results_list.clear()
        self.status.setText("Scanning...")
        self.scan_btn.setEnabled(False)

        def _run() -> None:
            try:
                from virgo_network_scanner import scan_subnet
                devices = scan_subnet(self.subnet_input.text())
            except Exception as exc:
                devices = [f"Error: {exc}"]

            for dev in (devices or ["(no devices found)"]):
                self.results_list.addItem(str(dev))
            self.status.setText(f"Found {len(self.results_list)} device(s)")
            self.scan_btn.setEnabled(True)

        threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# Diagnostics page
# ═══════════════════════════════════════════════════════════════════════

class DiagnosticsPage(PageWidget):
    """System health diagnostics."""

    def __init__(self) -> None:
        super().__init__(
            "",
            "CPU, memory, disk, and service health checks.",
        )

        self._add_row(
            QPushButton(f"{icon('run')}  Run Full Diagnostics", clicked=self._run_diag),
        )

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(500)
        self._add(self.output)

    def _run_diag(self) -> None:
        self.output.clear()
        self.output.appendPlainText("Running system diagnostics...\n")

        def _run() -> None:
            try:
                from virgo_diagnostics import run_all_checks
                report = run_all_checks()
                self.output.appendPlainText(json.dumps(report, indent=2))
            except Exception as exc:
                self.output.appendPlainText(f"Error: {exc}")

        threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# Alerts page
# ═══════════════════════════════════════════════════════════════════════

class AlertsPage(PageWidget):
    """Alert evaluation and history."""

    def __init__(self) -> None:
        super().__init__(
            "",
            "Threshold-based alert evaluation from diagnostics & network data.",
        )

        self._add_row(
            QPushButton(f"{icon('run')}  Evaluate Alerts", clicked=self._evaluate),
            QPushButton(f"{icon('delete')}  Clear Alerts", clicked=self._clear),
        )

        self.alerts_list = QListWidget()
        self._add(self.alerts_list)
        self.status = QLabel("No alerts evaluated yet.")
        self._add(self.status)

    def _evaluate(self) -> None:
        self.alerts_list.clear()
        self.status.setText("Evaluating...")

        def _run() -> None:
            try:
                from virgo_alerts import check_thresholds
                check_thresholds()
            except Exception as exc:
                self.alerts_list.addItem(f"Error: {exc}")

            # Load alerts file
            alert_path = OUTDIR / "ALERTS_TRIGGERED.txt"
            if alert_path.exists():
                text = alert_path.read_text()
                for line in text.strip().split("\n"):
                    self.alerts_list.addItem(line)
                self.status.setText(f"{len(self.alerts_list)} alert(s)")
            else:
                self.alerts_list.addItem("System clear — no alerts triggered.")
                self.status.setText("No alerts")

        threading.Thread(target=_run, daemon=True).start()

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
            "",
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
            "",
            "Inspect and replay saved pipeline / swarm sessions.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
        )

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
        )

        self.status = QLabel("No sessions yet.")
        self._add(self.status)
        self._current: dict[str, Any] | None = None

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

        if not sessions:
            self.status.setText("No sessions found in .virgo_memory/")
            return

        for s in sessions:
            label = s.get("name", "?")
            goal = (s.get("goal") or "").strip()
            if goal:
                label += f"  —  {goal[:60]}"
            phase = s.get("phase")
            if phase:
                label += f"  [{phase}]"
            item = QListWidgetItem(label)
            item.setData(256, s)  # Qt.UserRole
            self.session_list.addItem(item)
        self.status.setText(f"{len(sessions)} session(s)")

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
            "Run parallel sub-agents toward one overarching goal.",
        )

        goal_group = self._section("Swarm goal")
        goal_row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. build a REST API and a CLI that consumes it")
        goal_row.addWidget(self.goal_input, 1)
        goal_group.layout().addLayout(goal_row)  # type: ignore

        # Agent specs (name:goal, one per line)
        agents_group = self._section("Agents  (name:goal, one per line)")
        self.agents_input = QPlainTextEdit()
        self.agents_input.setPlaceholderText(
            "scout: research existing APIs\n"
            "builder: write the FastAPI app\n"
            "tester: write pytest tests"
        )
        self.agents_input.setMaximumHeight(120)
        agents_group.layout().addWidget(self.agents_input)  # type: ignore

        # Options
        opt_row = QHBoxLayout()
        self.use_llm = QPushButton(f"{icon('llm')}  LLM: ON")
        self.use_llm.setCheckable(True)
        self.use_llm.setChecked(True)
        self.use_llm.clicked.connect(self._toggle_llm)
        opt_row.addWidget(self.use_llm)

        self.share_btn = QPushButton("Shared board: OFF")
        self.share_btn.setCheckable(True)
        self.share_btn.setChecked(False)
        self.share_btn.clicked.connect(self._toggle_share)
        opt_row.addWidget(self.share_btn)

        self.ordered_btn = QPushButton("Ordered: OFF")
        self.ordered_btn.setCheckable(True)
        self.ordered_btn.setChecked(False)
        self.ordered_btn.clicked.connect(self._toggle_ordered)
        opt_row.addWidget(self.ordered_btn)
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

    def _toggle_share(self) -> None:
        self.share_btn.setText(f"Shared board: {'ON' if self.share_btn.isChecked() else 'OFF'}")

    def _toggle_ordered(self) -> None:
        self.ordered_btn.setText(f"Ordered: {'ON' if self.ordered_btn.isChecked() else 'OFF'}")

    def _launch(self) -> None:
        if self._running:
            return
        goal = self.goal_input.text().strip()
        if not goal:
            self.output.appendPlainText(f"{icon('warn')} Enter an overarching goal.")
            return
        # Load saved .env so the Settings model dropdowns drive the swarm.
        env_path = HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
        agents = []
        for line in self.agents_input.toPlainText().splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, _, ag = line.partition(":")
            agents.append((name.strip(), ag.strip()))
        if not agents:
            self.output.appendPlainText(
                f"{icon('warn')} Add at least one agent as name:goal."
            )
            return

        self._running = True
        self.output.clear()
        self.output.appendPlainText(f"{icon('rocket')} Launching swarm: {goal}")
        for n, g in agents:
            self.output.appendPlainText(f"  - {n}: {g}")

        args = [
            sys.executable, str(HERE / "cli.py"), "swarm",
            "--goal", goal,
            "--iterations", "3",
        ]
        for n, g in agents:
            args += ["--agent", f"{n}:{g}"]
        if self.use_llm.isChecked():
            args.append("--llm")
        if self.share_btn.isChecked():
            args.append("--share")
        if self.ordered_btn.isChecked():
            args.append("--ordered")

        def _run() -> None:
            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.output.appendPlainText(line.rstrip())
                proc.wait()
                self.output.appendPlainText(
                    f"\n{icon('done')} Swarm finished (exit {proc.returncode})."
                )
            except Exception as exc:
                self.output.appendPlainText(f"{icon('error')} {exc}")
            finally:
                self._running = False

        threading.Thread(target=_run, daemon=True).start()


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

        self._add_row(
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
            "",
            "Settings",
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

        self._add_row(
            QPushButton(f"{icon('save')}  Save", clicked=self._save),
        )

        self.save_status = QLabel("")
        self._add(self.save_status)

    def _save(self) -> None:
        env_path = HERE / ".env"
        lines = [f"# Virgo Desktop — saved {__import__('datetime').datetime.now()}\n"]
        for key, widget in self._fields.items():
            value = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
            lines.append(f"{key}={value}\n")
        env_path.write_text("".join(lines))
        self.save_status.setText(f"{icon('ok')} Saved to .env")
        QTimer.singleShot(3000, lambda: self.save_status.setText(""))


# ═══════════════════════════════════════════════════════════════════════
# About page
# ═══════════════════════════════════════════════════════════════════════

class AboutPage(PageWidget):
    """About Virgo Desktop."""

    def __init__(self) -> None:
        super().__init__(
            "",
        )

        about_text = QLabel(
            f"<h2>Virgo Desktop 0.1.0</h2>"
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
            f"<p>Built with PyQt6 · MIT License</p>"
            f"<p><a href='https://github.com/Aussielad89/virgo-agent' "
            f"style='color: #89b4fa;'>github.com/Aussielad89/virgo-agent</a></p>"
        )
        about_text.setWordWrap(True)
        about_text.setTextFormat(Qt.TextFormat.RichText)
        self._add(about_text)

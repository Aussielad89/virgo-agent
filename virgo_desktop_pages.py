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

from PyQt6.QtCore import Qt, QTimer
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
            f"{icon('run')}  Pipeline Runner",
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
            sys.executable, "-m", "virgo_run" if False else str(HERE / "cli.py"),
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

class ChatPage(PageWidget):
    """Interactive chat with Virgo."""

    def __init__(self) -> None:
        super().__init__(
            f"{icon('chat')}  Chat",
            "Talk to Virgo — powered by your local LLM.",
        )

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Start a conversation...")
        self._add(self.chat_log)

        input_row = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message and press Enter...")
        self.msg_input.returnPressed.connect(self._send)
        input_row.addWidget(self.msg_input, 1)
        self.send_btn = QPushButton(f"{icon('send')}  Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        self.content.addLayout(input_row)

    def on_activate(self) -> None:
        self.msg_input.setFocus()

    def _send(self) -> None:
        msg = self.msg_input.text().strip()
        if not msg:
            return
        self.chat_log.append(f"<b>You:</b> {msg}")
        self.msg_input.clear()

        # Try using the LLM via a subprocess call to virgo agent
        self.chat_log.append(f"<i>Virgo is thinking...</i>")
        QTimer.singleShot(1, lambda: self._do_llm(msg))

    def _do_llm(self, msg: str) -> None:
        try:
            result = subprocess.run(
                [sys.executable, str(HERE / "cli.py"), "agent", "--goal", msg, "--llm"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            reply = result.stdout.strip() or "(no response)"
        except subprocess.TimeoutExpired:
            reply = "(LLM timed out)"
        except Exception as exc:
            reply = f"(Error: {exc})"

        # Remove "thinking..." message and add real response
        cursor = self.chat_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveOperation.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(f"<b>Virgo:</b> {reply}\n\n")


# ═══════════════════════════════════════════════════════════════════════
# Network Scanner page
# ═══════════════════════════════════════════════════════════════════════

class NetworkPage(PageWidget):
    """Network discovery and device scanning."""

    def __init__(self) -> None:
        super().__init__(
            f"{icon('network')}  Network Scanner",
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
            f"{icon('diagnostics')}  System Diagnostics",
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
            f"{icon('alert')}  Alert Engine",
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
            f"{icon('scaffold')}  Project Scaffolds",
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
# Logs page
# ═══════════════════════════════════════════════════════════════════════

class LogsPage(PageWidget):
    """Virgo application logs."""

    def __init__(self) -> None:
        super().__init__(
            f"{icon('log')}  Application Logs",
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

class SettingsPage(PageWidget):
    """Virgo environment configuration."""

    def __init__(self) -> None:
        super().__init__(
            f"{icon('settings')}  Settings",
            "Environment variables and configuration.",
        )

        self._fields: dict[str, QLineEdit] = {}

        form = self._section("Environment")
        env_vars = {
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_API_KEY": "sk-no-key-required",
            "MODEL_PLANNER": "qwen2.5-coder:7b",
            "MODEL_GENERATOR": "qwen2.5-coder:7b",
            "MODEL_FIXER": "qwen2.5-coder:7b",
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
        for key, edit in self._fields.items():
            lines.append(f"{key}={edit.text()}\n")
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
            f"{icon('info')}  About",
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

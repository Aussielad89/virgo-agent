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

from PyQt6.QtCore import Qt, QTimer, QMetaObject, pyqtSlot, Q_ARG, QUrl, QEvent, QDir, QModelIndex, QSize
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QShortcut, QKeySequence, QFileSystemModel, QPen, QBrush
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget, QFileDialog,
    QSlider, QCompleter, QCheckBox, QDialog,
    QColorDialog, QGridLayout, QTreeView,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsEllipseItem,
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
        gb.setCheckable(True)
        gb.setChecked(True)
        # Collapse/expand by hiding content when unchecked
        gb.toggled.connect(lambda checked: gb.setFixedHeight(
            28 if not checked else gb.sizeHint().height()
        ))
        gb.toggled.connect(lambda checked: gb.setStyleSheet(
            f"QGroupBox::title {{ subcontrol-position: top left; padding: 4px 8px; "
            f"color: {'#89b4fa' if checked else '#6c7086'}; }}"
        ))
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
            # Desktop notification
            w = self.window()
            if hasattr(w, "notify"):
                w.notify("Pipeline", f"Exit code {rc} — {self.goal_input.text()[:60]}")


# ═══════════════════════════════════════════════════════════════════════
# Chat page
# ═══════════════════════════════════════════════════════════════════════

def _strip_think(text: str) -> str:
    """Remove  blocks and surrounding whitespace from model output."""
    import re
    return re.sub(r'\s*<think>.*?</think>\s*', '', text, flags=re.DOTALL)


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
        return f"\x00CODEBLOCK{len(code_blocks)-1}\x00"

    text = re.sub(
        r'```(\w*)[^\S\n]*\n(.*?)```',
        lambda m: _save_code(m),
        text,
        flags=re.DOTALL,
    )

    # Inline code `` `...` `` — protect from other rules
    inline_codes: list[str] = []
    def _save_inline(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00INLINE{len(inline_codes)-1}\x00"

    text = re.sub(r'`([^`\n]+)`', lambda m: _save_inline(m), text)

    # Headings
    text = re.sub(r'^### (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # Italic *text* or _text_ (single, not double)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)

    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Unordered lists
    lines = text.split("\n")
    in_list = False
    result: list[str] = []
    for line in lines:
        m = re.match(r'^(\s*)[-*+]\s+(.+)$', line)
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
        m = re.match(r'^(\s*)\d+\.\s+(.+)$', line)
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
        self.speak_btn = QPushButton(f"{icon('audio')}  Speak")
        self.speak_btn.setToolTip("Read last reply aloud")
        self.speak_btn.clicked.connect(self._speak_reply)
        self.mic_btn = QPushButton(f"{icon('mic')}  Mic")
        self.mic_btn.setToolTip("Speak into your microphone")
        self.mic_btn.clicked.connect(self._mic_input)
        toolbar.addWidget(self.speak_btn)
        toolbar.addWidget(self.mic_btn)
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
        completer = QCompleter(
            ["/help", "/tools", "/clear", "/read ", "/web ", "/py "], self.msg_input
        )
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.msg_input.setCompleter(completer)
        self.msg_input.textChanged.connect(self._update_token_count)
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
        self.content.addLayout(input_row)

        # Ctrl+Enter / Ctrl+Return sends the message.
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._send)

        # Font zoom
        for seq, delta in (("Ctrl++", 1), ("Ctrl+=", 1), ("Ctrl+-", -1)):
            QShortcut(QKeySequence(seq), self).activated.connect(
                lambda d=delta: self._zoom_font(d)
            )
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(
            lambda: self._zoom_font(0)
        )
        self._chat_font_size = 13

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
                self.chat_log.append(
                    f"<i>[Restored previous chat — {model}]</i>"
                )
            self.chat_log.append(
                f"<i>Type /clear to start fresh, or continue below.</i>"
            )
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

        if self._multi_models and len(self._multi_models) > 1:
            self.chat_log.append(
                f"<i>[Sending to {len(self._multi_models)} models...]</i>"
            )
            self._cancel = False
            self.stop_btn.setVisible(True)
            self.stop_btn.setEnabled(True)
            for model in self._multi_models:
                threading.Thread(
                    target=self._multi_stream, args=(msg, model), daemon=True
                ).start()
            return

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

    def _update_token_count(self) -> None:
        text = self.msg_input.text()
        est = len(text) // 4 or 0
        self.token_label.setText(f"~{est} tokens (input)")

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

    def _toggle_multi(self) -> None:
        """Open a dialog to select models for multi-model chat."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Multi-model — select models")
        dlg.resize(300, 350)
        dlg.setStyleSheet("QDialog { background: #1e1e2e; }")
        lo = QVBoxLayout(dlg)
        lo.addWidget(QLabel("<b style='color:#cdd6f4;'>Select 2+ models:</b>"))

        checks: list[tuple[QCheckBox, str]] = []
        for m in (getattr(self, "_available_models", [])
                  or [self.model_combo.itemText(i) for i in range(self.model_combo.count())]):
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
                self.chat_log.append(
                    f"<i>[Multi-mode: {', '.join(self._multi_models)}]</i>"
                )
            else:
                self.multi_btn.setText("M")

    def _multi_stream(self, msg: str, model: str) -> None:
        """Send to a single model in multi-mode."""
        from cli import VIRGO_SYSTEM_PROMPT
        import main
        try:
            client = main.get_client(model=model)
            msgs = [{"role": "system", "content": VIRGO_SYSTEM_PROMPT}] + self._history
            reply = client.chat_stream(msgs, temperature=self._temperature, max_tokens=2048)
        except Exception as exc:
            reply = f"(error: {exc})"

        # Append model's response to chat log (cross-thread safe).
        QMetaObject.invokeMethod(
            self, "_append_multi_reply", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, model), Q_ARG(str, reply or "(empty)"),
        )

    @pyqtSlot(str, str)
    def _append_multi_reply(self, model: str, reply: str) -> None:
        self.chat_log.append(
            f"<hr><b>{model}</b><br>{reply}"
        )
        self._history.append({"role": "assistant", "content": f"[{model}] {reply}"})
        if all(f"[{m}]" in str(self._history) for m in self._multi_models):
            self._busy = False
            self.stop_btn.setVisible(False)

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
        self.chat_log.insertHtml(self._escape(chunk))
        self.chat_log.verticalScrollBar().setValue(
            self.chat_log.verticalScrollBar().maximum()
        )

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
        for m in re.findall(r"(?:!\[[^\]]*\]\(([^)]+)\)|`?([\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp))`?)", reply, re.IGNORECASE):
            cand = m[0] or m[1]
            if cand and not cand.startswith("http"):
                self._add_to_gallery(cand)
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
        self._save_chat()

    def _run_tool(self, name: str, kwargs: dict[str, str]) -> None:
        from cli import _run_chat_tool  # lazy import (safe)
        try:
            out = _run_chat_tool(name, kwargs)
        except Exception as exc:
            out = f"(tool error: {exc})"
        self._append_assistant(f"[tool {name}] {out[:800]}")

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
        self.chat_log.setStyleSheet(
            f"QTextEdit {{ font-size: {self._chat_font_size}px; }}"
        )
        if delta != 0:
            self.chat_log.append(
                f"<i>[Font size: {self._chat_font_size}px]</i>"
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
                self._split_log.setStyleSheet(
                    f"font-size: {self._chat_font_size}px;"
                )
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

    # ── Prompt library ─────────────────────────────────────────────────
    _PROMPTS_DIR = Path(__file__).parent / ".virgo_prompts"

    def _show_prompt_lib(self) -> None:
        """Open the prompt library dialog — save or load prompt templates."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Prompt Library")
        dlg.resize(400, 350)
        dlg.setStyleSheet(f"QDialog {{ background: #1e1e2e; }}")
        layout = QVBoxLayout(dlg)

        # ── List existing prompts ──
        lbl = QLabel("Saved prompts (click to load):")
        lbl.setStyleSheet("color:#cdd6f4; font-weight:bold;")
        layout.addWidget(lbl)

        lst = QListWidget()
        lst.setStyleSheet(
            "background:#181825; border:1px solid #313244; border-radius:6px; "
            "color:#cdd6f4;"
        )
        layout.addWidget(lst)

        # Load prompts from disk
        self._PROMPTS_DIR.mkdir(exist_ok=True)
        prompt_files = sorted(self._PROMPTS_DIR.glob("*.json"))
        for pf in prompt_files:
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                name = data.get("name", pf.stem)
                item = QListWidgetItem(f"{icon('file')}  {name}")
                item.setData(33, str(pf))
                lst.addItem(item)
            except Exception:
                pass

        def _load_prompt(item) -> None:
            path = Path(item.data(33))
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                text = data.get("text", "")
                self.msg_input.setText(text)
                self.msg_input.setFocus()
                dlg.accept()
            except Exception:
                pass

        lst.itemDoubleClicked.connect(_load_prompt)

        # ── Save a new prompt ──
        save_row = QHBoxLayout()
        name_input = QLineEdit()
        name_input.setPlaceholderText("Prompt name…")
        name_input.setStyleSheet(
            "background:#181825; border:1px solid #313244; border-radius:6px; "
            "color:#cdd6f4; padding:6px 10px;"
        )
        save_row.addWidget(name_input, 1)
        save_btn = QPushButton("Save current input")
        save_btn.setStyleSheet(
            "background:#313244; border:1px solid #45475a; border-radius:6px; "
            "color:#cdd6f4; padding:6px 12px;"
        )
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        def _save_prompt() -> None:
            name = name_input.text().strip()
            if not name:
                return
            text = self.msg_input.text().strip()
            if not text:
                return
            slug = name.lower().replace(" ", "_").replace("/", "_")
            payload = {"name": name, "text": text}
            dest = self._PROMPTS_DIR / f"{slug}.json"
            dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            # Re-open dialog to refresh list
            dlg.accept()
            self._show_prompt_lib()

        save_btn.clicked.connect(_save_prompt)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "background:#313244; border:1px solid #45475a; border-radius:6px; "
            "color:#cdd6f4; padding:6px 12px;"
        )
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    def _speak_reply(self) -> None:
        """Read the last assistant reply aloud via edge-tts."""
        text = getattr(self, "_last_reply", "")
        if not text:
            self.chat_log.append("<i>[No reply to speak]</i>")
            return
        self.speak_btn.setEnabled(False)
        threading.Thread(
            target=self._speak_async, args=(text,), daemon=True
        ).start()

    def _speak_async(self, text: str) -> None:
        try:
            import edge_tts, asyncio, tempfile
            communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            path = tmp.name
            tmp.close()
            asyncio.run(communicate.save(path))
            os.startfile(path)  # Windows default player
        except Exception as exc:
            QMetaObject.invokeMethod(
                self, "_append_log", Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, f"<i>[TTS error: {exc}]</i>"),
            )
        finally:
            QMetaObject.invokeMethod(
                self, "_enable_btn", Qt.ConnectionType.QueuedConnection,
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
            self, "_mic_done", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, text), Q_ARG(str, err),
        )

    @pyqtSlot(str, str)
    def _mic_done(self, text: str, err: str) -> None:
        self.mic_btn.setEnabled(True)
        if text:
            self.msg_input.setText(text)
            self.msg_input.setFocus()
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
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
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
        text = re.sub(r'<[^>]+>', '', text)
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
                    entry = {"name": fp.stem, "path": str(fp), "session_id": sid,
                             "model": model, "messages": len(msgs)}
                    item = QListWidgetItem(label)
                    item.setData(256, entry)
                    self.chat_list.addItem(item)
                    self._chat_sessions.append(entry)
                except Exception:
                    pass

        pipe_count = len(self._sessions)
        chat_count = len(self._chat_sessions)
        self.status.setText(f"{pipe_count} pipeline / {chat_count} chat session(s)")

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
            data = json.loads(Path(c['path']).read_text())
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
        w = self.window()
        if hasattr(w, "notify"):
            w.notify("Swarm", f"Finished — {self.goal_input.text()[:60]}")


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


class FilesPage(PageWidget):
    """File browser — tree view of the workspace."""

    def __init__(self) -> None:
        super().__init__("Files", "Browse and open project files")

        self._model = QFileSystemModel()
        root = str(HERE)
        self._model.setRootPath(root)
        self._model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )

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

    def _open_file(self, idx: QModelIndex) -> None:
        path = Path(self._model.filePath(idx))
        if path.is_dir():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            self.preview.setPlainText(text[:5000])
            if len(text) > 5000:
                self.preview.append(
                    f"\n\n[... truncated — file is {path.stat().st_size:,} bytes]"
                )
        except Exception as e:
            self.preview.setPlainText(f"Error reading {path.name}: {e}")

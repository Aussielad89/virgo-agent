"""Virgo Desktop pages for the build-on-top features.

New pages plugged into virgo_desktop.py:

* RunTimelinePage — live agent run timeline (polled from the session store)
* ArtifactsPage   — versioned artifact browser with diff
* MemoryPage      — unified memory recall + profile editor + runbooks
* BudgetPage      — spend vs limit with overrun alerts
* RagPage         — local knowledge base query + virtual notes

Imports are defensive so a missing optional module never breaks the app.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from virgo_desktop_pages import PageWidget
from _log import OUTDIR

_ACCENT = "#a6e3a1"
_MUTED = "#a6adc8"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════════════════════════
# RunTimelinePage — live agent execution feed
# ═══════════════════════════════════════════════════════════════════════


class RunTimelinePage(PageWidget):
    """Watch agent runs live: start one, or resume a saved session."""

    _row_ready = pyqtSignal(str, str, str, str)  # phase, message, detail, ts

    def __init__(self) -> None:
        super().__init__("Run Timeline", "Live ReAct loop feed — start a goal, watch it think, act and finish")
        self._current_sid: str | None = None
        self._seen_events = 0
        self._last_events: list[dict] = []
        self._last_goal = ""
        self._last_ts = ""

        # ── controls ──
        ctrl = QGroupBox("Agent")
        cl = QVBoxLayout(ctrl)
        row = QHBoxLayout()
        self.goal_in = QLineEdit()
        self.goal_in.setPlaceholderText("Goal, e.g. write a report from mock_logs.txt")
        row.addWidget(self.goal_in, 1)
        self.run_btn = QPushButton("Run Agent")
        self.run_btn.clicked.connect(self._start_run)
        row.addWidget(self.run_btn)
        cl.addLayout(row)

        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Resume:"))
        self.session_box = QComboBox()
        self.session_box.setMinimumWidth(320)
        rrow.addWidget(self.session_box, 1)
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(self._resume_session)
        rrow.addWidget(self.resume_btn)
        self.refresh_btn = QPushButton("Refresh sessions")
        self.refresh_btn.clicked.connect(self._refresh_sessions)
        rrow.addWidget(self.refresh_btn)
        cl.addLayout(rrow)
        self._add(ctrl)

        # ── event table ──
        table_box = QGroupBox("Events")
        tl = QVBoxLayout(table_box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["phase", "message", "detail", "time"])
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 320)
        self.table.setColumnWidth(2, 380)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tl.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.export_svg_btn = QPushButton("💾 Export SVG")
        self.export_svg_btn.clicked.connect(self._export_svg)
        btn_row.addWidget(self.export_svg_btn)
        self.replay_btn = QPushButton("↺ Replay")
        self.replay_btn.clicked.connect(self._replay)
        btn_row.addWidget(self.replay_btn)
        self.timeline_status = QLabel("")
        self.timeline_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        btn_row.addWidget(self.timeline_status, 1)
        tl.addLayout(btn_row)
        self._add(table_box)

        self._row_ready.connect(self._append_row)
        self._timer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ── actions ──
    def _refresh_sessions(self) -> None:
        try:
            from session_store import get_store

            rows = get_store().list_sessions()
        except Exception:
            rows = []
        self.session_box.clear()
        for r in rows:
            self.session_box.addItem(
                f"{r['session_id']}  [{r['status']}]", r["session_id"]
            )
        self.session_box.setCurrentIndex(-1)

    def _start_run(self) -> None:
        goal = self.goal_in.text().strip()
        if not goal:
            return
        from agent_runtime import AgentConfig, build_runtime

        sid = f"live_{datetime.now(UTC).strftime('%H%M%S')}"
        self._current_sid = sid
        self._seen_events = 0
        self._last_goal = goal
        self._last_events = []
        self._last_ts = ""
        self.table.setRowCount(0)

        def _worker() -> None:
            try:
                config = AgentConfig(
                    max_steps=12, max_retries=2,
                    session_id=sid, checkpoint_every=1, save_session=True,
                )
                runtime = build_runtime(config=config, include_mcp=False)
                runtime.run(
                    goal,
                    progress_callback=lambda phase, msg, detail=None: self._row_ready.emit(
                        phase, msg, detail or "", _now_iso()
                    ),
                )
            except Exception as exc:
                self._row_ready.emit("error", str(exc), "", _now_iso())

        threading.Thread(target=_worker, daemon=True).start()
        self.run_btn.setEnabled(False)

    def _resume_session(self) -> None:
        sid = self.session_box.currentData()
        if not sid:
            return
        from agent_runtime import AgentConfig, build_runtime
        from session_store import get_store

        snap = get_store().load_checkpoint(sid)
        if snap is None:
            return
        self._current_sid = sid
        self._seen_events = 0
        self.table.setRowCount(0)
        goal = snap.goal
        self._last_goal = goal
        self._last_events = []
        self._last_ts = ""

        def _worker() -> None:
            try:
                config = AgentConfig(
                    max_steps=12, max_retries=2,
                    resume_from=sid, checkpoint_every=1, save_session=True,
                )
                runtime = build_runtime(config=config, include_mcp=False)
                runtime.run(
                    goal,
                    progress_callback=lambda phase, msg, detail=None: self._row_ready.emit(
                        phase, msg, detail or "", _now_iso()
                    ),
                )
            except Exception as exc:
                self._row_ready.emit("error", str(exc), "", _now_iso())

        threading.Thread(target=_worker, daemon=True).start()
        self.run_btn.setEnabled(False)

    def _poll(self) -> None:
        sid = self._current_sid
        if not sid:
            self.run_btn.setEnabled(True)
            return
        try:
            from session_store import get_store

            events = get_store().read_events(sid)
        except Exception:
            events = []
        self._last_events = events
        if len(events) <= self._seen_events:
            return
        for ev in events[self._seen_events :]:
            self._row_ready.emit(
                ev.get("phase", "?"), ev.get("message", ""),
                ev.get("detail") or "", ev.get("ts", ""),
            )
        self._seen_events = len(events)
        # A done/failed event means the run finished.
        if events and events[-1].get("phase") in ("done", "error"):
            self._save_timeline(events)
            self._current_sid = None
            self.run_btn.setEnabled(True)
            self._refresh_sessions()

    def _append_row(self, phase: str, message: str, detail: str, ts: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        colors = {
            "step": "#89b4fa", "tool": "#f9e2af", "eval": "#a6e3a1",
            "retry": "#f38ba8", "done": "#a6e3a1", "error": "#f38ba8",
        }
        color = colors.get(phase, _MUTED)
        for col, text in ((0, phase), (1, message), (2, detail), (3, ts)):
            item = QTableWidgetItem(str(text)[:200])
            item.setForeground(Qt.GlobalColor.white)
            if col in (0, 3):
                item.setForeground(Qt.GlobalColor.white)
            self.table.setItem(row, col, item)
        self.table.item(row, 0).setForeground(
            Qt.GlobalColor.white
        )
        self.table.item(row, 0).setBackground(Qt.GlobalColor.darkGray)  # placeholder
        self.table.item(row, 0).setData(Qt.ItemDataRole.ForegroundRole, color)
        self.table.scrollToBottom()

    # ── timeline persistence / export / replay ──
    def _save_timeline(self, events: list[dict]) -> None:
        """Append a finished run's timeline to OUTDIR/run_timelines.json."""
        try:
            if not events:
                return
            self._last_events = events
            self._last_ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            OUTDIR.mkdir(exist_ok=True)
            path = OUTDIR / "run_timelines.json"
            records: list[dict] = []
            if path.exists():
                try:
                    records = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    records = []
                if not isinstance(records, list):
                    records = []
            records.append(
                {
                    "ts": self._last_ts,
                    "goal": self._last_goal or "",
                    "events": events,
                }
            )
            path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            self.timeline_status.setText(f"Save failed: {exc}")

    def _export_svg(self) -> None:
        """Render the current run's events as a dark-theme SVG in OUTDIR."""
        events = self._last_events or []
        if not events:
            self.timeline_status.setText("No timeline data yet.")
            return
        try:
            ts = self._last_ts or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            path = OUTDIR / f"run_timeline_{ts}.svg"
            path.write_text(self._render_svg(events), encoding="utf-8")
            self.timeline_status.setText(f"Saved {path.name}")
        except Exception as exc:  # noqa: BLE001
            self.timeline_status.setText(f"Export failed: {exc}")

    def _replay(self) -> None:
        """Load the most recent saved timeline and re-render it in the table."""
        try:
            path = OUTDIR / "run_timelines.json"
            if not path.exists():
                self.timeline_status.setText("No timeline data yet.")
                return
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list) or not records:
                self.timeline_status.setText("No timeline data yet.")
                return
            latest = records[-1]
            events = latest.get("events") or []
            if not events:
                self.timeline_status.setText("No timeline data yet.")
                return
            self._last_events = events
            self._last_goal = str(latest.get("goal", ""))
            self._last_ts = str(latest.get("ts", ""))
            self.table.setRowCount(0)
            for ev in events:
                self._append_row(
                    str(ev.get("phase", "?")), str(ev.get("message", "")),
                    str(ev.get("detail") or ""), str(ev.get("ts", "")),
                )
            self.timeline_status.setText(
                f"Replayed {len(events)} events ({self._last_goal or 'run'})"
            )
        except Exception as exc:  # noqa: BLE001
            self.timeline_status.setText(f"Replay failed: {exc}")

    @staticmethod
    def _render_svg(events: list[dict]) -> str:
        """Dark-theme SVG flowchart of the run's events (640x360 viewBox)."""
        labels = []
        for ev in events[:12]:
            phase = str(ev.get("phase", "?"))
            msg = str(ev.get("message", "")) or str(ev.get("detail", ""))
            label = f"{phase}: {msg}" if msg else phase
            labels.append(label[:28])

        def esc(s: str) -> str:
            return (
                s.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;")
            )

        cols, bw, bh = 3, 190, 54
        gap_x, gap_y = 24, 30
        left, top = 22, 24
        rows = (len(labels) + cols - 1) // cols or 1
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" '
            'width="640" height="360">',
            '<rect width="640" height="360" fill="#181825"/>',
            '<text x="320" y="16" fill="#cdd6f4" font-family="sans-serif" '
            'font-size="12" text-anchor="middle" font-weight="bold">Run timeline</text>',
        ]
        for i, label in enumerate(labels):
            row, col = divmod(i, cols)
            x = left + col * (bw + gap_x)
            y = top + row * (bh + gap_y)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" '
                f'fill="#1e1e2e" stroke="#89b4fa" stroke-width="1.5"/>'
            )
            parts.append(
                f'<text x="{x + bw / 2}" y="{y + bh / 2 + 4}" fill="#cdd6f4" '
                f'font-family="monospace" font-size="10" text-anchor="middle">'
                f"{esc(label)}</text>"
            )
            if i + 1 < len(labels):
                x1 = x + bw
                y1 = y + bh / 2
                if col == cols - 1:
                    x2 = x - (cols - 1) * (bw + gap_x) + bw / 2
                    y2 = y + bh + gap_y
                else:
                    x2 = x + bw + gap_x
                    y2 = y1
                parts.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                    f'stroke="#45475a" stroke-width="1.5" marker-end="url(#arr)"/>'
                )
        parts.append(
            '<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="6" '
            'refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#45475a"/>'
            "</marker></defs>"
        )
        parts.append("</svg>")
        return "\n".join(parts)

    def on_activate(self) -> None:
        self._refresh_sessions()


# ═══════════════════════════════════════════════════════════════════════
# ArtifactsPage — versioned outputs + diffs
# ═══════════════════════════════════════════════════════════════════════


class ArtifactsPage(PageWidget):
    """Browse stored artifacts, inspect versions, diff any two."""

    def __init__(self) -> None:
        super().__init__("Artifacts", "Versioned run outputs — diff any two versions")
        top = QGroupBox("Artifacts")
        tl = QVBoxLayout(top)
        brow = QHBoxLayout()
        self.list = QListWidget()
        brow.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh)
        side.addWidget(self.refresh_btn)
        self.show_btn = QPushButton("Show latest")
        self.show_btn.clicked.connect(self._show_latest)
        side.addWidget(self.show_btn)
        diffrow = QHBoxLayout()
        diffrow.addWidget(QLabel("Diff"))
        self.v1 = QSpinBox()
        self.v1.setRange(0, 9999)
        self.v2 = QSpinBox()
        self.v2.setRange(0, 9999)
        diffrow.addWidget(self.v1)
        diffrow.addWidget(self.v2)
        side.addLayout(diffrow)
        self.diff_btn = QPushButton("Diff")
        self.diff_btn.clicked.connect(self._diff)
        side.addWidget(self.diff_btn)
        side.addStretch()
        brow.addLayout(side)
        tl.addLayout(brow)
        self._add(top)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumHeight(260)
        self._add(self.view)

        self._refresh()

    def _store(self):
        from artifact_store import get_artifacts

        return get_artifacts()

    def _refresh(self) -> None:
        self.list.clear()
        try:
            rows = self._store().list()
        except Exception:
            rows = []
        for r in rows:
            item = QListWidgetItem(
                f"{r['name']}  v{r['latest']}/{r['versions']}  @ {r['updated_at']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, r["name"])
            self.list.addItem(item)

    def _current(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _show_latest(self) -> None:
        name = self._current()
        if not name:
            return
        try:
            art = self._store().get(name)
        except Exception as exc:
            self.view.setPlainText(str(exc))
            return
        data = art["data"]
        if not isinstance(data, str):
            import json

            data = json.dumps(data, ensure_ascii=False, indent=2)
        self.view.setPlainText(
            f"=== {name} v{art['version']} @ {art['ts']} ===\n{data[:6000]}"
        )
        versions = self._store().versions(name)
        if versions:
            self.v1.setValue(versions[-2]["version"] if len(versions) > 1 else versions[0]["version"])
            self.v2.setValue(versions[-1]["version"])

    def _diff(self) -> None:
        name = self._current()
        if not name:
            return
        try:
            text = self._store().diff(name, self.v1.value() or None, self.v2.value() or None)
        except Exception as exc:
            text = str(exc)
        self.view.setPlainText(text)


# ═══════════════════════════════════════════════════════════════════════
# MemoryPage — unified recall + profile + runbooks
# ═══════════════════════════════════════════════════════════════════════


class MemoryPage(PageWidget):
    """Search everything Virgo remembers; manage the user profile."""

    def __init__(self) -> None:
        super().__init__("Memory", "Unified recall (experience + learning + semantic) + user profile + runbooks")

        recall_box = QGroupBox("Recall")
        rl = QVBoxLayout(recall_box)
        rrow = QHBoxLayout()
        self.query_in = QLineEdit()
        self.query_in.setPlaceholderText("e.g. web scraper prices")
        rrow.addWidget(self.query_in, 1)
        self.recall_btn = QPushButton("Recall")
        self.recall_btn.clicked.connect(self._recall)
        rrow.addWidget(self.recall_btn)
        rl.addLayout(rrow)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMaximumHeight(180)
        rl.addWidget(self.results)
        self._add(recall_box)

        prof_box = QGroupBox("Profile")
        pl = QVBoxLayout(prof_box)
        prow = QHBoxLayout()
        self.fact_key = QLineEdit()
        self.fact_key.setPlaceholderText("key")
        self.fact_val = QLineEdit()
        self.fact_val.setPlaceholderText("value")
        prow.addWidget(self.fact_key)
        prow.addWidget(self.fact_val, 1)
        self.add_btn = QPushButton("Remember")
        self.add_btn.clicked.connect(self._add_fact)
        prow.addWidget(self.add_btn)
        self.del_btn = QPushButton("Forget")
        self.del_btn.clicked.connect(self._del_fact)
        prow.addWidget(self.del_btn)
        pl.addLayout(prow)
        self.facts = QListWidget()
        self.facts.setMaximumHeight(120)
        pl.addWidget(self.facts)
        self._add(prof_box)

        rb_box = QGroupBox("Runbooks")
        rbl = QHBoxLayout(rb_box)
        self.runbook_btn = QPushButton("Generate runbooks from repeated failures")
        self.runbook_btn.clicked.connect(self._gen_runbooks)
        rbl.addWidget(self.runbook_btn)
        self.runbook_count = QLabel("")
        self.runbook_count.setStyleSheet(f"color: {_ACCENT};")
        rbl.addWidget(self.runbook_count)
        rbl.addStretch()
        self._add(rb_box)

        self._refresh_facts()

    def _mem(self):
        from memory_store import get_unified

        return get_unified()

    def _recall(self) -> None:
        q = self.query_in.text().strip()
        if not q:
            return
        try:
            hits = self._mem().recall(q, k=6)
        except Exception as exc:
            self.results.setPlainText(f"recall failed: {exc}")
            return
        if not hits:
            self.results.setPlainText("(nothing relevant remembered yet)")
            return
        lines = []
        for e in hits:
            status = "OK" if e.get("success") else "FAIL"
            lines.append(f"[{status}][{e.get('source','?')}] {str(e.get('goal',''))[:90]}")
            lesson = e.get("lesson") or e.get("outcome") or ""
            if lesson:
                lines.append(f"    lesson: {str(lesson)[:200]}")
        self.results.setPlainText("\n".join(lines))

    def _refresh_facts(self) -> None:
        self.facts.clear()
        try:
            facts = self._mem().profile.facts()
        except Exception:
            facts = []
        for f in facts:
            self.facts.addItem(f"{f['key']}: {f['value']}")

    def _add_fact(self) -> None:
        key = self.fact_key.text().strip()
        val = self.fact_val.text().strip()
        if key:
            self._mem().profile.set(key, val)
            self.fact_key.clear()
            self.fact_val.clear()
            self._refresh_facts()

    def _del_fact(self) -> None:
        it = self.facts.currentItem()
        if not it:
            return
        key = it.text().split(":", 1)[0].strip()
        self._mem().profile.remove(key)
        self._refresh_facts()

    def _gen_runbooks(self) -> None:
        try:
            from runbook import get_runbooks

            written = get_runbooks().generate()
        except Exception as exc:
            self.runbook_count.setText(f"error: {exc}")
            return
        self.runbook_count.setText(f"{len(written)} written" if written else "no clusters yet")

    def on_activate(self) -> None:
        self._refresh_facts()


# ═══════════════════════════════════════════════════════════════════════
# BudgetPage — spend vs limit
# ═══════════════════════════════════════════════════════════════════════


class BudgetPage(PageWidget):
    """Estimated spend per day with a configurable limit and alerts."""

    def __init__(self) -> None:
        super().__init__("Budget", "Cost tracking for agent runs — set a daily limit and never overspend silently")

        top = QGroupBox("Today")
        tl = QVBoxLayout(top)
        self.status_label = QLabel("—")
        self.status_label.setStyleSheet(f"font-size: 15px; color: {_ACCENT};")
        tl.addWidget(self.status_label)
        setrow = QHBoxLayout()
        setrow.addWidget(QLabel("Daily limit ($):"))
        self.limit_in = QLineEdit()
        self.limit_in.setFixedWidth(120)
        setrow.addWidget(self.limit_in)
        self.set_btn = QPushButton("Set limit")
        self.set_btn.clicked.connect(self._set_limit)
        setrow.addWidget(self.set_btn)
        setrow.addStretch()
        tl.addLayout(setrow)
        self._add(top)

        recent_box = QGroupBox("Recent spend")
        rl = QVBoxLayout(recent_box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["time", "model", "cost $", "tokens", "goal"])
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(4, 300)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rl.addWidget(self.table)
        self._add(recent_box)

        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _budget(self):
        from budget import get_budget

        return get_budget()

    def _refresh(self) -> None:
        try:
            tracker = self._budget()
            v = tracker.check()
            self.status_label.setText(tracker.status_text())
            rows = tracker.recent(20)
        except Exception as exc:
            self.status_label.setText(f"budget unavailable: {exc}")
            return
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            vals = [
                str(r.get("ts", "")), str(r.get("model", "")),
                f"{r.get('cost', 0):.4f}", str(r.get("estimated_tokens", 0)),
                str(r.get("goal", ""))[:60],
            ]
            for col, text in enumerate(vals):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _set_limit(self) -> None:
        try:
            limit = float(self.limit_in.text())
        except ValueError:
            return
        self._budget().set_limit(limit)
        self.limit_in.clear()
        self._refresh()

    def on_activate(self) -> None:
        self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# RagPage — local knowledge base
# ═══════════════════════════════════════════════════════════════════════


class RagPage(PageWidget):
    """Query kb/ + virtual notes; add notes to the retrievable corpus."""

    def __init__(self) -> None:
        super().__init__("Knowledge Base", "Local RAG over kb/ and your notes — no cloud needed")

        top = QGroupBox("Status")
        tl = QHBoxLayout(top)
        self.status_label = QLabel("—")
        tl.addWidget(self.status_label, 1)
        self.index_btn = QPushButton("Refresh status")
        self.index_btn.clicked.connect(self._status)
        tl.addWidget(self.index_btn)
        self._add(top)

        qbox = QGroupBox("Query")
        ql = QVBoxLayout(qbox)
        qrow = QHBoxLayout()
        self.query_in = QLineEdit()
        self.query_in.setPlaceholderText("Ask the knowledge base…")
        qrow.addWidget(self.query_in, 1)
        self.query_btn = QPushButton("Search")
        self.query_btn.clicked.connect(self._query)
        qrow.addWidget(self.query_btn)
        ql.addLayout(qrow)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        ql.addWidget(self.results)
        self._add(qbox)

        nbox = QGroupBox("Virtual note")
        nl = QHBoxLayout(nbox)
        self.note_name = QLineEdit()
        self.note_name.setPlaceholderText("name")
        self.note_name.setFixedWidth(150)
        self.note_text = QLineEdit()
        self.note_text.setPlaceholderText("text to make retrievable (e.g. how to run this project)")
        nl.addWidget(self.note_name)
        nl.addWidget(self.note_text, 1)
        self.note_btn = QPushButton("Add note")
        self.note_btn.clicked.connect(self._add_note)
        nl.addWidget(self.note_btn)
        self._add(nbox)

        self._status()

    def _rag(self):
        from local_rag import get_rag

        return get_rag()

    def _status(self) -> None:
        try:
            st = self._rag().status()
        except Exception as exc:
            self.status_label.setText(f"rag unavailable: {exc}")
            return
        self.status_label.setText(
            f"backend: {st.get('backend','?')} | kb docs: {st.get('doc_count',0)} "
            f"| chunks: {st.get('chunk_count',0)} | notes: {st.get('virtual_docs',0)}"
        )

    def _query(self) -> None:
        q = self.query_in.text().strip()
        if not q:
            return
        try:
            hits = self._rag().query(q, k=5)
        except Exception as exc:
            self.results.setPlainText(f"query failed: {exc}")
            return
        if not hits:
            self.results.setPlainText("(no relevant knowledge found)")
            return
        lines = []
        for h in hits:
            lines.append(f"[from {h['source']}]\n{h['text'][:500]}\n")
        self.results.setPlainText("\n".join(lines))

    def _add_note(self) -> None:
        name = self.note_name.text().strip()
        text = self.note_text.text().strip()
        if name and text:
            self._rag().add_virtual(name, text)
            self.note_name.clear()
            self.note_text.clear()
            self._status()

    def on_activate(self) -> None:
        self._status()

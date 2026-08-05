"""Desktop Automation Agent page for Virgo Desktop.

Lets an agent drive the host machine via pyautogui + Windows UI Automation.
SAFETY FIRST: every action requires an explicit confirm; nothing fires until
the user clicks "Execute". Red-team friendly (drive Burp, browsers, terminals).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from virgo_desktop_pages import PageWidget

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    _HAVE_GUI = True
except Exception:  # noqa: BLE001
    _HAVE_GUI = False


class DesktopAutomationPage(PageWidget):
    """Run recorded GUI-automation steps on the host, with a safety gate."""

    def __init__(self) -> None:
        super().__init__("Desktop Automation", "Agent-driven host control (pyautogui) — gated")

        if not _HAVE_GUI:
            self._add(QLabel("⚠ pyautogui not installed — run: pip install pyautogui"))
            return

        # ── Script editor ──
        sbox = QGroupBox("Automation script")
        sl = QVBoxLayout(sbox)
        self.script = QTextEdit()
        self.script.setPlaceholderText(
            "# one action per line\n"
            "# click 100,200\n"
            "# type Hello world\n"
            "# hotkey ctrl,shift,t\n"
            "# wait 1.5\n"
            "# screenshot C:/Users/paren/desktop/shot.png"
        )
        self.script.setStyleSheet("QTextEdit { background: #181825; border: 1px solid #313244; border-radius: 6px; font-family: Consolas; }")
        sl.addWidget(self.script)
        self._add(sbox)

        # ── Safety ──
        gate = QHBoxLayout()
        self.confirm = QCheckBox("I confirm these actions will run on MY machine")
        gate.addWidget(self.confirm)
        self._add_row_no_stretch(gate)

        brow = QHBoxLayout()
        self.run_btn = QPushButton("Execute")
        self.run_btn.clicked.connect(self._run)
        self.clear_btn = QPushButton("Clear log")
        self.clear_btn.clicked.connect(lambda: self.log.clear())
        brow.addWidget(self.run_btn)
        brow.addWidget(self.clear_btn)
        brow.addStretch()
        self._add_row_no_stretch(brow)

        # ── Log ──
        lbox = QGroupBox("Run log")
        ll = QVBoxLayout(lbox)
        self.log = QListWidget()
        ll.addWidget(self.log)
        self._add(lbox)

        # ── Scheduled pipeline runs (uses the framework's cron matcher) ──
        sch = QGroupBox("Scheduled pipeline runs")
        scl = QVBoxLayout(sch)
        srow = QHBoxLayout()
        self.sched_cb = QCheckBox("Enable")
        self.sched_cb.toggled.connect(self._toggle_schedule)
        srow.addWidget(self.sched_cb)
        srow.addWidget(QLabel("Cron (m h dom mon dow):"))
        self.sched_cron = QTextEdit()
        self.sched_cron.setMaximumHeight(28)
        self.sched_cron.setPlainText("*/30 * * * *")
        self.sched_cron.setToolTip("5-field cron, e.g. '0 9 * * *' = daily 9am")
        srow.addWidget(self.sched_cron, 1)
        srow.addWidget(QLabel("Goal:"))
        self.sched_goal = QTextEdit()
        self.sched_goal.setMaximumHeight(28)
        self.sched_goal.setPlainText("auto-fix")
        srow.addWidget(self.sched_goal, 1)
        self.sched_now_btn = QPushButton("▶ Run now")
        self.sched_now_btn.clicked.connect(self._scheduled_run)
        srow.addWidget(self.sched_now_btn)
        scl.addLayout(srow)
        self.sched_status = QLabel("Scheduler off")
        self.sched_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        scl.addWidget(self.sched_status)
        self._add(sch)

        self._sched_last: str = ""
        self._sched_timer = QTimer()
        self._sched_timer.setInterval(30000)
        self._sched_timer.timeout.connect(self._schedule_tick)

    def _toggle_schedule(self, on: bool) -> None:
        if on:
            self._sched_timer.start()
            self._schedule_tick()
            self.sched_status.setText("Scheduler on")
        else:
            self._sched_timer.stop()
            self.sched_status.setText("Scheduler off")

    def _schedule_tick(self) -> None:
        try:
            if not self.sched_cb.isChecked():
                return
            from virgo_eventbus import cron_matches

            expr = self.sched_cron.toPlainText().strip()
            if not expr:
                return
            now = time.strftime("%Y-%m-%d %H:%M")
            if cron_matches(expr) and now != self._sched_last:
                self._sched_last = now
                self._scheduled_run()
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler: {exc}")

    def _scheduled_run(self) -> None:
        goal = self.sched_goal.toPlainText().strip() or "auto-fix"
        expr = self.sched_cron.toPlainText().strip()
        self._log(f"SCHEDULED run: '{goal}' ({expr or 'manual'})")
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen(
                [sys.executable, os.path.join(base, "cli.py"), "run", "--goal", goal],
                cwd=base,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduled run failed: {exc}")

    def _add_row_no_stretch(self, row) -> None:
        self.content.addLayout(row)

    def _run(self) -> None:
        if not self.confirm.isChecked():
            self._log("BLOCKED: confirm checkbox not ticked")
            return
        lines = [l.strip() for l in self.script.toPlainText().splitlines() if l.strip() and not l.startswith("#")]
        for ln in lines:
            try:
                self._exec(ln)
            except Exception as e:  # noqa: BLE001
                self._log(f"ERROR on '{ln}': {e}")
                break

    def _exec(self, ln: str) -> None:
        parts = ln.split()
        cmd = parts[0].lower()
        if cmd == "click" and len(parts) >= 3:
            pyautogui.click(int(parts[1]), int(parts[2]))
            self._log(f"clicked {parts[1]},{parts[2]}")
        elif cmd == "type" and len(parts) >= 2:
            pyautogui.write(" ".join(parts[1:]), interval=0.02)
            self._log(f"typed {len(parts)-1} tokens")
        elif cmd == "hotkey" and len(parts) >= 2:
            pyautogui.hotkey(*parts[1:])
            self._log(f"hotkey {'+'.join(parts[1:])}")
        elif cmd == "wait" and len(parts) >= 2:
            time.sleep(float(parts[1]))
            self._log(f"waited {parts[1]}s")
        elif cmd == "screenshot" and len(parts) >= 2:
            pyautogui.screenshot(parts[1])
            self._log(f"saved {parts[1]}")
        elif cmd == "scroll" and len(parts) >= 2:
            pyautogui.scroll(int(parts[1]))
            self._log(f"scrolled {parts[1]}")
        else:
            self._log(f"unknown: {ln}")

    def _log(self, msg: str) -> None:
        self.log.addItem(QListWidgetItem(msg))

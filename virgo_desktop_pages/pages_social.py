"""Virgo Desktop pages — social (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

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


# ═══════════════════════════════════════════════════════════════════════
# Event Bus page — trigger Virgo workflows from external events
# ═══════════════════════════════════════════════════════════════════════


class EventBusPage(PageWidget):
    """Configure and monitor the Virgo Event / Webhook Bus.

    Wires the four event sources (Telegram, file-drop, cron, webhook) to
    workflow triggers backed by the orchestrator pipeline.  All bus events
    arrive on background threads, so UI updates are marshalled through Qt
    signals.
    """

    _sig_log = pyqtSignal(str)
    _sig_refresh = pyqtSignal()

    _GREEN = (
        "QPushButton { background: #a6e3a1; color: #1e1e2e; font-weight: bold; "
        "border: none; border-radius: 6px; padding: 6px 16px; }"
        "QPushButton:hover { background: #89d89e; }"
        "QPushButton:disabled { background: #313244; color: #6c7086; }"
    )

    def __init__(self) -> None:
        super().__init__(
            "Event Bus",
            "Trigger Virgo workflows from Telegram, file drops, cron & webhooks.",
        )
        # Lazy import keeps the desktop import chain resilient even if the
        # bus module's optional deps are missing.
        from virgo_eventbus import Trigger, get_bus

        self.Trigger = Trigger
        self.bus = get_bus()
        self.bus.set_listener(self._on_bus_event)
        self._trigger_ids: list[str] = []

        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh)
        self._sig_log.connect(self._append_log)
        self._sig_refresh.connect(self._refresh)

        self._restore_triggers_view()
        self._refresh()

    # ── UI construction ────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Bus control ──
        ctrl = self._section("Bus Control")
        row = QHBoxLayout()
        self.start_btn = QPushButton(f"{icon('rocket')}  Start Bus")
        self.start_btn.setStyleSheet(self._GREEN)
        self.start_btn.clicked.connect(self._toggle_bus)
        self.stop_btn = QPushButton(f"{icon('error')}  Stop Bus")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._toggle_bus)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addStretch()
        ctrl.layout().addLayout(row)

        self.status_label = QLabel("Status: stopped")
        self.status_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        ctrl.layout().addWidget(self.status_label)
        self.stats_label = QLabel("Events: 0   •   Fired: 0   •   Errors: 0")
        self.stats_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        ctrl.layout().addWidget(self.stats_label)

        # ── Sources ──
        src = self._section("Sources")
        self.source_labels: dict[str, QLabel] = {}
        for name in ("telegram", "file", "cron", "webhook"):
            h = QHBoxLayout()
            self.source_labels[name] = QLabel(f"{name}: idle")
            h.addWidget(self.source_labels[name])
            btn = QPushButton("Start")
            btn.setObjectName(f"src_{name}")
            btn.clicked.connect(
                lambda _checked=False, n=name: self._toggle_source(n)
            )
            h.addWidget(btn)
            h.addStretch()
            src.layout().addLayout(h)

        wh = QHBoxLayout()
        self.webhook_url_label = QLabel("Webhook URL: (start the bus)")
        self.webhook_url_label.setStyleSheet("color: #89b4fa;")
        wh.addWidget(self.webhook_url_label, 1)
        copy_btn = QPushButton(f"{icon('copy') if False else '📋'}  Copy")
        copy_btn.clicked.connect(self._copy_webhook_url)
        wh.addWidget(copy_btn)
        src.layout().addLayout(wh)

        # ── Add trigger ──
        add = self._section("Add Trigger")
        form = QGridLayout()
        form.setSpacing(8)

        self.src_combo = QComboBox()
        self.src_combo.addItems(["telegram", "file", "cron", "webhook"])
        self.src_combo.currentTextChanged.connect(self._sync_form_for_source)
        form.addWidget(QLabel("Source:"), 0, 0)
        form.addWidget(self.src_combo, 0, 1)

        self.match_combo = QComboBox()
        self.match_combo.addItems(
            ["contains", "startswith", "exact", "regex", "glob", "tag", "username"]
        )
        self.match_value = QLineEdit()
        self.match_value.setPlaceholderText("match value (e.g. 'ping' or '*.py')")
        form.addWidget(QLabel("Match:"), 1, 0)
        form.addWidget(self.match_combo, 1, 1)
        form.addWidget(self.match_value, 1, 2)

        self.sched_value = QLineEdit()
        self.sched_value.setPlaceholderText("cron schedule, e.g. '0 9 * * 1-5'")
        form.addWidget(QLabel("Schedule:"), 2, 0)
        form.addWidget(self.sched_value, 2, 1, 1, 2)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["pipeline", "shell", "notify"])
        self.action_value = QLineEdit()
        self.action_value.setPlaceholderText("goal / command / message")
        form.addWidget(QLabel("Action:"), 3, 0)
        form.addWidget(self.action_combo, 3, 1)
        form.addWidget(self.action_value, 3, 2)

        add.layout().addLayout(form)
        add_btn = QPushButton(f"{icon('run')}  Add Trigger")
        add_btn.setStyleSheet(self._GREEN)
        add_btn.clicked.connect(self._add_trigger)
        add.layout().addWidget(add_btn)

        # ── Triggers table ──
        trig = self._section("Triggers")
        self.triggers_table = QTableWidget(0, 7)
        self.triggers_table.setHorizontalHeaderLabels(
            ["Name", "Source", "Match", "Action", "Enabled", "Runs", "Actions"]
        )
        self.triggers_table.setColumnWidth(0, 150)
        self.triggers_table.setColumnWidth(1, 80)
        self.triggers_table.setColumnWidth(2, 160)
        self.triggers_table.setColumnWidth(3, 180)
        self.triggers_table.setColumnWidth(4, 70)
        self.triggers_table.setColumnWidth(5, 50)
        self.triggers_table.setColumnWidth(6, 120)
        trig.layout().addWidget(self.triggers_table)
        trig_btns = QHBoxLayout()
        refresh_btn = QPushButton(f"{icon('refresh')}  Refresh")
        refresh_btn.clicked.connect(self._restore_triggers_view)
        trig_btns.addWidget(refresh_btn)
        trig_btns.addStretch()
        trig.layout().addLayout(trig_btns)

        # ── Live log ──
        logsec = self._section("Live Event Log")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(220)
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background: #11111b; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; font-family: Consolas, monospace; "
            "font-size: 12px; }"
        )
        logsec.layout().addWidget(self.log_view)

    def _sync_form_for_source(self, source: str) -> None:
        self.sched_value.setEnabled(source == "cron")

    # ── Actions ────────────────────────────────────────────────────

    def _toggle_bus(self) -> None:
        if self.bus.is_running():
            self.bus.stop()
            self._append_log(f"{icon('ok')} Event bus stopped.")
        else:
            self.bus.start()
            self._append_log(f"{icon('rocket')} Event bus started.")
        self._refresh()

    def _toggle_source(self, name: str) -> None:
        src = self.bus.sources.get(name)
        if src is None:
            return
        running = getattr(src, "_running", False)
        if running:
            src.stop()
            self._append_log(f"{icon('ok')} Source '{name}' stopped.")
        else:
            src.start()
            self._append_log(f"{icon('rocket')} Source '{name}' started.")
        self._refresh()

    def _copy_webhook_url(self) -> None:
        wh = self.bus.sources.get("webhook")
        url = wh.url if wh is not None else "http://127.0.0.1:8765/webhook"
        try:
            from PyQt6.QtWidgets import QApplication

            QApplication.clipboard().setText(url)
            self._append_log(f"{icon('ok')} Copied webhook URL: {url}")
        except Exception:
            self._append_log(f"Webhook URL: {url}")

    def _add_trigger(self) -> None:
        source = self.src_combo.currentText()
        mtype = self.match_combo.currentText()
        mval = self.match_value.text().strip()
        sched = self.sched_value.text().strip()
        action_type = self.action_combo.currentText()
        aval = self.action_value.text().strip()

        match: dict = {}
        if mval:
            match[mtype] = mval
        if source == "cron" and sched:
            match["schedule"] = sched

        action: dict = {"type": action_type}
        if action_type == "pipeline":
            action["goal"] = aval or "default goal"
        elif action_type == "shell":
            action["cmd"] = aval
        else:
            action["message"] = aval

        import uuid

        trig = self.Trigger(
            id=uuid.uuid4().hex[:8],
            name=f"{source}: {mval or sched or action_type}",
            source=source,
            match=match,
            action=action,
        )
        self.bus.add_trigger(trig)
        self._append_log(
            f"{icon('ok')} Added trigger '{trig.name}' ({source}) → "
            f"{action_type}"
        )
        self._restore_triggers_view()

    def _run_now(self, trigger_id: str) -> None:
        result = self.bus.trigger_workflow_now(trigger_id)
        if result is None:
            self._append_log(f"{icon('error')} Trigger {trigger_id} not found.")
            return
        self._append_log(
            f"{icon('zap')} Manual run: {result.get('status')} — "
            f"{result.get('goal') or result.get('message') or ''}"
        )
        self._refresh()

    def _delete(self, trigger_id: str) -> None:
        if self.bus.remove_trigger(trigger_id):
            self._append_log(f"{icon('ok')} Removed trigger {trigger_id}.")
        self._restore_triggers_view()

    def _set_enabled(self, trigger_id: str, enabled: bool) -> None:
        self.bus.enable_trigger(trigger_id, bool(enabled))
        self._restore_triggers_view()

    # ── Table rendering ────────────────────────────────────────────

    def _restore_triggers_view(self) -> None:
        triggers = self.bus.list_triggers()
        self._trigger_ids = [t.id for t in triggers]
        self.triggers_table.setRowCount(len(triggers))
        for i, t in enumerate(triggers):
            self.triggers_table.setItem(i, 0, QTableWidgetItem(t.name))
            self.triggers_table.setItem(i, 1, QTableWidgetItem(t.source))
            self.triggers_table.setItem(i, 2, QTableWidgetItem(self._match_summary(t.match)))
            self.triggers_table.setItem(i, 3, QTableWidgetItem(self._action_summary(t.action)))

            cb = QCheckBox()
            cb.setChecked(t.enabled)
            cb.stateChanged.connect(
                lambda state, tid=t.id: self._set_enabled(
                    tid, state == Qt.CheckState.Checked
                )
            )
            self.triggers_table.setCellWidget(i, 4, cb)
            self.triggers_table.setItem(i, 5, QTableWidgetItem(str(t.runs)))

            act = QHBoxLayout()
            run_btn = QPushButton("Run")
            run_btn.setStyleSheet(
                "QPushButton { background: #89b4fa; color: #1e1e2e; border: none; "
                "border-radius: 5px; padding: 3px 10px; }"
            )
            run_btn.clicked.connect(lambda _c=False, tid=t.id: self._run_now(tid))
            del_btn = QPushButton("Del")
            del_btn.setObjectName("stopButton")
            del_btn.clicked.connect(lambda _c=False, tid=t.id: self._delete(tid))
            act.addWidget(run_btn)
            act.addWidget(del_btn)
            w = QWidget()
            w.setLayout(act)
            self.triggers_table.setCellWidget(i, 6, w)

    @staticmethod
    def _match_summary(match: dict) -> str:
        if not match:
            return "(any)"
        if "schedule" in match:
            return f"cron {match['schedule']}"
        parts = [f"{k}={v}" for k, v in match.items() if k != "schedule"]
        return ", ".join(parts) or "(any)"

    @staticmethod
    def _action_summary(action: dict) -> str:
        atype = action.get("type", "pipeline")
        if atype == "pipeline":
            return f"pipeline: {action.get('goal', '')[:40]}"
        if atype == "shell":
            return f"shell: {action.get('cmd', '')[:40]}"
        return f"notify: {action.get('message', '')[:40]}"

    # ── Thread-safe updates ────────────────────────────────────────

    def _on_bus_event(self, event, fired) -> None:
        text = f"[{event.timestamp[11:19]}] {icon('sat') if event.source == 'webhook' else event.source}: {event.text[:80]}"
        if fired:
            text += f"  → fired {len(fired)} trigger(s)"
        self._sig_log.emit(text)
        self._sig_refresh.emit()

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        if self.log_view.blockCount() > 1000:
            self.log_view.clear()

    def _refresh(self) -> None:
        running = self.bus.is_running()
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText(f"Status: {'running' if running else 'stopped'}")
        stats = self.bus.status()["stats"]
        self.stats_label.setText(
            f"Events: {stats.get('events', 0)}   •   "
            f"Fired: {stats.get('fired', 0)}   •   "
            f"Errors: {stats.get('errors', 0)}"
        )
        src_status = self.bus.status()["sources"]
        for name, lbl in self.source_labels.items():
            st = src_status.get(name, {})
            on = st.get("running", False)
            lbl.setText(f"{name}: {'● running' if on else '○ idle'}")
            lbl.setStyleSheet(
                f"color: {'#a6e3a1' if on else '#6c7086' }; font-size: 13px;"
            )
        wh = self.bus.sources.get("webhook")
        if wh is not None and getattr(wh, "_running", False):
            backend = getattr(wh, "_backend", "?")
            self.webhook_url_label.setText(f"Webhook URL: {wh.url}  ({backend})")

        # Refresh run counts without rebuilding the table.
        for i, tid in enumerate(self._trigger_ids):
            trig = self.bus.get_trigger(tid)
            if trig is not None:
                item = self.triggers_table.item(i, 5)
                if item is not None:
                    item.setText(str(trig.runs))

    def on_activate(self) -> None:
        self._refresh_timer.start()
        self._refresh()

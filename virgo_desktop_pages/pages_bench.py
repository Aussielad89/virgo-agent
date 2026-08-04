"""Virgo Desktop pages — bench (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

from .pages_settings import _live_ollama_models

_BENCH_PROMPT = "Write a Python function that returns the nth Fibonacci number using memoization."


class BenchmarkPage(PageWidget):
    """Multi-Model Thermal Dashboard — compare every Ollama model on the same prompt."""

    def __init__(self) -> None:
        super().__init__(
            "Thermal Bench",
            "Run all Ollama models on one prompt — compare speed & quality",
        )

        # ── Prompt input ──
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt:"))
        self._prompt_input = QLineEdit()
        self._prompt_input.setText("Explain Python decorators in one paragraph.")
        self._prompt_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; }"
        )
        prompt_row.addWidget(self._prompt_input, 1)
        self.content.addLayout(prompt_row)

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        self._run_all_btn = QPushButton("🔥  Run all models")
        self._run_all_btn.clicked.connect(self._run_all)
        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_all)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        ctrl_row.addWidget(self._run_all_btn)
        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addWidget(self._status_label)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Results table (color-coded heatmap) ──
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            "Model", "Latency", "Tokens", "Tok/s", "Quality", "Status", "Preview"
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 80)
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; gridline-color: #313244; font-size: 12px; }"
            "QTableWidget::item { padding: 4px 8px; }"
            "QTableView::item:selected { background: #45475a; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 6px; color: #a6adc8; font-weight: bold; }"
        )
        # Disable sorting initially so row inserts stay orderly
        self._add(self._table)

        # — Full output viewer (expandable) —
        self._output_view = QPlainTextEdit()
        self._output_view.setReadOnly(True)
        self._output_view.setMaximumHeight(200)
        self._output_view.setVisible(False)
        self._add(self._output_view)

        # ── State ──
        self._running: set[str] = set()
        self._results: dict[str, dict] = {}
        self._cancelled = False
        self._bench_prompt = _BENCH_PROMPT

    def _run_all(self) -> None:
        """Kick off benchmarks on every available model in parallel."""
        prompt = self._prompt_input.text().strip() or self._bench_prompt

        models = _live_ollama_models()
        if not models:
            models = PREFERRED_MODELS[:]

        # Clean up the list to ignore cloud endpoints, remotes, and non-generative models
        models = [
            m for m in models
            if not m.endswith(":cloud")
            and "/" not in m
            and "embed" not in m
            and "mistral-large" not in m
        ]

        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._results.clear()
        self._running = set(models)
        self._cancelled = False
        self._run_all_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._output_view.setVisible(False)
        self._status_label.setText(f"Running {len(models)} model(s)...")

        for model in models:
            threading.Thread(
                target=self._bench_one,
                args=(model, prompt),
                daemon=True
            ).start()

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    def _stop_all(self) -> None:
        self._cancelled = True
        self._stop_btn.setVisible(False)
        self._run_all_btn.setEnabled(True)
        self._status_label.setText("Cancelled.")
        self._running.clear()

    def _bench_one(self, model: str, prompt: str) -> None:
        """Benchmark a single model against Ollama and update the table."""
        import time
        import urllib.request

        t0 = time.time()
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 256},
                }).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=600).read())
            dt = time.time() - t0
            text = resp.get("response", "")
            toks = resp.get("eval_count", 0) or len(text.split())
            tok_s = round(toks / dt, 1) if dt > 0 else 0
            quality = self._score_output(prompt, text)
            QMetaObject.invokeMethod(
                self,
                "_add_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, model),
                Q_ARG(str, f"{dt:.2f}s"),
                Q_ARG(str, str(toks)),
                Q_ARG(str, f"{tok_s:.1f}"),
                Q_ARG(str, f"{quality}/10"),
                Q_ARG(str, "✅ Done"),
                Q_ARG(str, text[:80].replace("\n", " ")),
            )
        except Exception as exc:
            QMetaObject.invokeMethod(
                self,
                "_add_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, model),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, "—"),
                Q_ARG(str, f"❌ {exc!s:.50}"),
                Q_ARG(str, ""),
            )

    @pyqtSlot(str, str, str, str, str, str, str)
    def _add_result(
        self, model: str, lat: str, toks: str,
        tps: str, qual: str, status: str, preview: str,
    ) -> None:
        self._results[model] = {
            "latency": lat, "tokens": toks, "tok_s": tps,
            "quality": qual, "output": preview,
        }
        self._insert_row(model, self._results[model])

        self._running.discard(model)
        if not self._running and not self._cancelled:
            self._finish()

    def _insert_row(self, model: str, r: dict, rank: int | None = None) -> None:
        """Append one result row (rank = podium position, shown when set)."""
        _color = QColor
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Colour-code latency (green < 5s, yellow < 20s, red >= 20s)
        try:
            lat_val = float(r["latency"].rstrip("s"))
            if lat_val < 5:
                bg = _color("#1a3a2a")
            elif lat_val < 20:
                bg = _color("#3a3a1a")
            else:
                bg = _color("#3a1a1a")
        except Exception:
            bg = _color("#1e1e2e")

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        name = " ".join(p for p in (f"{rank}." if rank else "", medal, model) if p)
        items = [
            (name, _color("#89b4fa")),
            (r["latency"], _color("#cdd6f4")),
            (r["tokens"], _color("#a6adc8")),
            (r["tok_s"], _color("#a6e3a1")),
            (r["quality"], _color("#f5c2e7")),
            (r.get("status", "✅ Done"), _color("#a6adc8")),
            (r["output"], _color("#6c7086")),
        ]
        for col, (text, fg) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(fg)
            item.setBackground(bg)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, model)
            self._table.setItem(row, col, item)

    def _finish(self) -> None:
        """All models done — rank best → worst, re-sort the table, show the podium."""
        self._run_all_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        ranked = sorted(
            self._results.items(),
            key=lambda kv: (
                float(kv[1]["quality"].split("/")[0]) if kv[1]["quality"] != "—" else 0,
                -float(kv[1]["latency"].rstrip("s")) if kv[1]["latency"] != "—" else 0,
            ),
            reverse=True,
        )
        # Rebuild the table so the best model sits on top
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for i, (model, r) in enumerate(ranked, 1):
            self._insert_row(model, r, rank=i)
        # The "1. 🥇 model" text sorts numerically, so force column 0 ascending
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # Status line: full best → worst ranking
        parts = [
            f"{i}. {model} ({r['quality']}, {r['latency']})"
            for i, (model, r) in enumerate(ranked, 1)
        ]
        self._status_label.setText(
            ("🏁 Done — best → worst: " + "  →  ".join(parts)) if parts else "Done."
        )

    @staticmethod
    def _score_output(prompt: str, output: str) -> int:
        """Heuristic quality: keyword relevance + structure."""
        import re
        if not output:
            return 0
        pwords = set(re.findall(r"\w+", prompt.lower()))
        owords = re.findall(r"\w+", output.lower())
        if not owords:
            return 0
        overlap = len([w for w in owords if w in pwords]) / max(1, len(pwords))
        length_bonus = min(1.0, len(owords) / 100.0)
        score = int(round((overlap * 0.5 + length_bonus * 0.5) * 10))
        return max(0, min(10, score))

    def _show_full_output(self, item: QTableWidgetItem) -> None:
        """Double-click a row to see the full output."""
        row = item.row()
        model_item = self._table.item(row, 0)
        if not model_item:
            return
        model = model_item.data(Qt.ItemDataRole.UserRole) or model_item.text()
        result = self._results.get(model)
        if not result:
            return
        self._output_view.setPlainText(
            f"Model: {model}\n"
            f"Latency: {result['latency']}  |  Tokens: {result['tokens']}  "
            f"|  Tok/s: {result['tok_s']}  |  Quality: {result['quality']}\n"
            f"{'─' * 60}\n"
            f"Full output:\n{result.get('_full', '(not stored)')}"
        )
        self._output_view.setVisible(True)


# ═══════════════════════════════════════════════════════════════════════
# Settings page
# ═══════════════════════════════════════════════════════════════════════

# Preferred local models (benchmarked on this machine). The Settings page
# merges these with whatever Ollama currently has pulled.


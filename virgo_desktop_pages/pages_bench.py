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

        # ── Rank actions: promote a podium model + export results ──
        rank_row = QHBoxLayout()
        rank_row.addWidget(QLabel("Set default:"))
        self.rank_combo = QComboBox()
        self.rank_combo.setMinimumWidth(150)
        rank_row.addWidget(self.rank_combo)
        self.promote_btn = QPushButton("🏆  Set as default model")
        self.promote_btn.setEnabled(False)
        self.promote_btn.clicked.connect(self._promote_selected)
        rank_row.addWidget(self.promote_btn)
        rank_row.addStretch()
        self.csv_btn = QPushButton("💾  Export CSV")
        self.csv_btn.setEnabled(False)
        self.csv_btn.clicked.connect(lambda: self._export("csv"))
        rank_row.addWidget(self.csv_btn)
        self.md_btn = QPushButton("💾  Export MD")
        self.md_btn.setEnabled(False)
        self.md_btn.clicked.connect(lambda: self._export("md"))
        rank_row.addWidget(self.md_btn)
        self.content.addLayout(rank_row)

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
        # Zero-pad so the text sort ("01." < "02." < ... < "10.") matches the rank order
        name = " ".join(p for p in (f"{rank:02d}." if rank else "", medal, model) if p)
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

    def _ranked(self) -> list[tuple[str, dict]]:
        """Current results sorted best → worst (quality, then speed)."""
        return sorted(
            self._results.items(),
            key=lambda kv: (
                float(kv[1]["quality"].split("/")[0]) if kv[1]["quality"] != "—" else 0,
                -float(kv[1]["latency"].rstrip("s")) if kv[1]["latency"] != "—" else 0,
            ),
            reverse=True,
        )

    def _finish(self) -> None:
        """All models done — rank best → worst, re-sort the table, show the podium."""
        self._run_all_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        ranked = self._ranked()
        # Rebuild the table so the best model sits on top
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for i, (model, r) in enumerate(ranked, 1):
            self._insert_row(model, r, rank=i)
        # The "1. 🥇 model" text sorts numerically, so force column 0 ascending
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # Rank actions become available once a run completes
        medals = ["🥇 1st", "🥈 2nd", "🥉 3rd"]
        self.rank_combo.clear()
        for i, (model, _r) in enumerate(ranked[:3]):
            self.rank_combo.addItem(f"{medals[i] if i < 3 else ''} {model}".strip())
        self.promote_btn.setEnabled(bool(ranked))
        self.csv_btn.setEnabled(bool(ranked))
        self.md_btn.setEnabled(bool(ranked))

        # Status line: top of the podium + total (the table carries the full order)
        parts = [
            f"{i}. {model} ({r['quality']}, {r['latency']})"
            for i, (model, r) in enumerate(ranked, 1)
        ]
        if not parts:
            self._status_label.setText("Done.")
        elif len(parts) <= 3:
            self._status_label.setText("🏁 Done — best → worst: " + "  →  ".join(parts))
        else:
            self._status_label.setText(
                "🏁 Done — best → worst: " + "  →  ".join(parts[:3])
                + f"  →  … ({len(ranked)} models ranked)"
            )

    def _promote_selected(self) -> None:
        """Set the podium pick as the default model (virgo.toml + live chat switch)."""
        ranked = self._ranked()
        idx = self.rank_combo.currentIndex()
        if not ranked or idx < 0 or idx >= len(ranked):
            return
        model = ranked[idx][0]
        medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(idx, "")
        toml = HERE / "virgo.toml"
        try:
            lines = toml.read_text(encoding="utf-8").splitlines(keepends=True)
            section: str | None = None
            changed = False
            for i, ln in enumerate(lines):
                s = ln.strip()
                if s.startswith("[") and s.endswith("]"):
                    section = s[1:-1].strip()
                    continue
                if section not in ("model", "chat"):
                    continue
                key = s.split("=", 1)[0].strip()
                if (section == "model" and key == "generator") or (
                    section == "chat" and key == "model"
                ):
                    lines[i] = re.sub(r'=.*', f'= "{model}"', ln)
                    changed = True
            if changed:
                toml.write_text("".join(lines), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._status_label.setText(f"Could not update virgo.toml: {exc}")
            return
        # Live-switch the chat page if it is open
        win = self.window()
        if win is not None:
            chat = getattr(win, "pages", {}).get("chat")
            if chat is not None and hasattr(chat, "model_combo"):
                chat.model_combo.setCurrentText(model)
            if hasattr(win, "_notify_tray"):
                win._notify_tray("Default model updated", f"{medal} {model} is now the chat default")
        self._status_label.setText(f"{medal} Default model → {model}")

    def _export(self, fmt: str) -> None:
        """Write the ranked results to OUTDIR as CSV or Markdown."""
        import time as _time

        ranked = self._ranked()
        if not ranked:
            self._status_label.setText("Nothing to export yet.")
            return
        ts = _time.strftime("%Y%m%d-%H%M%S")
        path = OUTDIR / f"bench_results_{ts}.{fmt}"
        rows = []
        for i, (model, r) in enumerate(ranked, 1):
            rows.append((i, model, r["latency"], r["tokens"], r["tok_s"], r["quality"]))
        if fmt == "csv":
            import csv as _csv
            import io

            buf = io.StringIO()
            w = _csv.writer(buf)
            w.writerow(["rank", "model", "latency", "tokens", "tok_s", "quality"])
            w.writerows(rows)
            text = buf.getvalue()
        else:
            head = "| # | Model | Latency | Tokens | Tok/s | Quality |\n|---|---|---|---|---|---|\n"
            body = "".join(
                f"| {i} | {m} | {lat} | {tok} | {tps} | {q} |\n"
                for i, m, lat, tok, tps, q in rows
            )
            text = head + body
        try:
            OUTDIR.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
            self._status_label.setText(f"Exported → {path}")
        except Exception as exc:  # noqa: BLE001
            self._status_label.setText(f"Export failed: {exc}")

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


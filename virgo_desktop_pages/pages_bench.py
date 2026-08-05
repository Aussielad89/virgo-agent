"""Virgo Desktop pages — bench (split from the monolith)."""
from __future__ import annotations

import requests
import threading

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
        self.pull_missing_btn = QPushButton("⬇  Pull missing models")
        self.pull_missing_btn.setEnabled(False)
        self.pull_missing_btn.clicked.connect(self._pull_missing)
        rank_row.addWidget(self.pull_missing_btn)
        rank_row.addStretch()
        self.csv_btn = QPushButton("💾  Export CSV")
        self.csv_btn.setEnabled(False)
        self.csv_btn.clicked.connect(lambda: self._export("csv"))
        rank_row.addWidget(self.csv_btn)
        self.md_btn = QPushButton("💾  Export MD")
        self.md_btn.setEnabled(False)
        self.md_btn.clicked.connect(lambda: self._export("md"))
        rank_row.addWidget(self.md_btn)
        self.history_btn = QPushButton("📚  History")
        self.history_btn.clicked.connect(self._show_history)
        rank_row.addWidget(self.history_btn)
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
        self._skip_archive = False

        # ── Cross-agent contract: web dashboard drops BENCH_TRIGGER.txt ──
        self._trigger_timer = QTimer(self)
        self._trigger_timer.setInterval(5000)
        self._trigger_timer.timeout.connect(self._check_web_trigger)
        self._trigger_timer.start()

    def _run_all(self) -> None:
        """Kick off benchmarks on every available model in parallel."""
        prompt = self._prompt_input.text().strip() or self._bench_prompt
        self._bench_prompt = prompt

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
            "quality": qual, "status": status, "output": preview,
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
        self.pull_missing_btn.setEnabled(bool(self._missing_models()))

        # Archive this run for the history view (skipped when loading a past run)
        if not self._skip_archive:
            self._archive()

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

    def _missing_models(self) -> list[str]:
        """Models the last run reported as not installed (status mentions pull/404)."""
        missing = []
        for model, r in self._results.items():
            text = " ".join(str(r.get(k, "")) for k in ("status", "error")).lower()
            if "not found" in text or "pull" in text or "404" in text:
                missing.append(model)
        return missing

    def _run_models(self, models: list[str]) -> None:
        """Bench a specific subset of models, keeping existing results for others."""
        if not models:
            return
        prompt = self._prompt_input.text().strip() or self._bench_prompt
        self._bench_prompt = prompt
        self._table.setSortingEnabled(False)
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
                daemon=True,
            ).start()
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    def _pull_missing(self) -> None:
        """Pull every model the last run flagged as missing, then re-bench them."""
        names = self._missing_models()
        if not names:
            self._status_label.setText("No missing models to pull.")
            return
        self.pull_missing_btn.setEnabled(False)
        self._pulled_models = names
        self._status_label.setText(f"⬇ Pulling {len(names)} missing model(s)...")

        def _worker() -> None:
            for name in names:
                try:
                    r = requests.post(
                        "http://localhost:11434/api/pull",
                        json={"model": name},
                        stream=True,
                        timeout=600,
                    )
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:  # noqa: BLE001
                            continue
                        if ev.get("status"):
                            self._set_status(f"⬇ pulling {name}: {ev['status']}")
                        if ev.get("error"):
                            self._set_status(f"⬇ pulling {name}: error {ev['error']}")
                    self._set_status(f"done {name}")
                except Exception as exc:  # noqa: BLE001
                    self._set_status(f"⬇ pull {name} failed: {exc}")
            QMetaObject.invokeMethod(
                self, "_rerun_pulled", Qt.ConnectionType.QueuedConnection
            )

        threading.Thread(target=_worker, daemon=True).start()

    @pyqtSlot(str)
    def _set_status(self, text: str) -> None:
        """Thread-safe update of the bench status line."""
        self._status_label.setText(text)

    @pyqtSlot()
    def _rerun_pulled(self) -> None:
        """Bench the freshly pulled models (old rows for other models stay)."""
        models = list(getattr(self, "_pulled_models", []))
        self._pulled_models = []
        self.pull_missing_btn.setEnabled(True)
        self._run_models(models)

    def _archive(self) -> None:
        """Append the finished run to OUTDIR/bench_results.json (JSON list)."""
        from datetime import datetime

        ranked = self._ranked()
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "prompt": self._bench_prompt,
            "winner": ranked[0][0] if ranked else None,
            "results": [
                {
                    "model": model,
                    "latency": r.get("latency", "—"),
                    "tokens": r.get("tokens", "—"),
                    "tok_s": r.get("tok_s", "—"),
                    "quality": r.get("quality", "—"),
                    "status": r.get("status", "✅ Done"),
                }
                for model, r in ranked
            ],
        }
        path = OUTDIR / "bench_results.json"
        try:
            history: list = []
            if path.exists():
                try:
                    history = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    history = []
                if not isinstance(history, list):
                    history = []
            history.append(record)
            OUTDIR.mkdir(exist_ok=True)
            path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._status_label.setText(f"Could not save bench history: {exc}")

    def _show_history(self) -> None:
        """Open a dialog of past bench runs; Load restores a run's results."""
        from datetime import datetime as _dt

        path = OUTDIR / "bench_results.json"
        history: list = []
        try:
            if path.exists():
                history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            history = []
        if not isinstance(history, list) or not history:
            self._status_label.setText("No bench history yet.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Bench history")
        dlg.resize(560, 380)
        dlg.setStyleSheet(
            "QDialog { background: #1e1e2e; }"
            "QListWidget { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; font-size: 12px; }"
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 14px; color: #cdd6f4; }"
            "QPushButton:hover { background: #45475a; }"
        )
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        for rec in history:
            try:
                ts_disp = _dt.fromisoformat(str(rec.get("ts", ""))).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except Exception:  # noqa: BLE001
                ts_disp = str(rec.get("ts", "?"))[:16]
            winner = rec.get("winner") or "—"
            n = len(rec.get("results", []))
            lst.addItem(f"{ts_disp}  🥇 {winner}  ({n} models)")
        lay.addWidget(lst)
        row = QHBoxLayout()
        load_btn = QPushButton("Load")
        close_btn = QPushButton("Close")
        row.addWidget(load_btn)
        row.addWidget(close_btn)
        row.addStretch()
        lay.addLayout(row)
        close_btn.clicked.connect(dlg.reject)

        def _load() -> None:
            it = lst.currentItem()
            if it is None:
                return
            idx = lst.row(it)
            if 0 <= idx < len(history):
                self._load_history_run(history[idx])
            dlg.accept()

        load_btn.clicked.connect(_load)
        lst.itemDoubleClicked.connect(lambda _item: _load())
        dlg.exec()

    def _load_history_run(self, rec: dict) -> None:
        """Restore a past run's results and re-render the bench table."""
        results: dict[str, dict] = {}
        for r in rec.get("results", []):
            model = r.get("model")
            if not model:
                continue
            results[model] = {
                "latency": r.get("latency", "—"),
                "tokens": r.get("tokens", "—"),
                "tok_s": r.get("tok_s", "—"),
                "quality": r.get("quality", "—"),
                "status": r.get("status", "✅ Done"),
                "output": r.get("output", ""),
            }
        if not results:
            self._status_label.setText("No results in that run.")
            return
        self._results = results
        self._skip_archive = True
        try:
            self._finish()
        finally:
            self._skip_archive = False

    def _check_web_trigger(self) -> None:
        """Cross-agent contract: start a bench when the web dashboard drops a
        trigger file (OUTDIR/BENCH_TRIGGER.txt) younger than 120 s."""
        import time

        if self._running:
            return
        trigger = OUTDIR / "BENCH_TRIGGER.txt"
        try:
            if not trigger.exists():
                return
            if time.time() - trigger.stat().st_mtime > 120:
                return
            trigger.unlink()
            self._status_label.setText("🌐 Bench triggered from web dashboard")
            self._run_all()
        except Exception:  # noqa: BLE001
            pass

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


"""Local Model Manager for Virgo Desktop.

Manages Ollama models (list/pull/delete) via localhost:11434, shows CPU/RAM
load per model, and picks the cheapest model that fits a given task. No paid
APIs, no cloud. Pure local.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import requests
from PyQt6.QtCore import QMetaObject, QTimer, Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
)

from virgo_desktop_pages import PageWidget
from _log import OUTDIR

OLLAMA = "http://localhost:11434"

# Rough cost ranking — smaller models are "cheaper" for the router.
_SIZE_RANK = {
    "0.5": 1, "0.6": 1, "0.8": 2, "1.5": 3, "2": 3, "2b": 3, "3": 4,
    "3.5": 4, "3.8": 4, "4": 5, "4b": 5, "7": 6, "8": 6, "9": 7,
    "10.7": 8, "11": 8, "13": 9, "14": 9, "30": 10, "32": 10, "35": 11,
    "70": 12, "120": 13, "400": 14,
}


def _size_rank(name: str) -> int:
    low = name.lower()
    for key, rank in sorted(_SIZE_RANK.items(), key=lambda kv: -len(kv[0])):
        if key in low:
            return rank
    if "cloud" in low:
        return 99
    return 50


def _api(path: str, method: str = "GET", **kw) -> Any:
    try:
        r = requests.request(method, f"{OLLAMA}{path}", timeout=30, **kw)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


class ModelManagerPage(PageWidget):
    """Browse, pull, delete Ollama models; route tasks to the cheapest fit."""

    def __init__(self) -> None:
        super().__init__("Model Manager", "Local Ollama control — no cloud, no paid APIs")
        self.models: list[dict] = []

        # ── Model list ──
        box = QGroupBox("Local models")
        bl = QVBoxLayout(box)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { background: #181825; border: 1px solid #313244; border-radius: 6px; }")
        bl.addWidget(self.list)
        row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._load)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.delete_btn)
        row.addStretch()
        bl.addLayout(row)
        self._add(box)

        # ── Pull ──
        pbox = QGroupBox("Pull a model")
        pl = QVBoxLayout(pbox)
        prow = QHBoxLayout()
        self.pull_in = QTextEdit()
        self.pull_in.setMaximumHeight(28)
        self.pull_in.setPlaceholderText("e.g. qwen3.5:0.8b")
        self.pull_btn = QPushButton("Pull")
        self.pull_btn.clicked.connect(self._pull)
        prow.addWidget(QLabel("Model:"))
        prow.addWidget(self.pull_in, 1)
        prow.addWidget(self.pull_btn)
        pl.addLayout(prow)
        self.pull_log = QTextEdit()
        self.pull_log.setMaximumHeight(80)
        self.pull_log.setReadOnly(True)
        pl.addWidget(self.pull_log)
        self._add(pbox)

        # ── Router ──
        rbox = QGroupBox("Cheapest-fit router")
        rl = QVBoxLayout(rbox)
        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Task hint (e.g. embed, chat, code, big):"))
        self.task_in = QTextEdit()
        self.task_in.setMaximumHeight(28)
        self.task_in.setText("chat")
        rrow.addWidget(self.task_in, 1)
        self.route_btn = QPushButton("Pick model")
        self.route_btn.clicked.connect(self._route)
        rrow.addWidget(self.route_btn)
        rl.addLayout(rrow)
        self.route_out = QLabel("—")
        self.route_out.setStyleSheet("color: #a6e3a1; font-size: 13px;")
        rl.addWidget(self.route_out)
        self._add(rbox)

        # ── Remote providers (OpenAI-compatible endpoints) ──
        rg = QGroupBox("Remote providers (OpenAI-compatible)")
        rgl = QVBoxLayout(rg)
        self.remote_list = QListWidget()
        self.remote_list.setMaximumHeight(96)
        rgl.addWidget(self.remote_list)
        rr = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._remote_add)
        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(self._remote_remove)
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._remote_test)
        rr.addWidget(add_btn)
        rr.addWidget(rm_btn)
        rr.addWidget(test_btn)
        rr.addStretch()
        rgl.addLayout(rr)
        self.remote_status = QLabel("No remote providers configured.")
        self.remote_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        rgl.addWidget(self.remote_status)
        self._add(rg)

        self._remotes: list[dict] = []
        self._remote_load()

        self._load()

    # ── actions ──
    def _load(self) -> None:
        data = _api("/api/tags")
        self.models = data.get("models", []) if isinstance(data, dict) else []
        if "error" in data:
            self.pull_log.append(f"list error: {data['error']}")
            return
        self.list.clear()
        for m in self.models:
            name = m.get("name", "?")
            sz = m.get("size", 0)
            item = QListWidgetItem(f"{name}  ({sz / 1e9:.1f} GB)")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)

    def _delete(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        _api(f"/api/delete", method="DELETE", json={"model": name})
        self.pull_log.append(f"deleted {name}")
        self._load()

    def _pull(self) -> None:
        name = self.pull_in.toPlainText().strip()
        if not name:
            return
        self.pull_log.append(f"pulling {name} …")
        try:
            r = requests.post(f"{OLLAMA}/api/pull", json={"model": name},
                              stream=True, timeout=600)
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if ev.get("status"):
                    self.pull_log.append(ev["status"])
                if ev.get("error"):
                    self.pull_log.append(f"ERR {ev['error']}")
            self.pull_log.append(f"done {name}")
        except Exception as e:  # noqa: BLE001
            self.pull_log.append(f"pull failed: {e}")
        self._load()

    def _route(self) -> None:
        hint = self.task_in.toPlainText().strip().lower()
        if not self.models:
            self._load()
        ranked = sorted(self.models, key=lambda m: _size_rank(m.get("name", "")))
        # never route to a cloud model unless explicitly asked
        local = [m for m in ranked if "cloud" not in m.get("name", "").lower()]
        pool = local if not ("cloud" in hint) else ranked
        # pick slightly larger if "big"/"code"/"reason" requested
        if any(k in hint for k in ("big", "reason", "deep", "code")):
            pick = pool[min(len(pool) - 1, max(0, len(pool) // 2))]
        else:
            pick = pool[0] if pool else (ranked[0] if ranked else None)
        if pick:
            self.route_out.setText(f"→ {pick.get('name')}  (rank {_size_rank(pick.get('name',''))}/14)")
        else:
            self.route_out.setText("no models available")

    # ── remote providers ──
    def _remote_path(self) -> Path:
        return OUTDIR / "REMOTE_PROVIDERS.json"

    def _remote_load(self) -> None:
        self._remotes = []
        try:
            if self._remote_path().exists():
                self._remotes = json.loads(self._remote_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._remotes = []
        self.remote_list.clear()
        for r in self._remotes:
            self.remote_list.addItem(f"{r.get('name','?')}  —  {r.get('base_url','')}")
        if self._remotes:
            self.remote_status.setText(f"{len(self._remotes)} provider(s) configured")
        else:
            self.remote_status.setText("No remote providers configured.")

    def _remote_save(self) -> None:
        try:
            OUTDIR.mkdir(exist_ok=True)
            self._remote_path().write_text(
                json.dumps(self._remotes, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            self.remote_status.setText(f"save failed: {exc}")
        self._remote_load()

    def _remote_add(self) -> None:
        name, ok1 = QInputDialog.getText(self, "Remote provider", "Name:")
        if not ok1 or not name.strip():
            return
        url, ok2 = QInputDialog.getText(
            self, "Remote provider",
            "Base URL (OpenAI-compatible), e.g. https://api.openai.com/v1",
        )
        if not ok2 or not url.strip():
            return
        key, ok3 = QInputDialog.getText(self, "Remote provider", "API key (optional):")
        self._remotes = [r for r in self._remotes if r.get("name") != name.strip()]
        self._remotes.append(
            {
                "name": name.strip(),
                "base_url": url.strip().rstrip("/"),
                "api_key": key.strip() if ok3 else "",
            }
        )
        self._remote_save()

    def _remote_remove(self) -> None:
        it = self.remote_list.currentItem()
        if not it:
            return
        name = it.text().split("  —  ")[0]
        self._remotes = [r for r in self._remotes if r.get("name") != name]
        self._remote_save()

    def _remote_test(self) -> None:
        it = self.remote_list.currentItem()
        if not it:
            return
        name = it.text().split("  —  ")[0]
        prov = next((r for r in self._remotes if r.get("name") == name), None)
        if not prov:
            return
        self.remote_status.setText(f"Testing {name}…")
        base = prov.get("base_url", "").rstrip("/")

        def _do() -> None:
            try:
                headers = (
                    {"Authorization": f"Bearer {prov['api_key']}"}
                    if prov.get("api_key")
                    else {}
                )
                resp = requests.get(f"{base}/models", headers=headers, timeout=10)
                if resp.status_code == 200:
                    ids = [m.get("id", "?") for m in resp.json().get("data", [])][:5]
                    msg = f"✓ {name} OK — {len(ids)} model(s): {', '.join(ids) or 'none listed'}"
                else:
                    msg = f"✗ {name} HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                msg = f"✗ {name}: {exc}"
            QMetaObject.invokeMethod(
                self,
                "_remote_status_set",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, msg),
            )

        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot(str)
    def _remote_status_set(self, text: str) -> None:
        self.remote_status.setText(text)

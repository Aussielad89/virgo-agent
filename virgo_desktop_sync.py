"""Self-hosted Sync client page for Virgo Desktop.

Pushes/pulls encrypted snapshots (workflows, memory, settings) to a local
Flask sync server (virgo_sync_server.py) — no Firebase, no third party.
Payloads are XOR-scrambled with a passphrase + base64 so they are not stored
in plaintext in the server DB.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import requests
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from virgo_desktop_pages import PageWidget

SERVER = "http://localhost:8686"


def _scramble(text: str, key: str) -> str:
    k = key.encode()
    raw = text.encode()
    out = bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))
    return base64.b64encode(out).decode()


def _unscramble(b64: str, key: str) -> str:
    k = key.encode()
    raw = base64.b64decode(b64)
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(raw)).decode()


class SyncPage(PageWidget):
    """Encrypted, self-hosted sync (replaces Firebase)."""

    def __init__(self) -> None:
        super().__init__("Sync", "Self-hosted, encrypted sync — no cloud")

        cfg = QGroupBox("Server")
        cl = QVBoxLayout(cfg)
        row = QHBoxLayout()
        row.addWidget(QLabel("URL:"))
        self.url = QLineEdit(SERVER)
        row.addWidget(self.url, 1)
        cl.addLayout(row)
        keyrow = QHBoxLayout()
        keyrow.addWidget(QLabel("Passphrase:"))
        self.passp = QLineEdit("virgo-local")
        self.passp.setEchoMode(QLineEdit.EchoMode.Password)
        keyrow.addWidget(self.passp, 1)
        cl.addLayout(keyrow)
        self._add(cfg)

        snap = QGroupBox("Snapshot (local files to sync)")
        sl = QVBoxLayout(snap)
        self.snap = QTextEdit()
        self.snap.setMaximumHeight(80)
        self.snap.setPlaceholderText(
            "Paths to sync, one per line, relative to project root:\n"
            "workflows/\nmemory.json\nsettings.json"
        )
        sl.addWidget(self.snap)
        self._add(snap)

        act = QHBoxLayout()
        self.push_btn = QPushButton("Push selected")
        self.push_btn.clicked.connect(self._push)
        self.pull_btn = QPushButton("Pull all")
        self.pull_btn.clicked.connect(self._pull)
        act.addWidget(self.push_btn)
        act.addWidget(self.pull_btn)
        act.addStretch()
        self._add_row_no_stretch(act)

        lg = QGroupBox("Log")
        ll = QVBoxLayout(lg)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        ll.addWidget(self.log)
        self._add(lg)

    def _add_row_no_stretch(self, row) -> None:
        self.content.addLayout(row)

    def _root(self) -> Path:
        return Path(__file__).resolve().parent

    def _push(self) -> None:
        base = self.url.text().strip().rstrip("/")
        key = self.passp.text() or "virgo-local"
        paths = [p.strip() for p in self.snap.toPlainText().splitlines() if p.strip()]
        for p in paths:
            fp = self._root() / p
            if not fp.exists():
                self.log.append(f"skip (missing) {p}")
                continue
            data = fp.read_text(errors="ignore") if fp.is_file() else "DIR"
            blob = _scramble(json.dumps({"path": p, "data": data}), key)
            try:
                r = requests.post(f"{base}/put",
                                  json={"key": p, "data": blob, "ts": int(time.time())},
                                  timeout=20)
                self.log.append(f"pushed {p}: {r.status_code}")
            except Exception as e:  # noqa: BLE001
                self.log.append(f"push {p} FAILED: {e}")

    def _pull(self) -> None:
        base = self.url.text().strip().rstrip("/")
        key = self.passp.text() or "virgo-local"
        try:
            keys = requests.get(f"{base}/list", timeout=20).json().get("keys", [])
        except Exception as e:  # noqa: BLE001
            self.log.append(f"list FAILED: {e}")
            return
        for item in keys:
            k = item["key"]
            try:
                r = requests.get(f"{base}/get/{k}", timeout=20).json()
                payload = json.loads(_unscramble(r["data"], key))
                fp = self._root() / payload["path"]
                if payload["data"] != "DIR":
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(payload["data"], errors="ignore")
                    self.log.append(f"pulled {k}")
            except Exception as e:  # noqa: BLE001
                self.log.append(f"pull {k} FAILED: {e}")

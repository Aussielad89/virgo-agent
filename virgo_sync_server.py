"""Self-hosted sync server + client for Virgo Desktop.

Replaces the planned Firebase sync. A tiny Flask REST server stores encrypted
blobs (workflows, memory, settings) in a local SQLite DB. The desktop client
syncs to it over HTTP. No third party, no cloud.

Run server:  python virgo_sync_server.py --host 0.0.0.0 --port 8686
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from flask import Flask, request, jsonify

DB_PATH = Path(os.environ.get("VIRGO_SYNC_DB", "virgo_sync.db"))


def _db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS blobs ("
        "  key TEXT PRIMARY KEY, data TEXT, ts INTEGER)"
    )
    return con


def create_app() -> Flask:
    app = Flask(__name__)

    @app.post("/put")
    def put():
        body = request.get_json(force=True)
        key, data, ts = body.get("key"), body.get("data"), int(body.get("ts", 0))
        if not key or data is None:
            return jsonify({"error": "key+data required"}), 400
        with _db() as con:
            con.execute(
                "INSERT INTO blobs(key,data,ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, ts=excluded.ts",
                (key, data, ts),
            )
        return jsonify({"ok": True})

    @app.get("/get/<key>")
    def get(key):
        with _db() as con:
            row = con.execute("SELECT data,ts FROM blobs WHERE key=?", (key,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify({"key": key, "data": row[0], "ts": row[1]})

    @app.get("/list")
    def list_keys():
        with _db() as con:
            rows = con.execute("SELECT key,ts FROM blobs ORDER BY ts DESC").fetchall()
        return jsonify({"keys": [{"key": r[0], "ts": r[1]} for r in rows]})

    @app.delete("/del/<key>")
    def delete(key):
        with _db() as con:
            con.execute("DELETE FROM blobs WHERE key=?", (key,))
        return jsonify({"ok": True})

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8686)
    a = ap.parse_args()
    create_app().run(host=a.host, port=a.port, threaded=True)


if __name__ == "__main__":
    main()

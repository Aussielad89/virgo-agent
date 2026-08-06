"""
virgo_audit — immutable audit chain for pipeline runs.

Hashes every pipeline run and chains them (blockchain-style) for
tamper-evident logs of generated code, author, and test results.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
CHAIN_FILE = HERE / ".virgo_audit_chain.json"


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_chain() -> list[dict[str, Any]]:
    if CHAIN_FILE.exists():
        try:
            return json.loads(CHAIN_FILE.read_text())
        except Exception:
            return []
    return []


def _save_chain(chain: list[dict[str, Any]]) -> None:
    try:
        CHAIN_FILE.write_text(json.dumps(chain, indent=2, default=str))
    except Exception:
        pass


def append_record(record: dict[str, Any]) -> dict[str, Any]:
    chain = _load_chain()
    prev_hash = chain[-1]["entry_hash"] if chain else "0" * 64
    payload = {
        "timestamp": datetime.now().isoformat(),
        "prev_hash": prev_hash,
        "record": record,
    }
    entry_hash = _hash_payload(payload)
    entry = {
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
        "timestamp": payload["timestamp"],
        "record": record,
    }
    chain.append(entry)
    _save_chain(chain)
    log.info("audit: appended entry %s", entry_hash[:12])
    return entry


def verify_chain() -> dict[str, Any]:
    chain = _load_chain()
    if not chain:
        return {"valid": True, "entries": 0}
    prev = "0" * 64
    bad = []
    for idx, entry in enumerate(chain):
        if entry.get("prev_hash") != prev:
            bad.append(f"entry {idx}: prev_hash mismatch (expected {prev[:12]}, got {entry.get('prev_hash','')[:12]})")
        payload = {
            "timestamp": entry.get("timestamp"),
            "prev_hash": entry.get("prev_hash"),
            "record": entry.get("record"),
        }
        expected = _hash_payload(payload)
        if entry.get("entry_hash") != expected:
            bad.append(f"entry {idx}: hash mismatch")
        prev = entry.get("entry_hash", "")
    return {
        "valid": not bad,
        "entries": len(chain),
        "broken_links": len(bad),
        "issues": bad[:10],
        "head_hash": chain[-1]["entry_hash"] if chain else "",
    }


def tail(n: int = 5) -> list[dict[str, Any]]:
    chain = _load_chain()
    return chain[-n:]


def export_chain(path: str) -> None:
    chain = _load_chain()
    Path(path).write_text(json.dumps(chain, indent=2, default=str))


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Audit Chain")
    sub = p.add_subparsers(dest="command")
    w = sub.add_parser("write")
    w.add_argument("--record", required=True)
    v = sub.add_parser("verify")
    t = sub.add_parser("tail")
    t.add_argument("--n", type=int, default=5)
    e = sub.add_parser("export")
    e.add_argument("path")
    args = p.parse_args()
    if args.command == "write":
        try:
            record = json.loads(args.record)
        except Exception:
            record = {"raw": args.record}
        entry = append_record(record)
        print(json.dumps(entry, indent=2, default=str))
    elif args.command == "verify":
        print(json.dumps(verify_chain(), indent=2))
    elif args.command == "tail":
        print(json.dumps(tail(args.n), indent=2, default=str))
    elif args.command == "export":
        export_chain(args.path)
        print(f"exported to {args.path}")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()

"""
virgo_telemetry.py — optional anonymous usage telemetry for virgo-agent.

Events are written to .virgo_telemetry/events.jsonl (one JSON object per line).
The file is rotated when it reaches 5 MB.

Opt-out:
  - Environment variable: VIRGO_TELEMETRY=0
  - Config toggle: .virgo_desktop_config.json  {"telemetry": false}

No event contains file paths, user text, or model outputs.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_VALID_EVENTS = {
    "page_view",
    "tool_run",
    "pipeline_run",
    "chat_send",
    "crash",
    "setting_change",
}

TELEMETRY_DIR = Path(__file__).parent / ".virgo_telemetry"
EVENT_FILE = TELEMETRY_DIR / "events.jsonl"
MAX_FILE_BYTES = 5 * 1024 * 1024


def _is_enabled() -> bool:
    """Return True if telemetry is enabled via env var + config toggle."""
    if os.getenv("VIRGO_TELEMETRY", "1") == "0":
        return False
    try:
        config_path = Path(__file__).parent / ".virgo_desktop_config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("telemetry") is False:
                return False
    except Exception:
        pass
    return True


def _rotate_if_needed() -> None:
    """Rotate the event file if it exceeds MAX_FILE_BYTES."""
    try:
        if EVENT_FILE.exists() and EVENT_FILE.stat().st_size >= MAX_FILE_BYTES:
            rotated = TELEMETRY_DIR / "events.jsonl.1"
            if rotated.exists():
                rotated.unlink()
            EVENT_FILE.replace(rotated)
    except Exception:
        pass


def _get_virgo_version() -> str:
    try:
        from cli import VERSION  # noqa: PLC0415
        return str(VERSION)
    except Exception:
        return "0.0.0"


def track(
    event: str,
    *,
    page_id: str = "",
    tool_id: str = "",
    duration_ms: float = 0.0,
    success: bool = True,
    extra: dict | None = None,
) -> None:
    """Record a single telemetry event."""
    if not _is_enabled():
        return
    if event not in _VALID_EVENTS:
        return
    try:
        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed()
        record = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "page_id": page_id or "",
            "tool_id": tool_id or "",
            "duration_ms": duration_ms,
            "success": success,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "virgo_version": _get_virgo_version(),
        }
        if extra and isinstance(extra, dict):
            record.update(extra)
        with EVENT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def summary() -> str:
    """Return a human-readable summary of recorded events."""
    try:
        if not EVENT_FILE.exists():
            return "No telemetry data recorded."
        counts: dict[str, int] = {}
        total = 0
        with EVENT_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ev = rec.get("event", "unknown")
                counts[ev] = counts.get(ev, 0) + 1
                total += 1
        lines = [f"Telemetry events: {total}"]
        for ev in sorted(counts):
            lines.append(f"  {ev}: {counts[ev]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error reading telemetry: {exc}"


def export_to(dest: str | Path) -> str:
    """Copy the event file to dest. Returns a status string."""
    dest = Path(dest)
    try:
        if not EVENT_FILE.exists():
            return "No telemetry data to export."
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(EVENT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        return f"Exported {EVENT_FILE.stat().st_size} bytes to {dest}"
    except Exception as exc:
        return f"Export failed: {exc}"


def purge() -> str:
    """Delete all stored telemetry events. Returns a status string."""
    try:
        if not EVENT_FILE.exists():
            return "No telemetry data to purge."
        size = EVENT_FILE.stat().st_size
        EVENT_FILE.unlink()
        return f"Purged {size} bytes of telemetry data."
    except Exception as exc:
        return f"Purge failed: {exc}"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Virgo telemetry manager")
    parser.add_argument("command", choices=["summary", "export", "purge"])
    parser.add_argument("path", nargs="?", default=".", help="Destination for export")
    args = parser.parse_args()

    if args.command == "summary":
        print(summary())
    elif args.command == "export":
        print(export_to(args.path))
    elif args.command == "purge":
        print(purge())


if __name__ == "__main__":
    main()

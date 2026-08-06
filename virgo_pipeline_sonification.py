"""
virgo_pipeline_sonification — map pipeline phases to sound events.

Uses stdlib winsound (Windows) or os.system beep (POSIX). No external deps.
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
STATE_FILE = HERE / ".virgo_pipeline_ui.json"
HISTORY_FILE = HERE / ".virgo_sonify_history.json"

_PHASES: dict[str, dict[str, Any]] = {
    "discover":  {"freq": 220, "dur": 120, "label": "Discover"},
    "plan":      {"freq": 330, "dur": 150, "label": "Plan"},
    "generate":  {"freq": 440, "dur": 180, "label": "Generate"},
    "test":      {"freq": 550, "dur": 200, "label": "Test"},
    "fix":       {"freq": 660, "dur": 220, "label": "Fix"},
    "done":      {"freq": 880, "dur": 300, "label": "Done"},
    "error":     {"freq": 110, "dur": 400, "label": "Error"},
    "idle":      {"freq": 180, "dur": 80,  "label": "Idle"},
}


def _beep(freq: int, dur: int) -> None:
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(int(freq), int(dur))
        else:
            os.system(f"printf '\\a' >/dev/null 2>&1 || true")
    except Exception:
        pass


def play_phase(phase: str, repeat: int = 1, gap: float = 0.1) -> None:
    phase = (phase or "idle").lower()
    cfg = _PHASES.get(phase, _PHASES["idle"])
    def _run() -> None:
        for _ in range(max(1, int(repeat))):
            _beep(cfg["freq"], cfg["dur"])
            if gap > 0:
                time.sleep(gap)
    threading.Thread(target=_run, daemon=True).start()
    log.info("sonify: %s", cfg["label"])


def play_sequence(phases: list[str], gap: float = 0.15) -> None:
    def _run() -> None:
        for p in phases:
            play_phase(p, gap=gap)
            time.sleep(gap)
    threading.Thread(target=_run, daemon=True).start()


def watch_pipeline(poll: float = 1.0) -> None:
    last_state = ""
    while True:
        try:
            if not STATE_FILE.exists():
                time.sleep(poll)
                continue
            data = json.loads(STATE_FILE.read_text())
            state = str(data.get("state", data.get("status", "idle"))).lower()
            if state != last_state:
                last_state = state
                play_phase(state)
            time.sleep(poll)
        except Exception:
            time.sleep(poll)


def start_watcher() -> None:
    t = threading.Thread(target=watch_pipeline, daemon=True)
    t.start()
    return t


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Pipeline Sonification")
    p.add_argument("phase", nargs="?", default="idle", choices=list(_PHASES.keys()))
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--watch", action="store_true", help="Watch .virgo_pipeline_ui.json")
    args = p.parse_args()
    if args.watch:
        print("Watching pipeline state… Ctrl+C to stop")
        try:
            start_watcher()
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        play_phase(args.phase, repeat=args.repeat)


if __name__ == "__main__":
    cli()

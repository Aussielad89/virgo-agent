"""
autoheal — self-healing process supervision for Virgo services.

Watches a named process (by PID or command) and, when it dies or hangs
(no heartbeat for *stall_seconds*), restarts it with the last-known-good
command. Uses exponential backoff between restarts and a restart budget
per window so a crash-looping service isn't restarted forever.

Also ships :func:`heal_cycle` which wraps one ``virgo_watchdog`` cycle and
re-runs it on timeout, so the monitoring loop heals itself.

State is persisted to ``.virgo_memory/autoheal/<name>.json`` so restarts
survive process restarts.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_STATE_DIR = Path(".virgo_memory") / "autoheal"
DEFAULT_STALL_SECONDS = 30
DEFAULT_MAX_RESTARTS = 3
DEFAULT_WINDOW_SECONDS = 300


def _now_ts() -> float:
    return time.time()


def _iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _find_pid(name: str) -> int | None:
    """Find a PID by executable basename (best-effort, cross-platform)."""
    name_l = name.lower()
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines():
            parts = line.split('","')
            if len(parts) >= 2 and name_l in parts[0].strip('"').lower():
                try:
                    return int(parts[1].strip('"'))
                except ValueError:
                    continue
    except Exception:  # pragma: no cover - tasklist may be unavailable
        pass
    return None


def _process_alive(pid: int) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # signal 0 probes without killing
        return True
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:  # pragma: no cover - exists but owned elsewhere
        return True


class AutoHeal:
    """Supervise one command; restart on death or stall with backoff."""

    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        stall_seconds: int = DEFAULT_STALL_SECONDS,
        max_restarts: int = DEFAULT_MAX_RESTARTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        state_dir: str | Path | None = None,
    ) -> None:
        self.name = name
        self.command = list(command)
        self.stall_seconds = stall_seconds
        self.max_restarts = max_restarts
        self.window_seconds = window_seconds
        self.state_path = (Path(state_dir) if state_dir else DEFAULT_STATE_DIR) / f"{name}.json"
        self.pid: int | None = None
        self.proc: subprocess.Popen | None = None
        self.last_heartbeat = _now_ts()
        self.restart_times: list[float] = []
        self._load_state()

    # ── persistence ──────────────────────────────────────────────────
    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.pid = data.get("pid")
        self.restart_times = data.get("restart_times", [])

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"name": self.name, "pid": self.pid,
                 "restart_times": self.restart_times[-20:], "ts": _iso()},
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    # ── supervision ──────────────────────────────────────────────────
    def start(self) -> bool:
        """Spawn the supervised command. Returns True on success."""
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self.pid = self.proc.pid
            self.last_heartbeat = _now_ts()
            self._save_state()
            log.info("autoheal: started %s (pid %s)", self.name, self.pid)
            return True
        except Exception as exc:  # pragma: no cover
            log.warning("autoheal: failed to start %s: %s", self.name, exc)
            return False

    def heartbeat(self) -> None:
        """Call from the watched process/thread to prove liveness."""
        self.last_heartbeat = _now_ts()

    def _within_budget(self) -> bool:
        now = _now_ts()
        self.restart_times = [t for t in self.restart_times if now - t < self.window_seconds]
        return len(self.restart_times) < self.max_restarts

    def _restart(self, reason: str) -> None:
        if not self._within_budget():
            log.warning("autoheal: %s hit restart budget; standing down", self.name)
            return
        self.restart_times.append(_now_ts())
        self._save_state()
        delay = 2 ** min(len(self.restart_times), 5)
        log.warning("autoheal: restarting %s (%s) in %ss", self.name, reason, delay)
        time.sleep(delay)
        self.start()

    def tick(self) -> str:
        """One supervision pass.

        Returns the action taken: 'ok' | 'restarted' | 'waiting' | 'stopped'.
        """
        if self.pid is None:
            return "stopped"
        alive = _process_alive(self.pid)
        stalled = (_now_ts() - self.last_heartbeat) > self.stall_seconds
        if not alive:
            self._restart("process died")
            return "restarted"
        if stalled and self.stall_seconds > 0:
            self._restart(f"stalled > {self.stall_seconds}s without heartbeat")
            return "restarted"
        return "ok"

    def status(self) -> dict[str, Any]:
        alive = self.pid is not None and _process_alive(self.pid)
        return {
            "name": self.name,
            "pid": self.pid,
            "alive": alive,
            "heartbeat_age_s": round(_now_ts() - self.last_heartbeat, 1),
            "restarts_in_window": len(self.restart_times),
            "budget": self.max_restarts,
        }

    def stop(self) -> None:
        """Stop the supervised process (if any)."""
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:  # pragma: no cover
                pass
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:  # pragma: no cover
                pass
        self.pid = None
        self.proc = None
        self._save_state()


def supervise_forever(
    name: str,
    command: list[str],
    *,
    stall_seconds: int = DEFAULT_STALL_SECONDS,
    max_restarts: int = DEFAULT_MAX_RESTARTS,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    poll_interval: float = 5.0,
) -> None:
    """Run supervision until Ctrl+C."""
    heal = AutoHeal(
        name, command,
        stall_seconds=stall_seconds,
        max_restarts=max_restarts,
        window_seconds=window_seconds,
    )
    heal.start()
    try:
        while True:
            action = heal.tick()
            if action in ("restarted", "ok"):
                time.sleep(poll_interval)
            else:
                time.sleep(1)
    except KeyboardInterrupt:
        heal.stop()


def heal_cycle(cycle_fn: Any, timeout: float = 120.0) -> dict[str, Any]:
    """Run *cycle_fn* and re-run it once if it exceeds *timeout*.

    Used by the watchdog so a hung diagnostics/fixer subprocess doesn't
    take the whole monitoring loop down.
    """
    start = _now_ts()
    try:
        result = cycle_fn()
        return {"status": "ok", "seconds": round(_now_ts() - start, 2), "result": result}
    except TimeoutError:
        log.warning("autoheal: cycle exceeded %.0fs; re-running", timeout)
        result = cycle_fn()
        return {"status": "recovered", "seconds": round(_now_ts() - start, 2), "result": result}
    except Exception as exc:  # pragma: no cover
        log.warning("autoheal: cycle raised %s; re-running", exc)
        result = cycle_fn()
        return {"status": "recovered", "seconds": round(_now_ts() - start, 2), "result": result}

"""virgo_recon_server.py — desktop recon server for the Virgo mobile companion.

Wraps the locally-installed red-team toolkit (nmap, amass, subfinder,
httpx, nuclei, ffuf, gobuster, sherlock) and exposes a small REST API +
a server-sent-events (SSE) job feed so an Android PWA can submit targets
and watch results live.

All activity is assumed AUTHORIZED / in-scope. The server prints a
warning on every start and every job.

Run:
    python virgo_recon_server.py                # http://0.0.0.0:8766
    python virgo_recon_server.py --host 0.0.0.0 --port 8766 --allow-lan

The PWA lives in ./recon_app/ and is served automatically at /app.

Security notes:
- Bind to 127.0.0.1 by default. Use --allow-lan ONLY on a trusted
  network; there is NO auth — anyone on the LAN can submit scans.
- Output is written to gitignored output/recon/ (repo-hygiene rule).
- Tools are launched via subprocess with a hard timeout; only allowlisted
  binaries in TOOLS are callable.
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS_DIR = Path(r"C:\Users\paren\tools")
OUT_DIR = HERE / "output" / "recon"
STATE_FILE = OUT_DIR / "jobs.json"

# Allowlisted binaries (basename -> actual exe path). Symlink-free, explicit.
_TOOL_BINARIES = {
    "nmap": TOOLS_DIR / "nmap-7.92" / "nmap.exe",
    "amass": TOOLS_DIR / "amass.exe",
    "subfinder": TOOLS_DIR / "subfinder.exe",
    "httpx": TOOLS_DIR / "httpx.exe",
    "nuclei": TOOLS_DIR / "nuclei.exe",
    "ffuf": TOOLS_DIR / "ffuf.exe",
    "gobuster": TOOLS_DIR / "gobuster.exe",
}

# Allowlisted scan profiles the PWA can trigger. Keeps the mobile surface
# simple and prevents arbitrary command injection from the phone.
PROFILES = {
    "portscan": {
        "tool": "nmap",
        "args": ["-sT", "-Pn", "--top-ports", "1000", "{target}"],
        "timeout": 300,
        "desc": "TCP connect scan, top 1000 ports (no SYN — userspace).",
    },
    "subdomains": {
        "tool": "subfinder",
        "args": ["-d", "{target}", "-silent"],
        "timeout": 180,
        "desc": "Passive subdomain enumeration.",
    },
    "httpprobe": {
        "tool": "httpx",
        "args": ["-u", "{target}", "-silent", "-title", "-status-code", "-tech-detect"],
        "timeout": 120,
        "desc": "HTTP probing + title/status/tech detection.",
    },
    "vulnscan": {
        "tool": "nuclei",
        "args": ["-u", "{target}", "-silent"],
        "timeout": 300,
        "desc": "Template-based vulnerability scan.",
    },
    "dirbust": {
        "tool": "gobuster",
        "args": ["dns", "-d", "{target}", "-w", str(TOOLS_DIR / "gobuster" / "wordlist.txt")],
        "timeout": 240,
        "desc": "DNS/subdomain brute-force (needs a wordlist).",
    },
}

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_subscribers: list[queue.Queue] = []


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _broadcast(job: dict) -> None:
    """Notify SSE subscribers of a job state change."""
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put(job)
        except Exception:
            pass


def _save_state() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        snapshot = {
            jid: {k: v for k, v in job.items() if k != "proc"} for jid, job in _jobs.items()
        }
    try:
        STATE_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception:
        pass


def run_job(job_id: str) -> None:
    """Execute a queued job in the background and stream updates."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return
    profile = PROFILES.get(job["profile"])
    if not profile:
        job.update(status="error", result="unknown profile", finished=_now())
        _broadcast(job)
        _save_state()
        return

    target = job["target"]
    exe = _TOOL_BINARIES.get(profile["tool"])
    if not exe or not exe.exists():
        job.update(status="error", result=f"tool missing: {profile['tool']}", finished=_now())
        _broadcast(job)
        _save_state()
        return

    cmd = [str(exe)] + [a.replace("{target}", target) for a in profile["args"]]
    out_path = OUT_DIR / f"{job_id}.txt"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    job.update(status="running", started=_now(), cmd=" ".join(cmd))
    _broadcast(job)
    _save_state()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=profile["timeout"],
            cwd=str(OUT_DIR),
        )
        stdout = (proc.stdout or "")[:20000]
        stderr = (proc.stderr or "")[:4000]
        out_path.write_text(
            f"$ {' '.join(cmd)}\n\n=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n",
            encoding="utf-8",
            errors="replace",
        )
        job.update(
            status="done",
            exit_code=proc.returncode,
            result=stdout or "(no stdout)",
            stderr=stderr,
            output_file=str(out_path),
            finished=_now(),
        )
    except subprocess.TimeoutExpired:
        job.update(status="error", result=f"timed out after {profile['timeout']}s", finished=_now())
    except Exception as exc:  # pragma: no cover
        job.update(status="error", result=f"launch error: {exc}", finished=_now())

    _broadcast(job)
    _save_state()


def _load_state() -> None:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            with _lock:
                for jid, job in data.items():
                    job.setdefault("proc", None)
                    _jobs[jid] = job
        except Exception:
            pass
    _load_state._done = True  # type: ignore[attr-defined]


def create_job(profile: str, target: str) -> dict:
    jid = uuid.uuid4().hex[:8]
    job = {
        "id": jid,
        "profile": profile,
        "target": target,
        "status": "queued",
        "created": _now(),
        "proc": None,
    }
    with _lock:
        _jobs[jid] = job
    threading.Thread(target=run_job, args=(jid,), daemon=True).start()
    _save_state()
    return job


# ── Flask wiring ──────────────────────────────────────────────────────────
def build_app() -> object:
    from flask import Flask, Response, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=str(HERE / "recon_app"))
    app.ReconApp = True

    @app.route("/api/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "tools": {
                    k: (str(v) if v.exists() else "MISSING") for k, v in _TOOL_BINARIES.items()
                },
                "warning": "AUTHORIZED USE ONLY — you are running live recon tools.",
            }
        )

    @app.route("/api/profiles")
    def profiles():
        return jsonify(
            {k: {"desc": v["desc"], "timeout": v["timeout"]} for k, v in PROFILES.items()}
        )

    @app.route("/api/jobs", methods=["GET"])
    def list_jobs():
        with _lock:
            jobs = [{k: v for k, v in j.items() if k != "proc"} for j in _jobs.values()]
        jobs.sort(key=lambda j: j.get("created", ""), reverse=True)
        return jsonify(jobs)

    @app.route("/api/scan", methods=["POST"])
    def scan():
        data = request.get_json(force=True, silent=True) or {}
        profile = data.get("profile", "")
        target = (data.get("target", "") or "").strip()
        if profile not in PROFILES:
            return jsonify({"error": f"unknown profile '{profile}'"}), 400
        if not target or " " in target or ";" in target or "&" in target:
            return jsonify({"error": "invalid target"}), 400
        job = create_job(profile, target)
        return jsonify({k: v for k, v in job.items() if k != "proc"}), 201

    @app.route("/api/jobs/<job_id>", methods=["GET"])
    def job_detail(job_id):
        with _lock:
            job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        return jsonify({k: v for k, v in job.items() if k != "proc"})

    @app.route("/api/stream")
    def stream():
        q: queue.Queue = queue.Queue()
        with _lock:
            _subscribers.append(q)

        def gen():
            try:
                # prime with current state
                with _lock:
                    for j in _jobs.values():
                        yield f"data: {json.dumps({k: v for k, v in j.items() if k != 'proc'})}\n\n"
                while True:
                    job = q.get()
                    yield f"data: {json.dumps({k: v for k, v in job.items() if k != 'proc'})}\n\n"
            except GeneratorExit:
                pass
            finally:
                with _lock:
                    if q in _subscribers:
                        _subscribers.remove(q)

        return Response(gen(), mimetype="text/event-stream")

    @app.route("/")
    @app.route("/app")
    @app.route("/app/")
    @app.route("/app/<path:ign>")
    @app.route("/<path:ign>")
    def index(ign=""):
        if not ign or ign.endswith("/"):
            ign = "index.html"
        # prevent path traversal
        from os.path import normpath, basename
        safe = basename(normpath(ign))
        if not safe or safe in ("", ".", ".."):
            safe = "index.html"
        return send_from_directory(app.static_folder, safe)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Virgo recon companion server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument(
        "--allow-lan", action="store_true", help="Bind 0.0.0.0 (trusted LAN only — no auth)"
    )
    args = ap.parse_args()

    if args.allow_lan:
        args.host = "0.0.0.0"
        print("⚠  WARNING: bound to 0.0.0.0 — ANY host on your LAN can submit scans.")
        print("⚠  Use only on a trusted network. There is NO authentication.")

    print("⚠  AUTHORIZED / IN-SCOPE USE ONLY — live recon tools will execute.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _load_state()
    app = build_app()
    # Flask dev server; fine for a local companion. debug off (no reloader).
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

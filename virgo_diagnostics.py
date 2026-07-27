"""
virgo_diagnostics — live system health for the Virgo agent environment.

Reports CPU/memory/disk usage, running processes, network interfaces,
Ollama/service status, and GPU (if available). Used by the desktop
DiagnosticsPage for real-time monitoring.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import OUTDIR

REPORT_FILE = OUTDIR / "virgo_diagnostics.json"


def get_system_stats() -> dict:
    """Return a dict of current system health metrics."""
    stats: dict = {
        "timestamp": datetime.now().isoformat(),
        "os": f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "cpu": {},
        "memory": {},
        "disk": {},
        "network": [],
        "services": {},
        "processes": [],
        "ollama": {},
    }

    # CPU
    try:
        import psutil
        stats["cpu"]["percent"] = psutil.cpu_percent(interval=0.5)
        stats["cpu"]["count"] = psutil.cpu_count()
        stats["cpu"]["freq_mhz"] = round(psutil.cpu_freq().current, 1) if psutil.cpu_freq() else None
    except Exception:
        stats["cpu"]["error"] = "psutil not available"

    # Memory
    try:
        mem = psutil.virtual_memory()
        stats["memory"]["total_gb"] = round(mem.total / 1024**3, 1)
        stats["memory"]["used_gb"] = round(mem.used / 1024**3, 1)
        stats["memory"]["percent"] = mem.percent
    except Exception:
        pass

    # Disk
    try:
        for part in psutil.disk_partitions():
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    stats["disk"].append({
                        "mount": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / 1024**3, 1),
                        "used_gb": round(usage.used / 1024**3, 1),
                        "percent": usage.percent,
                    })
                except Exception:
                    pass
    except Exception:
        pass

    # Network interfaces
    try:
        addrs = psutil.net_if_addrs()
        for name, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family == socket.AF_INET:  # IPv4
                    stats["network"].append({"interface": name, "ip": addr.address})
    except Exception:
        pass

    # Top processes by memory
    try:
        for proc in sorted(psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]),
                           key=lambda p: p.info.get("memory_percent", 0) or 0, reverse=True)[:10]:
            stats["processes"].append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "mem_pct": round(proc.info.get("memory_percent", 0) or 0, 1),
                "cpu_pct": round(proc.info.get("cpu_percent", 0) or 0, 1),
            })
    except Exception:
        pass

    # Services: check if key processes are running
    service_ports = {
        "Ollama": 11434,
        "Virgo Pipeline": None,  # check process
    }
    for svc_name, port in service_ports.items():
        if port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                result = sock.connect_ex(("127.0.0.1", port))
                stats["services"][svc_name] = "running" if result == 0 else "stopped"
            except Exception:
                stats["services"][svc_name] = "error"
            finally:
                sock.close()
        else:
            stats["services"][svc_name] = "checking"

    # Ollama model list
    try:
        import urllib.request
        raw = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3).read()
        data = json.loads(raw)
        models = [m["name"] for m in data.get("models", [])]
        stats["ollama"]["models"] = models
        stats["ollama"]["model_count"] = len(models)
    except Exception:
        stats["ollama"]["error"] = "unreachable"

    return stats


def format_report(stats: dict) -> str:
    """Format stats as a human-readable report string."""
    lines = [
        f"═══ System Health Report ═══",
        f"Host: {stats['hostname']}  |  OS: {stats['os']}",
        f"Time: {stats['timestamp']}",
        "",
    ]

    # CPU
    cpu = stats.get("cpu", {})
    if "error" not in cpu:
        freq = f" @ {cpu['freq_mhz']}MHz" if cpu.get("freq_mhz") else ""
        lines.append(f"CPU: {cpu.get('percent', '?')}%  ({cpu.get('count', '?')} cores{freq})")
    else:
        lines.append(f"CPU: {cpu['error']}")

    # Memory
    mem = stats.get("memory", {})
    if mem:
        lines.append(f"RAM: {mem['percent']}%  ({mem['used_gb']} / {mem['total_gb']} GB)")

    # Disk
    for disk in stats.get("disk", []):
        lines.append(f"DISK {disk['mount']}: {disk['percent']}%  ({disk['used_gb']} / {disk['total_gb']} GB)")

    # Network
    lines.append("")
    lines.append("─── Network ───")
    for iface in stats.get("network", []):
        lines.append(f"  {iface['interface']}: {iface['ip']}")
    if not stats.get("network"):
        lines.append("  (none)")

    # Services
    lines.append("")
    lines.append("─── Services ───")
    for svc, status in stats.get("services", {}).items():
        icon = "🟢" if status == "running" else "🔴"
        lines.append(f"  {icon} {svc}: {status}")

    # Ollama
    ollama = stats.get("ollama", {})
    if "error" not in ollama:
        lines.append(f"  🟢 Ollama: {ollama.get('model_count', 0)} models pulled")
    else:
        lines.append(f"  🔴 Ollama: {ollama['error']}")

    # Top processes
    lines.append("")
    lines.append("─── Top Processes (by memory) ───")
    for p in stats.get("processes", [])[:8]:
        lines.append(f"  {p['pid']:>6}  {p['name']:<20}  mem={p['mem_pct']}%  cpu={p['cpu_pct']}%")
    if not stats.get("processes"):
        lines.append("  (psutil not available)")

    return "\n".join(lines)

"""
sysinfo_plugin — system information tools.

Provides tool_* functions for CPU, RAM, disk, and general system info.
Uses psutil when available, falls back to os/procfs for minimal deps.
"""

from __future__ import annotations

import os
import platform
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── Optional psutil ──────────────────────────────────────────────────────

try:
    import psutil as _psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ── Startup timestamp (for uptime fallback) ──────────────────────────────

_start_time = time.time()


# ── Helpers ──────────────────────────────────────────────────────────────


def _read_proc(path: str) -> str:
    """Read a /proc file and return its content stripped, or ''."""
    try:
        return Path(path).read_text().strip()
    except (OSError, FileNotFoundError):
        return ""


def _parse_proc_stat() -> dict[str, float]:
    """Parse /proc/stat for CPU totals (fallback when psutil is missing).

    Returns a dict with keys ``user``, ``nice``, ``system``, ``idle``,
    ``iowait``, ``irq``, ``softirq``, ``steal``, ``guest``, ``guest_nice``.
    On any failure all values are 0.
    """
    line = _read_proc("/proc/stat")
    if not line.startswith("cpu "):
        return {}
    parts = line.split()
    # parts[0] is "cpu", the rest are the 10 tick counters
    keys = ["user", "nice", "system", "idle", "iowait", "irq", "softirq",
            "steal", "guest", "guest_nice"]
    values: dict[str, float] = {}
    for i, key in enumerate(keys):
        try:
            values[key] = float(parts[i + 1]) if i + 1 < len(parts) else 0.0
        except (ValueError, IndexError):
            values[key] = 0.0
    return values


def _parse_proc_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo for memory totals (fallback).

    Returns a dict with keys like ``MemTotal``, ``MemAvailable``, ``MemFree``
    (values in kilobytes).  On failure returns empty dict.
    """
    text = _read_proc("/proc/meminfo")
    if not text:
        return {}
    info: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        # strip " kB" suffix
        val = rest.strip().split()[0] if rest.strip() else "0"
        try:
            info[key] = int(val)
        except ValueError:
            info[key] = 0
    return info


def _format_bytes(n: int) -> str:
    """Format a byte count to a human-readable string."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if isinstance(n, float) else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PiB"


def _format_uptime(seconds: float) -> str:
    """Format *seconds* as a human-friendly duration string."""
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


# ── Tool functions ───────────────────────────────────────────────────────


def tool_cpu_usage() -> str:
    """Return current CPU utilisation as a formatted string.

    Uses psutil when available; falls back to parsing ``/proc/stat``
    (Linux) or returns an 'unavailable' message on unsupported platforms.
    """
    if _HAS_PSUTIL:
        percent = _psutil.cpu_percent(interval=0.5)
        logical = _psutil.cpu_count(logical=True)
        physical = _psutil.cpu_count(logical=False) or "?"
        return (
            f"CPU: {percent:.1f}%  "
            f"({logical} logical / {physical} physical cores)"
        )

    # Fallback: parse /proc/stat (Linux)
    before = _parse_proc_stat()
    if not before:
        return "CPU: unavailable (unsupported platform, install psutil)"

    time.sleep(0.5)
    after = _parse_proc_stat()
    if not after:
        return "CPU: unavailable (failed to read /proc/stat)"

    # Compute deltas
    total_before = sum(before.values())
    total_after = sum(after.values())
    idle_before = before.get("idle", 0)
    idle_after = after.get("idle", 0)

    delta_total = total_after - total_before
    delta_idle = idle_after - idle_before

    if delta_total <= 0:
        return "CPU: 0.0%"

    percent = (1.0 - delta_idle / delta_total) * 100.0
    return f"CPU: {percent:.1f}%"


def tool_ram_usage() -> str:
    """Return RAM used / total as a formatted string.

    Uses psutil when available; falls back to ``/proc/meminfo`` (Linux)
    or returns an 'unavailable' message.
    """
    if _HAS_PSUTIL:
        mem = _psutil.virtual_memory()
        used = mem.total - mem.available
        return (
            f"RAM: {_format_bytes(used)} used / {_format_bytes(mem.total)} total "
            f"({mem.percent:.1f}%)"
        )

    # Fallback: /proc/meminfo
    info = _parse_proc_meminfo()
    total_kb = info.get("MemTotal", 0)
    avail_kb = info.get("MemAvailable", 0)
    if total_kb <= 0:
        return "RAM: unavailable (unsupported platform, install psutil)"
    used_kb = total_kb - avail_kb
    percent = (used_kb / total_kb) * 100.0 if total_kb else 0.0
    return (
        f"RAM: {_format_bytes(used_kb * 1024)} used / "
        f"{_format_bytes(total_kb * 1024)} total "
        f"({percent:.1f}%)"
    )


def tool_disk_usage(path: str = "C:") -> str:
    """Return disk free / total for a given path (default ``C:``).

    Uses psutil when available; falls back to ``os.statvfs`` (Unix) or
    ``shutil.disk_usage`` (Python 3.3+).
    """
    # Normalise: C: → C:\ for Windows, else keep as-is
    target = path if os.name == "nt" and path.endswith(":") else path

    if _HAS_PSUTIL:
        try:
            du = _psutil.disk_usage(target)
        except PermissionError:
            return f"Disk ({path}): permission denied"
        except FileNotFoundError:
            return f"Disk ({path}): path not found"
        percent = du.used / du.total * 100.0 if du.total else 0.0
        return (
            f"Disk ({path}): "
            f"{_format_bytes(du.free)} free / {_format_bytes(du.total)} total "
            f"({percent:.1f}% used)"
        )

    # Fallback: shutil.disk_usage (stdlib, Python 3.3+)
    try:
        import shutil

        du = shutil.disk_usage(target)
    except (ImportError, PermissionError, FileNotFoundError, OSError):
        return f"Disk ({path}): unavailable (install psutil)"

    percent = du.used / du.total * 100.0 if du.total else 0.0
    return (
        f"Disk ({path}): "
        f"{_format_bytes(du.free)} free / {_format_bytes(du.total)} total "
        f"({percent:.1f}% used)"
    )


def tool_system_info() -> str:
    """Return OS, hostname, Python version, and uptime."""
    os_name = platform.system()
    os_release = platform.release()
    os_version = platform.version()
    hostname = platform.node()
    py_impl = platform.python_implementation()
    py_version = platform.python_version()

    # Uptime
    if _HAS_PSUTIL:
        uptime_secs = time.time() - _psutil.boot_time()
    else:
        # Fallback: process start time
        uptime_secs = time.time() - _start_time

    return (
        f"OS:          {os_name} {os_release} ({os_version})\n"
        f"Hostname:    {hostname}\n"
        f"Python:      {py_impl} {py_version}\n"
        f"Uptime:      {_format_uptime(uptime_secs)}"
    )


# ── Register function (optional — tool_* are auto-detected) ──────────────

def register(registry: object) -> None:
    """Register sysinfo tools with the provided *registry*.

    This function is optional — the plugin loader also discovers
    ``tool_*`` functions automatically.  Providing ``register``
    allows explicit control over tool naming or filtering.
    """
    from tools import Tool

    registry.register(Tool("system info", tool_system_info, tool_system_info.__doc__))
    registry.register(Tool("cpu usage", tool_cpu_usage, tool_cpu_usage.__doc__))
    registry.register(Tool("ram usage", tool_ram_usage, tool_ram_usage.__doc__))
    registry.register(Tool("disk usage", tool_disk_usage, tool_disk_usage.__doc__))

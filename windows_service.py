"""nssm service manager wrapper."""

import subprocess
from typing import Any


def _run(args: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        return {
            "command": " ".join(args),
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {
            "command": " ".join(args),
            "returncode": -1,
            "stdout": "",
            "stderr": "nssm executable not found",
        }
    except Exception as exc:
        return {
            "command": " ".join(args),
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def install(service_name: str, executable: str, args: list[str] | None = None) -> dict[str, Any]:
    args_list = ["nssm", "install", service_name, executable]
    if args:
        args_list.extend(args)
    return _run(args_list)


def remove(service_name: str) -> dict[str, Any]:
    return _run(["nssm", "remove", service_name, "confirm"])


def start(service_name: str) -> dict[str, Any]:
    return _run(["nssm", "start", service_name])


def stop(service_name: str) -> dict[str, Any]:
    return _run(["nssm", "stop", service_name])


def status(service_name: str) -> dict[str, Any]:
    return _run(["nssm", "status", service_name])

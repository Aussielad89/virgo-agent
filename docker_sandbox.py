"""
docker_sandbox — execute commands inside a throwaway container.

For untrusted code the allowlist sandbox is not enough: the command still
runs with the host's filesystem and privileges. This module runs commands
in an ephemeral Docker container (``docker run --rm``), mounting the
project directory read-only by default so results can be captured without
letting the container mutate the host.

Requires a working ``docker`` CLI. When Docker is unavailable the module
fails loudly with instructions rather than silently running on the host.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_IMAGE = "python:3.11-slim"
DEFAULT_TIMEOUT = 60


class DockerUnavailable(RuntimeError):
    """Raised when the docker CLI is missing or the daemon is down."""


def docker_available() -> bool:
    """True when the docker CLI exists and responds to ``docker version``."""
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False


class DockerSandbox:
    """Run commands in an ephemeral container with a read-only mount."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        timeout: int = DEFAULT_TIMEOUT,
        mount: str | Path | None = None,
        mount_target: str = "/workspace",
        read_only: bool = True,
    ) -> None:
        self.image = image
        self.timeout = timeout
        self.mount = str(mount or Path.cwd())
        self.mount_target = mount_target
        self.read_only = read_only

    def run(self, cmd: list[str] | str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
        """Run *cmd* inside a fresh container.

        Returns {"returncode", "stdout", "stderr"}.
        Raises DockerUnavailable when docker is not usable.
        """
        if not docker_available():
            raise DockerUnavailable(
                "Docker is not available. Install Docker Desktop / the docker "
                "CLI and ensure the daemon is running, or drop --docker."
            )
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)

        argv = [
            "docker", "run", "--rm",
            "-v", f"{self.mount}:{self.mount_target}:{'ro' if self.read_only else 'rw'}",
            "-w", self.mount_target,
        ]
        for key, val in (env or {}).items():
            argv += ["-e", f"{key}={val}"]
        argv += [self.image] + cmd

        log.info("docker_sandbox: %s", " ".join(argv))
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "returncode": -1,
                "stdout": exc.stdout or "",
                "stderr": f"container command timed out after {self.timeout}s",
            }
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }

    def run_capture(self, cmd: list[str] | str, *, env: dict[str, str] | None = None) -> str:
        """Convenience: return combined stdout/stderr text (like run_sandboxed)."""
        out = self.run(cmd, env=env)
        text = out["stdout"]
        if out["stderr"]:
            text += ("\n" + out["stderr"]) if text else out["stderr"]
        if out["returncode"] not in (0, None):
            text += f"\n[exit code {out['returncode']}]"
        return text or "(no output)"


def run_sandboxed_docker(
    cmd: list[str] | str,
    image: str = DEFAULT_IMAGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Drop-in sandbox-style runner: ``cmd`` inside a container.

    Raises ValueError when Docker is unavailable (mirrors the allowlist
    sandbox's "blocked" semantics so the agent sees a clear error).
    """
    try:
        return DockerSandbox(image=image, timeout=timeout).run_capture(cmd)
    except DockerUnavailable as exc:
        raise ValueError(f"Blocked by docker sandbox: {exc}") from exc

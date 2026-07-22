"""
AgentEnvironment — isolated virtual environment manager.

Creates and manages an ``agent_env`` venv inside the workspace,
providing dynamic pip install, script execution, and code-file
validation through the isolated Python interpreter.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import venv
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_DIR_NAME = "agent_env"


def _bin_subdir() -> str:
    """Return the platform-specific script subdirectory name."""
    return "Scripts" if sys.platform == "win32" else "bin"


# ===========================================================================
# Environment manager
# ===========================================================================


class AgentEnvironment:
    """Manage an isolated ``agent_env`` virtual environment.

    Typical usage::

        env = AgentEnvironment().setup()
        env.install("pandas", "requests")
        proc = env.run("import requests; print(requests.__version__)")
        print(proc.stdout)
    """

    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or os.getcwd()).resolve()
        self.env_dir = self.base_path / ENV_DIR_NAME
        self._python: Path | None = None
        self._ready = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def python(self) -> Path:
        """Path to the isolated Python executable."""
        if self._python is None:
            self._python = self.env_dir / _bin_subdir() / "python.exe"
        return self._python

    @property
    def is_ready(self) -> bool:
        """``True`` if the environment exists and has a Python executable."""
        return self.env_dir.is_dir() and self.python.is_file()

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def setup(self, recreate: bool = False) -> AgentEnvironment:
        """Create the virtual environment if it doesn't exist.

        If *recreate* is ``True`` any existing ``agent_env`` directory
        is deleted first.
        """
        if self.env_dir.exists():
            if recreate:
                shutil.rmtree(self.env_dir)
            else:
                self._ready = self.is_ready
                return self

        venv.create(str(self.env_dir), with_pip=True, clear=False)
        self._ready = self.is_ready
        if not self._ready:
            raise RuntimeError(f"Failed to create virtual environment at {self.env_dir}")
        return self

    def teardown(self) -> None:
        """Remove the virtual environment and all installed packages."""
        if self.env_dir.exists():

            def _onerror(func, path, exc_info):
                # Windows permission errors on __pycache__ — retry after chmod
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass

            shutil.rmtree(self.env_dir, onerror=_onerror)
        self._python = None
        self._ready = False

    # ------------------------------------------------------------------
    # Package management
    # ------------------------------------------------------------------

    def install(self, *packages: str, quiet: bool = False) -> str:
        """Install one or more packages via pip.

        Returns combined stdout/stderr on success.
        """
        self._ensure_ready()
        cmd = [str(self.python), "-m", "pip", "install"]
        if quiet:
            cmd.append("-q")
        cmd.extend(packages)
        return self._check(*cmd)

    def ensure(self, *packages: str, quiet: bool = True) -> str:
        """Install packages only if they are not already present."""
        self._ensure_ready()
        missing: list[str] = []
        for pkg in packages:
            # Normalise a possible version spec (e.g. "pandas>=2.0")
            name = re.split(r"[<>!=~]", pkg)[0].strip()
            rc = subprocess.run(
                [str(self.python), "-m", "pip", "show", name],
                capture_output=True,
                text=True,
            )
            if rc.returncode != 0:
                missing.append(pkg)
        if missing:
            return self.install(*missing, quiet=quiet)
        return ""

    # ------------------------------------------------------------------
    # Script execution
    # ------------------------------------------------------------------

    def run(
        self,
        script: str,
        cwd: str | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess:
        """Execute *script* (a string) with the isolated interpreter."""
        self._ensure_ready()
        return subprocess.run(
            [str(self.python), "-c", script],
            capture_output=True,
            text=True,
            cwd=cwd or str(self.base_path),
            **kwargs,  # type: ignore[arg-type]
        )

    def run_file(
        self,
        file_path: str,
        cwd: str | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess:
        """Execute *file_path* with the isolated interpreter."""
        self._ensure_ready()
        return subprocess.run(
            [str(self.python), str(file_path)],
            capture_output=True,
            text=True,
            cwd=cwd or str(self.base_path),
            **kwargs,  # type: ignore[arg-type]
        )

    def run_pip(self, *args: str) -> subprocess.CompletedProcess:
        """Run an arbitrary ``pip`` subcommand."""
        self._ensure_ready()
        return subprocess.run(
            [str(self.python), "-m", "pip", *args],
            capture_output=True,
            text=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.setup()

    @staticmethod
    def _check(*cmd: str) -> str:
        proc = subprocess.run(list(cmd), capture_output=True, text=True)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{msg}")
        return (proc.stdout + proc.stderr).strip()

    def __repr__(self) -> str:
        return f"<AgentEnvironment ready={self._ready} path={self.env_dir}>"

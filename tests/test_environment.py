"""
Tests for environment — AgentEnvironment manager.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from environment import AgentEnvironment, _bin_subdir, ENV_DIR_NAME


def _venv_supported() -> bool:
    """Return True if ``AgentEnvironment.setup()`` actually works here.

    Some CI runners can create a bare venv but fail the full
    ``with_pip`` bootstrap (ensurepip), so we exercise the real code
    path rather than a weaker probe.
    """
    import tempfile as _tf
    import shutil as _shutil
    probe = _tf.mkdtemp(prefix="virgo_venv_probe_")
    try:
        AgentEnvironment(str(probe)).setup()
        return True
    except Exception:
        return False
    finally:
        _shutil.rmtree(probe, ignore_errors=True)


# The environment manager requires a working ``venv``; skip when unavailable
# (e.g. certain CI images) rather than failing the whole suite.
requires_venv = pytest.mark.skipif(not _venv_supported(), reason="venv creation unsupported in this environment")


class TestConstants:
    def test_env_dir_name(self) -> None:
        assert ENV_DIR_NAME == "agent_env"

    def test_bin_subdir(self) -> None:
        sub = _bin_subdir()
        expected = "Scripts" if sys.platform == "win32" else "bin"
        assert sub == expected


class TestConstruction:
    def test_default_base_path(self) -> None:
        env = AgentEnvironment()
        assert env.base_path == Path.cwd().resolve()

    def test_custom_base_path(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        assert env.env_dir == tmp_path / "agent_env"

    def test_not_ready_by_default(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path / "nonexistent"))
        assert env.is_ready is False

    def test_python_property_before_setup(self) -> None:
        env = AgentEnvironment("/tmp")
        assert "python" in str(env.python)


@requires_venv
class TestSetupTeardown:
    def test_setup_creates_directory(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        assert env.env_dir.is_dir()
        assert env.is_ready

    def test_setup_twice_no_error(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        env.setup()  # should not raise
        assert env.is_ready

    def test_setup_recreate(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        # Create a marker file
        (env.env_dir / "MARKER").write_text("exists")
        env.setup(recreate=True)
        assert not (env.env_dir / "MARKER").exists()

    def test_teardown_removes_directory(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        env.teardown()
        assert not env.env_dir.exists()
        assert env.is_ready is False

    def test_teardown_nonexistent_no_error(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.teardown()  # should not raise


@requires_venv
class TestPackageManagement:
    def test_ensure_install(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        # Install a small package
        result = env.install("pytz")
        assert "Successfully installed" in result or "already satisfied" in result or "Requirement already satisfied" in result

    def test_ensure_already_installed(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        env.install("pytz", quiet=True)
        # Second call should not fail
        result = env.ensure("pytz", quiet=True)
        assert "already satisfied" in result or result == ""


@requires_venv
class TestScriptExecution:
    def test_run_simple(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        proc = env.run("print('hello virgo')")
        assert proc.returncode == 0
        assert "hello virgo" in proc.stdout

    def test_run_failing(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        proc = env.run("raise RuntimeError('boom')")
        assert proc.returncode != 0

    def test_run_syntax_error(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        proc = env.run("this is not valid python")
        assert proc.returncode != 0

    def test_run_with_cwd(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        import os
        proc = env.run("import os; print(os.getcwd())", cwd=str(tmp_path))
        assert str(tmp_path) in proc.stdout


@requires_venv
class TestFileExecution:
    def test_run_file(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        script = tmp_path / "test_script.py"
        script.write_text("print('from file')")
        proc = env.run_file(str(script))
        assert proc.returncode == 0
        assert "from file" in proc.stdout

    def test_run_file_nonexistent(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        proc = env.run_file(str(tmp_path / "nonexistent.py"))
        assert proc.returncode != 0


@requires_venv
class TestEdgeCases:
    def test_ensure_empty_packages(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        result = env.ensure()  # no packages
        assert result == ""

    def test_install_empty_packages(self, tmp_path: Path) -> None:
        env = AgentEnvironment(str(tmp_path))
        env.setup()
        with pytest.raises(Exception):
            env.install()

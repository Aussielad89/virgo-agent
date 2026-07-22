"""
Tests for tools — ToolRegistry and built-in tools.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from tools import Tool, ToolRegistry

# ===========================================================================
# Tool
# ===========================================================================


class TestTool:
    def test_basic_tool(self) -> None:
        def my_fn(x: int) -> int:
            return x * 2

        t = Tool(name="double", fn=my_fn, description="Doubles input")
        assert t.name == "double"
        assert t.description == "Doubles input"
        assert t(x=3) == 6

    def test_to_dict(self) -> None:
        def fn() -> None:
            pass

        t = Tool(name="test", fn=fn, description="A test tool")
        d = t.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "A test tool"


# ===========================================================================
# ToolRegistry
# ===========================================================================


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        r = ToolRegistry()
        t = Tool(name="foo", fn=lambda: "bar", description="")
        r.register(t)
        assert r.get("foo") is t

    def test_register_with_custom_name(self) -> None:
        r = ToolRegistry()
        t = Tool(name="foo", fn=lambda: "bar", description="")
        r.register(t, name="baz")
        assert r.get("baz") is t
        assert r.get("foo") is None

    def test_get_nonexistent(self) -> None:
        r = ToolRegistry()
        assert r.get("nonexistent") is None

    def test_execute(self) -> None:
        r = ToolRegistry()
        r.register(Tool(name="add", fn=lambda a, b: a + b, description=""))
        assert r.execute("add", a=2, b=3) == 5

    def test_execute_nonexistent_raises(self) -> None:
        r = ToolRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            r.execute("nonexistent")

    def test_list(self) -> None:
        r = ToolRegistry()
        r.register(Tool(name="a", fn=lambda: None, description="tool a"))
        r.register(Tool(name="b", fn=lambda: None, description="tool b"))
        tools = r.list()
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "a" in names
        assert "b" in names

    def test_register_defaults_creates_tools(self) -> None:
        r = ToolRegistry()
        r.register_defaults()
        assert r.get("file_sampler") is not None
        assert r.get("code_patcher") is not None
        assert r.get("web_fetch") is not None
        assert r.get("git_tool") is not None
        assert r.get("check_local_port") is not None
        assert r.get("db_sampler") is not None
        # python_runner requires env
        assert r.get("python_runner") is None

    def test_register_defaults_with_env_adds_runner(self) -> None:
        # Create a mock env
        class MockEnv:
            pass

        r = ToolRegistry()
        r.register_defaults(env=MockEnv())  # type: ignore
        assert r.get("python_runner") is not None


# ===========================================================================
# Built-in tool: file_sampler
# ===========================================================================


class TestFileSampler:
    @pytest.fixture
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register_defaults()
        return r

    def test_sample_csv(self, registry: ToolRegistry, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3\n4,5,6\n")
        result = registry.execute("file_sampler", file_path=str(f))
        assert result["format"] == "csv"
        assert result["sample_rows"] == 2

    def test_sample_json(self, registry: ToolRegistry, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('[{"x": 1}, {"x": 2}]')
        result = registry.execute("file_sampler", file_path=str(f))
        assert result["format"] == "json"

    def test_sample_text(self, registry: ToolRegistry, tmp_path: Path) -> None:
        f = tmp_path / "readme.txt"
        f.write_text("hello\nworld\n")
        result = registry.execute("file_sampler", file_path=str(f))
        assert result["format"] == "txt"

    def test_sample_nonexistent(self, registry: ToolRegistry) -> None:
        with pytest.raises(FileNotFoundError):
            registry.execute("file_sampler", file_path="/nonexistent/file.txt")


# ===========================================================================
# Built-in tool: code_patcher
# ===========================================================================


class TestCodePatcher:
    @pytest.fixture
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register_defaults()
        return r

    def test_write_new_file(self, registry: ToolRegistry, tmp_path: Path) -> None:
        target = tmp_path / "new_file.py"
        result = registry.execute(
            "code_patcher", file_path=str(target), content="x = 1", mode="write"
        )
        assert target.exists()
        assert target.read_text() == "x = 1"
        assert result.get("action") == "overwritten"

    def test_patch_existing_file(self, registry: ToolRegistry, tmp_path: Path) -> None:
        target = tmp_path / "patch_me.py"
        target.write_text("old_content")
        result = registry.execute(
            "code_patcher",
            file_path=str(target),
            content="new_content",
            old_string="old_content",
            mode="patch",
        )
        assert target.read_text() == "new_content"
        assert result.get("action") == "patched"

    def test_patch_not_found(self, registry: ToolRegistry, tmp_path: Path) -> None:
        target = tmp_path / "no_match.py"
        target.write_text("keep this")
        with pytest.raises(ValueError, match="old_string not found"):
            registry.execute(
                "code_patcher",
                file_path=str(target),
                content="replacement",
                old_string="nonexistent",
                mode="patch",
            )


# ===========================================================================
# Built-in tool: check_local_port
# ===========================================================================


class TestCheckLocalPort:
    @pytest.fixture
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register_defaults()
        return r

    def test_port_refused(self, registry: ToolRegistry) -> None:
        """Connecting to a random high port should fail quickly."""
        result = registry.execute("check_local_port", host="127.0.0.1", port=19999)
        # Returns a string like "closed" or "error: ..."
        assert isinstance(result, str)


# ===========================================================================
# Built-in tool: git_tool
# ===========================================================================


class TestGitTool:
    @pytest.fixture
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register_defaults()
        return r

    def test_git_not_a_repo(self, registry: ToolRegistry, tmp_path: Path) -> None:
        """Running git_tool outside a git repo should give a non-crash result."""
        result = registry.execute("git_tool", action="status")
        assert isinstance(result, dict)
        assert "returncode" in result


# ===========================================================================
# Built-in tool: python_runner
# ===========================================================================


class TestPythonRunner:
    @pytest.fixture
    def registry_with_env(self, tmp_path: Path) -> ToolRegistry:
        """Create a minimal environment for python_runner tests."""

        class MockEnv:
            env_dir = tmp_path / "agent_env"
            python = Path(sys.executable)
            base_path = tmp_path

            def _ensure_ready(self) -> None:
                pass

            def run(self, script, cwd=None, **kwargs):
                import subprocess

                return subprocess.run(
                    [str(self.python), "-c", script],
                    capture_output=True,
                    text=True,
                    cwd=cwd or str(self.base_path),
                )

        r = ToolRegistry()
        r.register_defaults(env=MockEnv())  # type: ignore
        return r

    def test_run_simple_script(self, registry_with_env: ToolRegistry) -> None:
        result = registry_with_env.execute("python_runner", script="print('hello')")
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    def test_run_failing_script(self, registry_with_env: ToolRegistry) -> None:
        result = registry_with_env.execute("python_runner", script="raise RuntimeError('boom')")
        assert result["returncode"] != 0

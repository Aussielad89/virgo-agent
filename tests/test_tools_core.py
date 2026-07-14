"""
Tests for tools_core — Tool, ToolRegistry, built-in tools, parse_tool_calls.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(HERE))

from tools_core import (
    Tool,
    ToolRegistry,
    make_builtin_registry,
    parse_tool_calls,
    _is_dangerous_command,
)


# ===========================================================================
# Tool dataclass
# ===========================================================================

class TestTool:
    def test_tool_fields(self) -> None:
        def run(args: str) -> str:
            return args.upper()
        t = Tool(name="up", description="uppercase", run=run, schema="<text>")
        assert t.name == "up"
        assert t.description == "uppercase"
        assert t.schema == "<text>"
        assert t.run("hi") == "HI"

    def test_tool_default_schema(self) -> None:
        t = Tool(name="x", description="d", run=lambda a: a)
        assert t.schema == ""

    def test_to_dict(self) -> None:
        t = Tool(name="x", description="d", run=lambda a: a, schema="S")
        d = t.to_dict()
        assert d == {"name": "x", "description": "d", "schema": "S"}


# ===========================================================================
# ToolRegistry
# ===========================================================================

class TestToolRegistry:
    def test_register_and_get(self) -> None:
        r = ToolRegistry()
        t = Tool(name="foo", description="", run=lambda a: "bar")
        r.register(t)
        assert r.get("foo") is t

    def test_get_nonexistent(self) -> None:
        r = ToolRegistry()
        assert r.get("nope") is None

    def test_list_tools(self) -> None:
        r = ToolRegistry()
        r.register(Tool(name="a", description="", run=lambda a: a))
        r.register(Tool(name="b", description="", run=lambda a: a))
        assert [t.name for t in r.list_tools()] == ["a", "b"]

    def test_call_success(self) -> None:
        r = ToolRegistry()
        r.register(Tool(name="add1", description="", run=lambda a: str(int(a) + 1)))
        assert r.call("add1", "41") == "42"

    def test_call_unknown(self) -> None:
        r = ToolRegistry()
        assert r.call("ghost", "x") == "ERROR: unknown tool ghost"

    def test_call_wraps_exception(self) -> None:
        def boom(args: str) -> str:
            raise RuntimeError("kaboom")
        r = ToolRegistry()
        r.register(Tool(name="boom", description="", run=boom))
        out = r.call("boom", "x")
        assert out.startswith("ERROR: tool boom failed")

    def test_describe_includes_tools(self) -> None:
        r = ToolRegistry()
        r.register(Tool(name="shell", description="run a command", run=lambda a: a,
                        schema="<cmd>"))
        desc = r.describe()
        assert "shell" in desc
        assert "run a command" in desc
        assert "<cmd>" in desc


# ===========================================================================
# Built-in registry
# ===========================================================================

class TestBuiltinRegistry:
    def test_builtin_names(self) -> None:
        reg = make_builtin_registry()
        names = {t.name for t in reg.list_tools()}
        assert names == {"shell", "file_read", "file_write", "python_run",
                         "web_fetch", "think"}

    def test_think_tool(self) -> None:
        reg = make_builtin_registry()
        assert reg.call("think", "I should plan first") == \
            "THOUGHT: I should plan first"

    def test_think_empty(self) -> None:
        reg = make_builtin_registry()
        assert reg.call("think", "") == "THOUGHT: "


# ===========================================================================
# Built-in tools — safe inputs
# ===========================================================================

class TestShellTool:
    def test_safe_command(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("shell", "echo hello_tools_core")
        assert "hello_tools_core" in out

    def test_empty_command(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("shell", "")
        assert out.startswith("ERROR")


class TestFileReadTool:
    def test_read_existing(self) -> None:
        reg = make_builtin_registry()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("alpha beta gamma")
            path = fh.name
        try:
            out = reg.call("file_read", path)
            assert "alpha beta gamma" in out
        finally:
            Path(path).unlink(missing_ok=True)

    def test_read_missing(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("file_read", "no_such_file_xyz.txt")
        assert out.startswith("ERROR")

    def test_read_truncates(self) -> None:
        reg = make_builtin_registry()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("x" * 9000)
            path = fh.name
        try:
            out = reg.call("file_read", path)
            assert "[truncated at 8000 chars]" in out
        finally:
            Path(path).unlink(missing_ok=True)


class TestFileWriteTool:
    def test_write_and_verify(self) -> None:
        reg = make_builtin_registry()
        import os
        d = tempfile.mkdtemp()
        path = os.path.join(d, "out.txt")
        try:
            out = reg.call("file_write", f"{path}\n---\nhello world")
            assert out.startswith("OK")
            assert Path(path).read_text(encoding="utf-8") == "hello world"
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_write_bad_format(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("file_write", "no separator here")
        assert out.startswith("ERROR")


class TestPythonRunTool:
    def test_run_code(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("python_run", "print(2 + 3)")
        assert "5" in out

    def test_run_error(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("python_run", "raise ValueError('boom')")
        assert out.startswith("ERROR") or "boom" in out


class TestWebFetchTool:
    def test_invalid_url(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("web_fetch", "")
        assert out.startswith("ERROR")

    def test_unreachable_url(self) -> None:
        reg = make_builtin_registry()
        out = reg.call("web_fetch", "http://127.0.0.1:1/nope")
        assert out.startswith("ERROR")


# ===========================================================================
# parse_tool_calls
# ===========================================================================

class TestParseFenced:
    def test_single(self) -> None:
        text = "Tool: shell\nARGS: echo hi\n"
        assert parse_tool_calls(text) == [("shell", "echo hi")]

    def test_args_multiline(self) -> None:
        text = "Tool: file_write\nARGS: path.txt\nline two\n"
        assert parse_tool_calls(text) == [("file_write", "path.txt\nline two")]

    def test_multiple(self) -> None:
        text = ("Tool: a\nARGS: 1\n"
                "Tool: b\nARGS: 2\n")
        assert parse_tool_calls(text) == [("a", "1"), ("b", "2")]

    def test_no_args_marker(self) -> None:
        text = "Tool: think\njust a thought\n"
        assert parse_tool_calls(text) == [("think", "just a thought")]

    def test_whitespace_tolerant(self) -> None:
        text = "   Tool:   shell   \n   ARGS:   echo hi   \n"
        assert parse_tool_calls(text) == [("shell", "echo hi")]


class TestParseJSON:
    def test_array(self) -> None:
        text = '[{"tool": "shell", "args": "echo hi"}]'
        assert parse_tool_calls(text) == [("shell", "echo hi")]

    def test_array_multiple(self) -> None:
        text = '[{"tool": "a", "args": "1"}, {"tool": "b", "args": "2"}]'
        assert parse_tool_calls(text) == [("a", "1"), ("b", "2")]

    def test_array_with_prose(self) -> None:
        text = 'here you go:\n[{"tool": "shell", "args": "ls"}]\nthanks'
        assert parse_tool_calls(text) == [("shell", "ls")]


class TestParseNoMatch:
    def test_plain_text(self) -> None:
        assert parse_tool_calls("I will just write some prose.") == []

    def test_empty(self) -> None:
        assert parse_tool_calls("") == []


# ===========================================================================
# helpers
# ===========================================================================

class TestHelpers:
    def test_dangerous_detection(self) -> None:
        assert _is_dangerous_command("rm -rf /")
        assert _is_dangerous_command("del file")
        assert _is_dangerous_command("shutdown /s")
        assert not _is_dangerous_command("echo hello")

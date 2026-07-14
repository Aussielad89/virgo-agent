"""Integration tests for the autonomous agent runtime + MCP bridge.

These exercise the full ReAct loop WITHOUT a live LLM (deterministic
fallback) and WITHOUT live MCP servers (graceful degradation), so they
run anywhere, fast.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_runtime import AgentRuntime, AgentConfig, build_runtime
from tools_core import ToolRegistry, make_builtin_registry, Tool, parse_tool_calls
from experience import ExperienceMemory
from evaluator import evaluate, Evaluation
from mcp_bridge import (
    discover_mcp_servers,
    _parse_mcp_servers_from_obj,
    _make_mcp_tool,
    McpServer,
)


# ── tools_core smoke ──────────────────────────────────────────────────

def test_builtin_registry_has_core_tools():
    reg = make_builtin_registry()
    names = {t.name for t in reg.list_tools()}
    assert {"shell", "file_read", "file_write", "python_run", "web_fetch", "think"} <= names


def test_file_write_and_read_roundtrip(tmp_path):
    reg = make_builtin_registry()
    target = tmp_path / "out.txt"
    res = reg.call("file_write", f"{target}\n---\nhello world")
    assert "OK" in res
    got = reg.call("file_read", str(target))
    assert "hello world" in got


def test_shell_runs(tmp_path):
    reg = make_builtin_registry()
    res = reg.call("shell", f"echo virgo_ok > {tmp_path/'x.txt'}")
    assert "virgo_ok" in res


def test_parse_tool_calls_fenced():
    text = "Tool: think\nARGS: plan it\nTool: file_write\nARGS: a.txt\n---\nhi"
    calls = parse_tool_calls(text)
    assert calls[0] == ("think", "plan it")
    assert calls[1][0] == "file_write"


def test_parse_tool_calls_json():
    text = '[{"tool": "shell", "args": "ls"}, {"tool": "think", "args": "x"}]'
    calls = parse_tool_calls(text)
    assert ("shell", "ls") in calls
    assert ("think", "x") in calls


def test_unknown_tool_errors():
    reg = make_builtin_registry()
    res = reg.call("does_not_exist", "x")
    assert "ERROR" in res


# ── experience memory ─────────────────────────────────────────────────

def test_experience_add_recall(tmp_path):
    mem = ExperienceMemory(path=str(tmp_path / "exp.jsonl"))
    mem.add("parse the log file", "used python_run", ["python_run"], "ok", True, "use csv module")
    hits = mem.recall("parse a log file", k=3)
    assert hits and hits[0]["success"] is True
    block = mem.format_for_prompt("parse log file")
    assert "PAST EXPERIENCE" in block
    assert "csv module" in block


# ── evaluator ─────────────────────────────────────────────────────────

def test_evaluator_deterministic_pass():
    transcript = (
        "Tool: think\nARGS: I will create the report file\n"
        "Tool: file_write\nARGS: report.txt\n---\n# Report\nDone.\n"
        "RESULT of file_write: OK report.txt\n"
        "The build a report file goal is now satisfied with the generated document.\n"
    )
    ev = evaluate("build a report file", transcript, client=None)
    assert ev.passed is True
    assert ev.score >= 0.5


def test_evaluator_detect_tool_error():
    ev = evaluate("do thing", "Tool: shell\nARGS: x\nRESULT: ERROR: boom\nDONE", client=None)
    assert ev.passed is False


class _FakeClient:
    def chat(self, messages, role="evaluator"):
        return json.dumps({"passed": True, "score": 0.9, "rationale": "looks good"})


def test_evaluator_llm_mode():
    ev = evaluate("goal", "Tool: think\nARGS: x\nDONE", client=_FakeClient())
    assert ev.passed is True and ev.score == 0.9


# ── agent runtime (no LLM) ────────────────────────────────────────────

def test_runtime_deterministic_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rt = build_runtime(client=None, config=AgentConfig(use_experience=False), include_mcp=False)
    res = rt.run("write a hello file")
    assert res.passed is True
    assert "file_write" in res.tools_used
    assert res.steps >= 1


def test_runtime_unknown_tool_recovers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reg = ToolRegistry()
    reg.register(Tool("think", "think", lambda a: f"THOUGHT: {a}"))
    # Force a bogus action by giving a fake client that emits an unknown tool.
    class _Bogus:
        def chat(self, messages, role="agent"):
            return "Tool: nope_xyz\nARGS: hi\nDONE"
    rt = AgentRuntime(registry=reg, client=_Bogus(), config=AgentConfig(use_experience=False))
    res = rt.run("do something")
    assert not res.passed  # unknown tool => error => not clean
    assert "nope_xyz" in res.transcript


# ── mcp bridge (no real servers) ──────────────────────────────────────

def test_mcp_discover_empty_when_no_config(tmp_path, monkeypatch):
    # Point discovery at an empty dir
    monkeypatch.setattr("mcp_bridge._discover_configs", lambda: [])
    specs = discover_mcp_servers()
    assert specs == {}


def test_mcp_parse_servers_from_obj():
    obj = {
        "mcpServers": {
            "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
        }
    }
    specs = _parse_mcp_servers_from_obj(obj)
    assert specs["fs"][0] == "npx"
    assert "@modelcontextprotocol/server-filesystem" in specs["fs"]


def test_mcp_make_tool_wraps_call():
    class _FakeServer:
        def __init__(self):
            self.calls = []
        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return "ran"
    srv = _FakeServer()
    tool = _make_mcp_tool("fs", "read", "read a file", srv)
    assert tool.name == "mcp_fs__read"
    out = tool.run('{"path": "/x"}')
    assert out == "ran"
    assert srv.calls[0] == ("read", {"path": "/x"})


def test_mcp_build_registry_no_servers(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_bridge._discover_configs", lambda: [])
    monkeypatch.setattr("mcp_bridge.discover_mcp_servers", lambda explicit=None: {})
    from mcp_bridge import build_mcp_registry
    reg = build_mcp_registry()
    assert len(reg.list_tools()) == 0


# ── LLM-format tolerance (regression: live qwen run) ──────────────────

def test_python_run_strips_code_fences():
    reg = make_builtin_registry()
    fenced = "```python\nprint('fenced_ok')\n```"
    out = reg.call("python_run", fenced)
    assert "fenced_ok" in out
    assert "SyntaxError" not in out


def test_python_run_strips_bare_fences():
    reg = make_builtin_registry()
    out = reg.call("python_run", "```\nprint('bare_ok')\n```")
    assert "bare_ok" in out


def test_file_write_kv_format(tmp_path):
    reg = make_builtin_registry()
    target = tmp_path / "kv.py"
    args = f'PATH={target} CONTENT="print(\\"hi\\")\\nx = 1"'
    res = reg.call("file_write", args)
    assert "OK" in res
    got = (tmp_path / "kv.py").read_text()
    assert 'print("hi")' in got
    assert "x = 1" in got


def test_file_write_first_line_path(tmp_path):
    reg = make_builtin_registry()
    target = tmp_path / "fl.txt"
    res = reg.call("file_write", f"{target}\nhello\nworld")
    assert "OK" in res
    assert (tmp_path / "fl.txt").read_text() == "hello\nworld"


def test_file_write_canonical_still_works(tmp_path):
    reg = make_builtin_registry()
    target = tmp_path / "canon.txt"
    res = reg.call("file_write", f"{target}\n---\nbody text")
    assert "OK" in res
    assert (tmp_path / "canon.txt").read_text() == "body text"


def test_file_write_rejects_garbage():
    reg = make_builtin_registry()
    res = reg.call("file_write", "this is not a valid single line with spaces and no path")
    assert "ERROR" in res

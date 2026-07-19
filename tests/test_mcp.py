"""Tests for mcp_server and mcp_bridge (protocol + discovery helpers)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mcp_bridge import (
    _build_env_from_cmd,
    _parse_kv,
    _parse_mcp_servers_from_obj,
)
from mcp_server import (
    PROTOCOL_VERSION,
    _dispatch,
    _handle_initialize,
    _handle_tools_call,
    _handle_tools_list,
    _rpc_error,
)


# ── Fake registry (mimics tools.ToolRegistry surface used by mcp_server) ──

class _FakeTool:
    def __init__(self, name, description="", ret=None, raises=None):
        self.name = name
        self.description = description
        self._ret = ret
        self._raises = raises

    def to_dict(self):
        return {"name": self.name, "description": self.description}

    def __call__(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._ret


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def list(self):
        return [t.to_dict() for t in self._tools.values()]

    def execute(self, name, **kwargs):
        return self._tools[name](**kwargs)


def _reg():
    return _FakeRegistry([
        _FakeTool("echo", "Echo a value", ret={"ok": True}),
        _FakeTool("boom", "Always fails", raises=RuntimeError("kaboom")),
    ])


# ── mcp_server handlers ────────────────────────────────────────────────

def test_initialize_handshake():
    resp = json.loads(_handle_initialize({"id": 1, "params": {"clientInfo": {"name": "test", "version": "9"}}}))
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "virgo-mcp"
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list_maps_metadata():
    resp = json.loads(_handle_tools_list({"id": 2}, _reg()))
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"echo", "boom"}
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["description"]


def test_tools_call_success():
    resp = json.loads(_handle_tools_call({"id": 3, "params": {"name": "echo", "arguments": {}}}, _reg()))
    assert resp["id"] == 3
    text = resp["result"]["content"][0]["text"]
    assert json.loads(text) == {"ok": True}


def test_tools_call_unknown_tool_errors():
    resp = json.loads(_handle_tools_call({"id": 4, "params": {"name": "nope"}}, _reg()))
    assert resp["error"]["code"] == -32602
    assert "Unknown tool" in resp["error"]["message"]


def test_tools_call_tool_exception_errors():
    resp = json.loads(_handle_tools_call({"id": 5, "params": {"name": "boom"}}, _reg()))
    assert resp["error"]["code"] == -32000
    assert "kaboom" in resp["error"]["message"]


# ── dispatch routing + hardening ────────────────────────────────────────

def test_dispatch_routes_known_methods():
    init = json.loads(_dispatch({"id": 1, "method": "initialize", "params": {}}, _reg()))
    assert init["result"]["serverInfo"]["name"] == "virgo-mcp"
    lst = json.loads(_dispatch({"id": 2, "method": "tools/list"}, _reg()))
    assert len(lst["result"]["tools"]) == 2


def test_dispatch_notification_returns_none():
    assert _dispatch({"method": "notifications/initialized"}, _reg()) is None


def test_dispatch_unknown_method_errors():
    resp = json.loads(_dispatch({"id": 9, "method": "bogus"}, _reg()))
    assert resp["error"]["code"] == -32601


def test_dispatch_survives_handler_crash():
    """A handler that raises must become a -32603, not crash the loop."""
    class _BadRegistry(_FakeRegistry):
        def list(self):
            raise RuntimeError("registry broken")

    resp = json.loads(_dispatch({"id": 1, "method": "tools/list"}, _BadRegistry([])))
    assert resp["error"]["code"] == -32603


# ── mcp_bridge pure helpers ──────────────────────────────────────────────

def test_parse_mcp_servers_from_obj():
    obj = {
        "mcpServers": {
            "fs": {"command": "npx", "args": ["-y", "server-fs"]},
            "api": {"command": "python", "args": ["s.py"], "env": {"TOKEN": "x"}},
            "bad": {"args": ["nope"]},  # no command -> skipped
        }
    }
    out = _parse_mcp_servers_from_obj(obj)
    assert out["fs"] == ["npx", "-y", "server-fs"]
    assert out["api"][0] == "__ENV__"
    assert json.loads(out["api"][1]) == {"TOKEN": "x"}
    assert "bad" not in out


def test_build_env_from_cmd_strips_marker():
    cmd, env = _build_env_from_cmd(["__ENV__", '{"A": "1"}', "python", "s.py"])
    assert cmd == ["python", "s.py"]
    assert env == {"A": "1"}


def test_parse_kv():
    assert _parse_kv("a=1\nb=two\nnotkv\nc= three") == {"a": "1", "b": "two", "c": "three"}


def test_rpc_error_shape():
    err = json.loads(_rpc_error(7, -1, "boom"))
    assert err["error"]["code"] == -1
    assert err["id"] == 7

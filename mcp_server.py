"""
mcp_server — expose Virgo's built-in tools as an MCP server (stdio transport).

Speaks the Model Context Protocol (JSON-RPC 2.0 over stdin/stdout) so that
Claude Desktop, Cursor, and other MCP hosts can discover and call Virgo's
:mod:`~tools` (file read/write, shell, web fetch, python run, etc.).

Usage
-----
Run directly::

    python mcp_server.py

Or via the installed entry point::

    virgo-mcp

The server registers the default ``ToolRegistry`` tools and serves them over
stdio.  No network port is opened — the protocol is line-delimited JSON on
stdin/stdout, which is what MCP hosts expect.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from tools import ToolRegistry

# ── MCP protocol constants ────────────────────────────────────────────
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "virgo-mcp", "version": "0.1.0"}


def _build_registry() -> ToolRegistry:
    """Create a ToolRegistry with all default tools registered."""
    reg = ToolRegistry()
    reg.register_defaults()  # no env → skips python_runner
    return reg


# ── JSON-RPC helpers ──────────────────────────────────────────────────


def _rpc_error(id: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


def _rpc_result(id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "result": result})


# ── MCP method handlers ──────────────────────────────────────────────


def _handle_initialize(req: dict) -> str:
    """Handle ``initialize`` — the MCP handshake."""
    client_info = req.get("params", {}).get("clientInfo", {})
    client_name = client_info.get("name", "unknown")
    client_version = client_info.get("version", "0.0")
    # Log to stderr so it doesn't interfere with stdio protocol
    print(f"[virgo-mcp] client connected: {client_name} v{client_version}", file=sys.stderr)
    return _rpc_result(
        req["id"],
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        },
    )


def _handle_tools_list(req: dict, registry: ToolRegistry) -> str:
    """Handle ``tools/list`` — return registered tool metadata."""
    tools_meta = registry.list()
    # Map Virgo tool fields to MCP Tool schema
    mcp_tools = []
    for t in tools_meta:
        mcp_tools.append(
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }
        )
    return _rpc_result(req["id"], {"tools": mcp_tools})


def _handle_tools_call(req: dict, registry: ToolRegistry) -> str:
    """Handle ``tools/call`` — execute a Virgo tool."""
    params = req.get("params", {})
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    try:
        result = registry.execute(tool_name, **arguments)
        # Serialise result to a string so it is always JSON-safe
        text = json.dumps(result, default=str, indent=2) if not isinstance(result, str) else result
        return _rpc_result(
            req["id"],
            {
                "content": [{"type": "text", "text": text}],
            },
        )
    except KeyError:
        return _rpc_error(req["id"], -32602, f"Unknown tool: {tool_name}")
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[virgo-mcp] error calling {tool_name}: {exc}", file=sys.stderr)
        print(tb, file=sys.stderr)
        return _rpc_error(req["id"], -32000, str(exc))


def _dispatch(req: dict, registry: ToolRegistry) -> str | None:
    """Route one MCP request to its handler.

    Returns the JSON-RPC response string, or ``None`` when no response is
    expected (e.g. notifications). Never raises — a handler failure is
    converted into a JSON-RPC internal-error response.
    """
    method = req.get("method", "")
    req_id = req.get("id")
    try:
        if method == "initialize":
            return _handle_initialize(req)
        elif method == "tools/list":
            return _handle_tools_list(req, registry)
        elif method == "tools/call":
            return _handle_tools_call(req, registry)
        elif method == "notifications/initialized":
            return None
        else:
            return _rpc_error(req_id, -32601, f"Method not found: {method}")
    except Exception as exc:  # defensive: never let one bad request kill the server
        print(f"[virgo-mcp] unhandled error: {exc}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return _rpc_error(req_id, -32603, f"Internal error: {exc}")


# ── Main loop ─────────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP stdio server loop."""
    registry = _build_registry()

    print(f"[virgo-mcp] ready with {len(registry.list())} tools", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            print(_rpc_error(None, -32700, "Parse error"), flush=True)
            continue

        try:
            resp = _dispatch(req, registry)
        except Exception as exc:  # defensive: never let one bad request kill the server
            print(f"[virgo-mcp] unhandled error: {exc}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            resp = _rpc_error(req.get("id"), -32603, f"Internal error: {exc}")

        if resp is not None:
            print(resp, flush=True)


if __name__ == "__main__":
    main()

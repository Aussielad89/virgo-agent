"""mcp_bridge — expose MCP (Model Context Protocol) servers as Virgo tools.

Virgo's runtime can *act* through tools. MCP servers are the richest source
of external capability (filesystems, browsers, custom APIs). This module
discovers MCP servers from the usual config locations, speaks the MCP
JSON-RPC-over-stdio protocol, and turns each server's tools into Virgo
``Tool`` objects usable by the agent runtime.

Design notes
------------
* Stdlib only (subprocess + json). No ``mcp`` SDK dependency required.
* Servers are launched as subprocesses and spoken to over stdin/stdout
  using newline-delimited JSON-RPC (the common ``stdio`` transport).
* If a server cannot be reached, it is skipped with a warning — the bridge
  never blocks the rest of the runtime.
* Discovery sources (in priority order): explicit ``--mcp`` server specs,
  a ``.mcp.json`` in the cwd, ``claude_desktop_config.json`` (AppData/
  Roaming), and ``~/.gemini/config/mcp_config.json``.

This is intentionally tolerant: in environments with no MCP servers
configured (e.g. a fresh dev box) ``discover_mcp_registry()`` simply
returns an empty registry and the runtime continues with builtin tools.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from _console import icon
from _log import log

try:  # tools_core may not exist yet at import time in some test setups
    from tools_core import Tool, ToolRegistry
except Exception:  # pragma: no cover - import shim for standalone use
    Tool = None  # type: ignore
    ToolRegistry = None  # type: ignore


# ── JSON-RPC client for a single stdio MCP server ─────────────────────


class McpServer:
    """A thin stdio JSON-RPC client for one MCP server process."""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self.command = command
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._req_id = 0
        self._tools: list[dict] = []
        self._ready = False
        self._read_queue: queue.Queue = queue.Queue()
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------
    def start(self, timeout: float = 20.0) -> bool:
        """Launch the server and complete MCP initialize handshake."""
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, FileNotFoundError) as exc:
            log.warning("MCP %s: cannot launch %s: %s", self.name, self.command, exc)
            return False

        # start background reader thread
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # initialize
        init = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "virgo", "version": "0.1"},
            },
            timeout=timeout,
        )
        if init is None:
            self.stop()
            return False
        # notifications/initialized (no response expected)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # list tools
        lst = self._request("tools/list", {}, timeout=timeout)
        if lst is None:
            self.stop()
            return False
        self._tools = lst.get("tools", []) or []
        self._ready = True
        log.info("MCP %s ready: %d tools", self.name, len(self._tools))
        return True

    def _reader_loop(self) -> None:
        """Read lines from stdout into a queue with a sentinel on EOF."""
        try:
            assert self._proc is not None and self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._reader_stop.is_set():
                    return
                self._read_queue.put(line)
        except Exception:
            pass
        finally:
            self._read_queue.put(None)  # EOF sentinel

    def stop(self) -> None:
        self._reader_stop.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=3)
            self._reader_thread = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._ready = False

    # -- protocol helpers ------------------------------------------------
    def _send(self, obj: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("server not started")
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()

    def _read_line(self, timeout: float) -> str | None:
        try:
            item = self._read_queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            return None  # EOF sentinel
        return item

    def _request(self, method: str, params: dict, timeout: float = 20.0) -> dict | None:
        with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            self._send(payload)
            deadline = time.time() + timeout
            while time.time() < deadline:
                raw = self._read_line(timeout)
                if raw is None:
                    return None
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == req_id:
                    if "error" in msg:
                        log.warning("MCP %s error on %s: %s", self.name, method, msg["error"])
                        return None
                    return msg.get("result", {})
            return None

    # -- tool access -----------------------------------------------------
    def list_tool_specs(self) -> list[dict]:
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Invoke an MCP tool; returns the concatenated text content."""
        if not self._ready:
            return f"ERROR: MCP server {self.name} not ready"
        result = self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=60.0,
        )
        if result is None:
            return f"ERROR: MCP {self.name} tool {tool_name} failed"
        parts: list[str] = []
        for item in result.get("content", []) or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts) if parts else "(no content)"


# ── Discovery ─────────────────────────────────────────────────────────


def _parse_mcp_servers_from_obj(obj: dict) -> dict[str, list[str]]:
    """Extract ``mcpServers`` definitions into {name: [cmd, ...]}."""
    out: dict[str, list[str]] = {}
    servers = obj.get("mcpServers", {})
    if not isinstance(servers, dict):
        return out
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        cmd = spec.get("command")
        if not cmd:
            continue
        args = spec.get("args", []) or []
        env = spec.get("env", {}) or {}
        full = [cmd, *([str(a) for a in args])]
        # Stash env additions in a side channel by re-using command list is
        # complex; keep it simple and pass env via a marker tuple string.
        if env:
            full = ["__ENV__", json.dumps(env), *full]
        out[name] = full
    return out


def _discover_configs() -> list[Path]:
    candidates = [
        Path.cwd() / ".mcp.json",
        Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
        Path.home() / ".gemini" / "config" / "mcp_config.json",
        Path.home() / ".config" / "claude" / "claude_desktop_config.json",
    ]
    found = []
    for c in candidates:
        try:
            if c.exists():
                found.append(c)
        except OSError:
            continue
    return found


def discover_mcp_servers(explicit: list[str] | None = None) -> dict[str, list[str]]:
    """Return {server_name: command_list} from configs + explicit specs.

    ``explicit`` entries are ``name=cmd args...`` strings passed via CLI.
    """
    servers: dict[str, list[str]] = {}
    for cfg in _discover_configs():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            servers.update(_parse_mcp_servers_from_obj(data))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("MCP config %s unreadable: %s", cfg, exc)
    if explicit:
        for spec in explicit:
            if "=" not in spec:
                continue
            name, cmd = spec.split("=", 1)
            servers[name.strip()] = cmd.strip().split()
    return servers


# ── Registry builder ──────────────────────────────────────────────────


def _build_env_from_cmd(cmd: list[str]) -> tuple[list[str], dict[str, str]]:
    env: dict[str, str] = {}
    if cmd and cmd[0] == "__ENV__":
        env = json.loads(cmd[1])
        cmd = cmd[2:]
    return cmd, env


def build_mcp_registry(
    explicit: list[str] | None = None,
    timeout: float = 20.0,
) -> ToolRegistry:
    """Launch discovered MCP servers and wrap their tools as Virgo tools.

    Returns a ToolRegistry (from tools_core) containing one Tool per
    remote tool, namespaced as ``mcp_<server>__<tool>``.
    """
    if ToolRegistry is None:
        raise RuntimeError("tools_core not importable")
    registry = ToolRegistry()
    specs = discover_mcp_servers(explicit)
    if not specs:
        log.info("MCP: no servers discovered")
        return registry

    for name, cmd in specs.items():
        cmd, env = _build_env_from_cmd(cmd)
        if env:
            merged = dict(os.environ)
            merged.update(env)
        else:
            merged = None
        server = McpServer(name, cmd)
        # Inject env by overriding popen environment if provided
        if merged is not None:
            server._env = merged  # type: ignore[attr-defined]
            _patch_env(server)
        if not server.start(timeout=timeout):
            log.warning("MCP: skipping unreachable server %s", name)
            continue
        for tool_spec in server.list_tool_specs():
            tname = tool_spec.get("name", "tool")
            tdesc = tool_spec.get("description", "") or ""
            registry.register(_make_mcp_tool(name, tname, tdesc, server))
    return registry


def _patch_env(server: McpServer) -> None:
    """Monkey-patch Popen to use the server's env (helper for env-in-cmd)."""
    real_start = server.start

    def _wrapped(timeout: float = 20.0) -> bool:
        import subprocess as _sp

        orig = _sp.Popen
        env = getattr(server, "_env", None)

        def _popen(*a, **kw):
            if env is not None and "env" not in kw:
                kw["env"] = env
            return orig(*a, **kw)

        _sp.Popen = _popen  # type: ignore[misc]
        try:
            return real_start(timeout=timeout)
        finally:
            _sp.Popen = orig  # type: ignore[misc]

    server.start = _wrapped  # type: ignore[method-assign]


def _make_mcp_tool(server_name: str, tool_name: str, description: str, server: McpServer) -> Tool:
    virgo_name = f"mcp_{server_name}__{tool_name}"

    def _run(args: str) -> str:
        try:
            # Args may be JSON or key=value pairs; try JSON first.
            try:
                arguments = json.loads(args)
            except json.JSONDecodeError:
                arguments = _parse_kv(args)
        except Exception as exc:  # pragma: no cover
            return f"ERROR: bad args ({exc})"
        return server.call_tool(tool_name, arguments)

    return Tool(
        name=virgo_name,
        description=f"[MCP:{server_name}] {description}",
        run=_run,
        schema="JSON object or key=value pairs",
    )


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# ── Standalone smoke runner (for manual testing) ──────────────────────


def main() -> None:  # pragma: no cover - manual CLI
    print(f"{icon('rocket')}  Virgo MCP bridge")
    specs = discover_mcp_servers()
    if not specs:
        print("  No MCP servers discovered in standard config locations.")
        print("  Tip: add a .mcp.json with an mcpServers block, or pass")
        print("       virgo agent --mcp 'mycli=python server.py'")
        return
    for name, cmd in specs.items():
        print(f"  {icon('tool')}  {name}: {' '.join(cmd)}")
    reg = build_mcp_registry(timeout=15.0)
    print(f"\n  Registered {len(reg.list_tools())} MCP tools.")


if __name__ == "__main__":  # pragma: no cover
    main()

"""
tools_core — action tool layer for the autonomous agent runtime.

This module provides a richer, *action* tool layer on top of the
pipeline-oriented ``tools.ToolRegistry``.  It is designed for an agent
runtime that needs to:

* register callable tools that take a single string argument and return a
  string result,
* call tools by name with graceful ``ERROR:``-style failure reporting,
* describe the available tools for injection into a system prompt, and
* parse tool invocations out of LLM output in either a fenced
  (``Tool:`` / ``ARGS:``) or JSON-array format.

All built-in tool callables are wrapped so that they NEVER raise — any
failure is converted into an ``ERROR:`` string, keeping the agent loop
robust.

Conventions follow AGENTS.md: stdlib-only unless reusing an existing
framework module (``virgo_sandbox``, ``tools``), and ``from _log import
log`` for logging.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:  # pragma: no cover - logging is optional in some environments
    from _log import log
except Exception:  # pragma: no cover

    class _NullLog:
        def info(self, *a, **k):
            pass

        def warn(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

        def debug(self, *a, **k):
            pass

    log = _NullLog()


# ===========================================================================
# Permission system
# ===========================================================================

# Risk levels for tools
RISK_UNKNOWN = 0
RISK_SAFE = 1  # read-only, no side effects
RISK_LOW = 2  # writes files but sandboxed
RISK_MEDIUM = 3  # executes code/subprocess
RISK_HIGH = 4  # destructive operations (rm, format, shutdown)
RISK_CRITICAL = 5  # full system access

_TOOL_RISK: dict[str, int] = {
    "think": RISK_SAFE,
    "file_read": RISK_SAFE,
    "file_write": RISK_LOW,
    "python_run": RISK_MEDIUM,
    "shell": RISK_HIGH,
    "web_fetch": RISK_LOW,
}


class PermissionDenied(Exception):
    """Raised when a tool call is denied by the permission gate."""

    pass


@dataclass
class AuditEntry:
    """A single audit log entry for a tool call."""

    ts: str
    tool: str
    args: str
    decision: str  # "allowed" | "denied" | "blocked"
    reason: str = ""


class PermissionGate:
    """Gatekeeper that decides whether a tool call is allowed.

    Controls tool access by risk level and maintains an audit trail.
    """

    def __init__(self, max_risk: int = RISK_HIGH) -> None:
        self.max_risk = max_risk
        self.audit_log: list[AuditEntry] = []
        self._allowlist: set[str] = set()  # always allowed tools
        self._blocklist: set[str] = set()  # always blocked tools

    def allow(self, *tools: str) -> None:
        """Always allow these tools, bypassing risk checks."""
        self._allowlist.update(tools)

    def block(self, *tools: str) -> None:
        """Always block these tools."""
        self._blocklist.update(tools)

    def risk_of(self, tool: str) -> int:
        """Return the risk level for a tool name."""
        return _TOOL_RISK.get(tool, RISK_UNKNOWN)

    def check(self, tool: str, args: str = "") -> None:
        """Check if *tool* is allowed. Raises PermissionDenied if blocked."""
        now = datetime.now(UTC).isoformat(timespec="seconds")

        if tool in self._blocklist:
            self.audit_log.append(
                AuditEntry(
                    ts=now,
                    tool=tool,
                    args=args,
                    decision="denied",
                    reason="tool is blocklisted",
                )
            )
            raise PermissionDenied(f"Tool '{tool}' is blocklisted")

        if tool in self._allowlist:
            self.audit_log.append(
                AuditEntry(
                    ts=now,
                    tool=tool,
                    args=args,
                    decision="allowed",
                    reason="allowlisted",
                )
            )
            return

        risk = self.risk_of(tool)
        if risk > self.max_risk:
            reason = (
                f"risk level {risk} exceeds max {self.max_risk}"
                if risk > RISK_UNKNOWN
                else "unknown tool"
            )
            self.audit_log.append(
                AuditEntry(
                    ts=now,
                    tool=tool,
                    args=args,
                    decision="denied",
                    reason=reason,
                )
            )
            raise PermissionDenied(f"Tool '{tool}' blocked: {reason} (max_risk={self.max_risk})")

        self.audit_log.append(
            AuditEntry(
                ts=now,
                tool=tool,
                args=args,
                decision="allowed",
                reason=f"risk={risk} <= max={self.max_risk}",
            )
        )

    def summary(self) -> str:
        """Return a text summary of recent audit entries."""
        lines = [f"Permission audit ({len(self.audit_log)} entries):"]
        for entry in self.audit_log[-20:]:
            icon = {"allowed": "✓", "denied": "✗", "blocked": "⚠"}.get(entry.decision, "?")
            lines.append(f"  {icon} [{entry.ts}] {entry.tool} — {entry.decision} ({entry.reason})")
        return "\n".join(lines)


# Default process-wide gate
_GATE: PermissionGate | None = None


def get_gate() -> PermissionGate:
    """Lazy singleton for the process-wide PermissionGate."""
    global _GATE
    if _GATE is None:
        _GATE = PermissionGate()
    return _GATE


def set_gate(gate: PermissionGate) -> None:
    """Replace the process-wide gate (used in tests)."""
    global _GATE
    _GATE = gate


# ===========================================================================
# Generic tool infrastructure
# ===========================================================================


@dataclass
class Tool:
    """A named, callable tool with metadata.

    Unlike the pipeline ``tools.Tool`` (which is keyword-argument based),
    this runtime tool is a single-argument callable: ``run(args: str) ->
    str``.  This keeps the agent-facing contract dead simple — the LLM
    emits a tool name and a blob of text, and the tool returns a text
    result.
    """

    name: str
    description: str
    run: Callable[[str], str]
    schema: str = ""  # human-readable argument format

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
        }


class ToolRegistry:
    """A registry of named runtime tools that can be looked up and run."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        """Register *tool* under its ``name``."""
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name, or ``None`` if not registered."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools (in insertion order)."""
        return list(self._tools.values())

    def call(self, name: str, args: str = "") -> str:
        """Run tool *name* with *args*.

        Returns the tool's string result, or an ``ERROR:`` string if the
        tool is unknown or raises during execution.
        """
        tool = self.get(name)
        if tool is None:
            log.warning("Tool call to unknown tool %r", name)
            return f"ERROR: unknown tool {name}"
        try:
            result = tool.run(args)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("Tool %r raised: %s", name, exc)
            return f"ERROR: tool {name} failed: {exc}"
        if not isinstance(result, str):
            # Coerce non-string results so the agent always gets text.
            try:
                result = json.dumps(result)
            except Exception:
                result = str(result)
        return result

    def describe(self) -> str:
        """Return a multi-line description of all tools for prompt injection."""
        lines = ["Available tools (invoke as: Tool: <name>\\nARGS: <args>):", ""]
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
            if tool.schema:
                # Indent the schema so it reads as a sub-line.
                for sline in tool.schema.splitlines() or [""]:
                    lines.append(f"    args: {sline}" if sline else "    args:")
        lines.append("")
        return "\n".join(lines)


# ===========================================================================
# Built-in tool implementations (all wrapped — never raise)
# ===========================================================================

# Command substrings that are always blocked in the subprocess fallback
# path (mirrors the dangerous-command spirit of virgo_sandbox).
_FALLBACK_BLOCKLIST: tuple[str, ...] = (
    "rmdir",
    "del ",
    "format",
    "shutdown",
    "mkfs",
    ":(){",
    "> /dev",
    "rm -rf",
)


def _is_dangerous_command(command: str) -> bool:
    """Return True if *command* contains a blocked destructive substring."""
    lowered = command.lower()
    return any(token in lowered for token in _FALLBACK_BLOCKLIST)


def _get_sandbox_runner() -> Callable[[list[str]], str] | None:
    """Return ``virgo_sandbox.run_sandboxed`` if importable, else ``None``."""
    try:
        from virgo_sandbox import run_sandboxed  # type: ignore

        return run_sandboxed
    except Exception:
        return None


def _shell(args: str) -> str:
    """Run a shell command (sandboxed) and return stdout/stderr."""
    import shlex
    import subprocess

    if not args or not args.strip():
        return "ERROR: empty command"

    runner = _get_sandbox_runner()
    if runner is not None:
        try:
            cmd = shlex.split(args)
        except ValueError as exc:
            return f"ERROR: cannot parse command: {exc}"
        try:
            return runner(cmd)
        except subprocess.CalledProcessError as exc:
            out = exc.stdout or ""
            if exc.stderr:
                out += ("\n" + exc.stderr) if out else exc.stderr
            out += f"\n[exit code {exc.returncode}]"
            return out
        except ValueError as exc:  # blocked by sandbox
            return f"ERROR: command blocked by sandbox: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"

    # --- Fallback: subprocess with a blocklist -------------------------
    if _is_dangerous_command(args):
        return "ERROR: command blocked by safety blocklist"
    try:
        cmd = shlex.split(args)
    except ValueError as exc:
        return f"ERROR: cannot parse command: {exc}"
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = proc.stdout or ""
        if proc.stderr:
            out += ("\n" + proc.stderr) if out else proc.stderr
        if proc.returncode != 0:
            out += f"\n[exit code {proc.returncode}]"
        return out
    except Exception as exc:
        return f"ERROR: {exc}"


def _file_read(args: str) -> str:
    """Read a file (first 8000 chars). *args* is the path."""
    if not args or not args.strip():
        return "ERROR: no path provided"
    path = Path(args.strip())
    if not path.exists():
        return f"ERROR: file not found: {args.strip()}"
    if not path.is_file():
        return f"ERROR: not a file: {args.strip()}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: cannot read file: {exc}"
    if len(text) > 8000:
        text = text[:8000] + "\n... [truncated at 8000 chars]"
    return text


def _file_write(args: str) -> str:
    """Write a file. Canonical format ``PATH\\n---\\nCONTENT``.

    Also tolerant of common LLM variants:
    * ``PATH=foo.py CONTENT="..."`` (quoted, with \\n escapes)
    * first line = path, remaining lines = content (no ``---`` separator)
    """
    if not args:
        return "ERROR: no input provided"

    sep = "\n---\n"
    # LLMs often emit literal backslash-n instead of real newlines.
    if sep not in args and "\\n---\\n" in args:
        args = args.replace("\\n", "\n").replace("\\t", "\t")
    if sep in args:
        path_str, content = args.split(sep, 1)
    else:
        parsed = _parse_kv_file_write(args)
        if parsed is not None:
            path_str, content = parsed
        else:
            # Fallback: first line is the path, the rest is content.
            lines = args.split("\n", 1)
            if len(lines) == 2 and lines[0].strip() and " " not in lines[0].strip():
                path_str, content = lines[0], lines[1]
            else:
                return "ERROR: invalid format, expected PATH\\n---\\nCONTENT"

    path = Path(path_str.strip())
    if not path.name:
        return "ERROR: invalid format, expected PATH\\n---\\nCONTENT"
    try:
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: cannot write file: {exc}"
    return f"OK: wrote {path} ({len(content)} chars)"


def _parse_kv_file_write(args: str) -> tuple[str, str] | None:
    """Parse ``PATH=... CONTENT="..."`` style file_write args.

    Returns ``(path, content)`` or ``None`` if the format doesn't match.
    """
    m = re.search(r"PATH\s*=\s*(.+?)\s+CONTENT\s*=\s*(.*)", args, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    path_str = m.group(1).strip().strip('"').strip("'")
    content = m.group(2).strip()
    # Unwrap a surrounding quote pair and decode common escapes.
    if len(content) >= 2 and content[0] in "\"'" and content[-1] == content[0]:
        content = content[1:-1]
        content = (
            content.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\'", "'")
        )
    return path_str, content


def _get_python_runner() -> Callable[..., object] | None:
    """Return ``tools.python_runner`` if importable, else ``None``."""
    try:
        from tools import python_runner  # type: ignore

        return python_runner
    except Exception:
        return None


def _strip_code_fences(code: str) -> str:
    """Extract runnable code from LLM output with markdown fences.

    * If a fenced block ``` ```lang ... ``` ``` exists, return its contents
      (the first block) — this discards surrounding prose the model often
      adds before/after the code.
    * Otherwise strip stray leading/trailing fence lines.
    * Un-fenced code is returned untouched.
    """
    if "```" not in code:
        return code
    # Prefer the contents of the first fenced block.
    m = re.search(r"```[^\n]*\n(.*?)```", code, re.DOTALL)
    if m and m.group(1).strip():
        return m.group(1).rstrip()
    # Fallback: drop bare fence lines.
    lines = [
        line
        for line in code.splitlines()
        if line.strip() != "```" and not line.lstrip().startswith("```")
    ]
    cleaned = "\n".join(lines)
    return cleaned if cleaned.strip() else code


def _python_run(args: str) -> str:
    """Execute Python code and return stdout/stderr."""
    if not args or not args.strip():
        return "ERROR: no code provided"

    args = _strip_code_fences(args)

    runner = _get_python_runner()
    if runner is not None:
        try:
            res = runner(args)
            if isinstance(res, dict):
                out = res.get("stdout", "") or ""
                err = res.get("stderr", "") or ""
                combined = out
                if err:
                    combined += ("\n" + err) if combined else err
                if res.get("returncode", 0):
                    combined += f"\n[exit code {res.get('returncode')}]"
                return combined or "ERROR: no output"
            if isinstance(res, str):
                return res or "ERROR: no output"
        except Exception:
            # Fall through to subprocess execution.
            pass

    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, "-c", args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = proc.stdout or ""
        if proc.stderr:
            out += ("\n" + proc.stderr) if out else proc.stderr
        if proc.returncode != 0:
            out += f"\n[exit code {proc.returncode}]"
        return out or "ERROR: no output"
    except Exception as exc:
        return f"ERROR: {exc}"


def _get_web_fetcher() -> Callable[[str], object] | None:
    """Return a ``tools`` web fetcher if importable, else ``None``."""
    try:
        from tools import web_fetch  # type: ignore

        return web_fetch
    except Exception:
        try:
            from tools import _web_fetch  # type: ignore

            return _web_fetch
        except Exception:
            return None


def _web_fetch(args: str) -> str:
    """Fetch a URL and return its text body (truncated to 8000 chars)."""
    if not args or not args.strip():
        return "ERROR: no url provided"
    url = args.strip()

    fetcher = _get_web_fetcher()
    if fetcher is not None:
        try:
            res = fetcher(url)
            if isinstance(res, dict):
                if "error" in res:
                    return f"ERROR: {res['error']}"
                body = res.get("content", "")
                body = body[:8000]
                return body or "ERROR: empty response"
            if isinstance(res, str):
                return res[:8000] or "ERROR: empty response"
        except Exception:
            # Fall through to urllib.
            pass

    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "virgo/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return body[:8000]
    except urllib.error.URLError as exc:
        return f"ERROR: cannot fetch {url}: {exc.reason}"
    except Exception as exc:
        return f"ERROR: cannot fetch {url}: {exc}"


def _think(args: str) -> str:
    """Echo reasoning text back to the model for in-band thinking."""
    return f"THOUGHT: {args}"


# ===========================================================================
# Built-in registry factory
# ===========================================================================


def make_builtin_registry() -> ToolRegistry:
    """Create a ``ToolRegistry`` pre-populated with the built-in tools."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="shell",
            description="Execute a shell command via the sandbox and return stdout/stderr.",
            run=_shell,
            schema="<command string>",
        )
    )
    reg.register(
        Tool(
            name="file_read",
            description="Read up to the first 8000 characters of a file.",
            run=_file_read,
            schema="PATH",
        )
    )
    reg.register(
        Tool(
            name="file_write",
            description="Write CONTENT to PATH (overwrites).",
            run=_file_write,
            schema="PATH\\n---\\nCONTENT",
        )
    )
    reg.register(
        Tool(
            name="python_run",
            description="Execute Python code and return stdout/stderr.",
            run=_python_run,
            schema="<python code>",
        )
    )
    reg.register(
        Tool(
            name="web_fetch",
            description="Fetch a URL and return its text body (truncated to 8000 chars).",
            run=_web_fetch,
            schema="URL",
        )
    )
    reg.register(
        Tool(
            name="think",
            description="Echo reasoning text back to the model (in-band thinking).",
            run=_think,
            schema="<free text>",
        )
    )
    return reg


# ===========================================================================
# Tool-call parsing
# ===========================================================================

_HEADER_RE = re.compile(
    r"^\s*Tool:\s*([A-Za-z0-9_\-]+)",
    re.IGNORECASE | re.MULTILINE,
)
_ARGS_RE = re.compile(r"^\s*ARGS:\s*", re.IGNORECASE)


def parse_tool_calls(text: str) -> list[tuple[str, str]]:
    """Parse LLM output for tool invocations.

    Supports two formats (returns the first one that yields results):

    a) Fenced::

           Tool: name
           ARGS: arg line
           more args

       The args run from the ``ARGS:`` marker until the next ``Tool:``
       header or end of text.  Leading ``ARGS:`` is stripped; if no
       ``ARGS:`` marker is present, the entire block is treated as args.

    b) JSON array::

           [{"tool": "name", "args": "..."}, ...]

    Returns a list of ``(name, args)`` tuples.  Tolerant of surrounding
    whitespace and prose.
    """
    json_results = _parse_json_array(text)
    if json_results is not None:
        return json_results
    return _parse_fenced(text)


def _parse_json_array(text: str) -> list[tuple[str, str]] | None:
    """Return parsed tool calls if *text* contains a JSON array, else None."""
    start = text.find("[")
    if start == -1:
        return None
    end = text.rfind("]")
    if end == -1 or end < start:
        return None
    snippet = text[start : end + 1]
    try:
        data = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    results: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, dict) and "tool" in item:
            name = str(item["tool"])
            raw_args = item.get("args", "")
            results.append((name, "" if raw_args is None else str(raw_args)))
    return results


def _parse_fenced(text: str) -> list[tuple[str, str]]:
    """Parse fenced ``Tool:`` / ``ARGS:`` invocations from *text*."""
    results: list[tuple[str, str]] = []
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        return results

    for i, m in enumerate(matches):
        name = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]

        raw_lines = [ln.strip() for ln in body.split("\n")]
        # Drop leading/trailing blank lines.
        while raw_lines and raw_lines[0] == "":
            raw_lines.pop(0)
        while raw_lines and raw_lines[-1] == "":
            raw_lines.pop()

        args_lines: list[str] = []
        if raw_lines and _ARGS_RE.match(raw_lines[0]):
            # Strip the "ARGS:" marker from the first line; keep the rest.
            first = _ARGS_RE.sub("", raw_lines[0], count=1)
            if first:
                args_lines.append(first)
            args_lines.extend(raw_lines[1:])
        else:
            args_lines = raw_lines

        args = "\n".join(args_lines).strip()
        results.append((name, args))

    return results

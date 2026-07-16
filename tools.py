"""
Tool registry and built-in workspace tools.

Provides a generic ``Tool`` / ``ToolRegistry`` system plus two built-in
tools designed to interoperate with ``AgentEnvironment``:

* **file_sampler** — read file previews and schemas without loading the
  whole file into memory.
* **code_patcher** — create or patch workspace files, with optional
  Python syntax validation via the agent environment.

The ``ToolRegistry.register_defaults(env=...)`` method registers all
built-in tools and wires ``env`` into the tools that need it.
"""

from __future__ import annotations

import csv
import json
import os
import re
import socket
import sqlite3
import subprocess
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from environment import AgentEnvironment


# ===========================================================================
# Generic tool infrastructure
# ===========================================================================

class Tool:
    """A named, callable tool with metadata."""

    def __init__(self, name: str, fn: Callable[..., Any], description: str) -> None:
        self.name = name
        self.fn = fn
        self.description = description

    def __call__(self, **kwargs: Any) -> Any:
        return self.fn(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


class ToolRegistry:
    """A registry of named tools that can be looked up and executed."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, name: Optional[str] = None) -> Tool:
        """Register *tool* under *name* (defaults to ``tool.name``)."""
        key = name or tool.name
        self._tools[key] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def execute(self, name: str, **kwargs: Any) -> Any:
        """Look up and call a tool, forwarding *kwargs*."""
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool {name!r} not found in registry")
        return tool(**kwargs)

    def list(self) -> list[dict[str, Any]]:
        """Return metadata for all registered tools."""
        return [t.to_dict() for t in self._tools.values()]

    def register_defaults(self, env: Optional[AgentEnvironment] = None) -> None:
        """Register the built-in file-sampler and code-patcher tools.

        If *env* is provided the code-patcher tool will use it for
        Python syntax validation, and a ``python_runner`` tool will
        also be registered.
        """
        self.register(self._make_file_sampler())
        self.register(self._make_code_patcher(env))
        self.register(self._make_check_local_port())
        self.register(self._make_web_fetch())
        self.register(self._make_git_tool())
        self.register(self._make_db_sampler())
        if env is not None:
            self.register(self._make_python_runner(env))

    # ------------------------------------------------------------------
    # Built-in tool factories (static to avoid closures over self)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_web_fetch() -> Tool:
        return Tool(
            name="web_fetch",
            fn=_web_fetch,
            description=(
                "Fetch a URL and return its content as text. "
                "Supports HTTP and HTTPS. Timeout is 30 seconds."
            ),
        )

    @staticmethod
    def _make_git_tool() -> Tool:
        return Tool(
            name="git_tool",
            fn=_git_tool,
            description=(
                "Run a git operation in the workspace. "
                "Actions: 'status', 'diff', 'log', 'add', 'commit', 'diff_name'. "
                "Usage: git_tool(action='status')"
            ),
        )

    @staticmethod
    def _make_db_sampler() -> Tool:
        return Tool(
            name="db_sampler",
            fn=_db_sampler,
            description=(
                "Extract schema and sample rows from a SQLite database. "
                "Returns table list, column info, and up to 5 sample rows per table."
            ),
        )

    @staticmethod
    def _make_check_local_port() -> Tool:
        return Tool(
            name="check_local_port",
            fn=_check_local_port,
            description=(
                "Test whether a TCP port on a given host is open and "
                "accepting connections. Uses a 1-second timeout."
            ),
        )

    @staticmethod
    def _make_file_sampler() -> Tool:
        return Tool(
            name="file_sampler",
            fn=_file_sampler,
            description=(
                "Read a sample and optional schema from a local file "
                "without loading it entirely into memory. "
                "Supports CSV, JSON, JSONL/NDJSON, and plain-text formats."
            ),
        )

    @staticmethod
    def _make_code_patcher(env: Optional[AgentEnvironment] = None) -> Tool:
        if env is not None:
            # Filter out env from kwargs so callers can still pass it
            def _make_fn(**kw: Any) -> Any:
                return _code_patcher(
                    **{k: v for k, v in kw.items() if k != "env"}, env=env
                )
            fn: Callable[..., Any] = _make_fn
        else:
            fn = _code_patcher
        return Tool(
            name="code_patcher",
            fn=fn,
            description=(
                "Write or patch a workspace code file. "
                "Modes: 'write' (create/overwrite) or 'patch' (find/replace). "
                "Creates a .bak backup before modifying existing files. "
                "When env is configured, validates Python syntax after writing."
            ),
        )

    @staticmethod
    def _make_python_runner(env: AgentEnvironment) -> Tool:
        return Tool(
            name="python_runner",
            fn=lambda **kw: _python_runner(env=env, **kw),
            description=(
                "Execute a Python script string using the isolated "
                "agent_env interpreter. Returns stdout, stderr, and "
                "the return code."
            ),
        )


# ===========================================================================
# file_sampler — safe file extraction
# ===========================================================================

def _infer_type(values: list[str]) -> str:
    """Guess the data type of a column from a sample of string values."""
    n = len(values)
    if n == 0:
        return "string"
    ints = floats = bools = 0
    for v in values:
        v = v.strip()
        if not v:
            continue
        if v.lower() in ("true", "false"):
            bools += 1
        elif _is_int(v):
            ints += 1
        elif _is_float(v):
            floats += 1
    total = max(bools + ints + floats, 1)
    if ints / total >= 0.6:
        return "integer"
    if floats / total >= 0.6:
        return "float"
    if bools / total >= 0.6:
        return "boolean"
    return "string"


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except ValueError:
        return False


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def _sample_csv(path: Path, sample_bytes: int, encoding: str) -> dict[str, Any]:
    """Sample a CSV file, returning column schema and row preview."""
    with open(path, "r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = [c.strip() for c in next(reader)]
        except StopIteration:
            return {"format": "csv", "warning": "empty file", "rows": [], "columns": []}

        rows: list[list[str]] = []
        bytes_read = 0
        for row in reader:
            rows.append(row)
            bytes_read += sum(len(cell.encode(encoding)) for cell in row) + len(row)
            if bytes_read >= sample_bytes:
                break

    schema = [
        {"name": col, "type": _infer_type([r[i] for r in rows if i < len(r)])}
        for i, col in enumerate(header)
    ]

    return {
        "format": "csv",
        "file": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "columns": header,
        "schema": schema,
        "sample_rows": len(rows),
        "rows": rows[:50],
    }


def _sample_json(path: Path, sample_bytes: int, encoding: str) -> dict[str, Any]:
    """Sample a JSON file (object or array)."""
    file_size = path.stat().st_size
    with open(path, "r", encoding=encoding) as fh:
        chunk = fh.read(sample_bytes)

    try:
        data = json.loads(chunk)
    except json.JSONDecodeError:
        # chunk may be truncated; re-read entire file
        with open(path, "r", encoding=encoding) as fh:
            data = json.load(fh)

    if isinstance(data, dict):
        schema = [{"name": k, "type": type(v).__name__} for k, v in data.items()]
        return {
            "format": "json",
            "file": str(path),
            "size": file_size,
            "encoding": encoding,
            "type": "object",
            "schema": schema,
            "sample": data,
        }

    if isinstance(data, list):
        sample = data[:25]
        schema: list[dict[str, Any]] = []
        if sample and isinstance(sample[0], dict):
            schema = [
                {"name": k, "type": type(v).__name__}
                for k, v in sample[0].items()
            ]
        return {
            "format": "json",
            "file": str(path),
            "size": file_size,
            "encoding": encoding,
            "type": "array",
            "length": len(data),
            "schema": schema,
            "sample": sample,
        }

    return {
        "format": "json",
        "file": str(path),
        "size": file_size,
        "encoding": encoding,
        "type": "scalar",
        "sample": data,
    }


def _sample_jsonl(path: Path, sample_bytes: int, encoding: str) -> dict[str, Any]:
    """Sample a JSONL / NDJSON file."""
    records: list[dict[str, Any]] = []
    bytes_read = 0
    with open(path, "r", encoding=encoding) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            bytes_read += len(line.encode(encoding)) + 1
            if bytes_read >= sample_bytes:
                break

    schema: list[dict[str, Any]] = []
    if records and isinstance(records[0], dict):
        schema = [{"name": k, "type": type(v).__name__} for k, v in records[0].items()]

    return {
        "format": "jsonl",
        "file": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "schema": schema,
        "sample_records": records[:50],
        "record_count": len(records),
    }


_IMPORT_RE = re.compile(
    r"^(?:from\s+[\w.]+(?:\s+import\s+[\w.*]+(?:,\s*[\w.*]+)*)"
    r"|import\s+[\w.]+(?:,\s*[\w.]+)*)",
    re.MULTILINE,
)


def _sample_python(path: Path, sample_bytes: int, encoding: str) -> dict[str, Any]:
    """Sample a Python file — imports + preview."""
    lines: list[str] = []
    imports: list[str] = []
    bytes_read = 0
    with open(path, "r", encoding=encoding) as fh:
        for line in fh:
            lines.append(line.rstrip("\n\r"))
            bytes_read += len(line.encode(encoding))
            if bytes_read >= sample_bytes:
                break

    text = "\n".join(lines)
    imports = _IMPORT_RE.findall(text)

    return {
        "format": "py",
        "file": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "sampled_bytes": bytes_read,
        "sampled_lines": len(lines),
        "preview": lines[:100],
        "imports": list(dict.fromkeys(imports)),  # deduped, ordered
    }


def _sample_text(path: Path, sample_bytes: int, encoding: str) -> dict[str, Any]:
    """Sample a plain-text file (first N bytes)."""
    lines: list[str] = []
    bytes_read = 0
    with open(path, "r", encoding=encoding) as fh:
        for line in fh:
            lines.append(line.rstrip("\n\r"))
            bytes_read += len(line.encode(encoding))
            if bytes_read >= sample_bytes:
                break

    return {
        "format": path.suffix.lower().lstrip(".") or "text",
        "file": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "sampled_bytes": bytes_read,
        "sampled_lines": len(lines),
        "preview": lines[:100],
    }


def _file_sampler(
    file_path: str,
    sample_size: int = 1_048_576,
    infer_schema: bool = True,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Extract a sample and optional schema from a local file.

    The file is never fully loaded into memory; it is read in chunks
    up to *sample_size* bytes (default 1 MiB).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not path.is_file():
        raise IsADirectoryError(f"Not a file: {file_path}")

    ext = path.suffix.lower()

    if ext == ".csv":
        return _sample_csv(path, sample_size, encoding)
    if ext == ".json":
        return _sample_json(path, sample_size, encoding)
    if ext in (".jsonl", ".ndjson"):
        return _sample_jsonl(path, sample_size, encoding)
    if ext == ".py":
        return _sample_python(path, sample_size, encoding)
    return _sample_text(path, sample_size, encoding)


# ===========================================================================
# code_patcher — write / patch workspace files
# ===========================================================================

_FENCE_RE = re.compile(
    r"^```(?:python)?\s*\n?(.*?)```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_fences(text: str) -> str:
    """Strip outer ```python … ``` markdown fences from *text*.

    Handles content that LLMs wrap in fenced code blocks.  If fences
    are detected the inner code is returned; otherwise *text* is
    returned unchanged.
    """
    m = _FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text


def _code_patcher(
    file_path: str,
    content: str,
    mode: str = "write",
    old_string: str = "",
    create_backup: bool = True,
    env: Optional[AgentEnvironment] = None,
) -> dict[str, Any]:
    """Write or patch a file in the workspace.

    Parameters
    ----------
    file_path:
        Path to the target file (relative or absolute).
    content:
        New content (mode="write") or replacement text (mode="patch").
    mode:
        ``"write"`` to create or overwrite, ``"patch"`` to find/replace.
    old_string:
        Text to search for (only used when mode="patch").
    create_backup:
        Backup existing file with a ``.bak`` suffix before modifying.
    env:
        When provided, Python files are syntax-validated after writing.

    Returns a dict with ``file``, ``mode``, ``action``, and optionally
    ``syntax_check`` / ``syntax_error``.
    """
    path = Path(file_path).resolve()
    result: dict[str, Any] = {
        "file": str(path),
        "mode": mode,
        "backup_created": False,
    }

    # -- Backup -----------------------------------------------------------
    if create_backup and path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        result["backup_created"] = True
        result["backup_file"] = str(backup)

    # -- Write / patch ----------------------------------------------------
    if mode == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _strip_fences(content)
        path.write_text(content, encoding="utf-8")
        result["action"] = "created" if not path.exists() else "overwritten"
    elif mode == "patch":
        if not path.exists():
            raise FileNotFoundError(f"Cannot patch non-existent file: {file_path}")
        current = path.read_text(encoding="utf-8")
        if old_string not in current:
            raise ValueError(
                f"old_string not found in {file_path}. "
                "Use mode='write' to create a new file."
            )
        content = _strip_fences(content)
        updated = current.replace(old_string, content, 1)
        path.write_text(updated, encoding="utf-8")
        result["action"] = "patched"
    else:
        raise ValueError(f"Unknown mode: {mode!r} (expected 'write' or 'patch')")

    # -- Syntax check (Python only) ---------------------------------------
    if env is not None and path.suffix == ".py":
        try:
            proc = env.run(
                textwrap.dedent(f"""\
                import py_compile, sys
                try:
                    py_compile.compile({str(path)!r}, doraise=True)
                except py_compile.PyCompileError as e:
                    print(e, file=sys.stderr)
                    sys.exit(1)
                """)
            )
            result["syntax_check"] = "passed" if proc.returncode == 0 else "failed"
            if proc.returncode != 0:
                result["syntax_error"] = proc.stderr.strip()
        except Exception as exc:
            result["syntax_check"] = "skipped"
            result["syntax_warning"] = str(exc)

    result["size"] = path.stat().st_size
    return result


# ===========================================================================
# check_local_port — test TCP port reachability
# ===========================================================================


def _check_local_port(
    port: int,
    host: str = "127.0.0.1",
) -> str:
    """Check whether *port* on *host* is accepting TCP connections."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        result = sock.connect_ex((host, port))
        if result == 0:
            return f"SUCCESS: Port {port} on {host} is open and accepting connections."
        return f"FAILED: Port {port} on {host} is closed or unreachable."
    except socket.gaierror:
        return f"FAILED: Port {port} on {host} is closed or unreachable."
    finally:
        sock.close()


# ===========================================================================
# python_runner — execute scripts via agent_env
# ===========================================================================

def _python_runner(
    env: AgentEnvironment,
    script: str,
    cwd: Optional[str] = None,
) -> dict[str, Any]:
    """Run *script* using the isolated ``agent_env`` interpreter."""
    proc = env.run(script, cwd=cwd)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


# ===========================================================================
# web_fetch — fetch URL content
# ===========================================================================


def _web_fetch(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch *url* and return its text content."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "virgo/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return {"url": url, "status": resp.status, "content": content[:100_000]}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


# ===========================================================================
# git_tool — basic git operations
# ===========================================================================


def _git_tool(action: str = "status") -> dict[str, Any]:
    """Run a git operation. Actions: status, diff, log, add, commit, diff_name."""
    valid = {"status", "diff", "log", "add", "commit", "diff_name"}
    if action not in valid:
        return {"error": f"Unknown action {action!r}. Valid: {', '.join(sorted(valid))}"}

    cmd = ["git"]
    if action == "status":
        cmd.append("status")
    elif action == "diff":
        cmd.extend(["diff", "--stat"])
    elif action == "diff_name":
        cmd.append("diff")
    elif action == "log":
        cmd.extend(["log", "--oneline", "-10"])
    elif action == "add":
        cmd.append("add")
    elif action == "commit":
        cmd.extend(["commit", "-m"])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
        return {
            "action": action,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip()[:5000],
            "stderr": proc.stderr.strip()[:2000],
        }
    except Exception as exc:
        return {"action": action, "error": str(exc)}


# ===========================================================================
# db_sampler — SQLite schema extraction
# ===========================================================================


def _db_sampler(file_path: str, max_rows: int = 5) -> dict[str, Any]:
    """Extract schema and sample rows from a SQLite database."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {file_path}")
    if path.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        raise ValueError(f"Not a SQLite file: {file_path}")

    try:
        conn = sqlite3.connect(str(path))
        cursor = conn.cursor()

        # Get all tables and views
        cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        objects = cursor.fetchall()

        tables = []
        for name, obj_type in objects:
            # Column info
            cursor.execute(f'PRAGMA table_info("{name}")')
            columns = [
                {"name": row[1], "type": row[2], "notnull": bool(row[3]), "default": row[4]}
                for row in cursor.fetchall()
            ]

            # Row count
            cursor.execute(f'SELECT COUNT(*) FROM "{name}"')
            row_count = cursor.fetchone()[0]

            # Sample rows
            samples = []
            if row_count > 0:
                cursor.execute(f'SELECT * FROM "{name}" LIMIT {max_rows}')
                samples = [list(row) for row in cursor.fetchall()]

            tables.append({
                "name": name,
                "type": obj_type,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": samples,
            })

        conn.close()
        return {"file": str(path), "tables": tables}

    except sqlite3.Error as exc:
        return {"file": str(path), "error": str(exc)}

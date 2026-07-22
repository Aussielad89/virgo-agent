"""
virgo_diff — diff two pipeline sessions showing metadata, files,
and content changes.

Usage::

    python virgo_diff.py <session-A> <session-B> [--brief] [--output file]
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon
from _log import log
from memory import load_state

# ===========================================================================
# Resolve & validate
# ===========================================================================


def resolve_session(name_or_path: str) -> dict[str, Any]:
    """Load a session dict by name (lookup in .virgo_memory/) or file path.

    Delegates to ``memory.load_state()`` which handles both conventions.
    """
    try:
        data = load_state(name_or_path)
    except FileNotFoundError:
        print(f"  {icon('error')} Session not found: {name_or_path}")
        sys.exit(1)
    except Exception as exc:
        print(f"  {icon('error')} Error loading {name_or_path!r}: {exc}")
        sys.exit(1)
    return data


# ===========================================================================
# Core diff logic
# ===========================================================================


def _safe_get(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Get nested value from a dict, returning *default* on missing keys."""
    val: Any = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val


def _files_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a ``{file_path: file_dict}`` index from *data*."""
    idx: dict[str, dict[str, Any]] = {}
    for f in data.get("discovered_files", []):
        if isinstance(f, dict) and "path" in f:
            idx[f["path"]] = f
    for f in data.get("generated_files", []):
        if isinstance(f, dict) and "path" in f:
            # Generated files take precedence for content diff
            idx[f["path"]] = f
    return idx


def _format_plans(data: dict[str, Any]) -> list[str]:
    """Extract plans as a list, handling both ``plan`` (str) and ``plans`` (list)."""
    plans_list: list[str] = []
    if "plans" in data and isinstance(data["plans"], list):
        for p in data["plans"]:
            if isinstance(p, str):
                plans_list.append(p)
    elif "plan" in data and isinstance(data["plan"], str) and data["plan"].strip():
        plans_list.append(data["plan"])
    return plans_list


def diff_sessions(
    session_a: dict[str, Any],
    session_b: dict[str, Any],
    brief: bool = False,
) -> dict[str, Any]:
    """Compare two session dicts and return a structured diff.

    Returns a dict with keys:
        - meta_a / meta_b: summary fields from each session
        - only_a: files present in A only
        - only_b: files present in B only
        - common: list of {path, status, diff} for shared files
        - plans_a / plans_b: plan text(s) from each session
    """
    result: dict[str, Any] = {
        "meta_a": {
            "name": session_a.get("name", ""),
            "goal": session_a.get("goal", ""),
            "phase": session_a.get("phase", ""),
            "iteration": session_a.get("iteration", 0),
            "max_iterations": session_a.get("max_iterations", 0),
            "loop_passed": session_a.get("loop_passed"),
            "generated_count": len(session_a.get("generated_files", [])),
            "discovered_count": len(session_a.get("discovered_files", [])),
        },
        "meta_b": {
            "name": session_b.get("name", ""),
            "goal": session_b.get("goal", ""),
            "phase": session_b.get("phase", ""),
            "iteration": session_b.get("iteration", 0),
            "max_iterations": session_b.get("max_iterations", 0),
            "loop_passed": session_b.get("loop_passed"),
            "generated_count": len(session_b.get("generated_files", [])),
            "discovered_count": len(session_b.get("discovered_files", [])),
        },
        "plans_a": _format_plans(session_a),
        "plans_b": _format_plans(session_b),
    }

    idx_a = _files_index(session_a)
    idx_b = _files_index(session_b)

    paths_a = set(idx_a.keys())
    paths_b = set(idx_b.keys())

    result["only_a"] = sorted(paths_a - paths_b)
    result["only_b"] = sorted(paths_b - paths_a)

    common_paths = sorted(paths_a & paths_b)
    common_entries: list[dict[str, Any]] = []
    for p in common_paths:
        entry: dict[str, Any] = {"path": p}
        fa = idx_a[p]
        fb = idx_b[p]

        # If both have content, compare it
        if "content" in fa and "content" in fb:
            if fa["content"] == fb["content"]:
                entry["status"] = "identical"
                entry["diff"] = ""
            else:
                entry["status"] = "modified"
                if not brief:
                    a_lines = fa["content"].splitlines(keepends=True)
                    b_lines = fb["content"].splitlines(keepends=True)
                    diff_lines = list(
                        difflib.unified_diff(
                            a_lines,
                            b_lines,
                            fromfile=f"a/{p}",
                            tofile=f"b/{p}",
                            lineterm="",
                        )
                    )
                    entry["diff"] = "".join(diff_lines)
                else:
                    entry["diff"] = ""
        elif "content" in fa or "content" in fb:
            entry["status"] = "content_mismatch"  # one has content, the other metadata only
            entry["diff"] = ""
        else:
            entry["status"] = "same_metadata"
            entry["diff"] = ""

        common_entries.append(entry)

    result["common"] = common_entries
    return result


# ===========================================================================
# Rendering
# ===========================================================================


def _status_icon(status: str) -> str:
    icons = {
        "identical": icon("ok"),
        "modified": icon("code"),
        "content_mismatch": icon("warn"),
        "same_metadata": icon("check"),
    }
    return icons.get(status, icon("info"))


def render_diff(diff: dict[str, Any], output_path: str | None = None) -> str:
    """Render a diff dict as a human-readable string.

    If *output_path* is provided, the output is also written to that file
    (plain text).  Returns the rendered string.
    """
    lines: list[str] = []
    _w = lines.append  # local alias for speed

    _w("")
    _w(f"  {'=' * 70}")
    _w(f"  {icon('virgo')}  Session Compare")
    _w(f"  {'=' * 70}")
    _w("")

    # -- Metadata side-by-side -------------------------------------------
    _w(f"  {'─' * 70}")
    _w("  Metadata")
    _w(f"  {'─' * 70}")
    _w("")
    _w(f"  {'Field':<30s}  {'Session A':<40s}  {'Session B'}")
    _w(f"  {'─' * 30}  {'─' * 40}  {'─' * 20}")

    ma = diff["meta_a"]
    mb = diff["meta_b"]

    fields = [
        ("Name", ma.get("name", ""), mb.get("name", "")),
        ("Goal", ma.get("goal", "")[:50], mb.get("goal", "")[:50]),
        ("Phase", ma.get("phase", ""), mb.get("phase", "")),
        ("Iteration", str(ma.get("iteration", 0)), str(mb.get("iteration", 0))),
        ("Max iterations", str(ma.get("max_iterations", 0)), str(mb.get("max_iterations", 0))),
        ("Loop passed", str(ma.get("loop_passed", "?")), str(mb.get("loop_passed", "?"))),
        ("Discovered", str(ma.get("discovered_count", 0)), str(mb.get("discovered_count", 0))),
        ("Generated", str(ma.get("generated_count", 0)), str(mb.get("generated_count", 0))),
    ]

    for label, va, vb in fields:
        marker = "  " if va == vb else "≠ "
        _w(f"  {marker}{label:<28s}  {va:<40s}  {vb}")

    _w("")

    # -- Plans -----------------------------------------------------------
    plans_a = diff.get("plans_a", [])
    plans_b = diff.get("plans_b", [])

    if plans_a or plans_b:
        _w(f"  {'─' * 70}")
        _w("  Plans")
        _w(f"  {'─' * 70}")
        _w("")
        if plans_a:
            _w(f"  {icon('brain')}  Session A plans:")
            _w(f"  {'─' * 30}")
            for i, p in enumerate(plans_a, 1):
                _w(f"    [{i}] {p[:200]}")
        else:
            _w(f"  {icon('info')}  Session A: no plans recorded")
        _w("")
        if plans_b:
            _w(f"  {icon('brain')}  Session B plans:")
            _w(f"  {'─' * 30}")
            for i, p in enumerate(plans_b, 1):
                _w(f"    [{i}] {p[:200]}")
        else:
            _w(f"  {icon('info')}  Session B: no plans recorded")
        _w("")

    # -- Files only in A -------------------------------------------------
    only_a = diff.get("only_a", [])
    only_b = diff.get("only_b", [])
    common = diff.get("common", [])

    _w(f"  {'─' * 70}")
    _w("  Files")
    _w(f"  {'─' * 70}")
    _w("")

    if only_a:
        _w(f"  {icon('arrow')}  Files only in Session A ({len(only_a)}):")
        for fp in only_a:
            _w(f"    {icon('file')}  {fp}")
        _w("")
    else:
        _w(f"  {icon('ok')}  No files unique to Session A")
        _w("")

    if only_b:
        _w(f"  {icon('arrow')}  Files only in Session B ({len(only_b)}):")
        for fp in only_b:
            _w(f"    {icon('file')}  {fp}")
        _w("")
    else:
        _w(f"  {icon('ok')}  No files unique to Session B")
        _w("")

    # -- Common files ----------------------------------------------------
    if common:
        modified = [e for e in common if e["status"] == "modified"]
        identical = [e for e in common if e["status"] == "identical"]
        others = [e for e in common if e["status"] not in ("modified", "identical")]

        _w(f"  {'─' * 70}")
        _w(f"  Common files ({len(common)} total)")
        _w(f"  {'─' * 70}")
        _w("")

        if identical:
            if not only_a and not only_b:
                _w(f"  {icon('ok')}  All {len(identical)} common files identical")
            else:
                _w(f"  {icon('ok')}  {len(identical)} file(s) identical across both sessions")

        if modified:
            _w("")
            _w(f"  {icon('code')}  Modified files ({len(modified)}):")
            for entry in modified:
                _w(f"    {icon('file')}  {entry['path']}")
                if entry.get("diff"):
                    # Indent each diff line for readability
                    for dline in entry["diff"].splitlines(keepends=True):
                        _w(f"      {dline.rstrip()}")
                    _w("")

        if others:
            for entry in others:
                st = entry["status"]
                _w(f"    {_status_icon(st)}  {entry['path']}  [{st}]")

    _w("")
    _w(f"  {'=' * 70}")
    _w(f"  {icon('done')}  Compare complete")
    _w(f"  {'=' * 70}")
    _w("")

    rendered = "\n".join(lines)

    if output_path:
        out = Path(output_path)
        out.write_text(rendered, encoding="utf-8")
        print(f"  {icon('save')}  Diff report written to: {out.resolve()}")
    else:
        print(rendered, end="")

    return rendered


# ===========================================================================
# CLI entry point
# ===========================================================================


def cmd_diff(args: argparse.Namespace) -> None:
    """Compare two saved sessions."""
    log.info("Diffing sessions: %s vs %s", args.session_a, args.session_b)

    data_a = resolve_session(args.session_a)
    data_b = resolve_session(args.session_b)

    diff = diff_sessions(data_a, data_b, brief=args.brief)
    render_diff(diff, output_path=args.output)


def main() -> None:
    """Standalone entry point for ``python virgo_diff.py``."""
    parser = argparse.ArgumentParser(
        prog="virgo-diff",
        description="Compare two pipeline sessions",
    )
    parser.add_argument("session_a", help="First session name or .json path")
    parser.add_argument("session_b", help="Second session name or .json path")
    parser.add_argument(
        "--brief",
        "-b",
        action="store_true",
        help="Only list file names, no content diffs",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write diff report to a file (.md or .txt)",
    )
    args = parser.parse_args()
    cmd_diff(args)


if __name__ == "__main__":
    main()

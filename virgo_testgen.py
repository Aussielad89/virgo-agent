"""
virgo_testgen — generate pytest test stubs from Python source files.

Scans Python files using AST, extracts functions and class methods,
and generates ``pytest``-style test files with placeholder stubs.

Usage::

    virgo testgen --path ./module.py
    virgo testgen --dir ./src --output ./tests --overwrite
    python virgo_testgen.py --path ./module.py
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

from _console import icon
from _log import log

HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------


def _extract_functions(tree: ast.Module, source: str) -> list[dict]:
    """Return module-level functions with signatures and docstrings."""
    items: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            items.append(
                {
                    "name": node.name,
                    "type": "async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function",
                    "doc": doc.split("\n")[0] if doc else "",
                    "args": _extract_args(node),
                    "returns": _type_name(node.returns),
                }
            )
    return items


def _extract_classes(tree: ast.Module, source: str) -> list[dict]:
    """Return classes with their methods and ``__init__`` signature."""
    classes: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            methods: list[dict] = []
            init_args: list[dict] = []
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(item) or ""
                    entry = {
                        "name": item.name,
                        "type": "async_method"
                        if isinstance(item, ast.AsyncFunctionDef)
                        else "method",
                        "doc": doc.split("\n")[0] if doc else "",
                        "args": _extract_args(item),
                        "returns": _type_name(item.returns),
                    }
                    if item.name == "__init__":
                        init_args = entry["args"]
                    else:
                        methods.append(entry)
            doc = ast.get_docstring(node) or ""
            classes.append(
                {
                    "name": node.name,
                    "type": "class",
                    "doc": doc.split("\n")[0] if doc else "",
                    "init_args": init_args,
                    "methods": methods,
                }
            )
    return classes


def _literal(node) -> str | None:
    """Return a ``repr`` string for a default value, or None if not a literal."""
    try:
        return repr(ast.literal_eval(node))
    except Exception:
        return None


def _type_name(node) -> str | None:
    """Best-effort string name of a type annotation node."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        base = _type_name(node.value)
        return base.lower() if base else None
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return None


def _extract_args(node) -> list[dict]:
    """Extract parameter metadata (name, annotation, default) for *node*."""
    a = node.args
    pos = list(a.posonlyargs) + list(a.args)
    n = len(pos)
    defaults = list(a.defaults)
    args: list[dict] = []
    for i, arg in enumerate(pos):
        default = None
        if defaults:
            idx = i - (n - len(defaults))
            if 0 <= idx < len(defaults):
                default = _literal(defaults[idx])
        args.append(
            {
                "name": arg.arg,
                "ann": _type_name(arg.annotation),
                "default": default,
            }
        )
    for j, arg in enumerate(a.kwonlyargs):
        default = _literal(a.kw_defaults[j]) if a.kw_defaults else None
        args.append(
            {
                "name": arg.arg,
                "ann": _type_name(arg.annotation),
                "default": default,
            }
        )
    if args and args[0]["name"] in ("self", "cls"):
        args = args[1:]
    return args


def _example_value(ann: str | None, default: str | None) -> str:
    """Pick a safe example argument value from a type annotation / default."""
    if default is not None:
        return default
    if ann in ("int", "float"):
        return "0"
    if ann == "bool":
        return "True"
    if ann == "str":
        return '"sample"'
    if ann in ("list", "tuple", "set"):
        return "[]" if ann != "set" else "set()"
    if ann == "dict":
        return "{}"
    return "None"


def _call_args(args: list[dict]) -> str:
    """Build an argument list string from extracted parameter metadata."""
    return ", ".join(_example_value(a["ann"], a["default"]) for a in args)


def _return_assert(ann: str | None) -> str | None:
    """Return an assertion snippet checking the contract of *ann*, if known."""
    mapping = {
        "int": "isinstance(result, int)",
        "float": "isinstance(result, float)",
        "bool": "isinstance(result, bool)",
        "str": "isinstance(result, str)",
        "list": "isinstance(result, list)",
        "dict": "isinstance(result, dict)",
        "tuple": "isinstance(result, tuple)",
        "set": "isinstance(result, set)",
    }
    return mapping.get(ann)


def analyze_file(path: Path) -> dict:
    """Parse *path* with AST and return structured metadata.

    Returns a dict with keys:
        - path
        - functions (list of {name, type, doc})
        - classes (list of {name, type, doc, methods})
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        log.warning("Syntax error in %s: %s", path.name, exc)
        return {"path": str(path), "functions": [], "classes": []}

    return {
        "path": str(path),
        "functions": _extract_functions(tree, source),
        "classes": _extract_classes(tree, source),
    }


# ---------------------------------------------------------------------------
# Test generation
# ---------------------------------------------------------------------------


def _safe_module_name(path: Path) -> str:
    """Derive a safe module name from *path* (e.g. 'virgo_testgen')."""
    stem = path.stem
    # Replace non-identifier characters with underscores
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in stem)
    if safe and safe[0].isdigit():
        safe = f"_{safe}"
    return safe or "module"


def _generate_test_content(analysis: dict, rel_path: str) -> str:
    """Generate pytest test file content for one Python module.

    Produces runnable *smoke tests*: each public symbol is called with
    example arguments derived from its signature, and the return value
    (when annotated) is checked against its declared type.
    """
    lines: list[str] = []
    lines.append(f'"""Tests for {rel_path} — auto-generated by virgo testgen."""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import pytest")
    lines.append("")

    import_path = rel_path.replace(os.sep, ".").replace("/", ".").replace("\\", ".")
    if import_path.endswith(".py"):
        import_path = import_path[:-3]
    lines.append(f"import {import_path}  # module under test")
    lines.append("")
    needs_asyncio = False

    # ----- Functions -----
    for fn in analysis.get("functions", []):
        name = fn["name"]
        if name.startswith("_"):  # skip private / dunder
            continue
        doc = fn.get("doc", "")
        stub_doc = f" # {doc}" if doc else ""
        call = _call_args(fn.get("args", []))
        is_async = fn["type"] == "async_function"
        if is_async:
            needs_asyncio = True
            invoke = f"asyncio.run({import_path}.{name}({call}))"
        else:
            invoke = f"{import_path}.{name}({call})"
        ra = _return_assert(fn.get("returns"))
        lines.append("")
        lines.append(f"def test_{name}():")
        lines.append(f'    """Smoke test for {name}{stub_doc}."""')
        lines.append(f"    result = {invoke}")
        if ra:
            lines.append(f"    assert {ra}")
        else:
            lines.append("    assert result is not None or result is None  # callable ran")
        lines.append("")

    # ----- Classes -----
    for cls in analysis.get("classes", []):
        cls_name = cls["name"]
        init_call = _call_args(cls.get("init_args", []))
        for method in cls.get("methods", []):
            mname = method["name"]
            if mname.startswith("_"):
                continue
            doc = method.get("doc", "")
            stub_doc = f" # {doc}" if doc else ""
            call = _call_args(method.get("args", []))
            is_async = method["type"] == "async_method"
            if is_async:
                needs_asyncio = True
                invoke = f"asyncio.run(obj.{mname}({call}))"
            else:
                invoke = f"obj.{mname}({call})"
            ra = _return_assert(method.get("returns"))
            lines.append("")
            lines.append(f"def test_{cls_name}_{mname}():")
            lines.append(f'    """Smoke test for {cls_name}.{mname}{stub_doc}."""')
            lines.append(f"    obj = {import_path}.{cls_name}({init_call})")
            lines.append(f"    result = {invoke}")
            if ra:
                lines.append(f"    assert {ra}")
            else:
                lines.append("    assert result is not None or result is None  # callable ran")
            lines.append("")

    if needs_asyncio:
        for i, l in enumerate(lines):
            if l.startswith("import ") and "module under test" in l:
                lines.insert(i + 1, "import asyncio")
                break
    return "\n".join(lines)


def generate_tests(
    path: str | Path,
    output_dir: str | Path = "./tests",
    overwrite: bool = False,
) -> list[Path]:
    """Generate test files for the Python source at *path*.

    Parameters
    ----------
    path:
        File or directory to scan.  Directories are walked recursively.
    output_dir:
        Directory where test files are written.
    overwrite:
        If True, overwrite existing test files without warning.

    Returns
    -------
    List of Paths to generated test files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    source_path = Path(path)
    if not source_path.exists():
        log.error("Path does not exist: %s", source_path)
        return []

    # Collect Python files
    if source_path.is_file():
        py_files = [source_path] if source_path.suffix == ".py" else []
    else:
        py_files = sorted(source_path.rglob("*.py"))

    if not py_files:
        log.warning("No .py files found at %s", source_path)
        return []

    generated: list[Path] = []

    for py_file in py_files:
        log.info("Analyzing %s", py_file)
        analysis = analyze_file(py_file)

        # Determine relative path for import statement
        try:
            rel = py_file.relative_to(source_path.parent if source_path.is_file() else source_path)
        except ValueError:
            rel = py_file.name

        content = _generate_test_content(analysis, str(rel))
        if not content.strip():
            log.info("  Skipped %s (no public symbols)", py_file.name)
            continue

        test_name = f"test_{py_file.stem}.py"
        out_file = output_path / test_name

        if out_file.exists() and not overwrite:
            log.warning("  Skipped (exists, use --overwrite): %s", out_file)
            continue

        out_file.write_text(content, encoding="utf-8")
        generated.append(out_file)
        log.info("  -> %s", out_file)

    return generated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for ``virgo testgen``."""
    parser = argparse.ArgumentParser(
        prog="virgo testgen",
        description="Generate pytest test stubs from Python source files.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--path",
        "-p",
        help="Single Python file to analyze.",
    )
    group.add_argument(
        "--dir",
        "-d",
        help="Directory to scan recursively for .py files.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./tests",
        help="Output directory for generated test files (default: ./tests).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing test files without warning.",
    )

    args = parser.parse_args(argv)

    source = args.path or args.dir
    if not source:
        parser.print_help()
        sys.exit(1)

    print(f"\n{icon('test')}  Generating tests from: {source}")
    results = generate_tests(
        path=source,
        output_dir=args.output,
        overwrite=args.overwrite,
    )

    if results:
        print(f"\n  {icon('ok')}  Generated {len(results)} test file(s) in {args.output}/")
        for f in results:
            print(f"     {icon('file')} {f}")
        print()
    else:
        print(f"\n  {icon('info')}  No test files were generated.\n")


if __name__ == "__main__":
    main()

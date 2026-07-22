#!/usr/bin/env python3
"""\
virgo_docgen — AST-based Python documentation generator.

Scans Python files, extracts docstrings from modules, classes, functions,
and methods, and generates Markdown or HTML API reference documentation.

Usage::

    virgo doc --path . --output docs/ --format md --recursive
    python virgo_docgen.py --path ./src --output docs/ --name "My Project"

Output formats:

    ``md`` (default)
        Generates one ``.md`` file per module, plus an index.
        Each file contains module docstring, class hierarchy, function
        signatures with docstrings, and cross-module links.

    ``html``
        Same content rendered as an HTML page with dark-theme styling.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ===========================================================================
# Data model
# ===========================================================================


@dataclass
class FunctionDoc:
    """Extracted documentation for a single function or method."""

    name: str
    signature: str
    docstring: str
    lineno: int = 0
    is_method: bool = False
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)


@dataclass
class ClassDoc:
    """Extracted documentation for a single class."""

    name: str
    docstring: str
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionDoc] = field(default_factory=list)
    lineno: int = 0
    decorators: list[str] = field(default_factory=list)


@dataclass
class ModuleDoc:
    """Extracted documentation for a single Python module (file)."""

    file_path: str
    module_name: str
    docstring: str
    classes: list[ClassDoc] = field(default_factory=list)
    functions: list[FunctionDoc] = field(default_factory=list)
    lineno: int = 0


# ===========================================================================
# AST extraction
# ===========================================================================


def _get_docstring(node: ast.AST) -> str:
    """Extract the docstring from an AST node, returning empty string if none."""
    try:
        doc = ast.get_docstring(node, clean=True)
        return doc or ""
    except Exception:
        return ""


def _get_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    """Extract decorator names from an AST node."""
    result: list[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            result.append(f"@{dec.func.id}")
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            result.append(f"@{ast.unparse(dec.func)}()")
        elif isinstance(dec, ast.Name):
            result.append(f"@{dec.id}")
        elif isinstance(dec, ast.Attribute):
            result.append(f"@{ast.unparse(dec)}")
        else:
            try:
                result.append(f"@{ast.unparse(dec)}")
            except Exception:
                result.append("@?")
    return result


def _get_bases(node: ast.ClassDef) -> list[str]:
    """Extract base class names from a class definition."""
    bases: list[str] = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:
            bases.append("?")
    return bases


def _get_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a compact signature string from a function definition node."""
    args = node.args
    parts: list[str] = []

    # Positional args
    for i, arg in enumerate(args.args):
        if i == 0 and getattr(arg, "arg", "") in ("self", "cls"):
            # Omit self/cls from signature
            continue
        arg_str = arg.arg
        if arg.annotation:
            try:
                anno = ast.unparse(arg.annotation)
                arg_str += f": {anno}"
            except Exception:
                pass
        parts.append(arg_str)

    # *args
    if args.vararg:
        arg_str = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            try:
                anno = ast.unparse(args.vararg.annotation)
                arg_str += f": {anno}"
            except Exception:
                pass
        parts.append(arg_str)
    elif args.kwonlyargs and not args.vararg:
        parts.append("*")

    # Keyword-only args
    for arg in args.kwonlyargs:
        arg_str = arg.arg
        if arg.annotation:
            try:
                anno = ast.unparse(arg.annotation)
                arg_str += f": {anno}"
            except Exception:
                pass
        parts.append(arg_str)

    # **kwargs
    if args.kwarg:
        arg_str = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            try:
                anno = ast.unparse(args.kwarg.annotation)
                arg_str += f": {anno}"
            except Exception:
                pass
        parts.append(arg_str)

    sig = ", ".join(parts)

    # Return annotation
    returns = ""
    if node.returns:
        try:
            returns = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass

    return f"({sig}){returns}"


def extract_docstrings(file_path: str) -> ModuleDoc | None:
    """Parse a Python file and extract all docstrings.

    Args:
        file_path: Path to a ``.py`` file.

    Returns:
        A ``ModuleDoc`` with module docstring, classes (with methods),
        and top-level functions, or ``None`` if the file cannot be parsed.
    """
    path = Path(file_path)
    if not path.exists():
        return None
    if path.suffix != ".py":
        return None

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return None

    module_name = path.stem
    if module_name == "__init__":
        # Use the parent directory name for __init__.py
        module_name = path.parent.name
    if not module_name:
        # Fall back to file name (before suffix) for edge cases
        module_name = path.name.replace(path.suffix, "") or "module"

    doc = _get_docstring(tree)
    classes: list[ClassDoc] = []
    functions: list[FunctionDoc] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            cls = _extract_class(node)
            classes.append(cls)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = _extract_function(node)
            functions.append(func)

    return ModuleDoc(
        file_path=str(path.resolve()),
        module_name=module_name,
        docstring=doc,
        classes=classes,
        functions=functions,
    )


def _extract_class(node: ast.ClassDef) -> ClassDoc:
    """Extract ClassDoc from an AST ClassDef node."""
    methods: list[FunctionDoc] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = _extract_function(item, is_method=True)
            methods.append(func)

    return ClassDoc(
        name=node.name,
        docstring=_get_docstring(node),
        bases=_get_bases(node),
        methods=methods,
        lineno=node.lineno,
        decorators=_get_decorators(node),
    )


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_method: bool = False,
) -> FunctionDoc:
    """Extract FunctionDoc from an AST FunctionDef or AsyncFunctionDef node."""
    return FunctionDoc(
        name=node.name,
        signature=_get_signature(node),
        docstring=_get_docstring(node),
        lineno=node.lineno,
        is_method=is_method,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=_get_decorators(node),
    )


def scan_directory(
    path: str,
    recursive: bool = False,
    exclude_dirs: list[str] | None = None,
) -> list[ModuleDoc]:
    """Scan a directory for Python files and extract docstrings.

    Skips common non-source directories by default (``.git``,
    ``__pycache__``, ``node_modules``, ``agent_env``, ``.venv``,
    ``.mypy_cache``, ``.pytest_cache``, ``.crush``, ``dist``,
    ``virgo_agent.egg-info``, ``.github``).

    Args:
        path: Directory path to scan.
        recursive: If True, walk subdirectories recursively.
        exclude_dirs: Additional directory names to skip. These are
            added to a built-in skip list.

    Returns:
        List of ``ModuleDoc`` objects for all parseable ``.py`` files.
    """
    root = Path(path)
    if not root.is_dir():
        # Single file
        doc = extract_docstrings(path)
        return [doc] if doc else []

    skip_dirs = {
        ".git",
        "__pycache__",
        "node_modules",
        "agent_env",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".crush",
        "dist",
        "virgo_agent.egg-info",
        ".github",
        ".hg",
        ".svn",
        "venv",
        "env",
        ".tox",
        "build",
        "*.egg-info",
    }
    if exclude_dirs:
        skip_dirs.update(exclude_dirs)

    modules: list[ModuleDoc] = []

    if recursive:
        iterator = root.rglob("*.py")
    else:
        iterator = root.glob("*.py")

    for py_file in sorted(iterator):
        # Skip files in excluded directories
        # Use the relative path parts to check against skip list
        try:
            rel = py_file.relative_to(root)
            parts = rel.parts[:-1]  # all parts except the filename
        except ValueError:
            parts = py_file.parts[:-1]
        if any(p in skip_dirs or p.endswith(".egg-info") for p in parts):
            continue
        doc = extract_docstrings(str(py_file))
        if doc:
            modules.append(doc)

    return modules


# ===========================================================================
# Helpers
# ===========================================================================


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rel_path(file_path: str, base_dir: str) -> str:
    """Get a relative path from base_dir to file_path."""
    try:
        return str(Path(file_path).relative_to(Path(base_dir).resolve()))
    except ValueError:
        return file_path


def _module_to_ref(module_name: str) -> str:
    """Convert a module name to a valid anchor reference."""
    return module_name.replace(".", "-").replace("/", "-").replace("\\", "-")


def _docstring_summary(docstring: str, max_len: int = 80) -> str:
    """Return the first line/sentence of a docstring."""
    if not docstring:
        return ""
    first_line = docstring.lstrip().split("\n")[0]
    if len(first_line) > max_len:
        first_line = first_line[: max_len - 3] + "..."
    return first_line


# ===========================================================================
# Markdown generation
# ===========================================================================


def generate_markdown(
    modules: list[ModuleDoc],
    project_name: str = "virgo",
    output_dir: str = "docs",
    base_dir: str | None = None,
) -> list[Path]:
    """Generate Markdown API reference documentation.

    Writes one ``.md`` file per module plus an ``index.md`` summary.
    All files are placed under *output_dir*.

    Args:
        modules: List of ``ModuleDoc`` objects to document.
        project_name: Display name for the project.
        output_dir: Output directory for generated files.
        base_dir: Base directory for computing relative paths (defaults to
            the common ancestor of all module paths).

    Returns:
        List of paths to the generated files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Determine base dir
    if base_dir is None:
        if modules:
            # Use common ancestor
            paths = [Path(m.file_path) for m in modules if m.file_path]
            if paths:
                base_dir = str(os.path.commonpath(paths))
            else:
                base_dir = "."
        else:
            base_dir = "."

    written: list[Path] = []

    # ── Index page ──────────────────────────────────────────────────────
    index_path = out / "index.md"
    index_lines = _build_markdown_index(modules, project_name, base_dir)
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    written.append(index_path)

    # ── Per-module pages ────────────────────────────────────────────────
    for mod in modules:
        md_lines = _build_markdown_module(mod, base_dir, modules)
        file_stem = _module_to_ref(mod.module_name)
        module_path = out / f"{file_stem}.md"
        module_path.write_text("\n".join(md_lines), encoding="utf-8")
        written.append(module_path)

    return written


def _build_markdown_index(
    modules: list[ModuleDoc],
    project_name: str,
    base_dir: str,
) -> list[str]:
    """Build the index.md content lines."""
    lines: list[str] = []
    lines.append(f"# {project_name} — API Reference")
    lines.append("")
    lines.append(f"Generated on {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"**{len(modules)} module(s)** documented.")
    lines.append("")

    # Module summary table
    lines.append("## Module Index")
    lines.append("")
    lines.append("| Module | File | Summary |")
    lines.append("|--------|------|---------|")
    for mod in modules:
        ref = _module_to_ref(mod.module_name)
        rel = _rel_path(mod.file_path, base_dir)
        summary = _docstring_summary(mod.docstring, 60)
        lines.append(f"| [{mod.module_name}]({ref}.md) | `{rel}` | {summary} |")
    lines.append("")

    # Class index
    all_classes: list[tuple[str, str, str]] = []
    for mod in modules:
        for cls in mod.classes:
            ref = _module_to_ref(mod.module_name)
            all_classes.append((cls.name, cls.docstring, ref))

    if all_classes:
        lines.append("## Classes")
        lines.append("")
        lines.append("| Class | Module | Summary |")
        lines.append("|-------|--------|---------|")
        for name, docstring, mod_ref in all_classes:
            summary = _docstring_summary(docstring, 60)
            lines.append(
                f"| [{name}]({mod_ref}.md#{_module_to_ref(name)}) | `{mod_ref}` | {summary} |"
            )
        lines.append("")

    # Function index
    all_funcs: list[tuple[str, str, str]] = []
    for mod in modules:
        for func in mod.functions:
            ref = _module_to_ref(mod.module_name)
            all_funcs.append((func.name, func.docstring, ref))

    if all_funcs:
        lines.append("## Functions")
        lines.append("")
        lines.append("| Function | Module | Summary |")
        lines.append("|----------|--------|---------|")
        for name, docstring, mod_ref in all_funcs:
            summary = _docstring_summary(docstring, 60)
            lines.append(
                f"| [{name}]({mod_ref}.md#{_module_to_ref(name)}) | `{mod_ref}` | {summary} |"
            )
        lines.append("")

    return lines


def _build_markdown_module(
    mod: ModuleDoc,
    base_dir: str,
    all_modules: list[ModuleDoc],
) -> list[str]:
    """Build the content lines for a single module .md file."""
    lines: list[str] = []
    rel = _rel_path(mod.file_path, base_dir)

    # Heading
    lines.append(f"# `{mod.module_name}`")
    lines.append("")
    lines.append(f"**File:** `{rel}`")
    lines.append("")

    # Back link
    lines.append("[← Back to index](index.md)")
    lines.append("")

    # Module docstring
    if mod.docstring:
        lines.append("## Module Docstring")
        lines.append("")
        for paragraph in mod.docstring.split("\n\n"):
            lines.append(paragraph.strip())
            lines.append("")
        lines.append("---")
        lines.append("")

    # Classes
    if mod.classes:
        lines.append("## Classes")
        lines.append("")
        for cls in mod.classes:
            _render_class_md(cls, lines, mod.module_name)
        lines.append("")

    # Functions
    if mod.functions:
        lines.append("## Functions")
        lines.append("")
        for func in mod.functions:
            _render_function_md(func, lines)
        lines.append("")

    return lines


def _render_class_md(cls: ClassDoc, lines: list[str], module_name: str) -> None:
    """Append Markdown for a single class to lines."""
    ref = _module_to_ref(cls.name)

    # Decorators
    for dec in cls.decorators:
        lines.append(f"    `{dec}`")

    # Class header
    bases_str = ""
    if cls.bases:
        bases_str = f"({', '.join(cls.bases)})"
    lines.append(f'### <a id="{ref}"></a>`class {cls.name}{bases_str}`')
    lines.append("")

    # Docstring
    if cls.docstring:
        for paragraph in cls.docstring.split("\n\n"):
            lines.append(f"{paragraph.strip()}")
            lines.append("")
    else:
        lines.append("*No docstring.*")
        lines.append("")

    # Methods
    if cls.methods:
        lines.append("**Methods:**")
        lines.append("")
        lines.append("| Method | Signature | Summary |")
        lines.append("|--------|-----------|---------|")
        for m in cls.methods:
            summary = _docstring_summary(m.docstring, 50)
            async_prefix = "async " if m.is_async else ""
            sig = m.signature
            # Truncate long signatures in the table
            if len(sig) > 50:
                sig = sig[:47] + "..."
            display_sig = f"`{async_prefix}{m.name}{sig}`"
            lines.append(f"| {m.name} | {display_sig} | {summary} |")
        lines.append("")

        # Detailed method docs
        for m in cls.methods:
            _render_function_md(m, lines, level=4)
    lines.append("---")
    lines.append("")


def _render_function_md(
    func: FunctionDoc,
    lines: list[str],
    level: int = 3,
) -> None:
    """Append Markdown for a single function/method to lines."""
    ref = _module_to_ref(func.name)
    hash_prefix = "#" * level

    # Decorators
    for dec in func.decorators:
        lines.append(f"    `{dec}`")

    # Signature line
    async_prefix = "async " if func.is_async else ""
    lines.append(f'{hash_prefix} <a id="{ref}"></a>`{async_prefix}def {func.name}{func.signature}`')
    lines.append("")

    # Docstring
    if func.docstring:
        for paragraph in func.docstring.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                lines.append(f"{paragraph}")
                lines.append("")
    else:
        lines.append("*No docstring.*")
        lines.append("")


# ===========================================================================
# HTML generation
# ===========================================================================


def generate_html(
    modules: list[ModuleDoc],
    project_name: str = "virgo",
    output_dir: str = "docs",
    base_dir: str | None = None,
) -> list[Path]:
    """Generate HTML API reference documentation.

    Writes an ``index.html`` with the full API reference for all modules.

    Args:
        modules: List of ``ModuleDoc`` objects to document.
        project_name: Display name for the project.
        output_dir: Output directory for generated files.
        base_dir: Base directory for computing relative paths (defaults to
            the common ancestor of all module paths).

    Returns:
        List of paths to the generated files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if base_dir is None:
        if modules:
            paths = [Path(m.file_path) for m in modules if m.file_path]
            if paths:
                base_dir = str(os.path.commonpath(paths))
            else:
                base_dir = "."
        else:
            base_dir = "."

    html = _build_html(modules, project_name, base_dir)
    index_path = out / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return [index_path]


def _build_html(
    modules: list[ModuleDoc],
    project_name: str,
    base_dir: str,
) -> str:
    """Build the complete HTML document as a string."""
    sections_html = ""

    for mod in modules:
        sections_html += _html_module_section(mod, base_dir)

    css = _html_styles()
    title = _escape_html(project_name)
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Module links in the sidebar
    sidebar_links = ""
    for mod in modules:
        ref = _module_to_ref(mod.module_name)
        sidebar_links += (
            f'<a href="#module-{ref}">'
            f'<span class="mod-name">{_escape_html(mod.module_name)}</span></a>\n'
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — API Reference</title>
  <style>
{css}
  </style>
</head>
<body>
  <nav class="sidebar">
    <div class="sidebar-header">{title}</div>
    <div class="sidebar-date">{date}</div>
    <div class="sidebar-section">Modules</div>
    {sidebar_links}
  </nav>
  <main class="content">
    <h1>{title} — API Reference</h1>
    <p class="meta">Generated on {date} &middot; {len(modules)} module(s)</p>
    {sections_html}
  </main>
</body>
</html>"""


def _html_styles() -> str:
    """Return the CSS styles for the HTML output."""
    return """\
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background:#0d0d12; color:#c0c0d0;
  font-family:system-ui,sans-serif;
  display:flex;
  min-height:100vh;
}
.sidebar {
  width:260px; background:#0a0a0f; border-right:1px solid #1a1a2a;
  padding:1.5rem 1rem; position:sticky; top:0; height:100vh;
  overflow-y:auto; flex-shrink:0;
}
.sidebar-header {
  font-size:1.1rem; font-weight:700; color:#00ffff;
  margin-bottom:0.25rem;
}
.sidebar-date { font-size:0.8rem; color:#666; margin-bottom:1.5rem; }
.sidebar-section {
  font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em;
  color:#888; margin-bottom:0.5rem;
}
.sidebar a {
  display:block; padding:0.25rem 0;
  color:#888; text-decoration:none; font-size:0.85rem;
  transition:color 0.15s;
}
.sidebar a:hover { color:#00ccff; }
.content {
  flex:1; padding:2rem; max-width:900px;
}
h1 { color:#00ffff; font-size:1.8rem; margin-bottom:0.25rem; }
.meta { color:#888; font-size:0.85rem; margin-bottom:2rem; }
h2 {
  color:#fff; font-size:1.4rem; margin:2rem 0 0.75rem;
  padding-bottom:0.4rem; border-bottom:1px solid #1e1e2e;
}
h3 {
  color:#ccc; font-size:1.1rem; margin:1.5rem 0 0.5rem;
}
h4 {
  color:#aaa; font-size:0.95rem; margin:1rem 0 0.25rem;
}
.module-file {
  font-size:0.8rem; color:#666; margin-bottom:1rem;
}
.module-docstring {
  background:#0a0a0f; border:1px solid #1a1a2a; border-radius:6px;
  padding:1rem; margin:0.5rem 0 1rem; line-height:1.6;
}
pre, code {
  font-family:"JetBrains Mono","Fira Code",monospace;
}
.class-header {
  background:#0e0e15; border:1px solid #1a1a2a; border-radius:6px;
  padding:0.75rem 1rem; margin:0.75rem 0;
  font-weight:600; color:#00ccff;
}
.class-doc {
  padding:0 0 0 1rem; margin:0.25rem 0 0.75rem;
  border-left:2px solid #1a1a3a; line-height:1.6;
}
.method-table {
  width:100%; border-collapse:collapse; font-size:0.85rem;
  margin:0.5rem 0 1rem;
}
.method-table th {
  text-align:left; padding:0.3rem 0.6rem;
  border-bottom:1px solid #1e1e2e; color:#00ffff;
  font-weight:500;
}
.method-table td {
  padding:0.3rem 0.6rem; border-bottom:1px solid #12121a;
  vertical-align:top;
}
.method-detail {
  background:#0a0a0f; border:1px solid #1a1a2a; border-radius:6px;
  padding:0.75rem 1rem; margin:0.5rem 0 1rem;
}
.method-sig {
  color:#ccc; margin-bottom:0.4rem;
}
.method-doc {
  line-height:1.6; font-size:0.9rem;
}
.func-header {
  background:#0e0e15; border:1px solid #1a1a2a; border-radius:6px;
  padding:0.75rem 1rem; margin:0.75rem 0;
  font-weight:600; color:#88ddff;
}
.func-doc {
  padding:0 0 0 1rem; margin:0.25rem 0 1rem;
  border-left:2px solid #1a1a3a; line-height:1.6;
}
.decorator {
  color:#8866cc; font-size:0.85rem;
}
code { background:#12121c; padding:0.1rem 0.3rem; border-radius:3px; font-size:0.85rem; }
a { color:#00ccff; }
hr { border:none; border-top:1px solid #1a1a2a; margin:1.5rem 0; }"""


def _html_module_section(mod: ModuleDoc, base_dir: str) -> str:
    """Build the HTML section for a single module."""
    ref = _module_to_ref(mod.module_name)
    rel = _rel_path(mod.file_path, base_dir)
    parts: list[str] = []

    parts.append(f'<section id="module-{ref}">')
    parts.append(f"<h2>{_escape_html(mod.module_name)}</h2>")
    parts.append(f'<p class="module-file">{_escape_html(rel)}</p>')

    if mod.docstring:
        doc_html = _escape_html(mod.docstring).replace("\n", "<br>")
        parts.append(f'<div class="module-docstring">{doc_html}</div>')

    # Classes
    for cls in mod.classes:
        parts.append(_html_class(cls))

    # Functions
    for func in mod.functions:
        parts.append(_html_function(func))

    parts.append("</section>")
    return "\n".join(parts)


def _html_class(cls: ClassDoc) -> str:
    """Build HTML for a class."""
    parts: list[str] = []
    cls_ref = _module_to_ref(cls.name)

    bases_str = ""
    if cls.bases:
        bases_str = f"({', '.join(cls.bases)})"

    # Decorators
    for dec in cls.decorators:
        parts.append(f'<div class="decorator">{_escape_html(dec)}</div>')

    parts.append(
        f'<div class="class-header" id="{cls_ref}">'
        f"class {_escape_html(cls.name)}{_escape_html(bases_str)}"
        f"</div>"
    )

    if cls.docstring:
        doc_html = _escape_html(cls.docstring).replace("\n", "<br>")
        parts.append(f'<div class="class-doc">{doc_html}</div>')

    # Method table
    if cls.methods:
        parts.append('<table class="method-table">')
        parts.append("<tr><th>Method</th><th>Signature</th><th>Summary</th></tr>")
        for m in cls.methods:
            async_prefix = "async " if m.is_async else ""
            sig = _escape_html(m.signature)
            summary = _escape_html(_docstring_summary(m.docstring, 60))
            parts.append(
                f"<tr>"
                f'<td><a href="#{_module_to_ref(m.name)}">{m.name}</a></td>'
                f"<td><code>{async_prefix}{m.name}{sig}</code></td>"
                f"<td>{summary}</td>"
                f"</tr>"
            )
        parts.append("</table>")

        # Detailed method docs
        for m in cls.methods:
            parts.append(_html_function(m, detail=True))

    return "\n".join(parts)


def _html_function(func: FunctionDoc, detail: bool = False) -> str:
    """Build HTML for a function or method."""
    parts: list[str] = []
    func_ref = _module_to_ref(func.name)
    async_prefix = "async " if func.is_async else ""

    # Decorators
    for dec in func.decorators:
        parts.append(f'<div class="decorator">{_escape_html(dec)}</div>')

    parts.append(
        f'<div class="func-header" id="{func_ref}">'
        f"<code>{async_prefix}def {_escape_html(func.name)}{_escape_html(func.signature)}</code>"
        f"</div>"
    )

    if func.docstring:
        doc_html = _escape_html(func.docstring).replace("\n", "<br>")
        parts.append(f'<div class="func-doc">{doc_html}</div>')
    else:
        parts.append('<div class="func-doc"><em>No docstring.</em></div>')

    return "\n".join(parts)


# ===========================================================================
# CLI entry point
# ===========================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``virgo_docgen``.

    Args:
        argv: Command-line argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 on success, 1 on error).
    """
    parser = argparse.ArgumentParser(
        prog="virgo doc",
        description="Generate API documentation from Python docstrings.",
        epilog="Files are written to --output (default: docs/).",
    )
    parser.add_argument(
        "--path",
        "-p",
        default=".",
        help="Path to scan (file or directory). Default: current dir.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="docs",
        help="Output directory. Default: docs/",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["md", "html"],
        default="md",
        help="Output format: md (markdown, default) or html.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Walk directories recursively.",
    )
    parser.add_argument(
        "--name",
        "-n",
        default="virgo",
        help="Project display name. Default: 'virgo'",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output.",
    )

    args = parser.parse_args(argv)

    path_arg = args.path
    output_dir = args.output
    fmt = args.format
    recursive = args.recursive
    project_name = args.name
    quiet = args.quiet

    # Scan
    if Path(path_arg).is_dir():
        if not quiet:
            print(f"  [docgen] Scanning {'recursively ' if recursive else ''}{path_arg}")
        modules = scan_directory(path_arg, recursive=recursive)
    else:
        if not quiet:
            print(f"  [docgen] Parsing {path_arg}")
        doc = extract_docstrings(path_arg)
        modules = [doc] if doc else []

    if not modules:
        print(f"  [docgen] No Python files found in {path_arg}")
        return 1

    if not quiet:
        print(f"  [docgen] Found {len(modules)} module(s)")

    # Generate
    try:
        if fmt == "html":
            written = generate_html(modules, project_name=project_name, output_dir=output_dir)
        else:
            written = generate_markdown(modules, project_name=project_name, output_dir=output_dir)
    except Exception as exc:
        print(f"  [docgen] Error generating docs: {exc}")
        return 1

    if not quiet:
        print(f"  [docgen] Wrote {len(written)} file(s) to {output_dir}/")
        for w in written:
            print(f"    {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
critic — static analysis for generated code.

Runs before the WTF loop to catch common issues:
• missing ``if __name__ == '__main__'`` guard
• bare ``except:`` clauses
• ``eval()`` / ``exec()`` calls
• overly long lines
• ``import *``
• missing docstrings on functions

Each check returns an ``Issue`` with severity and line number.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent


@dataclass
class Issue:
    """A single code-quality issue found during review."""
    severity: str          # "error" | "warning" | "info"
    message: str
    line: int = 0
    file: str = ""


@dataclass
class ReviewReport:
    """Result of reviewing one or more files."""
    files_reviewed: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def __str__(self) -> str:
        lines = [f"  Reviewed {self.files_reviewed} file(s)"]
        if not self.issues:
            lines.append("  No issues found.")
            return "\n".join(lines)
        lines.append(f"  {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        for i in self.issues:
            tag = "[ERR]" if i.severity == "error" else "[WARN]" if i.severity == "warning" else "[INFO]"
            loc = f":{i.line}" if i.line else ""
            lines.append(f"    {tag}  {i.file}{loc}  {i.message}")
        return "\n".join(lines)


# ===========================================================================
# Checks
# ===========================================================================

def _check_ast(tree: ast.Module, source: str, file: str, issues: list[Issue]) -> None:
    """Run AST-level checks on a parsed module."""
    lines = source.splitlines()

    # --- missing __name__ guard -------------------------------------------
    has_main_guard = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Check if the test compares __name__ to '__main__'
            if (isinstance(node.test, ast.Compare) and
                isinstance(node.test.left, ast.Name) and
                node.test.left.id == "__name__" and
                len(node.test.ops) == 1 and
                isinstance(node.test.ops[0], ast.Eq) and
                len(node.test.comparators) == 1 and
                isinstance(node.test.comparators[0], ast.Constant) and
                node.test.comparators[0].value == "__main__"):
                has_main_guard = True
                break

    # Only flag if the file has function/class defs or sys.exit calls
    has_defs = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   for n in ast.walk(tree))
    if has_defs and not has_main_guard:
        issues.append(Issue("warning", "Missing if __name__ == '__main__' guard", file=file))

    # --- bare except ------------------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(Issue(
                "error", "Bare except: catches all exceptions — use except Exception:",
                node.lineno if hasattr(node, 'lineno') else 0, file,
            ))

    # --- eval / exec ------------------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in ("eval", "exec"):
                issues.append(Issue(
                    "error", f"Use of {func_name}() — security risk",
                    node.lineno, file,
                ))

    # --- import * ---------------------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.names and any(
            n.name == "*" for n in node.names
        ):
            issues.append(Issue(
                "warning", "from X import * — pollutes namespace",
                node.lineno, file,
            ))

    # --- function docstrings ----------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                issues.append(Issue(
                    "info", f"Function '{node.name}' missing docstring",
                    node.lineno, file,
                ))


def _check_lines(source: str, file: str, issues: list[Issue]) -> None:
    """Run line-level checks."""
    for i, line in enumerate(source.splitlines(), 1):
        # Long lines (over 100 chars for generated code is lenient)
        if len(line) > 120 and not line.strip().startswith("#"):
            issues.append(Issue("info", f"Line too long ({len(line)} chars)", i, file))

        # Hardcoded secrets (simple heuristic)
        if re.search(r'(password|secret|token|api_key)\s*=\s*["\'][^"\']+["\']', line, re.IGNORECASE):
            issues.append(Issue(
                "warning", "Possible hardcoded secret on this line", i, file,
            ))


# ===========================================================================
# Public API
# ===========================================================================

def review_file(file_path: str) -> ReviewReport:
    """Run all checks on a single Python file, returning a ReviewReport."""
    report = ReviewReport()
    path = Path(file_path)
    if not path.exists():
        report.issues.append(Issue("error", f"File not found: {file_path}", file=file_path))
        return report

    source = path.read_text(encoding="utf-8")
    report.files_reviewed = 1
    base = str(file_path)

    try:
        tree = ast.parse(source, filename=file_path)
        _check_ast(tree, source, base, report.issues)
    except SyntaxError as exc:
        report.issues.append(Issue(
            "error", f"Syntax error: {exc.msg}",
            exc.lineno or 0, base,
        ))
        return report

    _check_lines(source, base, report.issues)
    return report


def review_files(file_paths: list[str]) -> ReviewReport:
    """Review multiple files, merging results into one report."""
    report = ReviewReport()
    for fp in file_paths:
        sub = review_file(fp)
        report.files_reviewed += sub.files_reviewed
        report.issues.extend(sub.issues)
    return report


def review_code(code: str, filename: str = "<string>") -> ReviewReport:
    """Review a code string as if it were a file."""
    report = ReviewReport()
    report.files_reviewed = 1
    try:
        tree = ast.parse(code, filename=filename)
        _check_ast(tree, code, filename, report.issues)
    except SyntaxError as exc:
        report.issues.append(Issue(
            "error", f"Syntax error: {exc.msg}", exc.lineno or 0, filename,
        ))
        return report
    _check_lines(code, filename, report.issues)
    return report

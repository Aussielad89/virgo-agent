"""
requirements_plugin — scan Python files for imports and sync with requirements.txt.

Tools
-----
- ``req scan [path]`` — scan Python files under *path* (default: project root)
  for third-party imports, compare with requirements.txt, and report
  missing, extra, and matched packages.
- ``req add <package>`` — add a package entry to requirements.txt (with
  ``>=0.0`` pin if not already present).
- ``req check`` — verify that requirements.txt exists and contains at
  least one dependency entry (non-comment, non-blank).

Export: ``register(registry)`` — called by the plugin loader.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import Any

# Reuse the stdlib set from autodepend to avoid duplication.
# We import it directly so the list stays in one place.
from autodepend import _STDLIB_MODULES, _KNOWN_THIRD_PARTY


# Add a few more names that are not actual packages
_STDLIB_MODULES = _STDLIB_MODULES | {
    "__future__",
    "__init__",
    "__main__",
    "antigravity",
    "this",
}

# ── helpers ────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent


def _find_requirements() -> Path | None:
    """Return the path to requirements.txt or None."""
    candidates = [
        PROJECT_ROOT / "requirements.txt",
        HERE / "requirements.txt",
        Path.cwd() / "requirements.txt",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# Regex for a bare version pin e.g. ``>=1.0``, ``==2.3.4``
_VERSION_PIN_RE = re.compile(r"([><=!~]+[\w.*,]+)")


def _parse_requirements(path: Path) -> dict[str, str]:
    """Parse requirements.txt into {package_name: full_line}.

    Lines starting with ``#`` or ``--`` are skipped.  Version pins are
    stripped only for the package key.
    """
    packages: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("--"):
            continue
        # Take everything before the first version comparator
        pkg = _VERSION_PIN_RE.split(line, 1)[0].strip()
        if pkg:
            packages[pkg.lower()] = line
    return packages


def _extract_imports_from_file(path: Path) -> set[str]:
    """Return the set of top-level third-party imports in a Python file.

    Handles:
      - ``import foo``
      - ``from foo import bar``
      - ``import foo.bar.baz`` → ``foo``
      - ``from foo.bar import baz`` → ``foo``

    Ignores stdlib and local-relative imports (those starting with ``.``).
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fall back to regex on syntax errors
        return _extract_imports_regex(source)

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top and not top.startswith("."):
                    imports.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                # `from . import something` — skip relative
                continue
            top = node.module.split(".")[0]
            if top and not top.startswith("."):
                imports.add(top)
    return imports


def _extract_imports_regex(source: str) -> set[str]:
    """Fallback regex-based import extraction for files that fail AST parse.

    Goal: detect ``import X`` and ``from X import …`` patterns.
    """
    imports: set[str] = set()
    pat = re.compile(
        r"^(?:import\s+([\w.]+)"
        r"|from\s+([\w.]+)\s+import\s+)",
        re.MULTILINE,
    )
    for m in pat.finditer(source):
        name = (m.group(1) or m.group(2)).split(".")[0]
        if name and not name.startswith("."):
            imports.add(name)
    return imports


def _is_stdlib(module: str) -> bool:
    """Return True if *module* is a Python standard-library module."""
    if module in _STDLIB_MODULES:
        return True
    # Dynamic check via sys.stdlib_module_names (Python 3.10+)
    try:
        return module in sys.stdlib_module_names  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return False


def _third_party_name(module: str) -> str:
    """Return the pip-installable package name for *module*, or *module*.

    Uses the mapping from autodepend; falls back to the module name.
    """
    return _KNOWN_THIRD_PARTY.get(module, module)


def _find_python_files(root: str | Path) -> list[Path]:
    """Recursively find all ``.py`` files under *root*, skipping hidden dirs."""
    root_p = Path(root).resolve()
    py_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_p):
        # Skip hidden directories, venvs, cache, node_modules, etc.
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in ("__pycache__", "venv", ".venv", "env", ".env",
                          "node_modules", ".git", ".mypy_cache", ".pytest_cache",
                          ".ruff_cache", "build", "dist")
        ]
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(Path(dirpath) / fn)
    return sorted(py_files)


# ── tool implementations ───────────────────────────────────────────────


def _tool_req_scan(path: str | None = None) -> dict[str, Any]:
    """Scan Python files for third-party imports and compare with requirements.txt.

    Parameters
    ----------
    path : str, optional
        Directory to scan recursively.  Defaults to the project root
        (parent of the ``plugins/`` directory).

    Returns
    -------
    dict with keys:
      - requirements_file (str or null)
      - scanned_files (int)
      - imported_packages (list of str) — all third-party imports found
      - in_requirements (list of str) — subset that already exist
      - missing (list of str) — imports NOT in requirements.txt
      - extra (list of str) — requirements.txt entries that were never imported
      - errors (list of str) — files that couldn't be read/parsed
    """
    scan_root = PROJECT_ROOT if path is None else Path(path)

    if not scan_root.exists():
        return {"error": f"Path not found: {scan_root}"}

    req_path = _find_requirements()
    req_packages = _parse_requirements(req_path) if req_path else {}

    # Collect all imports from Python files
    all_imports: set[str] = set()
    errors: list[str] = []
    py_files = _find_python_files(scan_root)
    for f in py_files:
        try:
            mods = _extract_imports_from_file(f)
            all_imports |= mods
        except Exception as exc:
            errors.append(f"{f.relative_to(PROJECT_ROOT)}: {exc}")

    # Filter to third-party only
    third_party_imports: set[str] = set()
    for mod in all_imports:
        if not _is_stdlib(mod):
            third_party_imports.add(mod)

    # Map module names to pip package names
    imported_pkgs: set[str] = {_third_party_name(m) for m in third_party_imports}
    # Also keep the bare module names if they're not in known mappings
    for m in third_party_imports:
        if m not in _KNOWN_THIRD_PARTY:
            imported_pkgs.add(m)

    imported_sorted = sorted(imported_pkgs, key=str.casefold)

    # Compare with requirements.txt
    req_lower = {k.lower(): v for k, v in req_packages.items()}
    in_req = [p for p in imported_sorted if p.lower() in req_lower]
    missing = [p for p in imported_sorted if p.lower() not in req_lower]
    extra = sorted(
        (v for k, v in req_packages.items() if k not in {p.lower() for p in imported_sorted}),
        key=str.casefold,
    )

    return {
        "requirements_file": str(req_path) if req_path else None,
        "scanned_files": len(py_files),
        "imported_packages": imported_sorted,
        "in_requirements": in_req,
        "missing": missing,
        "extra": extra,
        "errors": errors,
    }


def _tool_req_add(package: str) -> dict[str, Any]:
    """Add a package entry to requirements.txt.

    Parameters
    ----------
    package : str
        Package name, optionally with version pin (e.g. ``requests``,
        ``pydantic>=2.0``).

    Returns
    -------
    dict with keys:
      - file (str) — path to requirements.txt
      - package (str) — the full line that was written
      - action — ``"added"`` or ``"already_present"``
    """
    entry = package.strip()

    req_path = _find_requirements()
    if req_path is None:
        # Create at project root
        req_path = PROJECT_ROOT / "requirements.txt"

    # Parse current content
    text = req_path.read_text(encoding="utf-8") if req_path.exists() else ""

    existing = _parse_requirements(req_path) if req_path.exists() else {}

    # Strip version pin for comparison
    bare = _VERSION_PIN_RE.split(entry, 1)[0].strip().lower()

    if bare in {k.lower() for k in existing}:
        return {
            "file": str(req_path),
            "package": entry,
            "action": "already_present",
        }

    # Append — if file has content, ensure trailing newline
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"{entry}\n"
    req_path.write_text(text, encoding="utf-8")

    return {
        "file": str(req_path),
        "package": entry,
        "action": "added",
    }


def _tool_req_check() -> dict[str, Any]:
    """Check if requirements.txt exists and has entries.

    Returns
    -------
    dict with keys:
      - exists (bool)
      - has_entries (bool)
      - file (str or null)
      - entry_count (int)
      - packages (list of str) — package names found
    """
    req_path = _find_requirements()
    if req_path is None:
        return {
            "exists": False,
            "has_entries": False,
            "file": None,
            "entry_count": 0,
            "packages": [],
        }

    packages = _parse_requirements(req_path)
    return {
        "exists": True,
        "has_entries": len(packages) > 0,
        "file": str(req_path),
        "entry_count": len(packages),
        "packages": sorted(packages.keys(), key=str.casefold),
    }


# ── plugin entry point ─────────────────────────────────────────────────


def register(registry: Any) -> None:
    """Register the three requirements-sync tools with *registry*.

    Called automatically by ``plugins.load_path``.
    """
    from tools import Tool

    registry.register(
        Tool(
            name="req scan",
            fn=_tool_req_scan,
            description=(
                "Scan Python files for third-party imports and compare "
                "with requirements.txt.  Accepts optional 'path' kwarg "
                "to scan a subdirectory instead of the project root."
            ),
        )
    )
    registry.register(
        Tool(
            name="req add",
            fn=_tool_req_add,
            description=(
                "Add a package to requirements.txt.  Accepts 'package' "
                "kwarg (e.g. 'requests>=2.0').  Skips if already present."
            ),
        )
    )
    registry.register(
        Tool(
            name="req check",
            fn=_tool_req_check,
            description=(
                "Check if requirements.txt exists and has any dependency entries."
            ),
        )
    )

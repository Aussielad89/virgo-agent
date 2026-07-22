"""
virgo_scaffold — project scaffolding engine for virgo.

Reads scaffold definitions from ``scaffolds/*.json`` and generates
multi-file project skeletons with template substitution.

Usage::

    from virgo_scaffold import list_scaffolds, generate

    scaffolds = list_scaffolds()
    generate("fastapi-crud", output_dir="./myapp", project_name="myapi")
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
SCAFFOLDS_DIR = HERE / "scaffolds"

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def _installed_scaffolds_dir() -> Path | None:
    """Return the path to installed-scaffolds data dir (created on first install)."""
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("virgo-agent")
        if dist and dist.locate_file("."):
            data_dir = Path(dist.locate_file(".")).parent / "scaffolds"
            return data_dir if data_dir.is_dir() else None
    except Exception:
        pass
    return None


def _find_plugin_scaffolds() -> dict[str, dict[str, Any]]:
    """Scan installed packages for scaffold JSON definitions.

    Looks in each installed package's ``scaffolds/`` directory, and also
    checks for ``virgo_scaffolds`` entry points.

    Returns a dict mapping scaffold name → scaffold data.
    """
    plugins: dict[str, dict[str, Any]] = {}

    # Method 1: scan data directories via importlib.metadata
    try:
        import importlib.metadata

        for dist in importlib.metadata.distributions():
            # Try entry points first
            try:
                entries = dist.entry_points
                for ep in entries:
                    if ep.group == "virgo_scaffolds":
                        try:
                            loader = ep.load()
                            data = loader()
                            if isinstance(data, dict) and "name" in data:
                                plugins[data["name"].lower()] = data
                        except Exception:
                            continue
            except Exception:
                pass

            # Try scanning the package's scaffolds/ directory
            try:
                pkg_root = Path(dist.locate_file("."))
                # Navigate to potential scaffolds/ dirs
                for candidate in [pkg_root / "scaffolds", pkg_root.parent / "scaffolds"]:
                    if candidate.is_dir():
                        for path in sorted(candidate.glob("*.json")):
                            try:
                                data = json.loads(path.read_text(encoding="utf-8"))
                                name = data.get("name", path.stem).lower()
                                if name not in plugins:
                                    plugins[name] = data
                                    plugins[name]["_plugin"] = dist.metadata["Name"]
                            except Exception:
                                continue
            except Exception:
                continue
    except Exception:
        pass

    return plugins


def _all_scaffolds() -> list[dict[str, Any]]:
    """Return built-in + plugin scaffolds combined."""
    results: list[dict[str, Any]] = []

    # Built-in scaffolds
    if SCAFFOLDS_DIR.is_dir():
        for path in sorted(SCAFFOLDS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(
                    {
                        "name": data.get("name", path.stem),
                        "description": data.get("description", ""),
                        "version": data.get("version", "0.0.0"),
                        "dependencies": data.get("dependencies", []),
                        "_source": "built-in",
                        "_path": str(path),
                    }
                )
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Warning: skipping {path.name}: {exc}", file=sys.stderr)

    # Plugin scaffolds
    for name, data in _find_plugin_scaffolds().items():
        results.append(
            {
                "name": data.get("name", name),
                "description": data.get("description", ""),
                "version": data.get("version", "0.0.0"),
                "dependencies": data.get("dependencies", []),
                "_source": data.get("_plugin", "unknown"),
                "_path": str(data.get("_path", "")),
            }
        )

    return results


def _render(text: str, vars: dict[str, str]) -> str:
    """Replace ``{{var}}`` placeholders with values from *vars*."""

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return vars.get(key, m.group(0))

    return _VAR_RE.sub(_replace, text)


def _stars(v: str) -> str:
    """Return a string of ``*`` with the same length as *v* (for README headers)."""
    return "*" * len(v)


# ===========================================================================
# Public API
# ===========================================================================


def list_scaffolds() -> list[dict[str, Any]]:
    """Return metadata for all available scaffolds (built-in + plugins).

    Returns a list of dicts with keys: name, description, version, dependencies, _source.
    """
    return _all_scaffolds()


def load_scaffold(name: str) -> dict[str, Any] | None:
    """Load a scaffold definition by name (case-insensitive).

    Searches built-in scaffolds first, then plugin scaffolds.
    Returns the parsed JSON dict, or ``None`` if not found.
    """
    name_lower = name.lower()

    # Search built-in
    if SCAFFOLDS_DIR.is_dir():
        for path in SCAFFOLDS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("name", "").lower() == name_lower:
                    return data
            except (json.JSONDecodeError, OSError):
                continue

    # Search plugins
    plugins = _find_plugin_scaffolds()
    if name_lower in plugins:
        return plugins[name_lower]

    return None


def generate(
    scaffold_name: str,
    output_dir: str | Path = ".",
    **overrides: Any,
) -> list[Path]:
    """Generate a project from a scaffold definition.

    Parameters
    ----------
    scaffold_name:
        Name of the scaffold (case-insensitive).
    output_dir:
        Directory to create the project in. Created if it doesn't exist.
    **overrides:
        Template variables. Any variable not provided falls back to the
        scaffold's ``prompts`` defaults, or to the key name itself.

    Returns
    -------
    List of file paths that were created.

    Raises
    ------
    ValueError:
        If the scaffold is not found.
    """
    scaffold = load_scaffold(scaffold_name)
    if scaffold is None:
        raise ValueError(
            f"Scaffold {scaffold_name!r} not found. "
            f"Available: {[s['name'] for s in list_scaffolds()]}"
        )

    # Collect template variables: overrides > prompts defaults > key name
    defaults = scaffold.get("prompts", {})
    vars: dict[str, str] = {}
    all_keys: set[str] = set()

    # Scan all file paths and content for {{var}} patterns
    for file_path, content in scaffold.get("files", {}).items():
        for match in _VAR_RE.finditer(file_path):
            all_keys.add(match.group(1))
        for match in _VAR_RE.finditer(content):
            all_keys.add(match.group(1))

    for key in all_keys:
        if key in overrides:
            vars[key] = str(overrides[key])
        elif key in defaults:
            vars[key] = str(defaults[key])
        elif key == "stars":
            # Special built-in — computed from project_name
            pname = overrides.get("project_name", defaults.get("project_name", key))
            vars[key] = _stars(pname)
        else:
            vars[key] = key  # fallback

    # Create output directory
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    for file_path, content in scaffold.get("files", {}).items():
        rendered_path = _render(file_path, vars)
        rendered_content = _render(content, vars)
        target = root / rendered_path

        # Create parent directories
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(rendered_content, encoding="utf-8")
        created.append(target)

    return created


# ===========================================================================
# Plugin scaffold management (install / uninstall)
# ===========================================================================


def install_scaffold(package: str) -> None:
    """Install a scaffold package via pip and verify it provides scaffolds.

    The package should either:
    - Contain a ``scaffolds/*.json`` directory with scaffold definitions, or
    - Register ``virgo_scaffolds`` entry points in its ``pyproject.toml``.

    Raises ``SystemExit`` on failure.
    """
    import sys

    print(f"  Installing {package!r}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Error installing {package!r}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    # Verify the package provides scaffolds
    plugins = _find_plugin_scaffolds()
    # Check if any new scaffolds appeared (we can't easily diff, but we can report)
    installed_scaffolds = [
        s
        for s in plugins.values()
        if s.get("_plugin", "").lower() in package.lower()
        or package.lower() in str(s.get("_path", "")).lower()
    ]

    if installed_scaffolds:
        print(f"  Found {len(installed_scaffolds)} scaffold(s) in {package!r}:")
        for s in installed_scaffolds:
            print(f"    - {s.get('name', '?')}: {s.get('description', '')}")
    else:
        print(f"  Package {package!r} installed, but no scaffolds detected.")
        print(
            "  (Scaffolds must be in a ``scaffolds/`` dir or use ``virgo_scaffolds`` entry points)"
        )


def uninstall_scaffold(package: str) -> None:
    """Uninstall a scaffold package via pip."""
    import sys

    print(f"  Uninstalling {package!r}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", package, "-y"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Error uninstalling {package!r}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print(f"  Uninstalled {package!r}.")


# ===========================================================================
# CLI entry point
# ===========================================================================


def main() -> None:
    """Run the scaffold tool from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="virgo scaffold — project scaffolding")
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List available scaffolds")

    # show
    p_show = sub.add_parser("show", help="Show scaffold details")
    p_show.add_argument("name", help="Scaffold name")

    # generate
    p_gen = sub.add_parser(
        "generate", aliases=["gen", "g"], help="Generate a project from a scaffold"
    )
    p_gen.add_argument("name", help="Scaffold name")
    p_gen.add_argument(
        "--output", "-o", default=".", help="Output directory (default: current dir)"
    )
    p_gen.add_argument(
        "--var", "-v", action="append", default=[], help="Template variable (key=value)"
    )

    # install
    p_install = sub.add_parser("install", help="Install a scaffold package from PyPI")
    p_install.add_argument("package", help="Package name (pip installable)")

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Uninstall a scaffold package")
    p_uninstall.add_argument("package", help="Package name")

    args = parser.parse_args()

    if args.command == "list":
        scaffolds = list_scaffolds()
        if not scaffolds:
            print("No scaffolds found.")
            return
        print(f"\n  Available scaffolds ({len(scaffolds)}):\n")
        for s in scaffolds:
            deps = f"  [{', '.join(s['dependencies'])}]" if s["dependencies"] else ""
            print(f"    {s['name']}{' ' * (24 - len(s['name']))}{s['description']}{deps}")
        print()

    elif args.command == "show":
        scaffold = load_scaffold(args.name)
        if scaffold is None:
            print(f"Scaffold {args.name!r} not found.")
            sys.exit(1)
        print(f"\n  Name:        {scaffold.get('name', '?')}")
        print(f"  Description: {scaffold.get('description', '')}")
        print(f"  Version:     {scaffold.get('version', '0.0.0')}")
        deps = scaffold.get("dependencies", [])
        print(f"  Dependencies: {', '.join(deps) if deps else '(none)'}")
        prompts = scaffold.get("prompts", {})
        if prompts:
            print(f"  Variables:   {', '.join(prompts.keys())}")
        files = scaffold.get("files", {})
        print(f"  Files:       {len(files)}")
        print()

    elif args.command in ("generate", "gen", "g"):
        overrides = {}
        for kv in args.var:
            if "=" in kv:
                k, v = kv.split("=", 1)
                overrides[k] = v

        try:
            created = generate(args.name, output_dir=args.output, **overrides)
            print(f"\n  Generated {len(created)} files from scaffold {args.name!r}:\n")
            for path in created:
                rel = path.relative_to(Path(args.output).resolve())
                print(f"    {rel}")
            print()
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)

    elif args.command == "install":
        install_scaffold(args.package)

    elif args.command == "uninstall":
        uninstall_scaffold(args.package)


if __name__ == "__main__":
    main()

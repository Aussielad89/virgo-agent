"""virgo_init — interactive project initialization wizard.

Reuses virgo_scaffold.py's scaffold engine with interactive prompts
instead of ``--var`` flags.

Usage::

    from virgo_init import interactive_wizard

    # Interactive mode — prompts for variables, shows summary, confirms
    wizard("fastapi-crud", output_dir="./myapi")

    # Non-interactive — just uses defaults (like ``virgo scaffold`` without ``--var``)
    wizard("fastapi-crud", output_dir="./myapi", non_interactive=True)

CLI::

    virgo init                          # list scaffolds, pick one, prompt
    virgo init fastapi-crud             # use named scaffold, prompt
    virgo init fastapi-crud -o ./myproj # custom output dir
    virgo init --non-interactive        # skip prompts, use defaults
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from _console import icon
from virgo_scaffold import generate, list_scaffolds, load_scaffold


# ===========================================================================
# Interactive wizard
# ===========================================================================


def _pick_scaffold() -> str:
    """List available scaffolds and let the user pick one.

    Returns the selected scaffold name.
    """
    scaffolds = list_scaffolds()
    if not scaffolds:
        print(f"\n  {icon('error')} No scaffolds available.\n")
        sys.exit(1)

    print(f"\n  {icon('rocket')} Available scaffolds:\n")
    for i, s in enumerate(scaffolds, 1):
        deps = f"  [{', '.join(s['dependencies'])}]" if s["dependencies"] else ""
        print(f"    [{i:2d}] {s['name']:24s} {s['description']}{deps}")
    print()

    while True:
        try:
            choice = input(f"  {icon('arrow')} Select scaffold [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)

        if not choice:
            choice = "1"
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(scaffolds):
                return scaffolds[idx]["name"]
        print(f"  {icon('error')} Invalid choice. Enter a number 1\u2013{len(scaffolds)}.")


def _prompt_vars(
    scaffold: dict[str, Any],
    non_interactive: bool = False,
) -> dict[str, str]:
    """Prompt the user for each template variable in the scaffold.

    If *non_interactive* is True, use default values without asking.
    Returns a dict of variable name \u2192 value.
    """
    prompts = scaffold.get("prompts", {})
    vars_dict: dict[str, str] = {}

    if non_interactive or not prompts:
        for key, default in prompts.items():
            vars_dict[key] = str(default)
        return vars_dict

    print(f"\n  {icon('tool')} Configure {scaffold.get('name', 'scaffold')} variables:\n")

    for key, default in prompts.items():
        prompt_text = f"    {key} [{default}]: "
        try:
            value = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        vars_dict[key] = value if value else str(default)

    return vars_dict


def _show_summary(
    scaffold: dict[str, Any],
    vars_dict: dict[str, str],
    output_dir: str | Path,
) -> None:
    """Display a summary of what will be generated."""
    name = scaffold.get("name", "?")
    description = scaffold.get("description", "")
    files = scaffold.get("files", {})
    deps = scaffold.get("dependencies", [])

    print(f"\n  {'=' * 52}")
    print(f"  {icon('sparkle')} Generation summary")
    print(f"  {'=' * 52}")
    print(f"    Scaffold:  {name}")
    print(f"    About:     {description}")
    print(f"    Output:    {output_dir}")
    if deps:
        print(f"    Deps:      {', '.join(deps)}")
    print(f"    Files:     {len(files)}")
    print(f"  {'─' * 52}")
    for key, val in vars_dict.items():
        print(f"    {key} = {val}")
    print(f"  {'=' * 52}")


def _confirm() -> bool:
    """Ask user to confirm generation. Returns True if yes."""
    try:
        response = input(f"\n  {icon('arrow')} Generate project? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return response in ("", "y", "yes")


# ===========================================================================
# Public API
# ===========================================================================


def interactive_wizard(
    scaffold_name: str | None = None,
    output_dir: str | Path = ".",
    non_interactive: bool = False,
) -> list[Path]:
    """Run the interactive project initialization wizard.

    Parameters
    ----------
    scaffold_name:
        Name of the scaffold to use. If ``None``, lists available scaffolds
        and prompts the user to pick one.
    output_dir:
        Directory to generate the project in (default: current directory).
        The scaffold's file templates already include ``{{project_name}}/``
        prefixes, so files land in a subdirectory within *output_dir*.
    non_interactive:
        If ``True``, skip all prompts and use default values for all
        template variables. Behaves like ``virgo scaffold generate``
        without ``--var``.

    Returns
    -------
    List of file paths that were created.

    Raises
    ------
    SystemExit:
        If the user cancels or the scaffold is not found.
    """
    # ── Step 1: Pick a scaffold ──────────────────────────────────────────
    if scaffold_name is None:
        scaffold_name = _pick_scaffold()

    # ── Step 2: Load scaffold ────────────────────────────────────────────
    scaffold = load_scaffold(scaffold_name)
    if scaffold is None:
        print(f"\n  {icon('error')} Scaffold {scaffold_name!r} not found.\n")
        sys.exit(1)

    # ── Step 3: Collect template variables ───────────────────────────────
    vars_dict = _prompt_vars(scaffold, non_interactive=non_interactive)

    # ── Step 4: Show summary and confirm ─────────────────────────────────
    _show_summary(scaffold, vars_dict, output_dir)

    if not non_interactive:
        if not _confirm():
            print(f"  {icon('done')} Cancelled.\n")
            sys.exit(0)

    # ── Step 5: Generate ─────────────────────────────────────────────────
    try:
        created = generate(scaffold_name, output_dir=output_dir, **vars_dict)
        print(f"\n  {icon('ok')} Generated {len(created)} files from scaffold {scaffold_name!r}:\n")
        for path in created:
            rel = path.relative_to(Path(output_dir).resolve())
            print(f"    {icon('file')} {rel}")
        print()
        return created
    except ValueError as exc:
        print(f"\n  {icon('error')} {exc}\n")
        sys.exit(1)


def run_wizard(args: argparse.Namespace) -> None:
    """CLI handler for ``virgo init``. Delegates to :func:`interactive_wizard`."""
    interactive_wizard(
        scaffold_name=args.name,
        output_dir=args.output,
        non_interactive=args.non_interactive,
    )

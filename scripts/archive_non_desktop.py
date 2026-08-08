"""archive_non_desktop.py — safely archive orphaned experiments and legacy smoke scripts.

Every candidate is verified BEFORE moving:
  1. no other module imports it (grep of *.py, excluding tests/ and archive/)
  2. it is not listed in setup.py py_modules
  3. no test file references it

Tracked files move with ``git mv`` (history preserved); untracked scratch
files (e.g. *.bak) move with plain ``mv``. Dry-run by default; pass
``--execute`` to actually move. Everything lands under ``archive/``.

Usage:
    python scripts/archive_non_desktop.py            # dry run
    python scripts/archive_non_desktop.py --execute  # move files
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# ── Orphaned experiments (verified: no importers, not in py_modules) ──
EXPERIMENTS = [
    "_mem0_memory.py",
    "_agent_result.txt",
    "agent_a.py", "agent_a.py.bak",
    "agent_b.py", "agent_b.py.bak",
    "agent_c.py", "agent_c.py.bak",
    "agent_x.py", "agent_x.py.bak",
    "agent_y.py", "agent_y.py.bak",
    "alpha.py", "alpha.py.bak",
    "bb_test.py", "bb_test.py.bak",
    "beta.py", "beta.py.bak",
    "ci_agent.py",
    "fail_agent.py", "fail_agent.py.bak",
    "fast.py", "fast.py.bak",
    "first.py", "first.py.bak",
    "generated.py", "generated.py.bak",
    "github_scraper.py",
]

# ── Legacy smoke-test runners (AGENTS.md: "no test framework needed — legacy") ──
LEGACY_SMOKE = [
    "test_modules.py",
    "test_orchestrator.py",
    "test_critic_depend.py",
]

IMPORT_TEMPLATE = r"^\s*(?:from\s+{name}\s+import|import\s+{name}(?:\s|,|$))"


def git(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True).returncode == 0


def is_tracked(name: str) -> bool:
    return git("ls-files", "--error-unmatch", name)


def in_py_modules(name: str) -> bool:
    setup_py = HERE / "setup.py"
    if not setup_py.exists():
        return False
    text = setup_py.read_text(encoding="utf-8", errors="ignore")
    return f'"{name.replace(".py", "")}"' in text


def importers(name: str) -> list[Path]:
    hits: list[Path] = []
    for py in sorted(HERE.glob("*.py")):
        if py.name == name or py.name.startswith("test_") or "archive" in str(py):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        pat = re.compile(IMPORT_TEMPLATE.format(name=name.replace(".py", "")))
        if pat.search(text):
            hits.append(py)
    return hits


def test_references(name: str) -> list[Path]:
    """Flag only *real* imports of the root module from tests.

    Naive substring matching false-positives on fixture filenames and
    prose (e.g. test_swarm's fake \"agent_a\" task names, \"fastapi\"
    strings, docstring words) -- only import statements count.
    """
    hits: list[Path] = []
    tests_dir = HERE / "tests"
    if not tests_dir.is_dir():
        return hits
    pat = re.compile(IMPORT_TEMPLATE.format(name=name.replace(".py", "")))
    for py in sorted(tests_dir.glob("*.py")):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if pat.search(text):
            hits.append(py)
    return hits


def classify(name: str) -> tuple[str, list[str]]:
    """Return (verdict, reasons). verdict: 'ok' | 'blocked' | 'absent'."""
    path = HERE / name
    if not path.exists():
        return "absent", []
    reasons = []
    for imp in importers(name):
        reasons.append(f"imported by {imp.name}")
    if in_py_modules(name):
        reasons.append("listed in setup.py py_modules")
    for ref in test_references(name):
        reasons.append(f"referenced by tests/{ref.name}")
    return ("ok" if not reasons else "blocked", reasons)


def main() -> None:
    execute = "--execute" in sys.argv
    if not execute and "--help" in sys.argv:
        print(__doc__)
        return

    plan: list[tuple[Path, Path, str]] = []  # (src, dst, verdict)
    for name, bucket in [(n, "experiments") for n in EXPERIMENTS] + \
                         [(n, "legacy_smoke") for n in LEGACY_SMOKE]:
        verdict, reasons = classify(name)
        if verdict == "absent":
            continue
        dst_dir = HERE / "archive" / bucket
        plan.append((HERE / name, dst_dir / name, verdict))
        if verdict == "blocked":
            print(f"  [SKIP] {name}  <- {', '.join(reasons)}")
        else:
            print(f"  [move] {name} -> archive/{bucket}/")

    print(f"\n{len(plan)} candidates evaluated: "
          f"{sum(1 for *_, v in plan if v == 'ok')} safe to move, "
          f"{sum(1 for *_, v in plan if v == 'blocked')} blocked, "
          f"{len(EXPERIMENTS) + len(LEGACY_SMOKE) - len(plan)} absent.")

    if not execute:
        print("\nDry run — nothing moved. Re-run with --execute to archive.")
        return

    for src, dst, verdict in plan:
        if verdict != "ok":
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_tracked(src.name):
            git("mv", str(src), str(dst))
        else:
            src.rename(dst)
        print(f"  moved {src.name} -> archive/{dst.parent.name}/")
    print("\nDone. Review with: git status; git diff --stat --cached")
    print("Roll back untracked moves: move files back from archive/experiments/")


if __name__ == "__main__":
    main()

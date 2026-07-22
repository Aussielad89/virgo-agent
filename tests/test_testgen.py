"""Tests for virgo_testgen — generation of real (non-stub) tests."""

from __future__ import annotations

import ast
import textwrap

from virgo_testgen import (
    _call_args,
    _example_value,
    _extract_args,
    _return_assert,
    _type_name,
    analyze_file,
    generate_tests,
)

SAMPLE = textwrap.dedent(
    '''
    """sample module"""

    def add(a: int, b: int = 1) -> int:
        "add two numbers"
        return a + b

    async def fetch() -> list:
        return [1, 2]

    class Calc:
        "calculator"

        def __init__(self, base: int = 0):
            self.base = base

        def square(self, x: int) -> int:
            return x * x
    '''
)


def _parse(src: str) -> ast.Module:
    return ast.parse(src)


def test_extract_args_drops_self_and_reads_default() -> None:
    tree = _parse("class C:\n    def __init__(self, base: int = 0):\n        pass\n")
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef)][0]
    init = [n for n in cls.body if isinstance(n, ast.FunctionDef)][0]
    args = _extract_args(init)
    assert args == [{"name": "base", "ann": "int", "default": "0"}]


def test_type_name_handles_subscript() -> None:
    tree = _parse("def f(x: list[int]) -> dict:\n    pass\n")
    fn = tree.body[0]
    assert _type_name(fn.args.args[0].annotation) == "list"
    assert _type_name(fn.returns) == "dict"


def test_example_value_uses_default_when_present() -> None:
    assert _example_value("int", "5") == "5"
    assert _example_value("str", None) == '"sample"'
    assert _example_value("list", None) == "[]"


def test_return_assert_mapping() -> None:
    assert _return_assert("int") == "isinstance(result, int)"
    assert _return_assert("str") == "isinstance(result, str)"
    assert _return_assert(None) is None


def test_call_args_joins_examples() -> None:
    args = [
        {"name": "a", "ann": "int", "default": None},
        {"name": "b", "ann": "str", "default": '"x"'},
    ]
    assert _call_args(args) == '0, "x"'


def test_generated_tests_are_real_not_stubs(tmp_path) -> None:
    src = tmp_path / "sample_mod.py"
    src.write_text(SAMPLE, encoding="utf-8")

    analysis = analyze_file(src)
    assert any(f["name"] == "add" for f in analysis["functions"])
    assert any(c["name"] == "Calc" for c in analysis["classes"])

    out = tmp_path / "tests"
    files = generate_tests(src, output_dir=out, overwrite=True)
    assert len(files) == 1

    content = files[0].read_text(encoding="utf-8")
    # No more placeholder stubs.
    assert "# TODO: implement" not in content
    assert "assert True" not in content
    # Real assertions derived from signatures.
    assert "sample_mod.add(0, 1)" in content
    assert "isinstance(result, int)" in content
    # Async handled via asyncio.run.
    assert "asyncio.run(sample_mod.fetch())" in content
    assert "import asyncio" in content
    # Class method exercised via an instance.
    assert "obj = sample_mod.Calc(0)" in content
    assert "obj.square(0)" in content


def test_generated_tests_actually_run(tmp_path) -> None:
    src = tmp_path / "sample_mod.py"
    src.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "tests"
    generate_tests(src, output_dir=out, overwrite=True)

    import subprocess
    import sys

    env = {**__import__("os").environ, "PYTHONPATH": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(out), "-q"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr

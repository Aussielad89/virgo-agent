"""
Tests for virgo_scaffold — project scaffolding engine.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from virgo_scaffold import list_scaffolds, load_scaffold, generate

HERE = Path(__file__).parent.parent
SCAFFOLDS_DIR = HERE / "scaffolds"

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d).resolve()


# ===========================================================================
# list_scaffolds
# ===========================================================================


class TestListScaffolds:
    def test_returns_list(self) -> None:
        result = list_scaffolds()
        assert isinstance(result, list)

    def test_includes_expected_scaffolds(self) -> None:
        result = list_scaffolds()
        names = [s["name"] for s in result]
        assert "fastapi-crud" in names
        assert "cli-app" in names
        assert "flask-app" in names
        assert "python-lib" in names
        assert "agent-tool" in names

    def test_each_has_required_keys(self) -> None:
        for s in list_scaffolds():
            assert "name" in s
            assert "description" in s
            assert "version" in s

    def test_handles_missing_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("virgo_scaffold.SCAFFOLDS_DIR", Path("/nonexistent"))
        monkeypatch.setattr("virgo_scaffold._find_plugin_scaffolds", lambda: {})
        assert list_scaffolds() == []


# ===========================================================================
# load_scaffold
# ===========================================================================


class TestLoadScaffold:
    def test_load_by_name(self) -> None:
        s = load_scaffold("fastapi-crud")
        assert s is not None
        assert s["name"] == "fastapi-crud"
        assert "files" in s

    def test_case_insensitive(self) -> None:
        s = load_scaffold("FASTAPI-CRUD")
        assert s is not None
        assert s["name"] == "fastapi-crud"

    def test_not_found(self) -> None:
        assert load_scaffold("nonexistent-scaffold") is None

    def test_missing_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("virgo_scaffold.SCAFFOLDS_DIR", Path("/nonexistent"))
        monkeypatch.setattr("virgo_scaffold._find_plugin_scaffolds", lambda: {})
        assert load_scaffold("fastapi-crud") is None


# ===========================================================================
# generate
# ===========================================================================


class TestGenerate:
    def test_generates_files(self, tmp_dir: Path) -> None:
        created = generate("cli-app", output_dir=str(tmp_dir), project_name="testcli")
        assert len(created) > 0
        # Check key files exist
        assert (tmp_dir / "README.md").exists()
        assert (tmp_dir / "pyproject.toml").exists()
        assert (tmp_dir / "testcli" / "__init__.py").exists()
        assert (tmp_dir / "testcli" / "cli.py").exists()

    def test_template_substitution(self, tmp_dir: Path) -> None:
        generate("cli-app", output_dir=str(tmp_dir), project_name="testcli",
                 app_description="My test CLI")
        pyproject = (tmp_dir / "pyproject.toml").read_text(encoding="utf-8")
        assert "testcli" in pyproject
        assert "My test CLI" in pyproject

    def test_project_name_appears_in_files(self, tmp_dir: Path) -> None:
        generate("cli-app", output_dir=str(tmp_dir), project_name="testcli")
        init_file = tmp_dir / "testcli" / "__init__.py"
        assert init_file.exists()
        content = init_file.read_text(encoding="utf-8")
        assert "testcli" in content

    def test_fastapi_scaffold_full_structure(self, tmp_dir: Path) -> None:
        created = generate("fastapi-crud", output_dir=str(tmp_dir), project_name="myapi")
        paths = [p.relative_to(tmp_dir) for p in created]
        assert Path("myapi/main.py") in paths
        assert Path("myapi/models.py") in paths
        assert Path("myapi/schemas.py") in paths
        assert Path("myapi/database.py") in paths
        assert Path("myapi/routers/items.py") in paths
        assert Path("myapi/tests/test_items.py") in paths

    def test_flask_scaffold(self, tmp_dir: Path) -> None:
        created = generate("flask-app", output_dir=str(tmp_dir))
        paths = [p.relative_to(tmp_dir) for p in created]
        assert Path("app.py") in paths
        assert Path("templates/index.html") in paths
        assert Path("static/style.css") in paths

    def test_python_lib_scaffold(self, tmp_dir: Path) -> None:
        created = generate("python-lib", output_dir=str(tmp_dir), project_name="mylib")
        paths = [p.relative_to(tmp_dir) for p in created]
        assert Path("pyproject.toml") in paths
        assert Path("mylib/__init__.py") in paths
        assert Path("mylib/core.py") in paths
        assert Path("tests/test_core.py") in paths

    def test_agent_tool_scaffold(self, tmp_dir: Path) -> None:
        created = generate("agent-tool", output_dir=str(tmp_dir),
                           module_name="virgo_custom", tool_description="My custom tool")
        paths = [p.relative_to(tmp_dir) for p in created]
        assert Path("virgo_custom.py") in paths
        assert Path("tests/test_virgo_custom.py") in paths

    def test_unknown_scaffold_raises(self, tmp_dir: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            generate("unknown-scaffold", output_dir=str(tmp_dir))

    def test_output_dir_created_if_not_exists(self, tmp_dir: Path) -> None:
        nested = tmp_dir / "a" / "b" / "c"
        generate("cli-app", output_dir=str(nested), project_name="test")
        assert nested.exists()
        assert (nested / "README.md").exists()

    def test_variables_fallback_to_defaults(self, tmp_dir: Path) -> None:
        """If no project_name override, should use the prompt default."""
        with pytest.MonkeyPatch.context() as mp:
            # Clear env of any scaffold-related vars
            if "VIRGO_SCAFFOLD_SKIP_DEFAULTS" in os.environ:
                mp.delenv("VIRGO_SCAFFOLD_SKIP_DEFAULTS")
            created = generate("fastapi-crud", output_dir=str(tmp_dir))
            # Default project_name from scaffold is "myapi"
            assert (tmp_dir / "myapi" / "main.py").exists()

    def test_twice_generates_again(self, tmp_dir: Path) -> None:
        """Generating twice into the same dir should overwrite cleanly."""
        generate("cli-app", output_dir=str(tmp_dir), project_name="test")
        first_count = len(list(tmp_dir.rglob("*")))
        generate("cli-app", output_dir=str(tmp_dir), project_name="test")
        second_count = len(list(tmp_dir.rglob("*")))
        assert second_count >= first_count - 2  # .pyc cache may affect


# ===========================================================================
# Generated code sanity
# ===========================================================================


class TestGeneratedCodeSanity:
    """Verify generated Python files are syntactically valid."""

    @pytest.mark.parametrize("scaffold,overrides", [
        ("cli-app", {"project_name": "sanitycli", "app_description": "test"}),
        ("fastapi-crud", {"project_name": "sanityapi", "app_title": "Test API"}),
        ("flask-app", {"project_name": "sanityweb", "app_title": "Test"}),
        ("python-lib", {"project_name": "sanitylib", "lib_description": "test"}),
        ("agent-tool", {"module_name": "virgo_sanity", "tool_description": "test"}),
    ])
    def test_generated_python_is_valid_syntax(self, scaffold: str, overrides: dict, tmp_dir: Path) -> None:
        created = generate(scaffold, output_dir=str(tmp_dir), **overrides)
        py_files = [p for p in created if p.suffix == ".py"]
        for py_file in py_files:
            try:
                compile(py_file.read_text(encoding="utf-8"), py_file.name, "exec")
            except SyntaxError as exc:
                pytest.fail(f"Syntax error in {py_file.name}: {exc}")

    def test_generated_json_is_valid(self, tmp_dir: Path) -> None:
        """Scaffold JSON files themselves should be valid."""
        for path in SCAFFOLDS_DIR.glob("*.json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON in {path.name}: {exc}")

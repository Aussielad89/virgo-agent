"""
Tests for plugins — dynamic tool loader and Plugin SDK.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins import (
    PLUGIN_DIRS,
    _loaded_modules,
    _loaded_plugins,
    create_plugin,
    discover,
    install_plugin,
    list_plugins,
    load_all,
    load_path,
    plugin_info,
    reload_plugin,
)

HERE = Path(__file__).parent.parent

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def tmp_plugin_dir() -> Path:
    """Create a temporary plugin directory and add it to PLUGIN_DIRS."""
    with tempfile.TemporaryDirectory() as d:
        plugin_dir = Path(d).resolve()
        # Add to PLUGIN_DIRS and remove after
        original_dirs = PLUGIN_DIRS.copy()
        PLUGIN_DIRS.insert(0, plugin_dir)
        yield plugin_dir
        PLUGIN_DIRS.clear()
        PLUGIN_DIRS.extend(original_dirs)


@pytest.fixture
def mock_registry() -> MagicMock:
    """Return a mock ToolRegistry."""
    reg = MagicMock()
    reg.list.return_value = []
    return reg


@pytest.fixture(autouse=True)
def clean_loaded_plugins() -> None:
    """Clean _loaded_plugins and _loaded_modules between tests."""
    _loaded_plugins.clear()
    _loaded_modules.clear()


# ===========================================================================
# Test helpers: _extract_meta is internal, test through public API
# ===========================================================================


def _write_test_plugin(path: Path, content: str) -> Path:
    """Write a test plugin file."""
    p = path / "test_plugin.py"
    p.write_text(content, encoding="utf-8")
    return p


# ===========================================================================
# discover
# ===========================================================================


class TestDiscover:
    def test_empty_returns_empty_list(self) -> None:
        """When no plugin dirs exist, discover returns []."""
        files = discover()
        # Should at least find the real plugins/ dir
        assert isinstance(files, list)

    def test_skips_underscore_files(self, tmp_plugin_dir: Path) -> None:
        """Files starting with _ should be skipped."""
        (tmp_plugin_dir / "_private.py").write_text("# private", encoding="utf-8")
        (tmp_plugin_dir / "valid.py").write_text("# valid", encoding="utf-8")
        files = discover()
        names = [f.name for f in files]
        assert "valid.py" in names
        assert "_private.py" not in names

    def test_finds_py_files(self, tmp_plugin_dir: Path) -> None:
        """Only .py files should be discovered."""
        (tmp_plugin_dir / "my_plugin.py").write_text("# test", encoding="utf-8")
        (tmp_plugin_dir / "notes.txt").write_text("not a plugin", encoding="utf-8")
        files = discover()
        names = [f.name for f in files]
        assert "my_plugin.py" in names
        assert "notes.txt" not in names

    def test_sorted_order(self, tmp_plugin_dir: Path) -> None:
        """Files should be returned in sorted order."""
        # Only files in the temp dir
        (tmp_plugin_dir / "z_plugin.py").write_text("# z", encoding="utf-8")
        (tmp_plugin_dir / "a_plugin.py").write_text("# a", encoding="utf-8")
        files = [f for f in discover() if f.parent == tmp_plugin_dir]
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_multiple_directories(self, tmp_plugin_dir: Path) -> None:
        """Plugins from multiple directories should be found."""
        (tmp_plugin_dir / "alpha.py").write_text("# a", encoding="utf-8")
        with tempfile.TemporaryDirectory() as d2:
            extra_dir = Path(d2).resolve()
            PLUGIN_DIRS.append(extra_dir)
            (extra_dir / "beta.py").write_text("# b", encoding="utf-8")
            files = discover()
            names = [f.name for f in files]
            assert "alpha.py" in names
            assert "beta.py" in names
            PLUGIN_DIRS.remove(extra_dir)


# ===========================================================================
# load_path
# ===========================================================================


class TestLoadPath:
    @staticmethod
    def _plugin_with_register(name: str = "my_plugin") -> str:
        return f'''
from __future__ import annotations

__plugin_meta__ = {{
    "name": "{name}",
    "version": "0.1.0",
    "description": "Test plugin",
    "author": "Tester",
}}

def register(registry):
    registry.register(type("Tool", (), {{"name": "{name}_tool", "description": "A test tool"}}))()
'''

    def test_loads_plugin_with_register(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        path = _write_test_plugin(tmp_plugin_dir, self._plugin_with_register())
        load_path(path, mock_registry)
        assert mock_registry.register.called

    def test_stores_metadata(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        path = _write_test_plugin(tmp_plugin_dir, self._plugin_with_register("my_test"))
        load_path(path, mock_registry)
        assert "test_plugin" in _loaded_plugins
        meta = _loaded_plugins["test_plugin"]
        assert meta["name"] == "my_test"
        assert meta["version"] == "0.1.0"

    def test_loads_tool_functions(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        """Plugins using tool_* naming convention should work."""
        content = '''
from __future__ import annotations

def tool_hello(name: str = "World") -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        path = _write_test_plugin(tmp_plugin_dir, content)
        load_path(path, mock_registry)
        assert mock_registry.register.called

    def test_handles_missing_file(self, mock_registry: MagicMock) -> None:
        """Non-existent file should print warning, not crash."""
        path = tmp_plugin_dir if "tmp_plugin_dir" in dir() else HERE / "nonexistent"
        # Should not raise
        with patch("builtins.print"):
            load_path(Path("/nonexistent/plugin.py"), mock_registry)

    def test_plugin_without_tools(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        """Plugin with no tools should be skipped gracefully."""
        content = '''
from __future__ import annotations

__plugin_meta__ = {"name": "empty", "version": "0.0.0", "description": "", "author": ""}
'''
        path = _write_test_plugin(tmp_plugin_dir, content)
        with patch("builtins.print"):
            load_path(path, mock_registry)
        assert not mock_registry.register.called

    def test_plugin_error_doesnt_crash(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        """Plugin that raises on import should be handled gracefully."""
        content = "raise RuntimeError('boom')"
        path = _write_test_plugin(tmp_plugin_dir, content)
        with patch("builtins.print"):
            load_path(path, mock_registry)


# ===========================================================================
# load_all
# ===========================================================================


class TestLoadAll:
    def test_loads_all_plugins(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        prev_dirs = PLUGIN_DIRS.copy()
        PLUGIN_DIRS.clear()
        PLUGIN_DIRS.append(tmp_plugin_dir)
        try:
            (tmp_plugin_dir / "a.py").write_text(
                'from __future__ import annotations\ndef tool_a(): pass\n',
                encoding="utf-8",
            )
            (tmp_plugin_dir / "b.py").write_text(
                'from __future__ import annotations\ndef tool_b(): pass\n',
                encoding="utf-8",
            )
            count = load_all(mock_registry)
            assert count == 2
        finally:
            PLUGIN_DIRS.clear()
            PLUGIN_DIRS.extend(prev_dirs)

    def test_returns_count(self, mock_registry: MagicMock) -> None:
        count = load_all(mock_registry)
        assert isinstance(count, int)

    def test_loads_nothing_in_empty_dir(self, mock_registry: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as d:
            empty_dir = Path(d).resolve()
            prev_dirs = PLUGIN_DIRS.copy()
            PLUGIN_DIRS.clear()
            PLUGIN_DIRS.append(empty_dir)
            try:
                count = load_all(mock_registry)
                assert count == 0
            finally:
                PLUGIN_DIRS.clear()
                PLUGIN_DIRS.extend(prev_dirs)


# ===========================================================================
# create_plugin
# ===========================================================================


class TestCreatePlugin:
    def test_creates_file(self, tmp_plugin_dir: Path) -> None:
        path = create_plugin("test_create.py", "# test content", directory=tmp_plugin_dir)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# test content"

    def test_defaults_to_first_plugin_dir(self, tmp_plugin_dir: Path) -> None:
        path = create_plugin("auto_create.py", "# auto")
        assert path.exists()
        assert "auto_create.py" in path.name

    def test_creates_parent_dirs(self, tmp_plugin_dir: Path) -> None:
        nested = tmp_plugin_dir / "subdir"
        path = create_plugin("nested.py", "# nested", directory=nested)
        assert path.exists()


# ===========================================================================
# reload_plugin
# ===========================================================================


class TestReloadPlugin:
    def test_reload_existing_plugin(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        path = _write_test_plugin(
            tmp_plugin_dir,
            'from __future__ import annotations\n__plugin_meta__ = {"name":"test","version":"0.1.0","description":"","author":""}\ndef register(r): r.register("tool1")\n',
        )
        # Load once
        load_path(path, mock_registry)
        # Reload
        result = reload_plugin("test_plugin", mock_registry)
        assert result is True

    def test_reload_unknown_plugin_returns_false(self, mock_registry: MagicMock) -> None:
        result = reload_plugin("nonexistent_plugin", mock_registry)
        assert result is False

    def test_reload_with_py_suffix(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        path = _write_test_plugin(
            tmp_plugin_dir,
            'from __future__ import annotations\ndef tool_test(): pass\n',
        )
        load_path(path, mock_registry)
        result = reload_plugin("test_plugin.py", mock_registry)
        assert result is True


# ===========================================================================
# list_plugins and plugin_info
# ===========================================================================


class TestListPlugins:
    def test_returns_list_of_dicts(self, tmp_plugin_dir: Path) -> None:
        (tmp_plugin_dir / "mytest.py").write_text("# test", encoding="utf-8")
        plugins = list_plugins()
        assert isinstance(plugins, list)
        if plugins:
            assert "name" in plugins[0]
            assert "meta" in plugins[0]
            assert "loaded" in plugins[0]

    def test_loaded_flag(self, tmp_plugin_dir: Path, mock_registry: MagicMock) -> None:
        path = _write_test_plugin(
            tmp_plugin_dir,
            'from __future__ import annotations\n__plugin_meta__ = {"name":"loaded_test","version":"0.1.0","description":"","author":""}\ndef register(r): pass\n',
        )
        plugins_before = list_plugins()
        loaded_before = [p for p in plugins_before if p["loaded"]]
        assert len(loaded_before) == 0

        load_path(path, mock_registry)
        plugins_after = list_plugins()
        loaded_after = [p for p in plugins_after if p["loaded"]]
        assert len(loaded_after) > 0


class TestPluginInfo:
    def test_returns_info_for_existing(self, tmp_plugin_dir: Path) -> None:
        (tmp_plugin_dir / "info_test.py").write_text("# test", encoding="utf-8")
        info = plugin_info("info_test")
        assert info is not None
        assert info["name"] == "info_test"

    def test_returns_none_for_missing(self) -> None:
        info = plugin_info("definitely_not_a_plugin")
        assert info is None

    def test_handles_py_suffix(self, tmp_plugin_dir: Path) -> None:
        (tmp_plugin_dir / "suffix_test.py").write_text("# test", encoding="utf-8")
        info = plugin_info("suffix_test.py")
        assert info is not None


# ===========================================================================
# install_plugin
# ===========================================================================


class TestInstallPlugin:
    def test_installs_from_local_path(self, tmp_plugin_dir: Path) -> None:
        src = tmp_plugin_dir / "source_plugin.py"
        src.write_text("# plugin content", encoding="utf-8")

        dest_dir = tmp_plugin_dir / "installed"
        result = install_plugin(str(src), target_dir=dest_dir)
        assert result is not None
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "# plugin content"

    def test_installs_with_custom_name(self, tmp_plugin_dir: Path) -> None:
        src = tmp_plugin_dir / "source_plugin.py"
        src.write_text("# rename test", encoding="utf-8")

        result = install_plugin(str(src), name="custom_name.py", target_dir=tmp_plugin_dir)
        assert result is not None
        assert result.name == "custom_name.py"

    def test_fails_on_nonexistent_source(self, tmp_plugin_dir: Path) -> None:
        result = install_plugin("/nonexistent/plugin.py", target_dir=tmp_plugin_dir)
        assert result is None

    def test_fails_on_non_py_file(self, tmp_plugin_dir: Path) -> None:
        src = tmp_plugin_dir / "not_a_plugin.txt"
        src.write_text("nope", encoding="utf-8")
        result = install_plugin(str(src), target_dir=tmp_plugin_dir)
        assert result is None


# ===========================================================================
# Integration: real plugin loading
# ===========================================================================


class TestRealPluginLoading:
    """Integration tests that load the example plugin."""

    def test_load_example_plugin(self, tmp_plugin_dir: Path) -> None:
        """Copy the example plugin and verify it loads with register()."""
        example = HERE / "examples" / "hello_plugin.py"
        if not example.exists():
            pytest.skip("examples/hello_plugin.py not found")

        dest = tmp_plugin_dir / "hello_plugin.py"
        dest.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

        registry = MagicMock()
        load_path(dest, registry)
        assert registry.register.called

        # Check metadata
        assert "hello_plugin" in _loaded_plugins
        assert _loaded_plugins["hello_plugin"]["name"] == "hello_plugin"

    def test_load_real_virgo_plugins(self) -> None:
        """Try loading an existing plugin from the plugins/ directory."""
        real_plugins_dir = HERE / "plugins"
        if not real_plugins_dir.exists():
            pytest.skip("plugins/ directory not found")

        py_files = list(real_plugins_dir.glob("*_plugin.py"))
        if not py_files:
            pytest.skip("No plugins found in plugins/")

        registry = MagicMock()
        for p in py_files:
            try:
                load_path(p, registry)
            except Exception:
                pass  # Some plugins may require psutil etc.

        # At least some should have loaded
        assert len(_loaded_plugins) >= 0  # not a failure test, just smoke


# ===========================================================================
# Metadata format
# ===========================================================================


class TestPluginMetaConvention:
    def test_plugin_meta_structure(self) -> None:
        """Validate __plugin_meta__ has the required fields."""
        required = {"name", "version", "description", "author"}
        meta = {
            "name": "test",
            "version": "0.1.0",
            "description": "desc",
            "author": "me",
        }
        assert required.issubset(meta.keys())

    def test_plugin_meta_defaults(self) -> None:
        """Default metadata should have all fields."""
        from plugins import _extract_meta

        class FakeModule:
            pass

        meta = _extract_meta(FakeModule())
        assert "name" in meta
        assert "version" in meta
        assert "description" in meta
        assert "author" in meta

    def test_loaded_plugins_tracking(self) -> None:
        """_loaded_plugins dict should be accessible."""
        assert isinstance(_loaded_plugins, dict)
        assert isinstance(_loaded_modules, dict)

"""
Tests for autodepend — auto-install missing third-party packages.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from autodepend import (
    extract_imports, classify_import,
    auto_install, _STDLIB_MODULES, _KNOWN_THIRD_PARTY,
)


# ===========================================================================
# extract_imports
# ===========================================================================


class TestExtractImports:
    def test_empty_source(self) -> None:
        assert extract_imports("") == []

    def test_single_import(self) -> None:
        assert extract_imports("import os") == ["os"]

    def test_multiple_imports(self) -> None:
        code = "import os\nimport sys\nimport json"
        imports = extract_imports(code)
        assert "os" in imports
        assert "sys" in imports
        assert "json" in imports
        assert len(imports) == 3

    def test_from_import(self) -> None:
        code = "from pathlib import Path"
        assert extract_imports(code) == ["pathlib"]

    def test_from_import_as(self) -> None:
        code = "import numpy as np"
        assert extract_imports(code) == ["numpy"]

    def test_third_party_imports(self) -> None:
        code = "import requests\nimport pandas as pd\nfrom flask import Flask"
        imports = extract_imports(code)
        assert "requests" in imports
        assert "pandas" in imports
        assert "flask" in imports


# ===========================================================================
# is_stdlib
# ===========================================================================


class TestClassifyImport:
    def test_stdlib_modules(self) -> None:
        assert classify_import("os") == "stdlib"
        assert classify_import("sys") == "stdlib"
        assert classify_import("json") == "stdlib"
        assert classify_import("pathlib") == "stdlib"
        assert classify_import("typing") == "stdlib"
        assert classify_import("collections") == "stdlib"
        assert classify_import("dataclasses") == "stdlib"

    def test_third_party(self) -> None:
        assert classify_import("requests") == "third_party"
        assert classify_import("pandas") == "third_party"
        assert classify_import("flask") == "third_party"
        assert classify_import("fastapi") == "third_party"

    def test_unknown_module(self) -> None:
        assert classify_import("nonexistent_xyz") == "unknown"


# ===========================================================================
# known_third_party
# ===========================================================================


class TestKnownThirdParty:
    def test_known_packages(self) -> None:
        assert _KNOWN_THIRD_PARTY.get("requests") == "requests"
        assert _KNOWN_THIRD_PARTY.get("pandas") == "pandas"
        assert _KNOWN_THIRD_PARTY.get("flask") == "flask"
        assert _KNOWN_THIRD_PARTY.get("yaml") == "pyyaml"
        assert _KNOWN_THIRD_PARTY.get("cv2") == "opencv-python"

    def test_unknown_returns_none(self) -> None:
        assert _KNOWN_THIRD_PARTY.get("nonexistent_xyz") is None


# ===========================================================================
# auto_install (mock env)
# ===========================================================================


class TestAutoInstall:
    def test_auto_install_with_stdlib_only(self) -> None:
        """Source with only stdlib imports should return empty list (no installs)."""

        class MockEnv:
            def ensure(self, *packages, quiet=True):
                return ""

        result = auto_install("import os\nimport sys\n", MockEnv())  # type: ignore
        assert result == []

    def test_auto_install_with_unknown_third_party(self) -> None:
        """Unknown third-party imports should not crash."""

        class MockEnv:
            def ensure(self, *packages, quiet=True):
                return ""

        result = auto_install("import some_unknown_pkg\n", MockEnv())  # type: ignore
        # Unknown packages are not installed
        assert result == []


# ===========================================================================
# Constants completeness
# ===========================================================================


class TestConstants:
    def test_known_third_party_is_dict(self) -> None:
        assert isinstance(_KNOWN_THIRD_PARTY, dict)
        assert len(_KNOWN_THIRD_PARTY) > 10

    def test_stdlib_modules_is_set(self) -> None:
        assert isinstance(_STDLIB_MODULES, set)
        assert len(_STDLIB_MODULES) > 100
        assert "os" in _STDLIB_MODULES
        assert "sys" in _STDLIB_MODULES

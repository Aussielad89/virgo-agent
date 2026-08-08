"""
Import-level smoke tests for experimental desktop pages.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 is a desktop-only dependency, not installed in CI")

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))


def test_experimental_page_imports() -> None:
    from virgo_desktop_pages import (
        SonificationPage,
        DreamsPage,
        FlavorPage,
        GhostPage,
        ArchaeologyPage,
        EmpathyPage,
        AuditPage,
        MemesPage,
        StigmergyPage,
        DivergencePage,
    )

    assert SonificationPage is not None
    assert DreamsPage is not None
    assert FlavorPage is not None
    assert GhostPage is not None
    assert ArchaeologyPage is not None
    assert EmpathyPage is not None
    assert AuditPage is not None
    assert MemesPage is not None
    assert StigmergyPage is not None
    assert DivergencePage is not None


class TestExperimentalPageInstantiation:
    @pytest.fixture(scope="class")
    def app(self) -> "QApplication":
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication(sys.argv)

    def test_sonification_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import SonificationPage

        page = SonificationPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_dreams_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import DreamsPage

        page = DreamsPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_flavor_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import FlavorPage

        page = FlavorPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_ghost_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import GhostPage

        page = GhostPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_archaeology_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import ArchaeologyPage

        page = ArchaeologyPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_empathy_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import EmpathyPage

        page = EmpathyPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_audit_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import AuditPage

        page = AuditPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_memes_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import MemesPage

        page = MemesPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_stigmergy_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import StigmergyPage

        page = StigmergyPage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

    def test_divergence_page(self, app: "QApplication") -> None:
        from virgo_desktop_pages import DivergencePage

        page = DivergencePage()
        assert hasattr(page, "run_btn")
        assert hasattr(page, "output")

"""
Tests for experimental virgo_* modules.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))


class TestPipelineSonification:
    def test_play_phase_does_not_raise(self) -> None:
        from virgo_pipeline_sonification import play_phase

        play_phase("discover")
        play_phase("plan")
        play_phase("generate")
        play_phase("test")
        play_phase("fix")
        play_phase("done")
        play_phase("error")
        play_phase("idle")

    def test_phases_keys_cover_expected(self) -> None:
        from virgo_pipeline_sonification import _PHASES

        expected = {"discover", "plan", "generate", "test", "fix", "done", "error", "idle"}
        assert set(_PHASES.keys()) == expected


class TestDreams:
    def test_dream_now_returns_dict_with_keys(self, tmp_path: Path) -> None:
        from virgo_dreams import DREAMS_DIR, dream_now

        original_dreams_dir = DREAMS_DIR
        try:
            import virgo_dreams as mod
            mod.DREAMS_DIR = tmp_path / ".virgo_dreams"
            mod.DREAMS_DIR.mkdir(exist_ok=True)
            mod.DREAM_INDEX = mod.DREAMS_DIR / "index.json"
            result = dream_now()
            assert isinstance(result, dict)
            assert "dreams" in result
            assert "insights" in result
        finally:
            mod.DREAMS_DIR = original_dreams_dir
            mod.DREAM_INDEX = original_dreams_dir / "index.json"

    def test_get_morning_briefing_returns_dict(self, tmp_path: Path) -> None:
        from virgo_dreams import DREAMS_DIR, get_morning_briefing

        original_dreams_dir = DREAMS_DIR
        try:
            import virgo_dreams as mod
            mod.DREAMS_DIR = tmp_path / ".virgo_dreams"
            mod.DREAMS_DIR.mkdir(exist_ok=True)
            mod.DREAM_INDEX = mod.DREAMS_DIR / "index.json"
            result = get_morning_briefing()
            assert isinstance(result, dict)
        finally:
            mod.DREAMS_DIR = original_dreams_dir
            mod.DREAM_INDEX = original_dreams_dir / "index.json"


class TestFlavor:
    def test_scan_repo_returns_expected_keys(self, tmp_path: Path) -> None:
        from virgo_flavor import FLAVOR_FILE, scan_repo

        original_flavor_file = FLAVOR_FILE
        try:
            import virgo_flavor as mod
            mod.FLAVOR_FILE = tmp_path / ".virgo_flavor.json"
            result = scan_repo(root=str(tmp_path))
            assert isinstance(result, dict)
            assert "dominant_flavor" in result
            assert "vector" in result
        finally:
            mod.FLAVOR_FILE = original_flavor_file

    def test_get_flavor_returns_cached_result(self, tmp_path: Path) -> None:
        from virgo_flavor import FLAVOR_FILE, get_flavor, scan_repo

        original_flavor_file = FLAVOR_FILE
        try:
            import virgo_flavor as mod
            mod.FLAVOR_FILE = tmp_path / ".virgo_flavor.json"
            scan_repo(root=str(tmp_path))
            cached = get_flavor()
            assert isinstance(cached, dict)
            assert "dominant_flavor" in cached
        finally:
            mod.FLAVOR_FILE = original_flavor_file


class TestGhost:
    def test_ghost_write_creates_file_under_dot_virgo_ghost(self, tmp_path: Path) -> None:
        from virgo_ghost import GHOST_INDEX, GHOST_ROOT, ghost_write

        original_ghost_root = GHOST_ROOT
        original_ghost_index = GHOST_INDEX
        try:
            import virgo_ghost as mod
            mod.GHOST_ROOT = tmp_path / ".virgo_ghost"
            mod.GHOST_INDEX = mod.GHOST_ROOT / ".ghost_index.json"
            target = ghost_write("test_ghost.py", "print('hello')", root=tmp_path)
            assert target.exists()
            assert target.parent.name == ".virgo_ghost"
        finally:
            mod.GHOST_ROOT = original_ghost_root
            mod.GHOST_INDEX = original_ghost_index

    def test_manifest_copies_ghost_to_real(self, tmp_path: Path) -> None:
        from virgo_ghost import GHOST_INDEX, GHOST_ROOT, ghost_write, manifest

        original_ghost_root = GHOST_ROOT
        original_ghost_index = GHOST_INDEX
        try:
            import virgo_ghost as mod
            mod.GHOST_ROOT = tmp_path / ".virgo_ghost"
            mod.GHOST_INDEX = mod.GHOST_ROOT / ".ghost_index.json"
            ghost_write("test_manifest.py", "print('manifested')", root=tmp_path)
            result = manifest("test_manifest.py", root=tmp_path)
            assert result is True
            real_path = tmp_path / "test_manifest.py"
            assert real_path.exists()
        finally:
            mod.GHOST_ROOT = original_ghost_root
            mod.GHOST_INDEX = original_ghost_index

    def test_discard_removes_ghost(self, tmp_path: Path) -> None:
        from virgo_ghost import GHOST_INDEX, GHOST_ROOT, ghost_write, discard

        original_ghost_root = GHOST_ROOT
        original_ghost_index = GHOST_INDEX
        try:
            import virgo_ghost as mod
            mod.GHOST_ROOT = tmp_path / ".virgo_ghost"
            mod.GHOST_INDEX = mod.GHOST_ROOT / ".ghost_index.json"
            ghost_write("test_discard.py", "print('discard me')", root=tmp_path)
            result = discard("test_discard.py")
            assert result is True
            assert not (tmp_path / ".virgo_ghost" / "test_discard.py").exists()
        finally:
            mod.GHOST_ROOT = original_ghost_root
            mod.GHOST_INDEX = original_ghost_index

    def test_list_ghosts_returns_list(self, tmp_path: Path) -> None:
        from virgo_ghost import GHOST_INDEX, GHOST_ROOT, ghost_write, list_ghosts

        original_ghost_root = GHOST_ROOT
        original_ghost_index = GHOST_INDEX
        try:
            import virgo_ghost as mod
            mod.GHOST_ROOT = tmp_path / ".virgo_ghost"
            mod.GHOST_INDEX = mod.GHOST_ROOT / ".ghost_index.json"
            ghost_write("list_test.py", "print(1)", root=tmp_path)
            ghosts = list_ghosts(root=tmp_path)
            assert isinstance(ghosts, list)
            assert len(ghosts) == 1
        finally:
            mod.GHOST_ROOT = original_ghost_root
            mod.GHOST_INDEX = original_ghost_index


class TestArchaeology:
    def test_blame_returns_list(self) -> None:
        from virgo_archaeology import blame

        result = blame("README.md")
        assert isinstance(result, list)

    def test_log_for_file_returns_list(self) -> None:
        from virgo_archaeology import log_for_file

        result = log_for_file("README.md")
        assert isinstance(result, list)


class TestEmpathy:
    def test_analyze_repo_mood_returns_expected_keys(self, tmp_path: Path) -> None:
        from virgo_empathy import EMPATHY_FILE, analyze_repo_mood

        original_empathy_file = EMPATHY_FILE
        try:
            import virgo_empathy as mod
            mod.EMPATHY_FILE = tmp_path / ".virgo_empathy.json"
            result = analyze_repo_mood()
            assert isinstance(result, dict)
            assert "mood" in result
            assert "tone" in result
            assert "risk_appetite" in result
        finally:
            mod.EMPATHY_FILE = original_empathy_file

    def test_calibrate_prompt_prepends_prefix_for_non_neutral_tone(self, tmp_path: Path) -> None:
        from virgo_empathy import EMPATHY_FILE, calibrate_prompt

        original_empathy_file = EMPATHY_FILE
        try:
            import virgo_empathy as mod
            mod.EMPATHY_FILE = tmp_path / ".virgo_empathy.json"
            mod.EMPATHY_FILE.write_text(
                '{"tone": "cautious", "mood": "stressed", "risk_appetite": "high"}'
            )
            result = calibrate_prompt("do the thing")
            assert result.startswith("[CAUTION]")
            assert "do the thing" in result
        finally:
            mod.EMPATHY_FILE = original_empathy_file


class TestAudit:
    def test_append_record_appends(self, tmp_path: Path) -> None:
        from virgo_audit import CHAIN_FILE, append_record

        original_chain_file = CHAIN_FILE
        try:
            import virgo_audit as mod
            mod.CHAIN_FILE = tmp_path / ".virgo_audit_chain.json"
            entry = append_record({"action": "test"})
            assert entry["entry_hash"] is not None
            assert mod.CHAIN_FILE.exists()
        finally:
            mod.CHAIN_FILE = original_chain_file

    def test_verify_chain_returns_dict_with_valid_key(self, tmp_path: Path) -> None:
        from virgo_audit import CHAIN_FILE, append_record, verify_chain

        original_chain_file = CHAIN_FILE
        try:
            import virgo_audit as mod
            mod.CHAIN_FILE = tmp_path / ".virgo_audit_chain.json"
            append_record({"action": "verify_test"})
            result = verify_chain()
            assert isinstance(result, dict)
            assert "valid" in result
        finally:
            mod.CHAIN_FILE = original_chain_file

    def test_tail_returns_list(self, tmp_path: Path) -> None:
        from virgo_audit import CHAIN_FILE, append_record, tail

        original_chain_file = CHAIN_FILE
        try:
            import virgo_audit as mod
            mod.CHAIN_FILE = tmp_path / ".virgo_audit_chain.json"
            append_record({"action": "tail_test"})
            result = tail(5)
            assert isinstance(result, list)
        finally:
            mod.CHAIN_FILE = original_chain_file


class TestMemes:
    def test_generate_meme_returns_expected_keys(self) -> None:
        from virgo_memes import generate_meme

        result = generate_meme("success")
        assert isinstance(result, dict)
        assert "title" in result
        assert "art" in result
        assert "outcome" in result


class TestStigmergy:
    def test_deposit_increases_failures_when_kind_fail(self, tmp_path: Path) -> None:
        from virgo_stigmergy import STIG_FILE, deposit

        original_stig_file = STIG_FILE
        try:
            import virgo_stigmergy as mod
            mod.STIG_FILE = tmp_path / "pheromones.json"
            mod.STIG_FILE.write_text("{}")
            deposit("test_file.py", amount=1.0, kind="fail")
            import json
            data = json.loads(mod.STIG_FILE.read_text())
            assert data["test_file.py"]["failures"] == 1
        finally:
            mod.STIG_FILE = original_stig_file

    def test_heatmap_returns_dict_with_hot_files(self, tmp_path: Path) -> None:
        from virgo_stigmergy import STIG_FILE, deposit, heatmap

        original_stig_file = STIG_FILE
        try:
            import virgo_stigmergy as mod
            mod.STIG_FILE = tmp_path / "pheromones.json"
            mod.STIG_FILE.write_text("{}")
            deposit("hot_file.py", amount=2.0, kind="edit")
            result = heatmap(root=tmp_path)
            assert isinstance(result, dict)
            assert "hot_files" in result
        finally:
            mod.STIG_FILE = original_stig_file


class TestDivergence:
    def test_create_root_returns_dict(self) -> None:
        from virgo_divergence import create_root

        result = create_root("session_123")
        assert isinstance(result, dict)
        assert "root_id" in result

    def test_fork_branch_returns_dict(self) -> None:
        from virgo_divergence import create_root, fork_branch

        root = create_root("session_fork_test")
        result = fork_branch(root["root_id"])
        assert isinstance(result, dict)
        assert "branch_id" in result

    def test_lineage_tree_returns_dict(self) -> None:
        from virgo_divergence import create_root, fork_branch, lineage_tree

        root = create_root("session_lineage_test")
        fork_branch(root["root_id"])
        result = lineage_tree(root["root_id"])
        assert isinstance(result, dict)
        assert "root" in result
        assert "branches" in result

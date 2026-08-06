"""Tests for virgo_checkpoint module."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest


class TestCheckpointManager:
    """Tests for CheckpointManager without orchestrator dependency."""

    def test_import(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint
        assert CheckpointManager is not None
        assert Checkpoint is not None

    def test_save_load_roundtrip(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            cp = Checkpoint(
                session="test_session",
                goal="Test goal",
                phase="testing",
                iteration=2,
                max_iterations=5,
                loop_passed=False,
                plan="Test plan",
                generated_files=[{"path": "a.py", "content": "print(1)", "passed": True, "iteration": 1}],
                test_logs=[{"file_path": "a.py", "passed": True, "returncode": 0, "stdout": "", "stderr": ""}],
                discovered_files=[],
                elapsed=10.5,
            )

            path = mgr.save(cp, "test_session", 10.5)
            assert path.exists()

            loaded = mgr.load("test_session")
            assert loaded is not None
            assert loaded.session == "test_session"
            assert loaded.iteration == 2
            assert loaded.goal == "Test goal"
            assert len(loaded.generated_files) == 1

    def test_load_specific_iteration(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            cp1 = Checkpoint(
                session="test_session", goal="Goal", phase="testing", iteration=1,
                max_iterations=5, loop_passed=False, plan="Plan",
                generated_files=[], test_logs=[], discovered_files=[], elapsed=5.0
            )
            cp2 = Checkpoint(
                session="test_session", goal="Goal", phase="testing", iteration=2,
                max_iterations=5, loop_passed=False, plan="Plan",
                generated_files=[], test_logs=[], discovered_files=[], elapsed=10.0
            )

            mgr.save(cp1, "test_session", 5.0)
            mgr.save(cp2, "test_session", 10.0)

            loaded1 = mgr.load_iteration("test_session", 1)
            loaded2 = mgr.load_iteration("test_session", 2)

            assert loaded1 is not None
            assert loaded1.iteration == 1
            assert loaded2 is not None
            assert loaded2.iteration == 2

    def test_list_sessions(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            # Create two sessions
            cp1 = Checkpoint(
                session="session_a", goal="Goal A", phase="testing", iteration=1,
                max_iterations=5, loop_passed=False, plan="Plan",
                generated_files=[], test_logs=[], discovered_files=[], elapsed=5.0
            )
            cp2 = Checkpoint(
                session="session_b", goal="Goal B", phase="complete", iteration=3,
                max_iterations=5, loop_passed=True, plan="Plan",
                generated_files=[{"path": "x.py", "content": "", "passed": True, "iteration": 3}],
                test_logs=[], discovered_files=[], elapsed=15.0
            )

            mgr.save(cp1, "session_a", 5.0)
            mgr.save(cp2, "session_b", 15.0)

            sessions = mgr.list_sessions()
            assert len(sessions) == 2
            names = [s["session"] for s in sessions]
            assert "session_a" in names
            assert "session_b" in names

    def test_delete_session(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            cp = Checkpoint(
                session="to_delete", goal="Goal", phase="testing", iteration=1,
                max_iterations=5, loop_passed=False, plan="Plan",
                generated_files=[], test_logs=[], discovered_files=[], elapsed=5.0
            )

            mgr.save(cp, "to_delete", 5.0)
            assert mgr.delete("to_delete")
            assert not mgr.delete("to_delete")  # already deleted
            assert mgr.load("to_delete") is None

    def test_restore_files(self):
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            cp = Checkpoint(
                session="restore_test", goal="Goal", phase="testing", iteration=1,
                max_iterations=5, loop_passed=False, plan="Plan",
                generated_files=[
                    {"path": "a.py", "content": "print('hello')", "passed": True, "iteration": 1},
                    {"path": "sub/b.py", "content": "print('world')", "passed": False, "iteration": 1},
                ],
                test_logs=[], discovered_files=[], elapsed=5.0
            )

            mgr.save(cp, "restore_test", 5.0)

            base = Path(tmpdir) / "restored"
            count = mgr.restore_files(cp, base)
            assert count == 2
            assert (base / "a.py").read_text() == "print('hello')"
            assert (base / "sub" / "b.py").read_text() == "print('world')"

    def test_checkpoint_summary(self):
        from virgo_checkpoint import Checkpoint

        cp = Checkpoint(
            session="my_session",
            goal="Build a web scraper",
            phase="testing",
            iteration=3,
            max_iterations=5,
            loop_passed=False,
            plan="Plan",
            generated_files=[{"path": "x.py", "content": "", "passed": True, "iteration": 1}],
            test_logs=[],
            discovered_files=[],
            elapsed=45.0,
        )

        summary = cp.summary()
        assert "my_session" in summary
        assert "Build a web scraper" in summary
        assert "testing" in summary
        assert "3/5" in summary


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_save_load_convenience(self):
        from virgo_checkpoint import Checkpoint, save_checkpoint, load_checkpoint, list_checkpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            # Override checkpoint dir by setting environment or using CheckpointManager directly
            from virgo_checkpoint import CheckpointManager
            import virgo_checkpoint
            original_dir = virgo_checkpoint.CHECKPOINT_DIR
            virgo_checkpoint.CHECKPOINT_DIR = Path(tmpdir)

            try:
                cp = Checkpoint(
                    session="convenience", goal="Test", phase="testing", iteration=1,
                    max_iterations=5, loop_passed=False, plan="Plan",
                    generated_files=[], test_logs=[], discovered_files=[], elapsed=1.0
                )

                save_checkpoint(cp, "convenience", 1.0)
                loaded = load_checkpoint("convenience")
                assert loaded is not None
                assert loaded.session == "convenience"

                sessions = list_checkpoints()
                assert len(sessions) == 1
            finally:
                virgo_checkpoint.CHECKPOINT_DIR = original_dir


class TestCheckpointIntegration:
    """Integration-style tests (mock state objects)."""

    def test_state_to_checkpoint_conversion(self):
        """Test that the manager can convert a dict-like state to checkpoint."""
        from virgo_checkpoint import CheckpointManager, Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(Path(tmpdir))

            # Simulate a WorkspaceState-like dict
            mock_state = {
                "goal": "Parse CSV file",
                "phase": "testing",
                "iteration": 2,
                "max_iterations": 5,
                "loop_passed": False,
                "plan": "Read CSV, compute stats, write JSON",
                "generated_files": [
                    {"path": "parser.py", "content": "import csv", "passed": False, "iteration": 1},
                ],
                "test_logs": [
                    {"file_path": "parser.py", "passed": False, "returncode": 1, "stdout": "", "stderr": "ModuleNotFoundError"},
                ],
                "discovered_files": [
                    {"path": "data.csv", "size": 1024, "language": "text"},
                ],
                "context": {"user": "test"},
            }

            # Use internal method to convert
            cp = mgr._state_to_checkpoint(mock_state, "mock_session", 20.0)

            assert cp.session == "mock_session"
            assert cp.goal == "Parse CSV file"
            assert cp.iteration == 2
            assert len(cp.generated_files) == 1
            assert cp.generated_files[0]["path"] == "parser.py"
            assert len(cp.test_logs) == 1
            assert cp.test_logs[0]["returncode"] == 1
            assert len(cp.discovered_files) == 1
            assert cp.context.get("user") == "test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
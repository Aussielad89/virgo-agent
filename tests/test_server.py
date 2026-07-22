"""Tests for the virgo web dashboard (server.py)."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import pytest
from fastapi.testclient import TestClient

from server import _build_app


@pytest.fixture
def client() -> TestClient:
    app = _build_app()
    return TestClient(app)


# ===========================================================================
# HTML page routes
# ===========================================================================


class TestPages:
    """HTML page routes return 200 and contain expected content."""

    def test_sessions_page(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "sessions" in resp.text.lower()

    def test_run_page(self, client: TestClient) -> None:
        resp = client.get("/run")
        assert resp.status_code == 200
        assert "run pipeline" in resp.text.lower()
        assert "goal" in resp.text.lower()

    def test_status_page(self, client: TestClient) -> None:
        resp = client.get("/status")
        assert resp.status_code == 200
        assert "system status" in resp.text.lower()

    def test_log_page(self, client: TestClient) -> None:
        resp = client.get("/log")
        assert resp.status_code == 200
        assert "live log" in resp.text.lower()


class TestSessionPage:
    def test_session_page_found(self, client: TestClient, tmp_path: Path) -> None:
        """Should return 200 for a session that exists."""
        from memory import save_state

        state = {
            "goal": "test goal",
            "phase": "test",
            "iteration": 1,
            "loop_passed": True,
            "generated_files": [],
            "test_logs": [],
        }
        save_state(state, "test_session_web")

        resp = client.get("/session/test_session_web")
        assert resp.status_code == 200
        assert "test_session_web" in resp.text

    def test_session_page_not_found(self, client: TestClient) -> None:
        """Should return 404 for a missing session."""
        resp = client.get("/session/nonexistent_session_xyz")
        assert resp.status_code == 404


# ===========================================================================
# Run pipeline (POST)
# ===========================================================================


class TestRunPipeline:
    def test_run_post_returns_html(self, client: TestClient) -> None:
        """POST /run should return a start confirmation message."""
        resp = client.post("/run", data={"goal": "print hello"})
        assert resp.status_code == 200
        assert "started" in resp.text.lower() or "print hello" in resp.text


# ===========================================================================
# Log routes
# ===========================================================================


class TestLogRoutes:
    def test_log_stream_returns_text(self, client: TestClient) -> None:
        """GET /log-stream should return plain text with at least 'waiting'."""
        resp = client.get("/log-stream")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_log_sse_returns_stream(self, client: TestClient) -> None:
        """GET /log-sse should return an SSE event stream."""
        resp = client.get("/log-sse")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ===========================================================================
# JSON API routes
# ===========================================================================


class TestApi:
    def test_api_sessions(self, client: TestClient) -> None:
        """GET /api/sessions should return a JSON list."""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_session_found(self, client: TestClient, tmp_path: Path) -> None:
        """GET /api/session/{name} should return the session state."""
        from memory import save_state

        save_state({"goal": "api test", "phase": "done"}, "api_test_session")

        resp = client.get("/api/session/api_test_session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["goal"] == "api test"

    def test_api_session_not_found(self, client: TestClient) -> None:
        """GET /api/session/{name} for missing session should return 404."""
        resp = client.get("/api/session/missing_api_session")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_api_status(self, client: TestClient) -> None:
        """GET /api/status should return JSON with version and counts."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "sessions" in data
        assert "experiences" in data


# ===========================================================================
# Error handling & edge cases
# ===========================================================================


class TestEdgeCases:
    def test_unsupported_method(self, client: TestClient) -> None:
        """Unsupported methods should return 405."""
        resp = client.put("/")
        assert resp.status_code == 405

    def test_trailing_slash_redirect(self, client: TestClient) -> None:
        """Known paths should work without trailing slash issues."""
        for path in ("/run", "/status", "/log"):
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"

    def test_all_html_pages_have_layout(self, client: TestClient) -> None:
        """All HTML pages should include the common layout (nav/container)."""
        for path in ("/", "/run", "/status", "/log"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert "virgo" in resp.text

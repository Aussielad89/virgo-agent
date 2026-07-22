"""Tests for the virgo chat persona + safe tool-use layer (cli.py)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from cli import (  # noqa: E402
    _CHAT_TOOLS,
    VIRGO_SYSTEM_PROMPT,
    _chat_blocked,
    _parse_tool_calls,
    _run_chat_tool,
)


class TestSystemPrompt:
    def test_prompt_present_and_descriptive(self) -> None:
        assert isinstance(VIRGO_SYSTEM_PROMPT, str)
        assert len(VIRGO_SYSTEM_PROMPT) > 100
        assert "Virgo" in VIRGO_SYSTEM_PROMPT

    def test_prompt_documents_tool_syntax(self) -> None:
        # The persona should teach the model the tool-call syntax.
        assert "[[virgo.read" in VIRGO_SYSTEM_PROMPT
        assert "[[virgo.web" in VIRGO_SYSTEM_PROMPT
        assert "[[virgo.py" in VIRGO_SYSTEM_PROMPT


class TestToolAllowlist:
    def test_only_safe_tools_allowed(self) -> None:
        assert set(_CHAT_TOOLS) == {"read", "write", "web", "py"}


class TestParseToolCalls:
    def test_parse_single_read(self) -> None:
        calls = _parse_tool_calls('[[virgo.read path="foo.py"]]')
        assert calls == [("read", {"path": "foo.py"})]

    def test_parse_multiple_calls(self) -> None:
        text = (
            'a [[virgo.read path="a.py"]] b '
            "[[virgo.web url=https://x.com]] c "
            '[[virgo.py code="print(1)"]]'
        )
        calls = _parse_tool_calls(text)
        assert ("read", {"path": "a.py"}) in calls
        assert ("web", {"url": "https://x.com"}) in calls
        assert ("py", {"code": "print(1)"}) in calls

    def test_parse_multiline_content(self) -> None:
        text = '[[virgo.write path="x.py" content="a\nb"]]'
        calls = _parse_tool_calls(text)
        assert calls == [("write", {"path": "x.py", "content": "a\nb"})]

    def test_no_calls_returns_empty(self) -> None:
        assert _parse_tool_calls("just text, no tool calls") == []


class TestRunChatTool:
    def test_write_then_read(self) -> None:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "note.txt")
        w = _run_chat_tool("write", {"path": p, "content": "hello chat"})
        assert "wrote" in w
        r = _run_chat_tool("read", {"path": p})
        assert r == "hello chat"

    def test_read_missing_file(self) -> None:
        out = _run_chat_tool("read", {"path": "does_not_exist_xyz.txt"})
        assert "not found" in out

    def test_blocked_path_refused(self) -> None:
        assert _chat_blocked(".env")
        assert _chat_blocked("secrets/.git/config")
        out = _run_chat_tool("read", {"path": ".env"})
        assert "blocked" in out

    def test_py_runs_code(self) -> None:
        out = _run_chat_tool("py", {"code": "print(2+2)"})
        assert "4" in out

    def test_unknown_tool(self) -> None:
        out = _run_chat_tool("explode", {"path": "x"})
        assert "unknown tool" in out

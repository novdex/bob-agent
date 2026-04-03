"""
Integration test: message -> dispatch -> agent loop -> tool -> response.

Tests the complete gateway -> agent -> tool -> response pipeline using
a mock LLM that returns predictable tool calls and text responses.
No real LLM API calls are made.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock LLM that returns a search_web tool call on first call, then text
# ---------------------------------------------------------------------------

_MOCK_TOOL_CALL_RESPONSE = {
    "ok": True,
    "content": "",
    "reasoning_content": "I should search for this.",
    "tool_calls": [
        {
            "id": "call_mock_test_001",
            "type": "function",
            "function": {
                "name": "search_web",
                "arguments": json.dumps({"query": "test query"}),
            },
        }
    ],
    "usage": {"total_tokens": 500, "prompt_tokens": 400, "completion_tokens": 100},
}

_MOCK_TEXT_RESPONSE = {
    "ok": True,
    "content": "Based on my search, here are the results for your query.",
    "reasoning_content": "",
    "tool_calls": None,
    "usage": {"total_tokens": 300, "prompt_tokens": 200, "completion_tokens": 100},
}

_MOCK_SEARCH_RESULT = {
    "ok": True,
    "results": [
        {"title": "Test Result", "snippet": "A test snippet", "url": "https://example.com"}
    ],
}

_call_count = 0


def _mock_call_llm(messages: list, tools: Optional[list] = None, **kwargs) -> dict:
    """Mock LLM: first call returns tool_call, second returns text."""
    global _call_count
    _call_count += 1
    if _call_count == 1:
        return _MOCK_TOOL_CALL_RESPONSE.copy()
    return _MOCK_TEXT_RESPONSE.copy()


def _mock_search_web(tool_name_or_args, args=None) -> dict:
    """Mock search_web tool that returns canned results."""
    return _MOCK_SEARCH_RESULT.copy()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_call_count():
    """Reset the mock call counter before each test."""
    global _call_count
    _call_count = 0
    yield
    _call_count = 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipelineWithMockLLM:
    """Test the complete gateway -> agent -> tool -> response pipeline."""

    @patch("mind_clone.agent.loop.call_llm", side_effect=_mock_call_llm)
    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", new_callable=dict)
    @patch("mind_clone.agent.loop.save_user_message")
    @patch("mind_clone.agent.loop.save_assistant_message")
    @patch("mind_clone.agent.loop.save_tool_result")
    @patch("mind_clone.agent.loop.prepare_messages_for_llm")
    @patch("mind_clone.agent.loop.load_identity")
    @patch("mind_clone.agent.loop.effective_tool_definitions")
    @patch("mind_clone.agent.loop.check_tool_allowed", return_value=(True, None))
    @patch("mind_clone.agent.loop.requires_approval", return_value=False)
    @patch("mind_clone.agent.loop.guarded_tool_result_payload")
    def test_full_pipeline_with_mock_llm(
        self,
        mock_guarded,
        mock_requires_approval,
        mock_check_tool,
        mock_tool_defs,
        mock_load_identity,
        mock_prepare_msgs,
        mock_save_tool,
        mock_save_assistant,
        mock_save_user,
        mock_dispatch,
        mock_llm,
    ):
        """Test the complete gateway -> agent -> tool -> response pipeline.

        Flow:
        1. Create a test message
        2. Pass through dispatch
        3. Agent loop processes it (mock LLM returns "search_web" tool call)
        4. Tool executes (mock returns canned results)
        5. Agent loop gets tool result
        6. Final response returned

        Verify: response is not empty, tool was called, no exceptions.
        """
        from mind_clone.agent.loop import run_agent_turn

        # Setup mocks
        mock_db = MagicMock()
        mock_prepare_msgs.return_value = [
            {"role": "system", "content": "You are Bob."},
            {"role": "user", "content": "Search for test query"},
        ]
        mock_load_identity.return_value = {"name": "Bob", "persona": "helpful"}
        mock_tool_defs.return_value = [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                    },
                },
            }
        ]

        # Mock execute_tool to use our mock search
        with patch("mind_clone.agent.loop.execute_tool", side_effect=_mock_search_web):
            # Mock guarded_tool_result_payload to pass through
            mock_guarded.side_effect = lambda _name, _cid, result: (json.dumps(result), False)

            # Run the agent turn
            response = run_agent_turn(mock_db, owner_id=1, user_message="Search for test query")

        # Verify
        assert response is not None, "Response should not be None"
        assert len(response) > 0, "Response should not be empty"
        assert "results" in response.lower() or "search" in response.lower() or "query" in response.lower(), \
            f"Response should reference results: {response}"

        # Verify LLM was called (at least twice: tool call + text response)
        assert mock_llm.call_count >= 2, f"LLM should be called at least twice, got {mock_llm.call_count}"

        # Verify user message was saved
        mock_save_user.assert_called_once()

        # Verify assistant message was saved
        mock_save_assistant.assert_called()

    def test_execute_tool_dispatch(self):
        """Test that execute_tool correctly dispatches to registered handlers."""
        from mind_clone.tools.registry import execute_tool, TOOL_DISPATCH

        # Register a test tool
        def mock_tool(args: dict) -> dict:
            return {"ok": True, "echo": args.get("input", "")}

        TOOL_DISPATCH["_test_echo"] = mock_tool
        try:
            result = execute_tool("_test_echo", {"input": "hello"})
            assert result["ok"] is True
            assert result["echo"] == "hello"
        finally:
            TOOL_DISPATCH.pop("_test_echo", None)

    def test_execute_tool_unknown(self):
        """Test that execute_tool returns error for unknown tools."""
        from mind_clone.tools.registry import execute_tool

        result = execute_tool("_nonexistent_tool_xyz", {})
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]

    def test_execute_tool_input_validation(self):
        """Test that execute_tool validates input types."""
        from mind_clone.tools.registry import execute_tool

        # Empty tool name
        result = execute_tool("", {})
        assert result["ok"] is False

        # Non-dict args
        result = execute_tool("some_tool", "not a dict")  # type: ignore
        assert result["ok"] is False

    def test_has_tool(self):
        """Test that has_tool correctly identifies registered tools."""
        from mind_clone.tools.registry import has_tool

        # Built-in tools should exist
        assert has_tool("search_web") is True
        assert has_tool("read_file") is True

        # Non-existent tool
        assert has_tool("_definitely_not_a_real_tool") is False

    def test_get_tool_names_returns_list(self):
        """Test that get_tool_names returns a sorted list."""
        from mind_clone.tools.registry import get_tool_names

        names = get_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert names == sorted(names), "Tool names should be sorted"

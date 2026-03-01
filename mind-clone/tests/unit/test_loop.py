"""
Tests for agent reasoning loop (maps to GAIA benchmark).

Covers: system prompt building, message complexity classification,
        context top_k limits, tool_call sanitization, gap detection.
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.agent.loop import (
    _sanitize_tool_pairs,
    _classify_message_complexity,
    _context_top_k,
    build_system_prompt,
    MAX_TOOL_LOOPS,
)


# ---------------------------------------------------------------------------
# _sanitize_tool_pairs (critical for Kimi K2.5 API compatibility)
# ---------------------------------------------------------------------------

class TestSanitizeToolPairs:
    """Tests for the tool_call ↔ tool response pairing invariant.

    Kimi K2.5 requires:
    1. Every tool_call_id in assistant messages must have a matching tool response
    2. Assistant messages with tool_calls must have reasoning_content field
    3. Assistant messages must not have empty content
    """

    def test_empty_messages(self):
        assert _sanitize_tool_pairs([]) == []

    def test_no_tool_calls_passes_through(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = _sanitize_tool_pairs(messages)
        assert len(result) == 3

    def test_matched_pair_preserved(self):
        messages = [
            {"role": "assistant", "content": "let me search",
             "tool_calls": [{"id": "tc_1", "function": {"name": "search_web", "arguments": "{}"}}]},
            {"role": "tool", "content": "results here", "tool_call_id": "tc_1"},
        ]
        result = _sanitize_tool_pairs(messages)
        assert any(m.get("tool_calls") for m in result if m["role"] == "assistant")
        assert any(m.get("tool_call_id") == "tc_1" for m in result)

    def test_orphaned_tool_call_stripped(self):
        """Assistant has tool_calls but no matching tool response → strip tool_calls."""
        messages = [
            {"role": "assistant", "content": "searching",
             "tool_calls": [{"id": "tc_orphan", "function": {"name": "search_web", "arguments": "{}"}}]},
        ]
        result = _sanitize_tool_pairs(messages)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "tool_calls" not in result[0]  # Stripped

    def test_orphaned_tool_response_dropped(self):
        """Tool response without matching assistant tool_call → dropped."""
        messages = [
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "content": "orphan result", "tool_call_id": "tc_missing"},
        ]
        result = _sanitize_tool_pairs(messages)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"

    def test_reasoning_content_injected(self):
        """Kimi K2.5 requires reasoning_content on assistant messages with tool_calls."""
        messages = [
            {"role": "assistant", "content": "using tool",
             "tool_calls": [{"id": "tc_1", "function": {"name": "search_web", "arguments": "{}"}}]},
            {"role": "tool", "content": "data", "tool_call_id": "tc_1"},
        ]
        result = _sanitize_tool_pairs(messages)
        assistant = [m for m in result if m["role"] == "assistant" and m.get("tool_calls")][0]
        assert "reasoning_content" in assistant

    def test_empty_content_placeholder_tool_calls(self):
        """Assistant with tool_calls but empty content → gets '(tool calls)' placeholder."""
        messages = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "tc_1", "function": {"name": "search_web", "arguments": "{}"}}]},
            {"role": "tool", "content": "data", "tool_call_id": "tc_1"},
        ]
        result = _sanitize_tool_pairs(messages)
        assistant = [m for m in result if m["role"] == "assistant" and m.get("tool_calls")][0]
        assert assistant["content"] == "(tool calls)"

    def test_empty_content_placeholder_no_tool_calls(self):
        """Plain assistant message with empty content → gets '(empty)' placeholder."""
        messages = [
            {"role": "assistant", "content": ""},
        ]
        result = _sanitize_tool_pairs(messages)
        assert result[0]["content"] == "(empty)"

    def test_multiple_tool_calls_all_matched(self):
        messages = [
            {"role": "assistant", "content": "multi",
             "tool_calls": [
                 {"id": "tc_a", "function": {"name": "search_web", "arguments": "{}"}},
                 {"id": "tc_b", "function": {"name": "read_file", "arguments": "{}"}},
             ]},
            {"role": "tool", "content": "result_a", "tool_call_id": "tc_a"},
            {"role": "tool", "content": "result_b", "tool_call_id": "tc_b"},
        ]
        result = _sanitize_tool_pairs(messages)
        assert len(result) == 3

    def test_partial_match_strips_all(self):
        """If ANY tool_call_id is missing its response, strip ALL tool_calls."""
        messages = [
            {"role": "assistant", "content": "multi",
             "tool_calls": [
                 {"id": "tc_a", "function": {"name": "search_web", "arguments": "{}"}},
                 {"id": "tc_b", "function": {"name": "read_file", "arguments": "{}"}},
             ]},
            {"role": "tool", "content": "result_a", "tool_call_id": "tc_a"},
            # tc_b response missing!
        ]
        result = _sanitize_tool_pairs(messages)
        # Assistant should be stripped of tool_calls, and orphan tool response for tc_a dropped
        assistant = [m for m in result if m["role"] == "assistant"][0]
        assert "tool_calls" not in assistant


# ---------------------------------------------------------------------------
# _classify_message_complexity
# ---------------------------------------------------------------------------

class TestMessageComplexity:
    """Maps to t2-bench — Bob needs to adapt behavior based on message type."""

    def test_simple_greeting(self):
        assert _classify_message_complexity("hello") == "simple"

    def test_simple_short_message(self):
        assert _classify_message_complexity("yes ok") == "simple"

    def test_simple_status(self):
        assert _classify_message_complexity("status") == "simple"

    def test_complex_research_request(self):
        assert _classify_message_complexity(
            "research and compare the top 5 AI frameworks for autonomous agents"
        ) == "complex"

    def test_complex_keyword_match(self):
        # "analyze" is a complex keyword, but needs >3 words to not be classified as simple
        assert _classify_message_complexity("please analyze this data carefully") == "complex"

    def test_normal_medium_message(self):
        assert _classify_message_complexity(
            "what is the weather today"
        ) == "normal"

    def test_empty_message(self):
        assert _classify_message_complexity("") == "simple"

    def test_none_message(self):
        assert _classify_message_complexity(None) == "simple"


# ---------------------------------------------------------------------------
# _context_top_k
# ---------------------------------------------------------------------------

class TestContextTopK:
    """Verifies context injection respects complexity-based limits."""

    def test_simple_limits(self):
        result = _context_top_k("simple")
        assert result["lessons"] == 1
        assert result["artifacts"] == 0
        assert result["episodes"] == 0

    def test_complex_limits(self):
        result = _context_top_k("complex")
        assert result["lessons"] == 5
        assert result["artifacts"] == 4
        assert result["episodes"] == 3

    def test_normal_limits(self):
        result = _context_top_k("normal")
        assert result["lessons"] == 3
        assert result["artifacts"] == 2


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:

    def test_basic_prompt_without_identity(self):
        prompt = build_system_prompt()
        assert "Mind Clone" in prompt
        assert "Bob" in prompt
        assert "tools" in prompt.lower()

    def test_prompt_with_identity(self):
        identity = {
            "agent_uuid": "test-uuid-123",
            "origin_statement": "I am Bob",
            "core_values": ["curiosity", "helpfulness"],
        }
        prompt = build_system_prompt(identity=identity)
        assert "test-uuid-123" in prompt
        assert "I am Bob" in prompt
        assert "curiosity" in prompt

    def test_prompt_includes_model_info(self):
        prompt = build_system_prompt()
        assert "Model:" in prompt

    def test_prompt_includes_create_tool_directive(self):
        prompt = build_system_prompt()
        assert "create_tool" in prompt


# ---------------------------------------------------------------------------
# MAX_TOOL_LOOPS constant
# ---------------------------------------------------------------------------

class TestConstants:

    def test_max_tool_loops_value(self):
        """MAX_TOOL_LOOPS=50 was raised to support complex multi-tool chains."""
        assert MAX_TOOL_LOOPS == 50

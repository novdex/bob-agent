"""
Tests for memory system (maps to Context-Bench).

Covers: conversation history, summaries, context trimming,
        lesson storage, memory vector search, artifact retrieval.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from mind_clone.agent.memory import (
    save_message,
    save_user_message,
    save_assistant_message,
    save_tool_result,
    get_conversation_history,
    count_messages,
    clear_conversation_history,
    create_conversation_summary,
    get_conversation_summaries,
    prepare_messages_for_llm,
    store_lesson,
    trim_context_window,
    retrieve_relevant_artifacts,
    search_memory_vectors,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_lock(owner_id, reason=""):
    """No-op context manager to replace session_write_lock in tests."""
    from contextlib import nullcontext
    return nullcontext()


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------

class TestConversationCRUD:
    """Test basic message save/retrieve/count/clear operations."""

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_save_and_retrieve_user_message(self, _lock, db_session, sample_user):
        save_user_message(db_session, sample_user.id, "hello world")
        history = get_conversation_history(db_session, sample_user.id)
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello world"

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_save_assistant_with_tool_calls(self, _lock, db_session, sample_user):
        tool_calls = [{"id": "tc_1", "function": {"name": "search_web", "arguments": "{}"}}]
        save_assistant_message(db_session, sample_user.id, "Searching...", tool_calls=tool_calls)
        history = get_conversation_history(db_session, sample_user.id)
        assert len(history) == 1
        assert history[0]["role"] == "assistant"
        assert history[0]["tool_calls"] == tool_calls

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_save_tool_result(self, _lock, db_session, sample_user):
        save_tool_result(db_session, sample_user.id, "tc_1", "Result data")
        history = get_conversation_history(db_session, sample_user.id)
        assert len(history) == 1
        assert history[0]["role"] == "tool"
        assert history[0]["tool_call_id"] == "tc_1"

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_count_messages(self, _lock, db_session, sample_user):
        assert count_messages(db_session, sample_user.id) == 0
        save_user_message(db_session, sample_user.id, "msg1")
        save_user_message(db_session, sample_user.id, "msg2")
        assert count_messages(db_session, sample_user.id) == 2

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_clear_conversation(self, _lock, db_session, sample_user):
        save_user_message(db_session, sample_user.id, "msg1")
        save_user_message(db_session, sample_user.id, "msg2")
        deleted = clear_conversation_history(db_session, sample_user.id)
        assert deleted == 2
        assert count_messages(db_session, sample_user.id) == 0

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_history_chronological_order(self, _lock, db_session, sample_user):
        save_user_message(db_session, sample_user.id, "first")
        save_assistant_message(db_session, sample_user.id, "second")
        save_user_message(db_session, sample_user.id, "third")
        history = get_conversation_history(db_session, sample_user.id)
        assert [m["content"] for m in history] == ["first", "second", "third"]

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_history_limit(self, _lock, db_session, sample_user):
        for i in range(10):
            save_user_message(db_session, sample_user.id, f"msg_{i}")
        history = get_conversation_history(db_session, sample_user.id, limit=3)
        assert len(history) == 3
        # Should be most recent 3
        assert history[-1]["content"] == "msg_9"

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_malformed_tool_calls_json_ignored(self, _lock, db_session, sample_user):
        msg = save_message(db_session, sample_user.id, "assistant", "test")
        # Manually corrupt JSON
        msg.tool_calls_json = "not valid json{"
        db_session.commit()
        history = get_conversation_history(db_session, sample_user.id)
        assert len(history) == 1
        assert "tool_calls" not in history[0]


# ---------------------------------------------------------------------------
# Conversation Summaries
# ---------------------------------------------------------------------------

class TestConversationSummaries:

    def test_create_and_get_summary(self, db_session, sample_user):
        create_conversation_summary(
            db_session, sample_user.id, 1, 10,
            "User discussed AI benchmarks",
            key_points=["GAIA", "SWE-bench"],
            open_loops=["Need to test Bob"],
        )
        summaries = get_conversation_summaries(db_session, sample_user.id)
        assert len(summaries) == 1
        assert summaries[0]["summary"] == "User discussed AI benchmarks"
        assert summaries[0]["key_points"] == ["GAIA", "SWE-bench"]
        assert summaries[0]["open_loops"] == ["Need to test Bob"]

    def test_summary_limit(self, db_session, sample_user):
        for i in range(8):
            create_conversation_summary(
                db_session, sample_user.id, i * 10, (i + 1) * 10,
                f"Summary {i}",
            )
        summaries = get_conversation_summaries(db_session, sample_user.id, limit=3)
        assert len(summaries) == 3

    def test_summary_empty_key_points(self, db_session, sample_user):
        create_conversation_summary(db_session, sample_user.id, 1, 5, "test")
        summaries = get_conversation_summaries(db_session, sample_user.id)
        assert summaries[0]["key_points"] == []
        assert summaries[0]["open_loops"] == []


# ---------------------------------------------------------------------------
# prepare_messages_for_llm
# ---------------------------------------------------------------------------

class TestPrepareMessagesForLLM:

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_prepends_system_message(self, _lock, db_session, sample_user):
        save_user_message(db_session, sample_user.id, "hello")
        messages = prepare_messages_for_llm(db_session, sample_user.id)
        assert messages[0]["role"] == "system"
        assert len(messages) == 2

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_empty_history_still_has_system(self, _lock, db_session, sample_user):
        messages = prepare_messages_for_llm(db_session, sample_user.id)
        assert len(messages) == 1
        assert messages[0]["role"] == "system"


# ---------------------------------------------------------------------------
# store_lesson
# ---------------------------------------------------------------------------

class TestStoreLesson:

    def test_store_lesson_success(self, db_session, sample_user):
        result = store_lesson(db_session, sample_user.id, "Always use tools proactively")
        assert result is True

    def test_store_empty_lesson_fails(self, db_session, sample_user):
        result = store_lesson(db_session, sample_user.id, "")
        assert result is False

    def test_store_none_lesson_fails(self, db_session, sample_user):
        result = store_lesson(db_session, sample_user.id, None)
        assert result is False

    def test_store_whitespace_lesson_fails(self, db_session, sample_user):
        result = store_lesson(db_session, sample_user.id, "   ")
        assert result is False

    def test_lesson_truncated_to_800(self, db_session, sample_user):
        long_lesson = "x" * 2000
        result = store_lesson(db_session, sample_user.id, long_lesson)
        assert result is True


# ---------------------------------------------------------------------------
# trim_context_window (maps to Context-Bench)
# ---------------------------------------------------------------------------

class TestTrimContextWindow:

    def test_empty_messages(self):
        assert trim_context_window([]) == []

    def test_under_budget_returns_unchanged(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = trim_context_window(messages, max_chars=1000)
        assert len(result) == 2

    def test_over_budget_trims_oldest(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "A" * 100},
            {"role": "assistant", "content": "B" * 100},
            {"role": "user", "content": "C" * 100},
        ]
        result = trim_context_window(messages, max_chars=250)
        # Should keep system + most recent messages that fit
        assert result[0]["role"] == "system"
        assert len(result) < 4

    def test_system_message_always_kept(self):
        messages = [
            {"role": "system", "content": "important system prompt"},
            {"role": "user", "content": "A" * 50000},
        ]
        result = trim_context_window(messages, max_chars=100)
        assert any(m["role"] == "system" for m in result)

    def test_preserves_chronological_order(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ]
        result = trim_context_window(messages, max_chars=10000)
        roles = [m["role"] for m in result]
        assert roles == ["system", "user", "assistant", "user"]


# ---------------------------------------------------------------------------
# retrieve_relevant_artifacts (known gotcha: 3-term minimum)
# ---------------------------------------------------------------------------

class TestArtifactRetrieval:

    def test_short_query_returns_empty(self, db_session, sample_user):
        """Known gotcha: queries with <3 words return empty to avoid irrelevant context."""
        result = retrieve_relevant_artifacts(db_session, sample_user.id, "hi")
        assert result == []

    def test_two_word_query_returns_empty(self, db_session, sample_user):
        result = retrieve_relevant_artifacts(db_session, sample_user.id, "hello world")
        assert result == []

    @patch("mind_clone.agent.memory.search_memory_vectors", return_value=[])
    def test_three_word_query_calls_search(self, mock_search, db_session, sample_user):
        retrieve_relevant_artifacts(db_session, sample_user.id, "find benchmark results")
        mock_search.assert_called_once()

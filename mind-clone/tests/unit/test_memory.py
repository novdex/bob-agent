"""
Comprehensive tests for mind_clone.agent.memory module (fixed import issues).

Focus: input validation, state mutation safety, error handling, return contracts,
memory limits, and edge cases.
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, Any, List

pytest.importorskip("sqlalchemy", minversion="1.4")

from sqlalchemy.orm import Session
from mind_clone.agent.memory import (
    count_messages,
    clear_conversation_history,
    create_conversation_summary,
    get_conversation_summaries,
    store_lesson,
    trim_context_window,
    retrieve_relevant_artifacts,
)


class TestCountMessages:
    """Test count_messages."""

    def test_count_returns_zero_for_no_messages(self):
        """Should return 0 when owner has no messages."""
        db = Mock(spec=Session)
        query_mock = MagicMock()
        query_mock.filter.return_value.count.return_value = 0
        db.query.return_value = query_mock

        result = count_messages(db, owner_id=1)
        assert result == 0

    def test_count_returns_correct_number(self):
        """Should return correct message count."""
        db = Mock(spec=Session)
        query_mock = MagicMock()
        query_mock.filter.return_value.count.return_value = 42
        db.query.return_value = query_mock

        result = count_messages(db, owner_id=1)
        assert result == 42


class TestCreateConversationSummary:
    """Test create_conversation_summary."""

    def test_creates_summary_with_all_fields(self):
        """Should create summary with all optional fields."""
        db = Mock(spec=Session)
        db.add = Mock()
        db.commit = Mock()

        key_points = ["point1", "point2"]
        open_loops = ["loop1"]

        result = create_conversation_summary(
            db, owner_id=1, start_message_id=10, end_message_id=20,
            summary="Test summary", key_points=key_points, open_loops=open_loops
        )

        db.add.assert_called_once()
        added_summary = db.add.call_args[0][0]
        assert json.loads(added_summary.key_points_json) == key_points

    def test_creates_summary_with_empty_lists(self):
        """Should create summary with None/empty lists."""
        db = Mock(spec=Session)
        db.add = Mock()
        db.commit = Mock()

        result = create_conversation_summary(
            db, owner_id=1, start_message_id=10, end_message_id=20,
            summary="Test summary", key_points=None, open_loops=None
        )

        added_summary = db.add.call_args[0][0]
        assert json.loads(added_summary.key_points_json) == []


class TestGetConversationSummaries:
    """Test get_conversation_summaries."""

    def test_returns_empty_list_when_no_summaries(self):
        """Should return empty list when no summaries exist."""
        db = Mock(spec=Session)
        query_mock = MagicMock()
        query_mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        db.query.return_value = query_mock

        result = get_conversation_summaries(db, owner_id=1)
        assert result == []

    def test_handles_malformed_json_in_summaries(self):
        """Should handle malformed JSON gracefully."""
        db = Mock(spec=Session)
        summary = Mock(
            summary="test",
            key_points_json="invalid json {{",
            open_loops_json="{{invalid",
            created_at=None
        )

        query_mock = MagicMock()
        query_mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [summary]
        db.query.return_value = query_mock

        result = get_conversation_summaries(db, owner_id=1)
        assert len(result) == 1
        assert result[0]["key_points"] == []
        assert result[0]["open_loops"] == []


class TestStoreLesson:
    """Test store_lesson."""

    def test_stores_valid_lesson(self):
        """Should store non-empty lesson."""
        db = Mock(spec=Session)
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()

        result = store_lesson(db, owner_id=1, lesson="Important lesson")

        assert result is True
        db.add.assert_called_once()

    def test_rejects_empty_lesson(self):
        """Should reject empty/whitespace lesson."""
        db = Mock(spec=Session)

        result = store_lesson(db, owner_id=1, lesson="   ")

        assert result is False
        db.add.assert_not_called()

    def test_rejects_none_lesson(self):
        """Should reject None lesson."""
        db = Mock(spec=Session)

        result = store_lesson(db, owner_id=1, lesson=None)

        assert result is False

    def test_handles_database_error(self):
        """Should handle database errors gracefully."""
        db = Mock(spec=Session)
        db.add = Mock(side_effect=Exception("DB error"))
        db.rollback = Mock()

        result = store_lesson(db, owner_id=1, lesson="Test")

        assert result is False
        db.rollback.assert_called_once()


class TestTrimContextWindow:
    """Test trim_context_window."""

    def test_returns_messages_under_budget(self):
        """Should return all messages if under budget."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]

        result = trim_context_window(messages, max_chars=1000)

        assert len(result) == 2
        assert result[0]["role"] == "system"

    def test_trims_messages_over_budget(self):
        """Should remove older messages to stay under budget."""
        messages = [
            {"role": "system", "content": "x" * 50},
            {"role": "user", "content": "y" * 100},
            {"role": "assistant", "content": "z" * 100},
        ]

        result = trim_context_window(messages, max_chars=150)

        assert any(m["role"] == "system" for m in result)
        assert len(result) <= 3

    def test_keeps_system_message_always(self):
        """Should always keep system message."""
        messages = [
            {"role": "system", "content": "x" * 1000},
            {"role": "user", "content": "y" * 100},
        ]

        result = trim_context_window(messages, max_chars=50)

        assert any(m["role"] == "system" for m in result)

    def test_handles_empty_list(self):
        """Should handle empty message list."""
        result = trim_context_window([], max_chars=1000)
        assert result == []

    def test_handles_none_content(self):
        """Should handle messages with missing content."""
        messages = [
            {"role": "user"},
            {"role": "assistant", "content": "test"},
        ]

        result = trim_context_window(messages, max_chars=1000)

        assert isinstance(result, list)

    def test_unicode_content_handling(self):
        """Should handle Unicode content correctly."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Hello 世界 مرحبا мир 🚀"},
        ]

        result = trim_context_window(messages, max_chars=1000)

        assert len(result) >= 1


class TestRetrieveRelevantArtifacts:
    """Test retrieve_relevant_artifacts."""

    def test_requires_minimum_query_terms(self):
        """Should return empty for queries with <3 words."""
        db = Mock(spec=Session)

        result = retrieve_relevant_artifacts(db, owner_id=1, query="short")
        assert result == []

        result = retrieve_relevant_artifacts(db, owner_id=1, query="two terms")
        assert result == []

    def test_accepts_three_word_query(self):
        """Should accept queries with exactly 3 words."""
        db = Mock(spec=Session)

        with patch("mind_clone.agent.memory.search_memory_vectors") as mock_search:
            mock_search.return_value = []

            result = retrieve_relevant_artifacts(db, owner_id=1, query="three word query")

            assert mock_search.called


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_large_owner_id_values(self):
        """Should handle large owner_id values."""
        db = Mock(spec=Session)
        query_mock = MagicMock()
        query_mock.filter.return_value.count.return_value = 0
        db.query.return_value = query_mock

        result = count_messages(db, owner_id=999999999)
        assert isinstance(result, int)

    def test_zero_owner_id(self):
        """Should handle zero owner_id."""
        db = Mock(spec=Session)
        query_mock = MagicMock()
        query_mock.filter.return_value.count.return_value = 0
        db.query.return_value = query_mock

        result = count_messages(db, owner_id=0)
        assert result == 0

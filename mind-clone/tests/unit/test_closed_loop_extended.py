"""
Tests for Closed Loop Feedback Engine — Loops 3 and 5 (maps to Vending-Bench).

Phase 1 covered Loops 1+6, 2, 4. This extends coverage to:
  Loop 3: cl_close_improvement_notes — marks notes applied/dismissed
  Loop 5: cl_check_dead_letter_pattern — blocks repeated failure strategies
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from mind_clone.core.closed_loop import (
    cl_close_improvement_notes,
    cl_check_dead_letter_pattern,
    CLOSED_LOOP_ENABLED,
)
from mind_clone.core.state import RUNTIME_STATE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_note_row(note_id=1, owner_id=1, status="open", summary="test note",
                   actions=None, retrieval_count=0, title="Test Note"):
    """Create a mock SelfImprovementNote row."""
    row = MagicMock()
    row.id = note_id
    row.owner_id = owner_id
    row.status = status
    row.summary = summary
    row.title = title
    row.actions_json = json.dumps(actions or ["use alternative approach", "break into smaller steps"])
    row.retrieval_count = retrieval_count
    return row


def _make_task(title="Deploy service"):
    """Create a mock task object."""
    task = MagicMock()
    task.title = title
    return task


# ---------------------------------------------------------------------------
# Loop 3: cl_close_improvement_notes
# ---------------------------------------------------------------------------

class TestCloseImprovementNotes:
    """Maps to Vending-Bench — tests that Bob learns from self-improvement notes."""

    def setup_method(self):
        RUNTIME_STATE.pop("cl_notes_applied", None)
        RUNTIME_STATE.pop("cl_notes_dismissed", None)

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False)
    def test_disabled_noop(self):
        cl_close_improvement_notes(["note"], "response", owner_id=1)
        assert RUNTIME_STATE.get("cl_notes_applied") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_empty_notes_noop(self):
        cl_close_improvement_notes([], "response text", owner_id=1)
        assert RUNTIME_STATE.get("cl_notes_applied") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_empty_response_noop(self):
        cl_close_improvement_notes(["note text"], "", owner_id=1)
        assert RUNTIME_STATE.get("cl_notes_applied") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_note_applied_when_action_matched(self, mock_session_local):
        """When response contains action text from the note, mark it 'applied'."""
        note_row = _make_note_row(
            summary="Always use alternative approach when stuck",
            actions=["use alternative approach", "break into smaller steps"],
            retrieval_count=0,
        )
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = note_row

        cl_close_improvement_notes(
            ["Always use alternative approach when stuck"],
            "I will use alternative approach to solve this differently.",
            owner_id=1,
        )

        assert note_row.status == "applied"
        assert int(RUNTIME_STATE.get("cl_notes_applied", 0)) >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_note_dismissed_after_max_retrievals(self, mock_session_local):
        """After 5 retrievals without match, note gets dismissed."""
        note_row = _make_note_row(
            summary="Always use search for latest data",
            actions=["search for latest data"],
            retrieval_count=4,  # Will become 5 after this call
        )
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = note_row

        cl_close_improvement_notes(
            ["Always use search for latest data"],
            "Here is a simple greeting response with no match.",
            owner_id=1,
        )

        assert note_row.status == "dismissed"
        assert int(RUNTIME_STATE.get("cl_notes_dismissed", 0)) >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_no_matching_row_skipped(self, mock_session_local):
        """If no DB row matches the note text, nothing happens."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        cl_close_improvement_notes(
            ["some note text that doesn't exist"],
            "response text",
            owner_id=1,
        )

        assert RUNTIME_STATE.get("cl_notes_applied") is None
        assert RUNTIME_STATE.get("cl_notes_dismissed") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_retrieval_count_incremented(self, mock_session_local):
        """Retrieval count should always increment on match attempt."""
        note_row = _make_note_row(retrieval_count=2)
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = note_row

        cl_close_improvement_notes(
            ["test note text goes here for matching"],
            "unrelated response",
            owner_id=1,
        )

        assert note_row.retrieval_count == 3

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_db_exception_handled_gracefully(self, mock_session_local):
        """DB errors should be caught, not crash the system."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.side_effect = Exception("DB connection lost")

        # Should not raise
        cl_close_improvement_notes(
            ["note text"],
            "response text",
            owner_id=1,
        )


# ---------------------------------------------------------------------------
# Loop 5: cl_check_dead_letter_pattern
# ---------------------------------------------------------------------------

class TestDeadLetterPattern:
    """Maps to Vending-Bench — tests that Bob blocks failing strategies."""

    def setup_method(self):
        RUNTIME_STATE.pop("cl_strategies_blocked", None)

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False)
    def test_disabled_noop(self):
        mock_db = MagicMock()
        cl_check_dead_letter_pattern(mock_db, 1, "reason", _make_task())
        assert RUNTIME_STATE.get("cl_strategies_blocked") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_empty_reason_noop(self):
        mock_db = MagicMock()
        cl_check_dead_letter_pattern(mock_db, 1, "", _make_task())
        assert RUNTIME_STATE.get("cl_strategies_blocked") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_embedding", return_value=None)
    def test_below_threshold_no_block(self, _):
        """2 failures in 7 days — below threshold (3), no block."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 2

        cl_check_dead_letter_pattern(mock_db, 1, "timeout error", _make_task())
        assert RUNTIME_STATE.get("cl_strategies_blocked") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_embedding")
    @patch("mind_clone.core.closed_loop.embedding_to_bytes", return_value=b"\x00")
    def test_at_threshold_creates_block(self, mock_embed_bytes, mock_get_emb):
        """3+ failures in 7 days — creates BLOCKED STRATEGY note."""
        import numpy as np
        mock_get_emb.return_value = np.ones(100, dtype=np.float32)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 3
        task = _make_task("Failing Deploy Task")

        cl_check_dead_letter_pattern(mock_db, 1, "timeout connecting to API", task)

        assert int(RUNTIME_STATE.get("cl_strategies_blocked", 0)) >= 1
        # Should add SelfImprovementNote + MemoryVector
        assert mock_db.add.call_count >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_embedding")
    @patch("mind_clone.core.closed_loop.embedding_to_bytes", return_value=b"\x00")
    def test_blocked_note_content(self, _, mock_get_emb):
        """Verify the blocked note contains the right information."""
        import numpy as np
        mock_get_emb.return_value = np.ones(100, dtype=np.float32)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 5
        task = _make_task("Broken Pipeline")

        cl_check_dead_letter_pattern(mock_db, 1, "connection refused", task)

        # Check the SelfImprovementNote was created correctly
        add_calls = mock_db.add.call_args_list
        note_call = add_calls[0][0][0]  # First positional arg of first add()
        assert "Blocked:" in note_call.title
        assert "BLOCKED STRATEGY" in note_call.summary
        assert note_call.priority == "critical"
        assert note_call.status == "open"

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_embedding")
    def test_zero_norm_embedding_skips_vector(self, mock_get_emb):
        """If embedding is zero vector, don't create MemoryVector row."""
        import numpy as np
        mock_get_emb.return_value = np.zeros(100, dtype=np.float32)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 3
        task = _make_task("Test Task")

        cl_check_dead_letter_pattern(mock_db, 1, "error reason", task)

        # Only 1 add (note), not 2 (note + vector)
        assert mock_db.add.call_count == 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_db_exception_handled(self):
        """DB errors should be caught, not crash."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB down")
        task = _make_task()

        # Should not raise
        cl_check_dead_letter_pattern(mock_db, 1, "some reason", task)

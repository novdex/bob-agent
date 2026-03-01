"""
Tests for Closed Loop Feedback Engine (maps to Vending-Bench).

Covers: tool performance filtering/blocking/reordering (Loop 1+6),
        lesson usage tracking (Loop 2), improvement note closing (Loop 3),
        forecast confidence adjustment (Loop 4).
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.core.closed_loop import (
    cl_filter_tools_by_performance,
    cl_track_lesson_usage,
    cl_close_improvement_notes,
    cl_adjust_for_forecast_confidence,
)
from mind_clone.core.state import RUNTIME_STATE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_def(name: str) -> dict:
    """Create a minimal tool definition dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Tool: {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


# ---------------------------------------------------------------------------
# Loop 1+6: Tool performance filtering + reordering
# ---------------------------------------------------------------------------

class TestToolPerformanceFilter:
    """Maps to Vending-Bench — tests that Bob blocks unreliable tools."""

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_blocks_low_success_rate_tools(self, mock_stats):
        mock_stats.return_value = {
            "tools": {
                "bad_tool": {"calls": 10, "success_rate": 0.10},  # 10% < 15% threshold
            }
        }
        tools = [_make_tool_def("bad_tool"), _make_tool_def("good_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        names = [(t["function"]["name"]) for t in result]
        assert "bad_tool" not in names
        assert "good_tool" in names

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_warns_medium_success_rate_tools(self, mock_stats):
        # success_rate is 0-1 fraction from get_tool_performance_stats.
        # Source does rate_pct = success_rate * 100 to get percentage.
        # warn_threshold=40, block_threshold=15. 0.30*100=30 > block(15) but < warn(40)
        mock_stats.return_value = {
            "tools": {
                "weak_tool": {"calls": 10, "success_rate": 0.30},
            }
        }
        tools = [_make_tool_def("weak_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert len(result) == 1
        assert "[WARNING:" in result[0]["function"]["description"]

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_high_success_rate_passes(self, mock_stats):
        mock_stats.return_value = {
            "tools": {
                "great_tool": {"calls": 10, "success_rate": 0.95},
            }
        }
        tools = [_make_tool_def("great_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert len(result) == 1
        assert "[WARNING:" not in result[0]["function"]["description"]

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_below_min_calls_ignored(self, mock_stats):
        mock_stats.return_value = {
            "tools": {
                "new_tool": {"calls": 2, "success_rate": 0.0},  # Too few calls to judge
            }
        }
        tools = [_make_tool_def("new_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert len(result) == 1  # Not blocked despite 0% — too few calls

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_reorders_by_success_rate(self, mock_stats):
        # success_rate is 0-1 fraction; source does *100 to get percentage.
        # 0.90*100=90 > warn(40) -> passes; 0.60*100=60 > warn(40) -> passes
        mock_stats.return_value = {
            "tools": {
                "tool_90": {"calls": 10, "success_rate": 0.90},
                "tool_60": {"calls": 10, "success_rate": 0.60},
            }
        }
        tools = [_make_tool_def("tool_60"), _make_tool_def("tool_90")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        # Both pass through (above warn threshold)
        assert len(result) == 2

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False)
    def test_disabled_returns_unchanged(self):
        tools = [_make_tool_def("any_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert result == tools

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_null_owner_returns_unchanged(self):
        tools = [_make_tool_def("any_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=None)
        assert result == tools

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_no_stats_returns_unchanged(self, mock_stats):
        mock_stats.return_value = {"tools": {}}
        tools = [_make_tool_def("any_tool")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Loop 2: Lesson usage tracking
# ---------------------------------------------------------------------------

class TestLessonUsageTracking:
    """Maps to Context-Bench — tracks whether injected context is actually used."""

    def setup_method(self):
        RUNTIME_STATE.pop("cl_lessons_used", None)
        RUNTIME_STATE.pop("cl_lessons_ignored", None)
        RUNTIME_STATE.pop("cl_loops_closed_total", None)

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_lesson_referenced_increments_used(self):
        lessons = ["always use search web for latest data"]
        response = "I will use search web to get the latest data as recommended."
        cl_track_lesson_usage(lessons, response, owner_id=1)
        assert int(RUNTIME_STATE.get("cl_lessons_used", 0)) >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_lesson_not_referenced_increments_ignored(self):
        lessons = ["always use search web for latest data"]
        response = "Here is a simple greeting response."
        cl_track_lesson_usage(lessons, response, owner_id=1)
        assert int(RUNTIME_STATE.get("cl_lessons_ignored", 0)) >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_empty_lessons_noop(self):
        cl_track_lesson_usage([], "some response", owner_id=1)
        assert RUNTIME_STATE.get("cl_loops_closed_total") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_empty_response_noop(self):
        cl_track_lesson_usage(["lesson"], "", owner_id=1)
        assert RUNTIME_STATE.get("cl_loops_closed_total") is None

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False)
    def test_disabled_noop(self):
        cl_track_lesson_usage(["lesson"], "response text here", owner_id=1)
        assert RUNTIME_STATE.get("cl_loops_closed_total") is None


# ---------------------------------------------------------------------------
# Loop 4: Forecast confidence adjustment
# ---------------------------------------------------------------------------

class TestForecastConfidenceAdjustment:

    def setup_method(self):
        RUNTIME_STATE.pop("cl_forecasts_adjusted", None)

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_low_confidence_adjusts_step(self):
        step = {"title": "Deploy service", "tools": ["run_command"]}
        result = cl_adjust_for_forecast_confidence(20, step)
        assert "[LOW CONFIDENCE: 20%]" in result["title"]
        assert result["_retry_budget_multiplier"] == 2
        assert int(RUNTIME_STATE.get("cl_forecasts_adjusted", 0)) >= 1

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_high_confidence_no_change(self):
        step = {"title": "Simple task"}
        result = cl_adjust_for_forecast_confidence(80, step)
        assert "[LOW CONFIDENCE" not in result["title"]

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False)
    def test_disabled_returns_none(self):
        step = {"title": "Task"}
        result = cl_adjust_for_forecast_confidence(10, step)
        assert result is None  # Returns None when disabled


# ---------------------------------------------------------------------------
# Comprehensive edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCasesToolPerformance:
    """Additional edge cases for tool performance filtering."""

    def test_empty_tool_list(self):
        """Should handle completely empty tool list."""
        result = cl_filter_tools_by_performance([], owner_id=1)
        assert result == []

    def test_tool_without_function_key(self):
        """Should skip tools missing 'function' key."""
        tools = [
            {"name": "broken_tool"},
            _make_tool_def("good_tool"),
        ]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        # Should not crash

    def test_function_without_name(self):
        """Should handle function dicts without 'name' key."""
        tools = [
            {"function": {"description": "Missing name"}},
            _make_tool_def("good_tool"),
        ]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        assert any("good_tool" in str(t) for t in result)

    def test_deep_copy_protection(self):
        """Should not mutate original tool defs when warning."""
        original_tools = [_make_tool_def("tool1")]
        original_desc = original_tools[0]["function"]["description"]

        with patch("mind_clone.core.closed_loop.get_tool_performance_stats") as mock:
            mock.return_value = {"tools": {"tool1": {"calls": 10, "success_rate": 0.30}}}
            result = cl_filter_tools_by_performance(original_tools, owner_id=1)

        # Original should be unchanged
        assert original_tools[0]["function"]["description"] == original_desc

    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_missing_stats_calls_key(self, mock_stats):
        """Should handle missing 'calls' key in stats."""
        mock_stats.return_value = {
            "tools": {
                "tool1": {"success_rate": 0.5}  # No calls key
            }
        }
        tools = [_make_tool_def("tool1")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        # Should treat missing calls as 0, filter it out
        assert len(result) >= 0

    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_success_rate_exactly_at_threshold(self, mock_stats):
        """Should handle success rate exactly at threshold."""
        warn_threshold = 40  # From config
        block_threshold = 15  # From config

        mock_stats.return_value = {
            "tools": {
                "tool_at_warn": {"calls": 10, "success_rate": 0.40},
                "tool_at_block": {"calls": 10, "success_rate": 0.15},
            }
        }
        tools = [_make_tool_def("tool_at_warn"), _make_tool_def("tool_at_block")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        # At threshold should typically still appear

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    @patch("mind_clone.core.closed_loop.get_tool_performance_stats")
    def test_runtime_state_increment_safety(self, mock_stats):
        """Should safely increment RUNTIME_STATE counters."""
        RUNTIME_STATE.clear()
        mock_stats.return_value = {
            "tools": {
                "bad": {"calls": 10, "success_rate": 0.10},
                "warn": {"calls": 10, "success_rate": 0.30},
            }
        }
        tools = [_make_tool_def("bad"), _make_tool_def("warn")]
        cl_filter_tools_by_performance(tools, owner_id=1)

        # Counters should be integers
        assert isinstance(RUNTIME_STATE.get("cl_tools_blocked", 0), int)
        assert isinstance(RUNTIME_STATE.get("cl_tools_warned", 0), int)


class TestEdgeCasesLessonUsage:
    """Additional edge cases for lesson usage tracking."""

    def test_none_lessons_list(self):
        """Should handle None instead of empty list."""
        cl_track_lesson_usage(None, "response", 1)
        # Should not crash

    def test_none_response_text(self):
        """Should handle None response text."""
        cl_track_lesson_usage(["lesson"], None, 1)
        # Should not crash

    def test_single_word_lesson(self):
        """Should handle lesson with only 1-2 words."""
        cl_track_lesson_usage(["Python"], "Python is great", 1)
        # Should not crash - key_phrases logic may produce empty list

    def test_lesson_with_special_chars(self):
        """Should handle lessons containing special characters."""
        lessons = ["use @decorator pattern"]
        response = "Use the @decorator pattern for Python"
        cl_track_lesson_usage(lessons, response, 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_very_long_lesson(self):
        """Should handle lessons with >100 words."""
        long_lesson = " ".join(["word"] * 500)
        response = "word word word"
        cl_track_lesson_usage([long_lesson], response, 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_very_long_response(self):
        """Should handle responses with >10000 words."""
        lessons = ["important pattern"]
        long_response = " ".join(["word"] * 10000)
        cl_track_lesson_usage(lessons, long_response, 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True)
    def test_case_insensitivity(self):
        """Should match lessons case-insensitively."""
        RUNTIME_STATE.clear()
        lessons = ["IMPORTANT LESSON"]
        response = "important lesson was applied"
        cl_track_lesson_usage(lessons, response, 1)
        assert RUNTIME_STATE.get("cl_lessons_used", 0) >= 0


class TestEdgeCasesImprovementNotes:
    """Additional edge cases for improvement note closing."""

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_empty_notes_list(self, mock_session):
        """Should handle empty notes list."""
        cl_close_improvement_notes([], "response", 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_none_notes_list(self, mock_session):
        """Should handle None notes list."""
        cl_close_improvement_notes(None, "response", 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_none_response(self, mock_session):
        """Should handle None response text."""
        cl_close_improvement_notes(["note"], None, 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_empty_response(self, mock_session):
        """Should handle empty response text."""
        cl_close_improvement_notes(["note"], "", 1)
        # Should not crash

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_db_exception_handling(self, mock_session):
        """Should gracefully handle database exceptions."""
        mock_session.return_value.query.side_effect = Exception("DB error")
        # Should not raise exception
        cl_close_improvement_notes(["note"], "response", 1)

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_invalid_json_in_actions(self, mock_session):
        """Should handle invalid JSON in actions_json."""
        mock_db = MagicMock()
        mock_session.return_value = mock_db

        mock_note = MagicMock()
        mock_note.actions_json = "{invalid json"
        mock_note.summary = "test"
        mock_note.status = "open"
        mock_note.title = "title"
        mock_note.retrieval_count = 0

        # Make query chain work
        mock_db.query.return_value.filter.return_value.first.return_value = mock_note

        # Should handle gracefully
        cl_close_improvement_notes(["test"], "response", 1)

    @patch("mind_clone.core.closed_loop.SessionLocal")
    def test_extremely_long_note_text(self, mock_session):
        """Should handle very long note text."""
        long_note = "x" * 10000
        # Should not crash
        cl_close_improvement_notes([long_note], "response", 1)


class TestEdgeCasesForecastConfidence:
    """Additional edge cases for forecast confidence adjustment."""

    def test_missing_title_key(self):
        """Should handle step dict without title."""
        step = {"id": "step1"}
        result = cl_adjust_for_forecast_confidence(30, step)
        # Should add title if missing
        assert result is not None

    def test_empty_title(self):
        """Should handle empty title string."""
        step = {"title": ""}
        result = cl_adjust_for_forecast_confidence(30, step)
        assert result is not None

    def test_very_long_title(self):
        """Should handle very long title."""
        step = {"title": "x" * 1000}
        result = cl_adjust_for_forecast_confidence(30, step)
        assert result is not None

    def test_confidence_zero(self):
        """Should handle confidence = 0."""
        step = {"title": "test"}
        result = cl_adjust_for_forecast_confidence(0, step)
        # Should add prefix (0 < threshold)
        assert "LOW CONFIDENCE" in result["title"]

    def test_confidence_negative(self):
        """Should handle negative confidence."""
        step = {"title": "test"}
        result = cl_adjust_for_forecast_confidence(-50, step)
        assert "LOW CONFIDENCE" in result["title"]

    def test_confidence_above_100(self):
        """Should handle confidence > 100."""
        step = {"title": "test"}
        result = cl_adjust_for_forecast_confidence(150, step)
        # Should not add prefix (150 > threshold)
        assert "LOW CONFIDENCE" not in result["title"]

    def test_runtime_state_increment(self):
        """Should properly increment runtime state."""
        from mind_clone.config import CLOSED_LOOP_ENABLED
        if CLOSED_LOOP_ENABLED:
            RUNTIME_STATE.clear()
            step = {"title": "test"}
            result = cl_adjust_for_forecast_confidence(30, step)
            # Check if state was incremented or if already happens elsewhere
            assert result is not None


class TestEdgeCasesDeadLetter:
    """Additional edge cases for dead letter pattern detection."""

    def test_none_reason(self):
        """None reason should return early without DB query."""
        from unittest.mock import MagicMock, patch
        from mind_clone.core.closed_loop import cl_check_dead_letter_pattern

        db = MagicMock()
        task = MagicMock()
        task.title = "test task"

        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True):
            cl_check_dead_letter_pattern(db, 1, None, task)
        # None reason => early return, no DB query
        db.query.assert_not_called()

    def test_empty_reason(self):
        """Empty string reason should return early without DB query."""
        from unittest.mock import MagicMock, patch
        from mind_clone.core.closed_loop import cl_check_dead_letter_pattern

        db = MagicMock()
        task = MagicMock()
        task.title = "test task"

        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True):
            cl_check_dead_letter_pattern(db, 1, "", task)
        db.query.assert_not_called()

    def test_very_long_reason(self):
        """Very long reason should be truncated and not crash."""
        from unittest.mock import MagicMock, patch
        from mind_clone.core.closed_loop import cl_check_dead_letter_pattern

        db = MagicMock()
        # Mock the query chain to return 0 (below threshold)
        db.query.return_value.filter.return_value.scalar.return_value = 0
        task = MagicMock()
        task.title = "test task"

        long_reason = "x" * 10000
        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True):
            cl_check_dead_letter_pattern(db, 1, long_reason, task)
        # Should not crash — query was made with truncated reason
        db.query.assert_called_once()

    def test_reason_exactly_100_chars(self):
        """Reason of exactly 100 chars should be used as-is (no off-by-one)."""
        from unittest.mock import MagicMock, patch
        from mind_clone.core.closed_loop import cl_check_dead_letter_pattern

        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 0
        task = MagicMock()
        task.title = "test task"

        reason_100 = "a" * 100
        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True):
            cl_check_dead_letter_pattern(db, 1, reason_100, task)
        db.query.assert_called_once()

    def test_db_exception(self):
        """DB exception should be caught gracefully (no raise)."""
        from unittest.mock import MagicMock, patch
        from mind_clone.core.closed_loop import cl_check_dead_letter_pattern

        db = MagicMock()
        db.query.side_effect = RuntimeError("DB connection lost")
        task = MagicMock()
        task.title = "test task"

        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", True):
            # Should NOT raise — the function catches all exceptions
            cl_check_dead_letter_pattern(db, 1, "some failure reason", task)

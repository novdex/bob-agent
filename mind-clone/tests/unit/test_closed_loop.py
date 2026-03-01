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
        mock_stats.return_value = {
            "tools": {
                "weak_tool": {"calls": 10, "success_rate": 0.30},  # 30% < 40% warn threshold
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
        mock_stats.return_value = {
            "tools": {
                "tool_90": {"calls": 10, "success_rate": 0.90},
                "tool_60": {"calls": 10, "success_rate": 0.60},
            }
        }
        tools = [_make_tool_def("tool_60"), _make_tool_def("tool_90")]
        result = cl_filter_tools_by_performance(tools, owner_id=1)
        names = [t["function"]["name"] for t in result]
        assert names.index("tool_90") < names.index("tool_60")

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
    def test_disabled_no_change(self):
        step = {"title": "Task"}
        result = cl_adjust_for_forecast_confidence(10, step)
        assert "[LOW CONFIDENCE" not in result["title"]

"""
Tests for budget governor (maps to Vending-Bench cost control).

Covers: RunBudget creation, budget_should_stop, budget_should_degrade,
        time-based limits, tool call limits, LLM call limits.
"""

import time
import pytest
from unittest.mock import patch

from mind_clone.core.budget import (
    RunBudget,
    create_run_budget,
    budget_should_stop,
    budget_should_degrade,
)


# ---------------------------------------------------------------------------
# RunBudget creation
# ---------------------------------------------------------------------------

class TestCreateRunBudget:

    def test_default_values(self):
        budget = create_run_budget()
        assert budget.max_seconds == 300
        assert budget.max_tool_calls == 40
        assert budget.max_llm_calls == 20
        assert budget.start_time > 0
        assert budget.tool_calls == 0
        assert budget.llm_calls == 0

    def test_custom_values(self):
        budget = create_run_budget(max_seconds=60, max_tool_calls=10, max_llm_calls=5)
        assert budget.max_seconds == 60
        assert budget.max_tool_calls == 10
        assert budget.max_llm_calls == 5

    def test_start_time_is_current(self):
        before = time.time()
        budget = create_run_budget()
        after = time.time()
        assert before <= budget.start_time <= after


# ---------------------------------------------------------------------------
# budget_should_stop
# ---------------------------------------------------------------------------

class TestBudgetShouldStop:

    def test_none_budget_returns_false(self):
        assert budget_should_stop(None) is False

    def test_fresh_budget_does_not_stop(self):
        budget = create_run_budget(max_seconds=300)
        assert budget_should_stop(budget) is False

    def test_tool_calls_exceeded(self):
        budget = create_run_budget(max_tool_calls=5)
        budget.tool_calls = 6
        assert budget_should_stop(budget) is True

    def test_llm_calls_exceeded(self):
        budget = create_run_budget(max_llm_calls=3)
        budget.llm_calls = 4
        assert budget_should_stop(budget) is True

    def test_time_exceeded(self):
        budget = create_run_budget(max_seconds=1)
        budget.start_time = time.time() - 10  # 10 seconds ago
        assert budget_should_stop(budget) is True

    def test_at_exact_limit_does_not_stop(self):
        budget = create_run_budget(max_tool_calls=5)
        budget.tool_calls = 5  # At limit, not over
        assert budget_should_stop(budget) is False


# ---------------------------------------------------------------------------
# budget_should_degrade
# ---------------------------------------------------------------------------

class TestBudgetShouldDegrade:

    def test_none_budget_returns_false(self):
        assert budget_should_degrade(None) is False

    def test_fresh_budget_does_not_degrade(self):
        budget = create_run_budget(max_seconds=300, max_tool_calls=40)
        assert budget_should_degrade(budget) is False

    def test_tool_calls_at_80_percent(self):
        budget = create_run_budget(max_tool_calls=10)
        budget.tool_calls = 9  # 90% > 80%
        assert budget_should_degrade(budget) is True

    def test_tool_calls_below_80_percent(self):
        budget = create_run_budget(max_tool_calls=10)
        budget.tool_calls = 7  # 70% < 80%
        assert budget_should_degrade(budget) is False

    def test_llm_calls_at_threshold(self):
        budget = create_run_budget(max_llm_calls=10)
        budget.llm_calls = 9  # 90% > 80%
        assert budget_should_degrade(budget) is True

    def test_custom_threshold(self):
        budget = create_run_budget(max_tool_calls=10)
        budget.tool_calls = 6  # 60%
        assert budget_should_degrade(budget, threshold=0.5) is True
        assert budget_should_degrade(budget, threshold=0.7) is False

    def test_time_at_threshold(self):
        budget = create_run_budget(max_seconds=10)
        budget.start_time = time.time() - 9  # 90% of 10s
        assert budget_should_degrade(budget) is True

    def test_zero_max_no_divide_by_zero(self):
        budget = RunBudget(
            max_seconds=0, max_tool_calls=0, max_llm_calls=0,
            start_time=time.time(),
        )
        # Should not raise ZeroDivisionError
        assert budget_should_degrade(budget) is False

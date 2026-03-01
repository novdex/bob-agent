"""
Budget governor functions.
"""
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger("mind_clone.budget")

@dataclass
class RunBudget:
    max_seconds: float
    max_tool_calls: int
    max_llm_calls: int
    start_time: float = 0
    tool_calls: int = 0
    llm_calls: int = 0

def create_run_budget(
    max_seconds: float = None,
    max_tool_calls: int = None,
    max_llm_calls: int = None,
):
    import time
    return RunBudget(
        max_seconds=max_seconds or 300,
        max_tool_calls=max_tool_calls or 40,
        max_llm_calls=max_llm_calls or 20,
        start_time=time.time(),
    )

def budget_should_stop(budget: RunBudget) -> bool:
    import time
    if not budget:
        return False
    elapsed = time.time() - budget.start_time
    return elapsed > budget.max_seconds or budget.tool_calls > budget.max_tool_calls or budget.llm_calls > budget.max_llm_calls

def budget_should_degrade(budget: RunBudget, threshold: float = 0.8) -> bool:
    import time
    if not budget:
        return False
    elapsed = time.time() - budget.start_time
    time_ratio = elapsed / budget.max_seconds if budget.max_seconds > 0 else 0
    tool_ratio = budget.tool_calls / budget.max_tool_calls if budget.max_tool_calls > 0 else 0
    llm_ratio = budget.llm_calls / budget.max_llm_calls if budget.max_llm_calls > 0 else 0
    return time_ratio > threshold or tool_ratio > threshold or llm_ratio > threshold


def budget_remaining(budget: RunBudget) -> dict:
    """Get remaining budget across all dimensions.

    Args:
        budget: The RunBudget to check

    Returns:
        Dict with keys: seconds_remaining, tool_calls_remaining, llm_calls_remaining
    """
    import time
    if not budget:
        return {
            "seconds_remaining": float("inf"),
            "tool_calls_remaining": float("inf"),
            "llm_calls_remaining": float("inf"),
        }
    elapsed = time.time() - budget.start_time
    return {
        "seconds_remaining": max(0, budget.max_seconds - elapsed),
        "tool_calls_remaining": max(0, budget.max_tool_calls - budget.tool_calls),
        "llm_calls_remaining": max(0, budget.max_llm_calls - budget.llm_calls),
    }


def budget_exhausted(budget: RunBudget) -> bool:
    """Check if any budget dimension is exhausted (at or over limit).

    Args:
        budget: The RunBudget to check

    Returns:
        True if any dimension is at or over its limit
    """
    import time
    if not budget:
        return False
    elapsed = time.time() - budget.start_time
    return (
        elapsed >= budget.max_seconds
        or budget.tool_calls >= budget.max_tool_calls
        or budget.llm_calls >= budget.max_llm_calls
    )


def validate_budget(budget: RunBudget) -> bool:
    """Validate that budget values are not negative.

    Args:
        budget: The RunBudget to validate

    Returns:
        True if valid, False if any negative values found

    Logs:
        Warning if negative values are detected
    """
    if not budget:
        return True
    if budget.tool_calls < 0:
        logger.warning("validate_budget: negative tool_calls=%d", budget.tool_calls)
        return False
    if budget.llm_calls < 0:
        logger.warning("validate_budget: negative llm_calls=%d", budget.llm_calls)
        return False
    if budget.max_tool_calls < 0:
        logger.warning("validate_budget: negative max_tool_calls=%d", budget.max_tool_calls)
        return False
    if budget.max_llm_calls < 0:
        logger.warning("validate_budget: negative max_llm_calls=%d", budget.max_llm_calls)
        return False
    return True


__all__ = [
    "RunBudget",
    "create_run_budget",
    "budget_should_stop",
    "budget_should_degrade",
    "budget_remaining",
    "budget_exhausted",
    "validate_budget",
]

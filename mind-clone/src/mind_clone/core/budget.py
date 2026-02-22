"""
Budget governor functions.
"""
from dataclasses import dataclass
from typing import Optional

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

__all__ = ["RunBudget", "create_run_budget", "budget_should_stop", "budget_should_degrade"]

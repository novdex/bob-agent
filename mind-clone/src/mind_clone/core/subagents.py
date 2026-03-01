"""
Sub-agent spawning system.

Allows Bob to decompose complex tasks and delegate subtasks to parallel
worker agents, each with a focused role and limited tool set.

Pillar: Autonomy, Reasoning
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mind_clone.core.subagents")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SUBAGENT_MAX_PARALLEL = 4
SUBAGENT_TIMEOUT_SECONDS = 120
SUBAGENT_MAX_TOOL_LOOPS = 5

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLE_PROMPTS: Dict[str, str] = {
    "researcher": (
        "You are a research agent. Find information using available tools. "
        "Be thorough, cite sources, and provide structured findings."
    ),
    "coder": (
        "You are a coding agent. Write clean, correct code. "
        "Read existing code first to understand patterns before writing."
    ),
    "analyst": (
        "You are an analysis agent. Examine data and provide structured insights. "
        "Use calculations and comparisons to support conclusions."
    ),
    "reviewer": (
        "You are a review agent. Check work quality, find bugs, "
        "and suggest improvements. Be specific and actionable."
    ),
    "planner": (
        "You are a planning agent. Break down complex tasks into clear, "
        "actionable steps. Identify dependencies and risks."
    ),
}

ROLE_TOOLS: Dict[str, List[str]] = {
    "researcher": ["search_web", "deep_research", "read_webpage", "read_file",
                    "semantic_memory_search", "research_memory_search", "read_pdf_url"],
    "coder": ["read_file", "write_file", "execute_python", "codebase_read",
              "codebase_search", "codebase_structure", "codebase_edit"],
    "analyst": ["read_file", "execute_python", "semantic_memory_search",
                "search_web", "read_webpage"],
    "reviewer": ["read_file", "codebase_read", "codebase_search",
                 "codebase_structure", "codebase_run_tests", "git_diff"],
    "planner": ["read_file", "list_directory", "codebase_structure",
                "semantic_memory_search", "search_web"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SubAgentResult:
    """Result from a sub-agent worker."""
    agent_name: str
    task: str
    result: str
    success: bool
    duration_ms: int
    tool_calls_made: int
    role: str = ""
    error: str = ""


@dataclass
class SubAgent:
    """Definition of a sub-agent."""
    name: str
    role: str
    tools: List[str] = field(default_factory=list)
    system_prompt: str = ""

    def __post_init__(self):
        if not self.system_prompt:
            self.system_prompt = ROLE_PROMPTS.get(self.role, ROLE_PROMPTS["researcher"])
        if not self.tools:
            self.tools = ROLE_TOOLS.get(self.role, ROLE_TOOLS["researcher"])


# ---------------------------------------------------------------------------
# Worker execution
# ---------------------------------------------------------------------------

def _run_worker(task_dict: dict, timeout: int = SUBAGENT_TIMEOUT_SECONDS) -> SubAgentResult:
    """Run a single sub-agent worker with a focused prompt and limited tools."""
    task_text = str(task_dict.get("task", "")).strip()
    role = str(task_dict.get("role", "researcher")).strip()
    agent_name = str(task_dict.get("name", f"worker_{role}")).strip()
    custom_tools = task_dict.get("tools", None)

    if not task_text:
        return SubAgentResult(
            agent_name=agent_name, task=task_text, result="",
            success=False, duration_ms=0, tool_calls_made=0,
            role=role, error="Empty task",
        )

    agent = SubAgent(name=agent_name, role=role, tools=custom_tools or [])
    system_prompt = agent.system_prompt

    # Build messages
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_text},
    ]

    # Get tool definitions filtered to this agent's tool set
    try:
        from ..tools.schemas import get_tool_schemas
        all_schemas = get_tool_schemas()
        tool_names = set(agent.tools)
        tools = [s for s in all_schemas if s.get("function", {}).get("name", "") in tool_names]
    except Exception:
        tools = []

    start = time.monotonic()
    tool_calls_made = 0
    final_text = ""

    try:
        from ..agent.llm import call_llm
        from ..tools.registry import execute_tool

        for loop_idx in range(SUBAGENT_MAX_TOOL_LOOPS):
            # Sanitize before every LLM call to prevent orphaned tool_call_id errors
            try:
                from ..agent.loop import _sanitize_tool_pairs
                messages = _sanitize_tool_pairs(messages)
            except Exception:
                pass
            result = call_llm(messages, tools=tools if tools else None, max_tokens=4096)

            if not result.get("ok"):
                return SubAgentResult(
                    agent_name=agent_name, task=task_text,
                    result=result.get("error", "LLM error"),
                    success=False, duration_ms=int((time.monotonic() - start) * 1000),
                    tool_calls_made=tool_calls_made, role=role,
                    error=result.get("error", ""),
                )

            content = result.get("content", "")
            tool_calls = result.get("tool_calls")

            if not tool_calls:
                final_text = content
                break

            # Execute tool calls
            messages.append({
                "role": "assistant", "content": content or "(tool calls)",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tool_calls_made += 1
                tool_name = tc.get("function", {}).get("name", "")
                tool_args_str = tc.get("function", {}).get("arguments", "{}")
                tool_call_id = tc.get("id", "")

                # Only execute allowed tools
                if tool_name not in tool_names:
                    tool_result = {"ok": False, "error": f"Tool {tool_name} not allowed for this agent"}
                else:
                    try:
                        args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except json.JSONDecodeError:
                        args = {}
                    tool_result = execute_tool(tool_name, args)

                result_str = json.dumps(tool_result, default=str)[:4000]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_str,
                })

        duration_ms = int((time.monotonic() - start) * 1000)
        _track_metric("subagent_tasks_completed")

        return SubAgentResult(
            agent_name=agent_name, task=task_text, result=final_text,
            success=True, duration_ms=duration_ms,
            tool_calls_made=tool_calls_made, role=role,
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _track_metric("subagent_tasks_failed")
        return SubAgentResult(
            agent_name=agent_name, task=task_text, result="",
            success=False, duration_ms=duration_ms,
            tool_calls_made=tool_calls_made, role=role,
            error=str(exc)[:500],
        )


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------

def spawn_subagents(
    tasks: List[dict],
    max_parallel: int = SUBAGENT_MAX_PARALLEL,
) -> List[SubAgentResult]:
    """Spawn multiple sub-agents to work on tasks concurrently.

    Args:
        tasks: List of {"task": "...", "role": "researcher|coder|analyst|reviewer", "tools": [...]}
        max_parallel: Max concurrent workers.

    Returns:
        List of SubAgentResult in same order as input tasks.
    """
    if not tasks:
        return []

    _track_metric("subagent_spawns_total")
    logger.info("SUBAGENT_SPAWN tasks=%d max_parallel=%d", len(tasks), max_parallel)

    results: List[SubAgentResult] = [None] * len(tasks)  # type: ignore

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as pool:
        future_to_idx = {
            pool.submit(_run_worker, task, SUBAGENT_TIMEOUT_SECONDS): idx
            for idx, task in enumerate(tasks)
        }

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result(timeout=SUBAGENT_TIMEOUT_SECONDS + 10)
            except Exception as exc:
                results[idx] = SubAgentResult(
                    agent_name=f"worker_{idx}",
                    task=tasks[idx].get("task", ""),
                    result="", success=False, duration_ms=0,
                    tool_calls_made=0, role=tasks[idx].get("role", ""),
                    error=str(exc)[:500],
                )

    total_ms = sum(r.duration_ms for r in results if r)
    succeeded = sum(1 for r in results if r and r.success)
    logger.info("SUBAGENT_COMPLETE total=%d succeeded=%d total_ms=%d",
                len(results), succeeded, total_ms)

    return results


# ---------------------------------------------------------------------------
# Task decomposition
# ---------------------------------------------------------------------------

_ROLE_KEYWORDS: Dict[str, List[str]] = {
    "researcher": ["research", "find", "search", "look up", "investigate", "discover", "learn about"],
    "coder": ["implement", "code", "build", "create", "write", "develop", "fix", "debug", "refactor"],
    "analyst": ["analyze", "compare", "evaluate", "measure", "assess", "benchmark", "calculate"],
    "reviewer": ["review", "check", "test", "verify", "validate", "audit", "inspect"],
    "planner": ["plan", "design", "architect", "organize", "structure", "outline"],
}


def decompose_task(complex_task: str) -> List[dict]:
    """Break a complex task into parallelizable subtasks using keyword heuristics."""
    if not complex_task:
        return []

    # Split on "and", "then", semicolons, numbered lists
    import re
    parts = re.split(r'\band\b|;|\bthen\b|\d+\.\s', complex_task)
    parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]

    if len(parts) <= 1:
        # Single task — assign role based on keywords
        role = _detect_role(complex_task)
        return [{"task": complex_task, "role": role, "name": f"worker_{role}"}]

    subtasks = []
    for i, part in enumerate(parts):
        role = _detect_role(part)
        subtasks.append({
            "task": part,
            "role": role,
            "name": f"worker_{role}_{i}",
        })

    return subtasks


def _detect_role(text: str) -> str:
    """Detect the best role for a task based on keywords."""
    text_lower = text.lower()
    best_role = "researcher"
    best_score = 0

    for role, keywords in _ROLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best_role = role

    return best_role


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _track_metric(key: str) -> None:
    """Increment runtime metric (best-effort)."""
    try:
        from ..core.state import increment_runtime_state
        increment_runtime_state(key)
    except Exception:
        pass

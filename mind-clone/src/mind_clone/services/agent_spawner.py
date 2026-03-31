"""
Multi-agent Spawning — Bob spawns sub-Bobs for parallel tasks.

Bob decomposes a complex goal into sub-tasks and runs them
in parallel threads, each with its own isolated context.
Results are collected and merged.

DeerFlow architecture — proven as #1 GitHub trending Feb 2026.
"""
from __future__ import annotations
import json
import logging
import threading
from typing import Optional
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.agent_spawner")

# ---------------------------------------------------------------------------
# Per-agent model configuration
# ---------------------------------------------------------------------------
# Maps agent role names to preferred LLM models.  Sub-agents and council
# agents look up their role here to decide which model to use.
AGENT_MODELS: dict[str, str] = {
    "technical": "nvidia/nemotron-3-super-120b-a12b:free",
    "sentiment": "nvidia/nemotron-3-super-120b-a12b:free",
    "chart": "nvidia/nemotron-3-super-120b-a12b:free",
    "researcher": "nvidia/nemotron-3-super-120b-a12b:free",
    "writer": "xiaomi/mimo-v2-pro",  # better quality for writing
}


def get_agent_model(role_or_model: str | None = None) -> str | None:
    """Resolve a model string from a role name or explicit model identifier.

    If *role_or_model* matches a key in ``AGENT_MODELS`` the mapped model
    is returned.  If it looks like a model identifier (contains ``/``) it
    is returned as-is.  Otherwise returns ``None`` (use default model).

    Args:
        role_or_model: Either a role key ("technical", "writer", ...) or
            a full model identifier ("nvidia/nemotron-...").

    Returns:
        Resolved model string, or None to use the caller's default.
    """
    if not role_or_model:
        return None
    # Explicit model identifier (contains slash)
    if "/" in role_or_model:
        return role_or_model
    # Lookup role
    return AGENT_MODELS.get(role_or_model.lower())


def spawn_sub_agent(task: str, owner_id: int, agent_id: str,
                    results: dict, tools_allowed: list = None,
                    model: str | None = None) -> None:
    """Run a sub-agent task in a background thread.

    Args:
        task: The task description to execute.
        owner_id: Owner ID for the agent.
        agent_id: Unique identifier for this sub-agent.
        results: Shared dict to store results (keyed by agent_id).
        tools_allowed: Optional list of tool names the agent may use.
        model: Optional LLM model override for this sub-agent.
    """
    try:
        from .task_isolator import run_isolated_task
        result = run_isolated_task(
            task, owner_id, tools_allowed=tools_allowed, model=model,
        )
        results[agent_id] = result
    except Exception as e:
        results[agent_id] = {"ok": False, "error": str(e)[:200]}


def run_parallel_agents(tasks: list[dict], owner_id: int = 1,
                        timeout: int = 120) -> dict:
    """Run multiple sub-agent tasks in parallel.

    Each task dict may include an optional ``model`` key to specify which
    LLM model the sub-agent should use.  The value can be a full model
    identifier (e.g. ``nvidia/nemotron-3-super-120b-a12b:free``) or a role
    name that maps to a model via ``AGENT_MODELS``.

    Args:
        tasks: List of task dicts: [{"id": "...", "task": "...", "tools": [...], "model": "..."}]
        owner_id: Owner ID for all agents.
        timeout: Max seconds to wait for all agents.

    Returns:
        Merged results dict.
    """
    results = {}
    threads = []
    for task_spec in tasks[:6]:  # max 6 parallel agents
        agent_id = task_spec.get("id", f"agent_{len(threads)}")
        task = task_spec.get("task", "")
        tools = task_spec.get("tools")
        model = get_agent_model(task_spec.get("model"))
        if not task:
            continue
        t = threading.Thread(
            target=spawn_sub_agent,
            args=(task, owner_id, agent_id, results, tools, model),
            daemon=True,
        )
        threads.append(t)
        t.start()
        logger.info("SPAWNED agent_id=%s model=%s task=%s", agent_id, model or "default", task[:50])

    for t in threads:
        t.join(timeout=timeout)

    return {
        "ok": True,
        "agents_spawned": len(threads),
        "results": results,
        "completed": sum(1 for r in results.values() if r.get("ok")),
    }


def decompose_and_spawn(goal: str, owner_id: int = 1) -> dict:
    """Decompose a complex goal into sub-tasks and run them in parallel."""
    from ..agent.llm import call_llm
    import re

    prompt = [{"role": "user", "content":
        f"Break this goal into 2-4 independent parallel sub-tasks.\n"
        f"Goal: {goal[:400]}\n\n"
        f'Return JSON: {{"tasks": [{{"id": "task1", "task": "...", "description": "..."}}]}}\n'
        f"Each task must be fully self-contained."}]
    try:
        result = call_llm(prompt, temperature=0.2)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
        match = re.search(r'\{.*"tasks".*\}', content, re.DOTALL)
        if not match:
            return {"ok": False, "error": "Could not decompose goal into tasks"}
        data = json.loads(match.group())
        tasks = data.get("tasks", [])
        if not tasks:
            return {"ok": False, "error": "No tasks generated"}
        logger.info("DECOMPOSED goal into %d tasks", len(tasks))
        return run_parallel_agents(tasks, owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_spawn_agents(args: dict) -> dict:
    """Tool: Spawn multiple sub-agents to run tasks in parallel."""
    owner_id = int(args.get("_owner_id", 1))
    goal = str(args.get("goal", "")).strip()
    tasks = args.get("tasks")
    if goal and not tasks:
        return decompose_and_spawn(goal, owner_id)
    if tasks and isinstance(tasks, list):
        return run_parallel_agents(tasks, owner_id)
    return {"ok": False, "error": "Either goal or tasks list required"}

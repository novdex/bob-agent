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


def spawn_sub_agent(task: str, owner_id: int, agent_id: str,
                    results: dict, tools_allowed: list = None) -> None:
    """Run a sub-agent task in a background thread."""
    try:
        from .task_isolator import run_isolated_task
        result = run_isolated_task(task, owner_id, tools_allowed=tools_allowed)
        results[agent_id] = result
    except Exception as e:
        results[agent_id] = {"ok": False, "error": str(e)[:200]}


def run_parallel_agents(tasks: list[dict], owner_id: int = 1,
                        timeout: int = 120) -> dict:
    """
    Run multiple sub-agent tasks in parallel.
    tasks: [{"id": "agent1", "task": "...", "tools": [...]}]
    Returns merged results dict.
    """
    results = {}
    threads = []
    for task_spec in tasks[:6]:  # max 6 parallel agents
        agent_id = task_spec.get("id", f"agent_{len(threads)}")
        task = task_spec.get("task", "")
        tools = task_spec.get("tools")
        if not task:
            continue
        t = threading.Thread(
            target=spawn_sub_agent,
            args=(task, owner_id, agent_id, results, tools),
            daemon=True,
        )
        threads.append(t)
        t.start()
        logger.info("SPAWNED agent_id=%s task=%s", agent_id, task[:50])

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

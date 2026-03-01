"""
Sub-agent tool functions.

Thin wrappers around the spawning engine in ``core.subagents``.
Tool functions live here (tools/); the engine lives in core/.

Pillar: Autonomy, Reasoning
"""

from __future__ import annotations

from ..core.subagents import spawn_subagents, decompose_task, SUBAGENT_MAX_PARALLEL


def tool_spawn_agents(args: dict) -> dict:
    """Spawn parallel sub-agents to work on tasks."""
    tasks = args.get("tasks", [])
    if not tasks:
        return {"ok": False, "error": "tasks list is required"}

    max_parallel = int(args.get("max_parallel", SUBAGENT_MAX_PARALLEL))
    results = spawn_subagents(tasks, max_parallel=max_parallel)

    return {
        "ok": True,
        "total": len(results),
        "succeeded": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "results": [
            {
                "agent": r.agent_name,
                "task": r.task[:100],
                "role": r.role,
                "success": r.success,
                "result": r.result[:2000] if r.result else "",
                "error": r.error,
                "duration_ms": r.duration_ms,
                "tool_calls": r.tool_calls_made,
            }
            for r in results
        ],
    }


def tool_decompose_task(args: dict) -> dict:
    """Break a complex task into parallelizable subtasks."""
    task = str(args.get("task", "")).strip()
    if not task:
        return {"ok": False, "error": "task description is required"}

    subtasks = decompose_task(task)
    return {"ok": True, "subtasks": subtasks, "count": len(subtasks)}

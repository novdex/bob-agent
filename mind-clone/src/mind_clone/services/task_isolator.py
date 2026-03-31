"""
Sub-agent isolation (Microsoft CORPGEN, Feb 2026).

KEY INSIGHT from CORPGEN research:
When an agent handles multiple tasks simultaneously, information from one task
contaminates reasoning about another — causing failures that look random but
are actually memory interference.

The fix: each complex sub-task runs in its OWN context scope. It receives only
what it needs, executes, and returns a structured result to the main agent.
No contamination between tasks.

CORPGEN proved: 3.5x improvement in completion rate (4.3% → 15.2%) just from
sub-agent isolation + hierarchical planning + tiered memory.

Bob's implementation:
- IsolatedTaskContext: wraps a sub-task with its own clean message history
- run_isolated_task(): executes a task in isolation, returns structured result
- Task decomposition: breaks complex requests into independent sub-tasks
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Optional
from dataclasses import dataclass, field

from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.task_isolator")

_MAX_ISOLATED_TOKENS = 4000
_ISOLATION_TIMEOUT = 120  # seconds


@dataclass
class IsolatedTaskContext:
    """A clean isolated context for a single sub-task."""
    task_id: str
    task_description: str
    owner_id: int
    parent_context: str = ""  # only essential info from parent
    messages: list = field(default_factory=list)
    result: Optional[dict] = None
    status: str = "pending"  # pending | running | done | failed


def _build_isolated_system_prompt(task: IsolatedTaskContext) -> str:
    """Build a minimal system prompt for an isolated sub-task."""
    lines = [
        "You are Bob, an autonomous AI agent handling a specific sub-task.",
        f"Sub-task: {task.task_description[:300]}",
        "",
        "IMPORTANT: Focus ONLY on this sub-task. Do not mix in other concerns.",
        "When done, respond with a clear, structured result.",
    ]
    if task.parent_context:
        lines.extend(["", f"Relevant context: {task.parent_context[:300]}"])
    return "\n".join(lines)


def run_isolated_task(
    task_description: str,
    owner_id: int,
    parent_context: str = "",
    tools_allowed: Optional[list] = None,
    model: Optional[str] = None,
) -> dict:
    """Run a task in an isolated context -- no contamination from other tasks.

    Args:
        task_description: What the sub-agent should do.
        owner_id: Owner ID for tool execution.
        parent_context: Optional context snippet from the parent task.
        tools_allowed: Optional whitelist of tool names the agent may use.
        model: Optional LLM model override (e.g. "nvidia/nemotron-3-super-120b-a12b:free").
            If provided, all LLM calls for this isolated task use this model.

    Returns:
        Structured result dict with ok, result, and any errors.
    """
    import uuid
    from ..agent.llm import call_llm
    from ..tools.registry import execute_tool, effective_tool_definitions

    task_id = uuid.uuid4().hex[:8]
    ctx = IsolatedTaskContext(
        task_id=task_id,
        task_description=task_description,
        owner_id=owner_id,
        parent_context=parent_context,
    )

    system_prompt = _build_isolated_system_prompt(ctx)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_description},
    ]

    # Only allow specified tools (or all if none specified)
    all_tools = effective_tool_definitions(owner_id=owner_id)
    if tools_allowed:
        tools = [t for t in all_tools if t.get("function", {}).get("name") in tools_allowed]
    else:
        tools = all_tools

    # Build extra kwargs for model override
    llm_kwargs: dict = {"temperature": 0.7}
    if model:
        llm_kwargs["model"] = model
        logger.info("ISOLATED_TASK model_override=%s task_id=%s", model, task_id)

    ctx.status = "running"
    tool_loops = 0
    max_loops = 15

    try:
        while tool_loops < max_loops:
            result = call_llm(messages, tools=tools, **llm_kwargs)

            if not result.get("ok"):
                return {
                    "ok": False,
                    "task_id": task_id,
                    "error": result.get("error", "LLM failed"),
                }

            content = result.get("content", "")
            tool_calls = result.get("tool_calls")

            if not tool_calls:
                ctx.status = "done"
                return {
                    "ok": True,
                    "task_id": task_id,
                    "result": truncate_text(content, 2000),
                    "tool_loops": tool_loops,
                }

            # Execute tools in isolation
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tool_loops += 1
                tool_name = tc.get("function", {}).get("name", "")
                try:
                    tool_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except Exception:
                    tool_args = {}

                tool_args["_owner_id"] = owner_id
                tool_result = execute_tool(tool_name, tool_args)

                result_str = json.dumps(tool_result, default=str)[:2000]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_str,
                })

        ctx.status = "failed"
        return {"ok": False, "task_id": task_id, "error": "Max tool loops reached"}

    except Exception as e:
        ctx.status = "failed"
        return {"ok": False, "task_id": task_id, "error": str(e)[:200]}


def decompose_and_isolate(
    user_message: str,
    owner_id: int,
) -> Optional[str]:
    """Decompose a complex multi-part task and run sub-tasks in isolation.

    Returns combined result string, or None if task doesn't need decomposition.

    Triggers when message contains multiple distinct goals (multi-step tasks).
    """
    from ..agent.llm import call_llm

    # Only decompose clearly multi-part requests
    multi_indicators = [
        " and then ", " after that ", " also ", " additionally ",
        "first.*then", "step 1", "1.", "multiple", "several tasks",
    ]
    msg_lower = user_message.lower()
    needs_decomposition = any(ind in msg_lower for ind in multi_indicators)

    # Also check length — very long requests often have multiple tasks
    if len(user_message.split()) > 40:
        needs_decomposition = True

    if not needs_decomposition:
        return None

    # Ask LLM to decompose into independent sub-tasks
    decompose_prompt = [
        {
            "role": "user",
            "content": (
                "Break this request into 2-4 independent sub-tasks that can be "
                "executed separately. Return JSON: {\"tasks\": [\"task1\", \"task2\", ...]}\n\n"
                f"Request: {user_message[:600]}"
            ),
        }
    ]

    try:
        result = call_llm(decompose_prompt, temperature=0.2)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)

        # Parse JSON
        import re
        json_match = re.search(r'\{.*"tasks".*\}', content, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())
        tasks = data.get("tasks", [])
        if not tasks or len(tasks) < 2:
            return None

        logger.info("TASK_DECOMPOSED count=%d", len(tasks))

        # Run each sub-task in isolation
        results = []
        for i, task_desc in enumerate(tasks[:4]):  # max 4 sub-tasks
            logger.info("ISOLATED_TASK %d/%d: %s", i+1, len(tasks), task_desc[:60])
            sub_result = run_isolated_task(
                task_description=str(task_desc),
                owner_id=owner_id,
                parent_context=f"Part of: {user_message[:200]}",
            )
            if sub_result.get("ok"):
                results.append(f"**Task {i+1}:** {sub_result.get('result', '')}")
            else:
                results.append(f"**Task {i+1}:** Failed — {sub_result.get('error', 'unknown')}")

        if results:
            return "\n\n".join(results)

    except Exception as e:
        logger.debug("DECOMPOSE_FAIL: %s", str(e)[:100])

    return None


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------

def tool_run_isolated_task(args: dict) -> dict:
    """Tool: Run a specific sub-task in an isolated context (no memory contamination)."""
    owner_id = int(args.get("_owner_id", 1))
    task = str(args.get("task", "")).strip()
    context = str(args.get("context", "")).strip()
    tools = args.get("tools_allowed")

    if not task:
        return {"ok": False, "error": "task is required"}

    return run_isolated_task(task, owner_id, parent_context=context,
                            tools_allowed=tools if isinstance(tools, list) else None)

"""
Multi-turn Planning — think before acting.

Instead of reacting turn-by-turn, Bob writes a structured plan BEFORE
executing complex tasks. Tracks progress step by step. Handles failures
by replanning rather than giving up.

Architecture:
1. PLAN — LLM decomposes task into numbered steps
2. EXECUTE — runs each step, tracks completion
3. REPLAN — if a step fails, adjusts plan and continues
4. REPORT — summarises what was done vs planned

Only activates for complex multi-step tasks (not simple chat).
Plan is injected as a system message so Bob stays on track.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.planner")

_COMPLEX_THRESHOLD = 5  # min words
_PLAN_KEYWORDS = {
    "research", "analyze", "analyse", "build", "create", "implement",
    "develop", "investigate", "compare", "write", "generate", "design",
    "fix", "debug", "refactor", "setup", "configure", "find", "search",
    "collect", "summarize", "summarise", "improve", "test", "deploy",
    "send", "fetch", "download", "process", "calculate",
}

_PLAN_PROMPT = """You are planning how to complete a task step by step.
Break this task into 3-6 clear, numbered steps. Be specific and actionable.
Each step should be completable with available tools.

Task: {task}

Return ONLY a numbered list like:
1. [First step]
2. [Second step]
3. [Third step]
Do not add explanations or headers. Just the numbered steps."""


def needs_planning(message: str) -> bool:
    """Decide if this message needs a plan before execution."""
    words = message.lower().split()
    if len(words) < _COMPLEX_THRESHOLD:
        return False
    return any(kw in message.lower() for kw in _PLAN_KEYWORDS)


def generate_plan(task: str) -> Optional[str]:
    """Generate a numbered execution plan for a complex task."""
    from ..agent.llm import call_llm

    prompt = [{"role": "user", "content": _PLAN_PROMPT.format(task=task[:500])}]
    try:
        result = call_llm(prompt, temperature=0.2)
        plan = ""
        if isinstance(result, dict) and result.get("ok"):
            plan = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                plan = choices[0].get("message", {}).get("content", plan)
        elif isinstance(result, str):
            plan = result

        plan = plan.strip()
        # Validate it looks like a numbered list
        if plan and re.search(r"^\d+\.", plan, re.MULTILINE):
            logger.info("PLAN_GENERATED steps=%d task=%s", plan.count("\n") + 1, task[:50])
            return truncate_text(plan, 800)
    except Exception as e:
        logger.debug("PLAN_GENERATION_FAIL: %s", str(e)[:80])
    return None


def inject_plan_context(
    user_message: str,
    messages: list,
) -> bool:
    """Generate plan and inject as system message before LLM call.

    Returns True if a plan was injected.
    """
    if not needs_planning(user_message):
        return False

    plan = generate_plan(user_message)
    if not plan:
        return False

    messages.append({
        "role": "system",
        "content": (
            "[EXECUTION PLAN] Follow this plan step by step to complete the task:\n\n"
            + plan +
            "\n\nWork through each step systematically. "
            "Use tools as needed. Track your progress. "
            "If a step fails, try an alternative approach before giving up."
        ),
    })
    logger.info("PLAN_INJECTED task=%s", user_message[:60])
    return True

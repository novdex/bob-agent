"""
Generator → Verifier → Reviser (DeepMind Aletheia, March 2026).

KEY INSIGHT from DeepMind research:
"Explicitly separating verification helps the model recognize flaws it initially
overlooks during generation." The same brain that generates an idea is bad at
spotting flaws in it. A separate critic catches what the generator misses.

Architecture:
  1. GENERATOR  — Bob plans how to tackle the task (normal)
  2. VERIFIER   — Separate LLM call critiques the plan before execution
  3. REVISER    — If flaws found, Bob revises the plan before acting

Only activates for complex tasks (research, build, analyze, implement, etc.)
to avoid adding latency to simple conversations.

Proven at highest level: DeepMind Aletheia achieved 95.1% on IMO-Proof Bench
using this exact architecture.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("mind_clone.services.verifier")

# Complexity threshold — only verify these task types
_COMPLEX_KEYWORDS = {
    "research", "analyze", "analyse", "compare", "build", "create", "design",
    "evaluate", "improve", "optimize", "optimise", "debug", "refactor",
    "implement", "develop", "architect", "plan", "strategy", "write",
    "generate", "fix", "solve", "investigate", "review", "audit",
}

_VERIFICATION_PROMPT = """You are a critical reviewer. An AI agent has written a plan to tackle a task.
Your job: find flaws BEFORE the agent executes. Be specific and blunt.

Task: {task}

Proposed plan/response:
{plan}

Review this plan for:
1. Missing steps or assumptions
2. Likely failure points
3. Incorrect reasoning
4. Anything that will probably go wrong

If the plan looks solid, say "PLAN OK".
If there are issues, list them briefly (max 3 bullet points).
Do NOT rewrite the plan. Just critique it."""

_REVISION_PROMPT = """You are an AI agent. A critic just reviewed your plan and found issues.
Revise your response to fix the problems identified.

Original task: {task}

Your original plan:
{plan}

Critic's feedback:
{critique}

Write a revised, improved plan that addresses the critique. Be concise."""


def _is_complex_task(user_message: str) -> bool:
    """Check if task is complex enough to warrant verification."""
    msg_lower = user_message.lower()
    word_count = len(msg_lower.split())
    if word_count < 4:
        return False
    return any(kw in msg_lower for kw in _COMPLEX_KEYWORDS)


def verify_and_revise(
    user_message: str,
    generated_plan: str,
    owner_id: int = 1,
) -> tuple[str, bool]:
    """Run the Verifier on a generated plan.

    Returns (final_plan, was_revised):
    - final_plan: either the original plan (if ok) or a revised version
    - was_revised: True if the verifier found issues and plan was revised
    """
    from ..agent.llm import call_llm

    # Step 1: Verify
    verify_messages = [
        {
            "role": "user",
            "content": _VERIFICATION_PROMPT.format(
                task=user_message[:400],
                plan=generated_plan[:1500],
            ),
        }
    ]

    try:
        verify_result = call_llm(verify_messages, temperature=0.2)
        critique = ""
        if isinstance(verify_result, dict) and verify_result.get("ok"):
            critique = verify_result.get("content", "")
            choices = verify_result.get("choices", [])
            if choices:
                critique = choices[0].get("message", {}).get("content", critique)
        elif isinstance(verify_result, str):
            critique = verify_result

        critique = critique.strip()
        logger.debug("VERIFIER_CRITIQUE len=%d", len(critique))

        # If plan is ok, return as-is
        if not critique or "PLAN OK" in critique.upper() or len(critique) < 20:
            return generated_plan, False

        # Step 2: Revise
        revise_messages = [
            {
                "role": "user",
                "content": _REVISION_PROMPT.format(
                    task=user_message[:400],
                    plan=generated_plan[:1500],
                    critique=critique[:500],
                ),
            }
        ]

        revise_result = call_llm(revise_messages, temperature=0.3)
        revised = ""
        if isinstance(revise_result, dict) and revise_result.get("ok"):
            revised = revise_result.get("content", "")
            choices = revise_result.get("choices", [])
            if choices:
                revised = choices[0].get("message", {}).get("content", revised)
        elif isinstance(revise_result, str):
            revised = revise_result

        revised = revised.strip()
        if revised and len(revised) > 50:
            logger.info("VERIFIER_REVISED task_len=%d critique_len=%d", len(user_message), len(critique))
            return revised, True

        # Revision failed — return original
        return generated_plan, False

    except Exception as e:
        logger.debug("VERIFIER_SKIP error=%s", str(e)[:100])
        return generated_plan, False


def maybe_verify(
    user_message: str,
    generated_content: str,
    owner_id: int = 1,
) -> str:
    """Verify and potentially revise content if task is complex.

    Returns final content (revised or original).
    Called from agent loop after first LLM response but before tool execution.
    """
    if not _is_complex_task(user_message):
        return generated_content

    if not generated_content or len(generated_content) < 100:
        return generated_content  # too short to verify meaningfully

    final, was_revised = verify_and_revise(user_message, generated_content, owner_id)

    if was_revised:
        logger.info("VERIFIER_IMPROVED task=%s", user_message[:60])

    return final

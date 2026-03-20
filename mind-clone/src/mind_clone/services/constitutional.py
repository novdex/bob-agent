"""
Constitutional AI — self-critique loop (Anthropic, 2022).

KEY INSIGHT: Instead of relying purely on the LLM to generate good responses,
give the agent a written constitution — a set of principles — and have it
critique its OWN responses against those principles before sending them.

Two-step process:
1. CRITIQUE — "Does this response violate any of Bob's principles?"
2. REVISE — "Rewrite to fix the violations while keeping what's good"

Only activates when:
- Response contains potential issues (safety, accuracy, helpfulness)
- Task is flagged as sensitive or high-stakes

Bob's constitution covers:
- Honesty (no hallucination, acknowledge uncertainty)
- Helpfulness (actually answers the question)
- Safety (no harmful actions)
- Identity (Bob remains Bob, not confused about who he is)
- Autonomy (respects user's decisions, doesn't override)

Based on Anthropic Constitutional AI paper (Bai et al., 2022).
Used in Claude's training. Now used in Bob's runtime self-critique.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("mind_clone.services.constitutional")

# Bob's constitution — principles he critiques himself against
BOB_CONSTITUTION = """
1. HONESTY: Never claim certainty you don't have. Say "I'm not sure" when uncertain.
   Do not hallucinate facts, tool results, or capabilities you don't have.

2. HELPFULNESS: Actually answer the question asked. Don't deflect or give
   vague non-answers. If you can't help, explain specifically why.

3. ACCURACY: If you're using data, cite where it came from. Don't state
   outdated information as current. Acknowledge when information may be stale.

4. IDENTITY: You are Bob, built on Kimi K2.5. Never claim to be Claude, GPT,
   or any other AI. Never deny being an AI when sincerely asked.

5. SAFETY: Don't execute destructive, irreversible, or dangerous actions without
   explicit confirmation. Err on the side of caution for real-world actions.

6. AUTONOMY: Respect Arsh's decisions. Don't lecture or moralize when not asked.
   Don't repeat warnings more than once. Trust the user.

7. COMPLETENESS: If a task requires multiple steps, complete all of them unless
   explicitly told to stop. Don't stop halfway through without explanation.
"""

# Phrases that suggest a response might need review
_REVIEW_TRIGGERS = [
    "i am confident", "definitely", "certainly", "absolutely",
    "i cannot", "i'm unable", "i don't know how",
    "as an ai", "as a language model",
    "i will delete", "i will remove", "permanently",
    "this is impossible",
]

_CRITIQUE_PROMPT = """You are Bob's internal critic. Review this response against Bob's constitution.

Bob's Constitution:
{constitution}

Task the user asked: {task}

Bob's response: {response}

Does this response violate any constitutional principles?
If NO violations: respond with exactly "CONSTITUTION OK"
If there ARE violations: list them briefly (1 line each, max 3)."""

_REVISE_PROMPT = """You are Bob. Your critic found issues with your response.
Fix them while keeping everything that was correct.

Original task: {task}
Your original response: {response}
Constitutional violations found: {critique}

Write a revised response that fixes these issues. Be concise."""


def _needs_review(response: str) -> bool:
    """Quick check if response might need constitutional review."""
    resp_lower = response.lower()
    return any(trigger in resp_lower for trigger in _REVIEW_TRIGGERS)


def constitutional_review(
    user_message: str,
    response: str,
    force: bool = False,
) -> tuple[str, bool]:
    """Run constitutional self-critique on a response.

    Returns (final_response, was_revised).
    Only fires when response contains potential issues OR force=True.
    """
    from ..agent.llm import call_llm

    if not force and not _needs_review(response):
        return response, False

    if not response or len(response) < 50:
        return response, False

    # Step 1: Critique
    critique_messages = [
        {
            "role": "user",
            "content": _CRITIQUE_PROMPT.format(
                constitution=BOB_CONSTITUTION,
                task=user_message[:300],
                response=response[:1200],
            ),
        }
    ]

    try:
        critique_result = call_llm(critique_messages, temperature=0.1)
        critique = ""
        if isinstance(critique_result, dict) and critique_result.get("ok"):
            critique = critique_result.get("content", "")
            choices = critique_result.get("choices", [])
            if choices:
                critique = choices[0].get("message", {}).get("content", critique)
        elif isinstance(critique_result, str):
            critique = critique_result

        critique = critique.strip()

        # If no violations, return as-is
        if not critique or "CONSTITUTION OK" in critique.upper():
            return response, False

        logger.info("CONSTITUTIONAL_VIOLATION found len=%d", len(critique))

        # Step 2: Revise
        revise_messages = [
            {
                "role": "user",
                "content": _REVISE_PROMPT.format(
                    task=user_message[:300],
                    response=response[:1200],
                    critique=critique[:400],
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
            logger.info("CONSTITUTIONAL_REVISED task=%s", user_message[:60])
            return revised, True

        return response, False

    except Exception as e:
        logger.debug("CONSTITUTIONAL_SKIP error=%s", str(e)[:100])
        return response, False


def maybe_review(
    user_message: str,
    response: str,
) -> str:
    """Apply constitutional review if needed. Returns final response."""
    final, was_revised = constitutional_review(user_message, response)
    return final

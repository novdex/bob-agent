"""
Co-Evolving Critic — critic improves alongside the agent (2026 paper).

KEY INSIGHT: The standard verifier uses a fixed critique template.
As Bob improves, the critique standard must also improve — otherwise
the critic goes stale and stops catching real issues.

The co-critic periodically updates its critique principles based on:
- What types of errors Bob actually makes (from Reflexion logs)
- What past critiques led to improvements (from ExperimentLog)
- Current performance metrics (composite score trends)

Based on: "No More Stale Feedback: Co-Evolving Critics for Open-World
Agent Learning" (2026) — jointly optimises agent policy and critic
via synchronized GRPO updates.

Bob's version: no gradient updates. Instead, the critic's principles
are updated by LLM based on real failure history. Same concept, simpler.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.co_critic")

# Default critique principles (starting point, evolves over time)
_DEFAULT_PRINCIPLES = [
    "Check for missing steps or assumptions in the plan",
    "Verify all tool calls have required parameters",
    "Ensure the response actually answers what was asked",
    "Check for overconfident claims without evidence",
    "Verify actions are reversible or have been confirmed",
]

# In-memory evolved principles (updated periodically)
_EVOLVED_PRINCIPLES: list[str] = []
_PRINCIPLES_VERSION: int = 0


def get_current_principles() -> list[str]:
    """Get current critic principles (evolved or default)."""
    return _EVOLVED_PRINCIPLES if _EVOLVED_PRINCIPLES else _DEFAULT_PRINCIPLES


def evolve_critic_principles(owner_id: int = 1) -> list[str]:
    """Update critic principles based on real failure history."""
    from ..agent.llm import call_llm
    from ..database.models import SelfImprovementNote, ExperimentLog

    db = SessionLocal()
    try:
        # Get recent failures from Reflexion
        failures = (
            db.query(SelfImprovementNote)
            .filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.status == "open",
            )
            .order_by(SelfImprovementNote.id.desc())
            .limit(10)
            .all()
        )
        failure_summaries = [r.summary[:100] for r in failures]

        # Get experiment results
        experiments = (
            db.query(ExperimentLog)
            .filter(ExperimentLog.owner_id == owner_id)
            .order_by(ExperimentLog.id.desc())
            .limit(5)
            .all()
        )
        exp_summaries = [
            f"{'✓' if e.improved else '✗'} {e.hypothesis_title[:60]}"
            for e in experiments
        ]
    finally:
        db.close()

    if not failure_summaries:
        return _DEFAULT_PRINCIPLES

    prompt = [{
        "role": "user",
        "content": (
            "You are updating an AI agent's self-critique principles based on "
            "its recent failure history.\n\n"
            f"Recent failures:\n" + "\n".join(f"- {f}" for f in failure_summaries[:5]) +
            f"\n\nRecent experiments:\n" + "\n".join(f"- {e}" for e in exp_summaries) +
            "\n\nCurrent principles:\n" + "\n".join(f"- {p}" for p in get_current_principles()) +
            "\n\nWrite 5 updated critique principles that would catch these specific "
            "types of failures. Keep what works. Replace what doesn't. "
            "Return ONLY 5 bullet points, one per line, starting with '-'."
        ),
    }]

    try:
        result = call_llm(prompt, temperature=0.3)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
        elif isinstance(result, str):
            content = result

        # Parse bullet points
        import re
        principles = [
            line.lstrip("- ").strip()
            for line in content.strip().split("\n")
            if line.strip().startswith("-") and len(line.strip()) > 10
        ][:5]

        if len(principles) >= 3:
            global _EVOLVED_PRINCIPLES, _PRINCIPLES_VERSION
            _EVOLVED_PRINCIPLES = principles
            _PRINCIPLES_VERSION += 1
            logger.info("CO_CRITIC_EVOLVED version=%d principles=%d", _PRINCIPLES_VERSION, len(principles))
            return principles
    except Exception as e:
        logger.debug("CO_CRITIC_EVOLVE_FAIL: %s", str(e)[:80])

    return _DEFAULT_PRINCIPLES


def co_critique(user_message: str, response: str) -> tuple[str, bool]:
    """Critique a response using evolved principles.

    Returns (final_response, was_revised).
    """
    from ..agent.llm import call_llm

    principles = get_current_principles()
    principles_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(principles))

    critique_prompt = [{
        "role": "user",
        "content": (
            f"Critique this AI response using these principles:\n{principles_text}\n\n"
            f"Task: {user_message[:200]}\n"
            f"Response: {response[:800]}\n\n"
            "List any violations (max 2). If none, reply: 'CRITIQUE OK'"
        ),
    }]

    try:
        result = call_llm(critique_prompt, temperature=0.1)
        critique = ""
        if isinstance(result, dict) and result.get("ok"):
            critique = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                critique = choices[0].get("message", {}).get("content", critique)
        elif isinstance(result, str):
            critique = result

        critique = critique.strip()
        if not critique or "CRITIQUE OK" in critique.upper() or len(critique) < 15:
            return response, False

        # Revise
        revise_prompt = [{
            "role": "user",
            "content": (
                f"Fix these issues in your response:\n{critique[:300]}\n\n"
                f"Original response: {response[:800]}\n\n"
                "Write a corrected version. Keep everything correct, fix only the issues."
            ),
        }]
        rev_result = call_llm(revise_prompt, temperature=0.3)
        revised = ""
        if isinstance(rev_result, dict) and rev_result.get("ok"):
            revised = rev_result.get("content", "")
            choices = rev_result.get("choices", [])
            if choices:
                revised = choices[0].get("message", {}).get("content", revised)
        elif isinstance(rev_result, str):
            revised = rev_result

        revised = revised.strip()
        if revised and len(revised) > 50:
            logger.info("CO_CRITIC_REVISED v=%d", _PRINCIPLES_VERSION)
            return revised, True

    except Exception as e:
        logger.debug("CO_CRITIC_FAIL: %s", str(e)[:80])

    return response, False


def tool_evolve_critic(args: dict) -> dict:
    """Tool: Evolve the critic's principles based on real failure history."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        principles = evolve_critic_principles(owner_id)
        return {
            "ok": True,
            "version": _PRINCIPLES_VERSION,
            "principles": principles,
            "message": f"Critic evolved to v{_PRINCIPLES_VERSION} with {len(principles)} principles",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

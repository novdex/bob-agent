"""
Reflexion — Stanford 2023 style verbal reinforcement learning.

After each failure (tool error OR bad outcome), Bob writes a verbal reflection:
  "I tried X, it failed because Y. Next time I should Z."

These reflections are:
1. Stored as SelfImprovementNotes in DB (searchable, persistent)
2. Injected into future turns when a similar task is detected
3. Retrieved by the recall system before any complex task

No gradient updates. No fine-tuning. Just structured lessons from experience.

Based on: Reflexion (Shinn et al., Stanford 2023) — beats GPT-4 on many benchmarks
via verbal reflection alone.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from sqlalchemy.orm import Session

from ..database.models import SelfImprovementNote
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.reflexion")

_MAX_REFLECTION_CHARS = 600
_REFLECTION_PRIORITY = "high"


# ---------------------------------------------------------------------------
# Core reflection generation
# ---------------------------------------------------------------------------

def generate_reflection(
    action_attempted: str,
    failure_reason: str,
    context: str = "",
) -> str:
    """Generate a verbal reflection from a failure using LLM.

    Returns a reflection string like:
    "I tried X. It failed because Y. Next time I should Z."
    """
    from ..agent.llm import call_llm

    prompt = [
        {
            "role": "user",
            "content": (
                "You are Bob, an autonomous AI agent. You just experienced a failure. "
                "Write a short verbal reflection (2-3 sentences) in first person.\n\n"
                f"What I tried: {action_attempted[:300]}\n"
                f"Why it failed: {failure_reason[:300]}\n"
                f"Context: {context[:200]}\n\n"
                "Format: 'I tried [X]. It failed because [Y]. Next time I should [Z].'\n"
                "Be specific and actionable. Max 3 sentences."
            ),
        }
    ]

    try:
        result = call_llm(prompt, temperature=0.3)
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
            return truncate_text(content.strip(), _MAX_REFLECTION_CHARS)
        elif isinstance(result, str):
            return truncate_text(result.strip(), _MAX_REFLECTION_CHARS)
    except Exception as e:
        logger.debug("REFLECTION_LLM_FAIL: %s", str(e)[:100])

    # Fallback: construct a basic reflection without LLM
    return (
        f"I tried {action_attempted[:100]}. "
        f"It failed because {failure_reason[:150]}. "
        f"Next time I should check for this error before attempting the same approach."
    )


# ---------------------------------------------------------------------------
# Save reflection as SelfImprovementNote
# ---------------------------------------------------------------------------

def save_reflection(
    db: Session,
    owner_id: int,
    title: str,
    reflection_text: str,
    tool_name: str = "",
    error_category: str = "tool_failure",
) -> Optional[SelfImprovementNote]:
    """Save a reflection as a SelfImprovementNote for future recall."""
    try:
        note = SelfImprovementNote(
            owner_id=owner_id,
            title=truncate_text(title, 120),
            summary=truncate_text(reflection_text, _MAX_REFLECTION_CHARS),
            actions_json=json.dumps([
                f"Recall this lesson before attempting: {truncate_text(title, 60)}"
            ]),
            evidence_json=json.dumps({
                "tool_name": tool_name,
                "error_category": error_category,
                "source": "reflexion",
            }),
            priority=_REFLECTION_PRIORITY,
            status="open",
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        logger.info("REFLECTION_SAVED id=%d title=%s", note.id, title[:50])
        return note
    except Exception as e:
        logger.error("REFLECTION_SAVE_FAIL: %s", e)
        db.rollback()
        return None


# ---------------------------------------------------------------------------
# Tool failure reflection (called after tool returns ok=False)
# ---------------------------------------------------------------------------

def reflect_on_tool_failure(
    owner_id: int,
    tool_name: str,
    tool_args: dict,
    error: str,
    user_message: str = "",
) -> None:
    """Generate and save a reflection after a tool failure.

    Runs in a background thread — non-blocking.
    """
    def _run():
        db = SessionLocal()
        try:
            # Don't spam reflections for trivial errors
            trivial = ["timeout", "rate limit", "network", "connection"]
            if any(t in error.lower() for t in trivial):
                return

            action = f"call {tool_name} with args {json.dumps(tool_args, default=str)[:150]}"
            reflection = generate_reflection(
                action_attempted=action,
                failure_reason=error,
                context=user_message[:150],
            )

            title = f"Tool failure: {tool_name} — {error[:60]}"
            save_reflection(db, owner_id, title, reflection,
                          tool_name=tool_name, error_category="tool_failure")
        except Exception as e:
            logger.debug("REFLECT_TOOL_FAILURE_ERR: %s", e)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Task failure reflection (called when a full task fails)
# ---------------------------------------------------------------------------

def reflect_on_task_failure(
    owner_id: int,
    user_message: str,
    final_response: str,
    failure_indicators: Optional[list] = None,
) -> None:
    """Generate and save a reflection after a full task fails.

    Detects failure by looking for failure phrases in Bob's response.
    Runs in a background thread.
    """
    _FAILURE_PHRASES = [
        "i was unable", "i couldn't", "i failed", "error occurred",
        "i apologize", "task incomplete", "maximum tool iterations",
        "i cannot complete", "something went wrong",
    ]

    def _run():
        response_lower = final_response.lower()
        indicators = failure_indicators or _FAILURE_PHRASES
        is_failure = any(phrase in response_lower for phrase in indicators)
        if not is_failure:
            return

        db = SessionLocal()
        try:
            # Extract what failed from the response
            failure_reason = truncate_text(final_response, 200)
            reflection = generate_reflection(
                action_attempted=truncate_text(user_message, 200),
                failure_reason=failure_reason,
                context="",
            )

            title = f"Task failed: {truncate_text(user_message, 80)}"
            save_reflection(db, owner_id, title, reflection,
                          error_category="task_failure")
        except Exception as e:
            logger.debug("REFLECT_TASK_FAILURE_ERR: %s", e)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Retrieve recent reflections (for prompt injection)
# ---------------------------------------------------------------------------

def get_recent_reflections(
    db: Session,
    owner_id: int,
    query: str = "",
    limit: int = 3,
) -> list[dict]:
    """Get recent high-priority reflections relevant to the current task."""
    q = (
        db.query(SelfImprovementNote)
        .filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.status == "open",
        )
        .order_by(SelfImprovementNote.id.desc())
        .limit(limit * 3)  # over-fetch, then filter
    )
    rows = q.all()

    if query and rows:
        # Simple keyword filter
        import re
        keywords = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
        if keywords:
            scored = []
            for r in rows:
                text = f"{r.title} {r.summary}".lower()
                overlap = sum(1 for k in keywords if k in text)
                scored.append((overlap, r))
            scored.sort(reverse=True)
            rows = [r for _, r in scored[:limit]]
        else:
            rows = rows[:limit]
    else:
        rows = rows[:limit]

    return [
        {
            "title": r.title,
            "lesson": r.summary,
            "priority": r.priority,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Inject reflections into messages before LLM call
# ---------------------------------------------------------------------------

def inject_reflexion_context(
    db: Session,
    owner_id: int,
    user_message: str,
    messages: list,
) -> None:
    """Inject relevant past reflections before the LLM call.

    Called from run_agent_turn — adds a system message with lessons learned
    from past failures so Bob doesn't repeat mistakes.
    """
    try:
        reflections = get_recent_reflections(db, owner_id, query=user_message, limit=3)
        if not reflections:
            return

        lines = ["[REFLEXION] Lessons from past failures — don't repeat these mistakes:"]
        for r in reflections:
            lines.append(f"• {r['lesson']}")

        messages.append({
            "role": "system",
            "content": "\n".join(lines),
        })
        logger.debug("REFLEXION_INJECTED count=%d", len(reflections))
    except Exception as e:
        logger.debug("REFLEXION_INJECT_SKIP: %s", str(e)[:100])

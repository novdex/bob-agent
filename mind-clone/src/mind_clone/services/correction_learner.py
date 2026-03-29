"""
Correction Learner — Bob learns permanently from user corrections.

When the user says "no", "wrong", "that's not right", "I meant X",
Bob extracts the lesson and saves it to permanent memory. These lessons
are recalled in future conversations via the reflexion/recall system.

This is how Bob gets smarter over time from human feedback.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, Any

from ..database.session import SessionLocal

logger = logging.getLogger("mind_clone.correction_learner")

# Phrases that indicate the user is correcting Bob
CORRECTION_SIGNALS = [
    "no,", "no ", "nope", "wrong", "that's wrong", "that's not right",
    "not what i", "i meant", "i said", "actually,", "actually ",
    "incorrect", "that's incorrect", "you're wrong", "you are wrong",
    "don't do that", "stop doing", "never do", "i didn't ask",
    "not like that", "not that", "try again", "redo", "fix this",
    "that's not what", "you misunderstood", "you got it wrong",
]


def is_correction(user_message: str) -> bool:
    """Detect if a user message is a correction/feedback.

    Args:
        user_message: The user's message text.

    Returns:
        True if the message appears to be correcting Bob.
    """
    msg_lower = user_message.strip().lower()
    if len(msg_lower) < 3:
        return False
    return any(signal in msg_lower for signal in CORRECTION_SIGNALS)


def extract_lesson_from_correction(
    user_message: str,
    bob_previous_message: str,
    owner_id: int = 1,
) -> Optional[str]:
    """Use LLM to extract a reusable lesson from a user correction.

    Args:
        user_message: The user's correction message.
        bob_previous_message: What Bob said that was wrong.
        owner_id: The user's owner ID.

    Returns:
        A lesson string, or None if no clear lesson can be extracted.
    """
    from ..agent.llm import call_llm

    prompt = [
        {"role": "system", "content": (
            "You extract lessons from user corrections. "
            "The user corrected the AI assistant. Extract a clear, reusable lesson "
            "that the assistant should remember for ALL future conversations. "
            "Format: 'LESSON: [what to do/not do]. REASON: [why].' "
            "Keep it under 100 words. If no clear lesson, respond with just 'NONE'."
        )},
        {"role": "user", "content": (
            f"The assistant said:\n{bob_previous_message[:500]}\n\n"
            f"The user corrected:\n{user_message[:500]}\n\n"
            f"What lesson should the assistant permanently learn?"
        )},
    ]

    try:
        result = call_llm(prompt, temperature=0.1)
        if not result.get("ok"):
            return None
        content = result.get("content", "").strip()
        if not content or content.upper() == "NONE" or len(content) < 10:
            return None
        return content[:300]
    except Exception as e:
        logger.debug("LESSON_EXTRACT_FAIL: %s", str(e)[:100])
        return None


def learn_from_correction(
    owner_id: int,
    user_message: str,
    bob_previous_message: str,
) -> Dict[str, Any]:
    """Full correction learning pipeline: detect → extract → save.

    Called from the agent loop's background tasks after each turn.

    Args:
        owner_id: User's owner ID.
        user_message: What the user said (the correction).
        bob_previous_message: What Bob said before (the mistake).

    Returns:
        Dict with ok, lesson, saved status.
    """
    if not is_correction(user_message):
        return {"ok": True, "correction": False}

    logger.info("CORRECTION_DETECTED owner=%d msg='%s'", owner_id, user_message[:50])

    # Extract lesson
    lesson = extract_lesson_from_correction(user_message, bob_previous_message, owner_id)
    if not lesson:
        return {"ok": True, "correction": True, "lesson": None, "reason": "no clear lesson"}

    # Save as permanent lesson in memory vectors
    db = SessionLocal()
    try:
        from ..agent.memory import store_lesson
        saved = store_lesson(db, owner_id, lesson, context=f"Correction: {user_message[:200]}")

        # Also save as a SelfImprovementNote for visibility
        from ..database.models import SelfImprovementNote
        note = SelfImprovementNote(
            owner_id=owner_id,
            title=f"User correction: {user_message[:60]}",
            summary=lesson,
            actions_json=json.dumps([{"action": "apply_lesson", "lesson": lesson}]),
            evidence_json=json.dumps({
                "user_correction": user_message[:300],
                "bob_mistake": bob_previous_message[:300],
            }),
            priority="high",
            status="open",
        )
        db.add(note)
        db.commit()

        logger.info("CORRECTION_LEARNED lesson='%s'", lesson[:80])
        return {"ok": True, "correction": True, "lesson": lesson, "saved": saved}

    except Exception as e:
        db.rollback()
        logger.error("CORRECTION_SAVE_FAIL: %s", str(e)[:100])
        return {"ok": False, "error": str(e)[:100]}
    finally:
        db.close()

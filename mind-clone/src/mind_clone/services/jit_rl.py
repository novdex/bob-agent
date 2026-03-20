"""
JitRL — Just-in-Time Reinforcement Learning (2026 paper).

No gradient updates needed. Instead:
1. Retrieve relevant past experiences at inference time
2. Score them by outcome quality
3. Use highest-scoring experiences as few-shot examples
4. Bob's behaviour is steered by what worked before

Based on: "JitRL: Just-In-Time Reinforcement Learning for Continual
Learning in LLM Agents Without Gradient Updates" (2026)
"""
from __future__ import annotations
import json
import logging
import re
from ..database.session import SessionLocal
from ..database.models import EpisodicMemory
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.jit_rl")


def retrieve_high_value_experiences(
    owner_id: int,
    query: str,
    limit: int = 3,
) -> list[dict]:
    """Retrieve past successful experiences relevant to current task."""
    db = SessionLocal()
    try:
        episodes = (
            db.query(EpisodicMemory)
            .filter(
                EpisodicMemory.owner_id == owner_id,
                EpisodicMemory.outcome == "success",
                EpisodicMemory.importance >= 0.4,
            )
            .order_by(EpisodicMemory.importance.desc())
            .limit(50)
            .all()
        )
        query_words = set(re.findall(r"[a-z]{4,}", query.lower()))
        scored = []
        for ep in episodes:
            ep_words = set(re.findall(r"[a-z]{4,}", (ep.situation or "").lower()))
            overlap = len(query_words & ep_words)
            if overlap > 0:
                scored.append((overlap * float(ep.importance or 0.5), ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "situation": ep.situation[:150],
                "action": ep.action_taken[:150],
                "outcome": ep.outcome,
                "importance": float(ep.importance or 0.5),
            }
            for _, ep in scored[:limit]
        ]
    finally:
        db.close()


def get_jit_examples_block(owner_id: int, user_message: str) -> str:
    """Return JitRL examples as a string block."""
    try:
        experiences = retrieve_high_value_experiences(owner_id, user_message)
        if not experiences:
            return ""
        lines = ["[JitRL] High-value past experiences for this type of task:"]
        for ex in experiences:
            lines.append(f"• Situation: {ex['situation']} → Action: {ex['action']} → {ex['outcome'].upper()}")
        return "\n".join(lines)
    except Exception:
        return ""


def inject_jit_examples(owner_id: int, user_message: str, messages: list) -> None:
    """Inject high-value past experiences as few-shot examples."""
    try:
        experiences = retrieve_high_value_experiences(owner_id, user_message)
        if not experiences:
            return
        lines = ["[JitRL] High-value past experiences for this type of task:"]
        for ex in experiences:
            lines.append(f"• Situation: {ex['situation']} → Action: {ex['action']} → {ex['outcome'].upper()}")
        messages.append({"role": "system", "content": "\n".join(lines)})
        logger.debug("JITRL_INJECTED count=%d", len(experiences))
    except Exception as e:
        logger.debug("JITRL_INJECT_SKIP: %s", str(e)[:80])

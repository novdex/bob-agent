"""
Bob Teaching Bob — future Bob learns from past Bob's best work.

When Bob solves something hard or excellent:
1. Generates a training example (input → ideal output)
2. Stores it as a high-importance skill + episodic memory
3. Future Bob retrieves these examples as few-shot demonstrations
4. Bob's quality compounds over time

This is the autonomous curriculum: Bob sets its own challenges
and learns from solving them. Voyager automatic curriculum pattern.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from ..database.session import SessionLocal
from ..database.models import SkillProfile, SkillVersion, EpisodicMemory
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.bob_teaches_bob")

_QUALITY_THRESHOLD = 300  # min response chars to be worth learning from
_COMPLEX_KEYWORDS = {"research","analyze","implement","build","design","debug","optimize","create","solve"}


def _is_high_quality_exchange(user_message: str, response: str) -> bool:
    """Detect if this was a high-quality exchange worth learning from."""
    if len(response) < _QUALITY_THRESHOLD:
        return False
    msg_lower = user_message.lower()
    return any(kw in msg_lower for kw in _COMPLEX_KEYWORDS)


def generate_training_example(user_message: str, response: str, owner_id: int = 1) -> Optional[dict]:
    """Generate a structured training example from a high-quality exchange."""
    from ..agent.llm import call_llm
    prompt = [{"role": "user", "content":
        f"Extract a reusable training example from this exchange.\n\n"
        f"User asked: {user_message[:300]}\n"
        f"Bob answered: {response[:600]}\n\n"
        f"Create a training example JSON:\n"
        f'{{"skill_name": "...", "task_pattern": "...", "key_approach": "...", "example_steps": ["step1", "step2"]}}\n'
        f"Focus on the generalizable approach, not the specific answer."}]
    try:
        result = call_llm(prompt, temperature=0.2)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.debug("TRAINING_EXAMPLE_FAIL: %s", str(e)[:80])
    return None


def store_teaching_moment(user_message: str, response: str, owner_id: int = 1) -> bool:
    """Store a high-quality exchange as a teaching moment for future Bob."""
    if not _is_high_quality_exchange(user_message, response):
        return False
    example = generate_training_example(user_message, response, owner_id)
    if not example:
        return False

    db = SessionLocal()
    try:
        # Save as a high-importance skill
        skill_name = example.get("skill_name", "learned_skill")
        body = (
            f"Task pattern: {example.get('task_pattern', '')}\n"
            f"Key approach: {example.get('key_approach', '')}\n"
            f"Steps: {json.dumps(example.get('example_steps', []))}\n\n"
            f"Example input: {user_message[:200]}\n"
            f"Example output: {response[:400]}"
        )
        # Check if similar skill exists
        existing = db.query(SkillProfile).filter(
            SkillProfile.owner_id == owner_id,
            SkillProfile.title.like(f"%{skill_name[:20]}%"),
        ).first()

        if not existing:
            from .skills import save_skill_profile
            save_skill_profile(db, owner_id, skill_key=skill_name,
                             title=f"Bob teaches Bob: {skill_name[:50]}",
                             body_text=truncate_text(body, 2000),
                             intent=example.get("task_pattern", user_message[:100]),
                             source_type="bob_teaches_bob", auto_created=True)

        # Also store as high-importance episodic memory
        ep = EpisodicMemory(
            owner_id=owner_id,
            situation=truncate_text(user_message, 200),
            action_taken=truncate_text(example.get("key_approach", response[:200]), 200),
            outcome="success",
            outcome_detail=truncate_text(body, 500),
            tools_used_json=json.dumps([]),
            source_type="bob_teaches_bob",
            importance=0.9,
        )
        db.add(ep); db.commit()
        logger.info("TEACHING_MOMENT_STORED skill=%s", skill_name)
        return True
    except Exception as e:
        logger.debug("STORE_TEACHING_FAIL: %s", str(e)[:80])
        db.rollback()
        return False
    finally:
        db.close()


def tool_store_teaching_moment(args: dict) -> dict:
    """Tool: Store a high-quality exchange as a teaching moment for future Bob."""
    owner_id = int(args.get("_owner_id", 1))
    user_msg = str(args.get("user_message", "")).strip()
    response = str(args.get("response", "")).strip()
    if not user_msg or not response:
        return {"ok": False, "error": "user_message and response required"}
    stored = store_teaching_moment(user_msg, response, owner_id)
    return {"ok": True, "stored": stored}


from typing import Optional

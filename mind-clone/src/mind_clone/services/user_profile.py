"""
Long-term User Profiling — Bob learns who Arsh is over time.

Builds a structured, evolving profile of the user:
- Communication style (direct/detailed, emoji/no emoji)
- Interests and topics they care about most
- Working hours and activity patterns
- Ongoing projects and their status
- Preferred response length
- Things that annoy them

Profile is updated after every conversation turn.
Injected into system prompt so Bob personalises everything.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from ..database.models import User
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.user_profile")

_DEFAULT_PROFILE = {
    "name": "Arsh",
    "communication_style": "direct, no-nonsense, brief",
    "preferred_response_length": "concise",
    "timezone": "Europe/London",
    "interests": ["AI agents", "autonomous systems", "Bob development", "crypto"],
    "active_projects": ["Bob AGI platform"],
    "dislikes": ["repetition", "filler words", "lengthy explanations when not needed"],
    "working_hours": "9am-11pm GMT",
    "last_updated": None,
}


def _load_profile(owner_id: int) -> dict:
    """Load user profile from DB meta_json."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if user and user.meta_json:
            try:
                data = json.loads(user.meta_json)
                profile = data.get("user_profile", {})
                if profile:
                    return {**_DEFAULT_PROFILE, **profile}
            except Exception:
                pass
        return dict(_DEFAULT_PROFILE)
    finally:
        db.close()


def _save_profile(owner_id: int, profile: dict) -> None:
    """Save updated profile to DB."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if not user:
            return
        try:
            existing = json.loads(user.meta_json or "{}")
        except Exception:
            existing = {}
        profile["last_updated"] = datetime.now(timezone.utc).isoformat()
        existing["user_profile"] = profile
        user.meta_json = json.dumps(existing, ensure_ascii=False)
        db.commit()
    except Exception as e:
        logger.error("PROFILE_SAVE_FAIL: %s", e)
        db.rollback()
    finally:
        db.close()


def update_profile_from_turn(
    owner_id: int,
    user_message: str,
    assistant_response: str,
) -> None:
    """Update user profile based on conversation turn (background thread)."""
    import threading
    def _run():
        try:
            from ..agent.llm import call_llm
            profile = _load_profile(owner_id)
            prompt = [{
                "role": "user",
                "content": (
                    f"Update this user profile JSON based on the conversation.\n"
                    f"Current profile: {json.dumps(profile)}\n\n"
                    f"User said: {user_message[:200]}\n"
                    f"Agent responded: {assistant_response[:200]}\n\n"
                    f"Return ONLY updated JSON with same keys. Only update if there's new info. "
                    f"Keep changes minimal. No explanations."
                ),
            }]
            result = call_llm(prompt, temperature=0.1)
            content = ""
            if isinstance(result, dict) and result.get("ok"):
                content = result.get("content", "")
                choices = result.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", content)
            elif isinstance(result, str):
                content = result
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                updated = json.loads(match.group())
                if isinstance(updated, dict) and "name" in updated:
                    _save_profile(owner_id, updated)
                    logger.debug("PROFILE_UPDATED owner=%d", owner_id)
        except Exception as e:
            logger.debug("PROFILE_UPDATE_FAIL: %s", str(e)[:80])
    threading.Thread(target=_run, daemon=True).start()


def get_profile_context_block(owner_id: int) -> str:
    """Return profile context as a string block."""
    try:
        profile = _load_profile(owner_id)
        return (
            f"[USER PROFILE] Name: {profile.get('name','User')} | "
            f"Style: {profile.get('communication_style','')} | "
            f"Response length: {profile.get('preferred_response_length','')}\n"
            f"Interests: {', '.join(profile.get('interests',[])[:5])}\n"
            f"Active projects: {', '.join(profile.get('active_projects',[])[:3])}\n"
            f"Dislikes: {', '.join(profile.get('dislikes',[])[:3])}"
        )
    except Exception:
        return ""


def inject_profile_context(
    owner_id: int,
    messages: list,
) -> None:
    """Inject user profile as system context before LLM call."""
    try:
        profile = _load_profile(owner_id)
        lines = [
            f"[USER PROFILE] Name: {profile.get('name','User')} | "
            f"Style: {profile.get('communication_style','')} | "
            f"Response length: {profile.get('preferred_response_length','')}",
            f"Interests: {', '.join(profile.get('interests',[])[:5])}",
            f"Active projects: {', '.join(profile.get('active_projects',[])[:3])}",
            f"Dislikes: {', '.join(profile.get('dislikes',[])[:3])}",
        ]
        messages.append({"role": "system", "content": "\n".join(lines)})
    except Exception as e:
        logger.debug("PROFILE_INJECT_SKIP: %s", str(e)[:80])


def tool_get_user_profile(args: dict) -> dict:
    """Tool: Get the current user profile."""
    owner_id = int(args.get("_owner_id", 1))
    return {"ok": True, "profile": _load_profile(owner_id)}


def tool_update_user_profile(args: dict) -> dict:
    """Tool: Manually update a field in the user profile."""
    owner_id = int(args.get("_owner_id", 1))
    field = str(args.get("field", "")).strip()
    value = args.get("value")
    if not field or value is None:
        return {"ok": False, "error": "field and value required"}
    profile = _load_profile(owner_id)
    profile[field] = value
    _save_profile(owner_id, profile)
    return {"ok": True, "field": field, "value": value}

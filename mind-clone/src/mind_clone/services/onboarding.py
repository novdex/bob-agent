"""
Onboarding wizard — guides new users through initial setup.

Tracks onboarding progress per user and provides step-by-step
configuration prompts. The wizard is triggered on first /start
and can be replayed with /onboard.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.models import User
from ..utils import truncate_text, utc_now_iso

logger = logging.getLogger("mind_clone.onboarding")

# Onboarding steps (ordered)
ONBOARDING_STEPS = [
    {
        "key": "welcome",
        "title": "Welcome",
        "prompt": (
            "Welcome to Mind Clone Agent! I'm your autonomous AI assistant.\n\n"
            "I can help with research, task automation, writing, coding, and more.\n"
            "Let me walk you through a quick setup."
        ),
    },
    {
        "key": "name",
        "title": "Your Name",
        "prompt": (
            "What should I call you? You can tell me your name or a nickname.\n"
            "(Type your name, or 'skip' to use your username)"
        ),
    },
    {
        "key": "interests",
        "title": "Your Interests",
        "prompt": (
            "What topics are you most interested in? This helps me prioritize "
            "research and suggestions.\n\n"
            "Examples: programming, crypto, science, business, creative writing\n"
            "(Type a few topics separated by commas, or 'skip')"
        ),
    },
    {
        "key": "tools",
        "title": "Tool Preferences",
        "prompt": (
            "Which capabilities would you like enabled?\n\n"
            "1. Web search & research (default: on)\n"
            "2. File reading & writing (default: on)\n"
            "3. Code execution (default: off)\n"
            "4. Browser automation (default: off)\n\n"
            "Type the numbers you want enabled (e.g. '1,2,3'), or 'default' for defaults."
        ),
    },
    {
        "key": "complete",
        "title": "Setup Complete",
        "prompt": (
            "You're all set! Here's what I can do:\n\n"
            "- Just message me naturally — I'll figure out what you need\n"
            "- Use /task to create background tasks\n"
            "- Use /status to check system health\n"
            "- Use /help for all commands\n\n"
            "Let's get started! What can I help you with?"
        ),
    },
]


def get_onboarding_state(db: Session, owner_id: int) -> Dict[str, Any]:
    """Get the current onboarding state for a user."""
    user = db.query(User).filter(User.id == owner_id).first()
    if not user:
        return {"completed": False, "current_step": 0, "step_key": "welcome"}

    # Check if onboarding metadata exists
    meta = {}
    if hasattr(user, "meta_json") and user.meta_json:
        try:
            meta = json.loads(user.meta_json)
        except Exception:
            meta = {}

    onboarding = meta.get("onboarding", {})
    completed = onboarding.get("completed", False)
    current_step = int(onboarding.get("current_step", 0))

    if current_step >= len(ONBOARDING_STEPS):
        completed = True
        current_step = len(ONBOARDING_STEPS) - 1

    step = ONBOARDING_STEPS[current_step]
    return {
        "completed": completed,
        "current_step": current_step,
        "step_key": step["key"],
        "step_title": step["title"],
        "step_prompt": step["prompt"],
        "total_steps": len(ONBOARDING_STEPS),
        "responses": onboarding.get("responses", {}),
    }


def advance_onboarding(
    db: Session, owner_id: int, response: str = ""
) -> Dict[str, Any]:
    """Process user response and advance to the next onboarding step."""
    user = db.query(User).filter(User.id == owner_id).first()
    if not user:
        return {"ok": False, "error": "User not found"}

    meta = {}
    if hasattr(user, "meta_json") and user.meta_json:
        try:
            meta = json.loads(user.meta_json)
        except Exception:
            meta = {}

    onboarding = meta.get("onboarding", {})
    current_step = int(onboarding.get("current_step", 0))
    responses = onboarding.get("responses", {})

    # Record the response for the current step
    if current_step < len(ONBOARDING_STEPS):
        step_key = ONBOARDING_STEPS[current_step]["key"]
        if response.strip().lower() != "skip" and response.strip():
            responses[step_key] = truncate_text(response.strip(), 500)

    # Advance
    current_step += 1
    completed = current_step >= len(ONBOARDING_STEPS)

    onboarding["current_step"] = current_step
    onboarding["completed"] = completed
    onboarding["responses"] = responses
    if completed:
        onboarding["completed_at"] = utc_now_iso()

    meta["onboarding"] = onboarding

    if hasattr(user, "meta_json"):
        user.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()

    # Return next step info
    if completed:
        step = ONBOARDING_STEPS[-1]
    else:
        step = ONBOARDING_STEPS[current_step]

    return {
        "ok": True,
        "completed": completed,
        "current_step": current_step,
        "step_key": step["key"],
        "step_prompt": step["prompt"],
    }


def reset_onboarding(db: Session, owner_id: int) -> Dict[str, Any]:
    """Reset onboarding state to start fresh."""
    user = db.query(User).filter(User.id == owner_id).first()
    if not user:
        return {"ok": False, "error": "User not found"}

    meta = {}
    if hasattr(user, "meta_json") and user.meta_json:
        try:
            meta = json.loads(user.meta_json)
        except Exception:
            meta = {}

    meta["onboarding"] = {"current_step": 0, "completed": False, "responses": {}}

    if hasattr(user, "meta_json"):
        user.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()

    return {"ok": True, "message": "Onboarding reset"}

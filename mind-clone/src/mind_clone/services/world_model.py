"""
World Model — Bob's mental model of your environment.

Bob tracks the state of things that matter:
- Active projects and their status
- Recent events and what they mean
- Predictions about what you'll need next
- Context that carries across sessions

Stored in DB, injected into context.
Updated after each conversation.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from ..database.models import User
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.world_model")

_DEFAULT_WORLD = {
    "projects": {
        "Bob AGI Platform": {
            "status": "active development",
            "location": "C:/projects/ai-agent-platform/mind-clone/",
            "recent_work": "building 15+ intelligence features",
            "next_steps": ["test all features", "merge to main branch"],
        }
    },
    "environment": {
        "os": "Windows 11",
        "python": "3.14",
        "bob_port": 8000,
        "branch": "agent/test",
    },
    "recent_events": [],
    "predictions": [],
    "last_updated": None,
}


def _load_world(owner_id: int) -> dict:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if user and user.meta_json:
            data = json.loads(user.meta_json or "{}")
            world = data.get("world_model", {})
            if world:
                return {**_DEFAULT_WORLD, **world}
        return dict(_DEFAULT_WORLD)
    except Exception:
        return dict(_DEFAULT_WORLD)
    finally:
        db.close()


def _save_world(owner_id: int, world: dict) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if not user:
            return
        existing = json.loads(user.meta_json or "{}")
        world["last_updated"] = datetime.now(timezone.utc).isoformat()
        existing["world_model"] = world
        user.meta_json = json.dumps(existing, ensure_ascii=False)
        db.commit()
    except Exception as e:
        logger.error("WORLD_MODEL_SAVE_FAIL: %s", e)
        db.rollback()
    finally:
        db.close()


def get_world_context_block(owner_id: int) -> str:
    """Return world model context as a string block."""
    try:
        world = _load_world(owner_id)
        projects = world.get("projects", {})
        proj_summary = "; ".join(
            f"{name}: {info.get('status','?')}" for name, info in list(projects.items())[:3]
        )
        events = world.get("recent_events", [])[-3:]
        lines = [f"[WORLD MODEL] Projects: {proj_summary}"]
        if events:
            lines.append(f"Recent events: {'; '.join(str(e) for e in events)}")
        return "\n".join(lines)
    except Exception:
        return ""


def inject_world_context(owner_id: int, messages: list) -> None:
    """Inject world model state into messages."""
    try:
        world = _load_world(owner_id)
        projects = world.get("projects", {})
        proj_summary = "; ".join(
            f"{name}: {info.get('status','?')}" for name, info in list(projects.items())[:3]
        )
        events = world.get("recent_events", [])[-3:]
        lines = [f"[WORLD MODEL] Projects: {proj_summary}"]
        if events:
            lines.append(f"Recent events: {'; '.join(str(e) for e in events)}")
        predictions = world.get("predictions", [])[:2]
        if predictions:
            lines.append(f"Predicted needs: {'; '.join(str(p) for p in predictions)}")
        messages.append({"role": "system", "content": "\n".join(lines)})
    except Exception as e:
        logger.debug("WORLD_MODEL_INJECT_SKIP: %s", str(e)[:80])


def update_world_from_turn(owner_id: int, user_message: str, response: str) -> None:
    """Update world model based on conversation turn."""
    import threading
    def _run():
        try:
            from ..agent.llm import call_llm
            world = _load_world(owner_id)
            prompt = [{
                "role": "user",
                "content": (
                    f"Update this world model JSON based on the conversation.\n"
                    f"Current model: {json.dumps(world)[:800]}\n\n"
                    f"User: {user_message[:150]}\nAgent: {response[:150]}\n\n"
                    f"Update only if new factual info was shared (project status changes, "
                    f"new events, completed tasks). Return the complete updated JSON. "
                    f"Add to recent_events if something notable happened. Keep it brief."
                ),
            }]
            result = call_llm(prompt, temperature=0.1)
            content = ""
            if isinstance(result, dict) and result.get("ok"):
                content = result.get("content", "")
                choices = result.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", content)
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                updated = json.loads(match.group())
                if isinstance(updated, dict) and "projects" in updated:
                    # Keep recent_events short
                    events = updated.get("recent_events", [])
                    updated["recent_events"] = events[-10:]
                    _save_world(owner_id, updated)
        except Exception as e:
            logger.debug("WORLD_UPDATE_FAIL: %s", str(e)[:80])
    threading.Thread(target=_run, daemon=True).start()


def tool_get_world_model(args: dict) -> dict:
    """Tool: Get Bob's current world model."""
    owner_id = int(args.get("_owner_id", 1))
    return {"ok": True, "world": _load_world(owner_id)}


def tool_update_world(args: dict) -> dict:
    """Tool: Update a field in Bob's world model."""
    owner_id = int(args.get("_owner_id", 1))
    section = str(args.get("section", "")).strip()
    key = str(args.get("key", "")).strip()
    value = args.get("value")
    if not section or not key or value is None:
        return {"ok": False, "error": "section, key, value required"}
    world = _load_world(owner_id)
    if section not in world:
        world[section] = {}
    if isinstance(world[section], dict):
        world[section][key] = value
    _save_world(owner_id, world)
    return {"ok": True, "section": section, "key": key, "value": value}

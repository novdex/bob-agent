"""
Voyager-style Skill Library tools.

Allows Bob to save completed tasks as reusable named skills,
recall similar skills before starting a task, and manage his
growing library of solved problems.
"""

from __future__ import annotations

import json
import logging

from ..database.session import SessionLocal
from ..database.models import SkillProfile, SkillVersion
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.tools.skill_library")

_MAX_BODY = 4000
_MAX_TITLE = 120
_MAX_QUERY = 500


def _get_skill_service():
    """Lazy import to avoid circular imports at module load time."""
    from ..services.skills import (
        save_skill_profile,
        list_skill_profiles,
        skill_profile_detail,
        set_skill_status,
        select_active_skills_for_prompt,
        _safe_skill_hints,
        _normalize_key,
    )
    return (
        save_skill_profile,
        list_skill_profiles,
        skill_profile_detail,
        set_skill_status,
        select_active_skills_for_prompt,
        _safe_skill_hints,
        _normalize_key,
    )


def tool_save_skill(args: dict) -> dict:
    """Save a completed task as a reusable skill in Bob's Voyager-style library.

    Call this AFTER successfully completing any non-trivial task so Bob
    can reuse the approach next time a similar request comes up.

    Args:
        title: Short descriptive name for the skill (required)
        body: Step-by-step instructions / approach that worked (required)
        trigger_hints: List of keywords/phrases that should trigger this skill
        skill_key: Optional unique key (auto-generated from title if omitted)
        intent: One-sentence description of what this skill accomplishes
        source: "task_completion" | "manual" | "research" (default: task_completion)
    """
    owner_id = int(args.get("_owner_id", 1))
    title = str(args.get("title", "")).strip()
    body = str(args.get("body", "")).strip()

    if not title:
        return {"ok": False, "error": "title is required"}
    if not body:
        return {"ok": False, "error": "body is required"}

    title = truncate_text(title, _MAX_TITLE)
    body = truncate_text(body, _MAX_BODY)

    (save_skill_profile, _, _, _, _, _safe_skill_hints, _normalize_key) = _get_skill_service()

    raw_hints = args.get("trigger_hints", [])
    if isinstance(raw_hints, str):
        raw_hints = [h.strip() for h in raw_hints.split(",") if h.strip()]
    trigger_hints = _safe_skill_hints(raw_hints)

    if not trigger_hints:
        trigger_hints = [w for w in title.lower().split() if len(w) > 3][:8]

    skill_key = str(args.get("skill_key", "")).strip()
    if not skill_key:
        skill_key = _normalize_key(title)

    intent = str(args.get("intent", "")).strip() or title
    source = str(args.get("source", "task_completion")).strip()

    db = SessionLocal()
    try:
        profile, version = save_skill_profile(
            db,
            owner_id=owner_id,
            skill_key=skill_key,
            title=title,
            body_text=body,
            intent=intent,
            trigger_hints=trigger_hints,
            source_type=source,
            auto_created=(source != "manual"),
            metadata={"saved_by": "tool_save_skill", "source": source},
        )
        return {
            "ok": True,
            "skill_id": profile.id,
            "skill_key": profile.skill_key,
            "title": profile.title,
            "version": version.version,
            "trigger_hints": trigger_hints,
            "message": f"Skill '{title}' saved (key={profile.skill_key}, v{version.version})",
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("tool_save_skill error: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


def tool_recall_skill(args: dict) -> dict:
    """Search Bob's skill library for relevant past approaches before starting a task.

    Call this at the START of any complex task — Bob may have solved something
    similar before and can reuse that approach.

    Args:
        query: Description of the task you're about to do (required)
        top_k: Max number of skills to return (default: 3)
    """
    owner_id = int(args.get("_owner_id", 1))
    query = str(args.get("query", "")).strip()
    top_k = min(int(args.get("top_k", 3)), 10)

    if not query:
        return {"ok": False, "error": "query is required"}

    query = truncate_text(query, _MAX_QUERY)

    (_, _, _, _, select_active_skills_for_prompt, _, _) = _get_skill_service()

    db = SessionLocal()
    try:
        blocks = select_active_skills_for_prompt(db, owner_id, query, top_k=top_k)
        if not blocks:
            return {
                "ok": True,
                "found": 0,
                "skills": [],
                "message": "No matching skills found. This might be a new type of task.",
            }
        return {
            "ok": True,
            "found": len(blocks),
            "skills": blocks,
            "message": f"Found {len(blocks)} relevant skill(s) from past experience.",
        }
    except Exception as e:
        logger.error("tool_recall_skill error: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


def tool_list_skills(args: dict) -> dict:
    """List all skills in Bob's library.

    Args:
        status: "active" | "archived" | "all" (default: active)
        limit: Max number to return (default: 20)
    """
    owner_id = int(args.get("_owner_id", 1))
    status_filter = str(args.get("status", "active")).strip()
    limit = min(int(args.get("limit", 20)), 100)

    (_, list_skill_profiles, _, _, _, _, _) = _get_skill_service()

    db = SessionLocal()
    try:
        if status_filter == "all":
            skills = list_skill_profiles(db, owner_id, status=None, limit=limit)
        else:
            skills = list_skill_profiles(db, owner_id, status=status_filter, limit=limit)

        result = []
        for s in skills:
            try:
                hints = json.loads(s.trigger_hints_json or "[]")
            except Exception:
                hints = []
            result.append({
                "id": s.id,
                "skill_key": s.skill_key,
                "title": s.title,
                "status": s.status,
                "version": s.active_version,
                "usage_count": s.usage_count or 0,
                "source_type": s.source_type,
                "trigger_hints": hints[:5],
                "created_at": str(s.created_at)[:19] if s.created_at else None,
            })

        return {"ok": True, "total": len(result), "skills": result}
    except Exception as e:
        logger.error("tool_list_skills error: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


def tool_get_skill(args: dict) -> dict:
    """Get full details of a specific skill including its body/instructions.

    Args:
        skill_id: The numeric ID of the skill (required)
    """
    owner_id = int(args.get("_owner_id", 1))
    skill_id = args.get("skill_id")
    if skill_id is None:
        return {"ok": False, "error": "skill_id is required"}
    try:
        skill_id = int(skill_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "skill_id must be an integer"}

    (_, _, skill_profile_detail, _, _, _, _) = _get_skill_service()

    db = SessionLocal()
    try:
        profile, versions = skill_profile_detail(db, skill_id)
        if not profile or profile.owner_id != owner_id:
            return {"ok": False, "error": f"Skill {skill_id} not found"}

        active_ver = next(
            (v for v in versions if v.version == profile.active_version), None
        )
        try:
            hints = json.loads(profile.trigger_hints_json or "[]")
        except Exception:
            hints = []

        return {
            "ok": True,
            "id": profile.id,
            "skill_key": profile.skill_key,
            "title": profile.title,
            "intent": profile.intent or "",
            "status": profile.status,
            "active_version": profile.active_version,
            "latest_version": profile.latest_version,
            "usage_count": profile.usage_count or 0,
            "source_type": profile.source_type,
            "trigger_hints": hints,
            "body": active_ver.body_text if active_ver else "",
            "versions_count": len(versions),
        }
    except Exception as e:
        logger.error("tool_get_skill error: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


def tool_archive_skill(args: dict) -> dict:
    """Archive a skill so it no longer gets matched (kept in history).

    Args:
        skill_id: The numeric ID of the skill to archive (required)
    """
    owner_id = int(args.get("_owner_id", 1))
    skill_id = args.get("skill_id")
    if skill_id is None:
        return {"ok": False, "error": "skill_id is required"}
    try:
        skill_id = int(skill_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "skill_id must be an integer"}

    (_, _, _, set_skill_status, _, _, _) = _get_skill_service()

    db = SessionLocal()
    try:
        profile = db.query(SkillProfile).filter(
            SkillProfile.id == skill_id,
            SkillProfile.owner_id == owner_id,
        ).first()
        if not profile:
            return {"ok": False, "error": f"Skill {skill_id} not found"}
        set_skill_status(db, skill_id, "archived")
        return {
            "ok": True,
            "skill_id": skill_id,
            "title": profile.title,
            "message": f"Skill '{profile.title}' archived.",
        }
    except Exception as e:
        logger.error("tool_archive_skill error: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()

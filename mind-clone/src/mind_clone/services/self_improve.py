"""
Self-Improvement Engine — Bob fixes his own code.

When Bob runs his retro and finds a bug or gap, instead of just
noting it in SelfImprovementNote, he can now actually fix it:

1. Reads the top open SelfImprovementNote
2. Uses codebase_search to find the relevant code
3. Uses the agent loop with codebase_edit to patch it
4. Runs tests to verify the fix
5. Commits if tests pass
6. Updates the SelfImprovementNote to "resolved"

This closes the self-improvement loop completely.
Called by the `self_improve` tool Bob can invoke.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from ..database.session import SessionLocal
from ..database.models import SelfImprovementNote
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.self_improve")

SELF_IMPROVE_ENABLED: bool = os.getenv("SELF_IMPROVE_ENABLED", "true").lower() in {"1", "true", "yes"}
BOB_CODEBASE_PATH = os.getenv("BOB_CODEBASE_PATH", r"C:\projects\ai-agent-platform\mind-clone")


def get_top_improvement_opportunity(owner_id: int) -> Optional[Dict[str, Any]]:
    """Get the highest priority open SelfImprovementNote."""
    db = SessionLocal()
    try:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        notes = (
            db.query(SelfImprovementNote)
            .filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.status == "open",
            )
            .order_by(SelfImprovementNote.created_at.desc())
            .limit(20)
            .all()
        )
        if not notes:
            return None

        notes.sort(key=lambda n: priority_order.get(n.priority, 1))
        n = notes[0]

        import json
        actions = []
        try:
            actions = json.loads(n.actions_json or "[]")
        except Exception:
            pass

        return {
            "id": n.id,
            "title": n.title,
            "summary": n.summary,
            "actions": actions,
            "priority": n.priority,
        }
    finally:
        db.close()


def mark_note_resolved(note_id: int, resolution: str) -> bool:
    """Mark a SelfImprovementNote as resolved."""
    db = SessionLocal()
    try:
        note = db.query(SelfImprovementNote).filter(SelfImprovementNote.id == note_id).first()
        if not note:
            return False
        note.status = "resolved"
        note.summary = note.summary + f"\n\n[RESOLVED] {truncate_text(resolution, 300)}"
        db.commit()
        logger.info("SELF_IMPROVE_RESOLVED note_id=%d", note_id)
        return True
    except Exception as e:
        db.rollback()
        logger.warning("SELF_IMPROVE_MARK_FAIL: %s", str(e)[:200])
        return False
    finally:
        db.close()


def build_self_improve_prompt(opportunity: Dict[str, Any]) -> str:
    """Build a prompt for Bob to attempt self-improvement."""
    actions_str = "\n".join(f"  - {a}" for a in opportunity.get("actions", [])[:3])
    return f"""You have identified this improvement opportunity in yourself:

Title: {opportunity['title']}
Priority: {opportunity['priority']}
Summary: {opportunity['summary'][:500]}

Suggested actions:
{actions_str or '  - Review and fix the underlying issue'}

Your task:
1. Use `codebase_search` to find the relevant code in your own codebase at {BOB_CODEBASE_PATH}
2. Analyse the issue
3. Use `codebase_edit` or `codebase_write` to fix it
4. Use `codebase_run_tests` to verify the fix doesn't break anything
5. Use `git_commit` to commit if tests pass
6. Report what you fixed

Be careful. Only make targeted, minimal changes. Do not refactor broadly.
If you cannot safely fix it, explain why and what would be needed."""


def tool_self_improve(args: dict) -> dict:
    """Tool: Bob attempts to fix his top self-improvement opportunity."""
    if not SELF_IMPROVE_ENABLED:
        return {"ok": False, "error": "Self-improvement disabled"}

    owner_id = int(args.get("_owner_id", 1))

    opportunity = get_top_improvement_opportunity(owner_id)
    if not opportunity:
        return {"ok": True, "message": "No open improvement opportunities found. Bob is in good shape."}

    prompt = build_self_improve_prompt(opportunity)

    # Run through the agent loop so Bob can use his codebase tools
    try:
        from ..agent.loop import run_agent_loop
        result = run_agent_loop(owner_id, prompt)
        return {
            "ok": True,
            "opportunity": opportunity["title"],
            "result": truncate_text(result, 1000),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

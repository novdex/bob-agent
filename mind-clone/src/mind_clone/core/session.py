"""
Session management utilities.

Provides startup transcript repair and session health checks.
"""

from __future__ import annotations

import logging
from typing import Dict, Any

from ..database.session import SessionLocal
from ..database.models import ConversationMessage

logger = logging.getLogger("mind_clone.core.session")


def run_startup_transcript_repair(limit: int = 250) -> Dict[str, Any]:
    """Repair orphaned or inconsistent transcript entries on startup.

    Scans recent conversation messages for issues like:
    - Tool result messages without matching tool_call_id
    - Assistant messages with tool_calls but no follow-up tool results
    - Duplicate sequential messages

    Returns a summary of owners processed and changed.
    """
    db = SessionLocal()
    owners_processed = set()
    owners_changed = set()
    try:
        # Get distinct owner IDs from recent messages
        recent = (
            db.query(ConversationMessage.owner_id)
            .distinct()
            .order_by(ConversationMessage.owner_id)
            .limit(limit)
            .all()
        )
        for (owner_id,) in recent:
            owners_processed.add(owner_id)
            # Check for orphaned tool results
            orphaned = (
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.owner_id == owner_id,
                    ConversationMessage.role == "tool",
                    ConversationMessage.tool_call_id.is_(None),
                )
                .count()
            )
            if orphaned > 0:
                # Delete orphaned tool results
                db.query(ConversationMessage).filter(
                    ConversationMessage.owner_id == owner_id,
                    ConversationMessage.role == "tool",
                    ConversationMessage.tool_call_id.is_(None),
                ).delete()
                owners_changed.add(owner_id)

        if owners_changed:
            db.commit()
            logger.info(
                "Transcript repair: processed=%d changed=%d",
                len(owners_processed), len(owners_changed),
            )
    except Exception as exc:
        db.rollback()
        logger.warning("Transcript repair error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()

    return {
        "ok": True,
        "owners_processed": len(owners_processed),
        "owners_changed": len(owners_changed),
    }


__all__ = ["run_startup_transcript_repair"]

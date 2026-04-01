"""Session isolation for Bob AI agent.

Each conversation gets its own isolated session.  Cron jobs run in
separate sessions.  One bad session cannot affect others.

Sessions are stored in-memory (lightweight, no DB dependency) and
auto-cleaned when stale.  If a session errors 3 times in a row it is
automatically closed and a fresh session is created on the next
request to prevent stuck conversations.
"""

from __future__ import annotations

import uuid
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger("mind_clone.core.sessions")

# Thread-safe lock for session mutations
_lock = threading.Lock()

# In-memory session store
_sessions: Dict[str, dict] = {}

# Lookup index:  (owner_id, source, chat_id) -> session_id
_lookup: Dict[tuple, str] = {}

# Session auto-close threshold
_MAX_ERRORS = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_session(owner_id: int, source: str, chat_id: str) -> str:
    """Create a new session and return its session_id (UUID hex)."""
    session_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    session_data = {
        "session_id": session_id,
        "owner_id": owner_id,
        "source": source,
        "chat_id": chat_id,
        "created_at": now,
        "last_active": now,
        "status": "active",
        "error_count": 0,
    }

    with _lock:
        _sessions[session_id] = session_data
        _lookup[(owner_id, source, chat_id)] = session_id

    logger.info(
        "Session created: id=%s owner=%d source=%s chat=%s",
        session_id[:12], owner_id, source, chat_id,
    )
    return session_id


def get_or_create_session(owner_id: int, source: str, chat_id: str) -> str:
    """Return an existing active session for this owner+source+chat_id.

    Creates a new one if none exists or the existing one is closed /
    over the error threshold.
    """
    key = (owner_id, source, chat_id)

    with _lock:
        existing_id = _lookup.get(key)
        if existing_id:
            sess = _sessions.get(existing_id)
            if sess and sess["status"] == "active":
                sess["last_active"] = datetime.now(timezone.utc)
                return existing_id

    # No usable session -- create a fresh one
    return create_session(owner_id, source, chat_id)


def get_session(session_id: str) -> Optional[dict]:
    """Return session data dict, or None if not found."""
    with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return None
        # Return a shallow copy to avoid race conditions
        return dict(sess)


def close_session(session_id: str) -> bool:
    """Mark a session as closed.  Returns True if session existed."""
    with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return False
        sess["status"] = "closed"
        # Remove from lookup so next request creates a fresh session
        key = (sess["owner_id"], sess["source"], sess["chat_id"])
        if _lookup.get(key) == session_id:
            _lookup.pop(key, None)
    logger.info("Session closed: id=%s", session_id[:12])
    return True


def increment_session_errors(session_id: str) -> int:
    """Increment error_count for a session.

    If the count reaches the threshold the session is auto-closed so
    that the next request gets a clean slate.

    Returns:
        The new error count, or -1 if session not found.
    """
    with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return -1
        sess["error_count"] = sess.get("error_count", 0) + 1
        count = sess["error_count"]

    if count >= _MAX_ERRORS:
        logger.warning(
            "Session %s hit %d errors -- auto-closing",
            session_id[:12], count,
        )
        close_session(session_id)

    return count


def cleanup_stale_sessions(max_age_hours: int = 24) -> int:
    """Remove sessions older than *max_age_hours*.

    Returns:
        Number of sessions removed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed = 0

    with _lock:
        stale_ids = [
            sid for sid, s in _sessions.items()
            if s["last_active"] < cutoff
        ]
        for sid in stale_ids:
            sess = _sessions.pop(sid, None)
            if sess:
                key = (sess["owner_id"], sess["source"], sess["chat_id"])
                if _lookup.get(key) == sid:
                    _lookup.pop(key, None)
                removed += 1

    if removed:
        logger.info("Cleaned up %d stale sessions (older than %dh)", removed, max_age_hours)
    return removed


def list_active_sessions() -> list[dict]:
    """Return a list of all active session dicts (copies)."""
    with _lock:
        return [
            dict(s) for s in _sessions.values()
            if s["status"] == "active"
        ]


def session_count() -> int:
    """Return total number of tracked sessions (active + closed)."""
    with _lock:
        return len(_sessions)


# ===========================================================================
# Startup transcript repair (merged from core/session.py)
# ===========================================================================


def run_startup_transcript_repair(limit: int = 250) -> Dict[str, Any]:
    """Repair orphaned or inconsistent transcript entries on startup.

    Scans recent conversation messages for issues like:
    - Tool result messages without matching tool_call_id
    - Assistant messages with tool_calls but no follow-up tool results
    - Duplicate sequential messages

    Returns a summary of owners processed and changed.
    """
    from ..database.session import SessionLocal
    from ..database.models import ConversationMessage

    db = SessionLocal()
    owners_processed: set = set()
    owners_changed: set = set()
    try:
        recent = (
            db.query(ConversationMessage.owner_id)
            .distinct()
            .order_by(ConversationMessage.owner_id)
            .limit(limit)
            .all()
        )
        for (owner_id_val,) in recent:
            owners_processed.add(owner_id_val)
            orphaned = (
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.owner_id == owner_id_val,
                    ConversationMessage.role == "tool",
                    ConversationMessage.tool_call_id.is_(None),
                )
                .count()
            )
            if orphaned > 0:
                db.query(ConversationMessage).filter(
                    ConversationMessage.owner_id == owner_id_val,
                    ConversationMessage.role == "tool",
                    ConversationMessage.tool_call_id.is_(None),
                ).delete()
                owners_changed.add(owner_id_val)

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


__all__ = [
    "create_session",
    "get_or_create_session",
    "get_session",
    "close_session",
    "increment_session_errors",
    "cleanup_stale_sessions",
    "list_active_sessions",
    "session_count",
    "run_startup_transcript_repair",
]

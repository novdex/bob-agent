"""
Conversation memory management for Mind Clone Agent.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database.models import ConversationMessage, ConversationSummary
from ..utils import truncate_text, utc_now_iso
from ..config import settings

logger = logging.getLogger("mind_clone.agent.memory")


def get_conversation_history(
    db: Session,
    owner_id: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Get recent conversation history for an owner (transcript-locked)."""
    from ..core.state import session_write_lock

    with session_write_lock(owner_id, reason="history_load"):
        rows = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.owner_id == owner_id)
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
            .all()
        )

    # Reverse to get chronological order
    rows = list(reversed(rows))

    messages = []
    for row in rows:
        msg = {
            "role": row.role,
            "content": row.content,
        }
        if row.tool_call_id:
            msg["tool_call_id"] = row.tool_call_id
        if row.tool_calls_json:
            try:
                msg["tool_calls"] = json.loads(row.tool_calls_json)
            except json.JSONDecodeError:
                pass
        messages.append(msg)

    return messages


def save_message(
    db: Session,
    owner_id: int,
    role: str,
    content: str,
    tool_call_id: Optional[str] = None,
    tool_calls: Optional[List[Dict]] = None,
) -> ConversationMessage:
    """Save a conversation message (transcript-locked)."""
    from ..core.state import session_write_lock

    tool_calls_json = None
    if tool_calls:
        tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)

    with session_write_lock(owner_id, reason="message_save"):
        msg = ConversationMessage(
            owner_id=owner_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_calls_json=tool_calls_json,
        )
        db.add(msg)
        db.commit()
    return msg


def save_user_message(db: Session, owner_id: int, content: str) -> ConversationMessage:
    """Save a user message."""
    return save_message(db, owner_id, "user", content)


def save_assistant_message(
    db: Session,
    owner_id: int,
    content: str,
    tool_calls: Optional[List[Dict]] = None,
) -> ConversationMessage:
    """Save an assistant message."""
    return save_message(db, owner_id, "assistant", content, tool_calls=tool_calls)


def save_tool_result(
    db: Session,
    owner_id: int,
    tool_call_id: str,
    content: str,
) -> ConversationMessage:
    """Save a tool result."""
    return save_message(db, owner_id, "tool", content, tool_call_id=tool_call_id)


def count_messages(db: Session, owner_id: int) -> int:
    """Count total messages for an owner."""
    return db.query(ConversationMessage).filter(
        ConversationMessage.owner_id == owner_id
    ).count()


def clear_conversation_history(db: Session, owner_id: int) -> int:
    """Clear all conversation history for an owner (transcript-locked). Returns count deleted."""
    from ..core.state import session_write_lock

    with session_write_lock(owner_id, reason="history_clear"):
        count = db.query(ConversationMessage).filter(
            ConversationMessage.owner_id == owner_id
        ).delete()
        db.commit()
    return count


def create_conversation_summary(
    db: Session,
    owner_id: int,
    start_message_id: int,
    end_message_id: int,
    summary: str,
    key_points: Optional[List[str]] = None,
    open_loops: Optional[List[str]] = None,
) -> ConversationSummary:
    """Create a summary of a conversation chunk."""
    summary_obj = ConversationSummary(
        owner_id=owner_id,
        start_message_id=start_message_id,
        end_message_id=end_message_id,
        summary=summary,
        key_points_json=json.dumps(key_points or [], ensure_ascii=False),
        open_loops_json=json.dumps(open_loops or [], ensure_ascii=False),
    )
    db.add(summary_obj)
    db.commit()
    return summary_obj


def get_conversation_summaries(
    db: Session,
    owner_id: int,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get recent conversation summaries."""
    rows = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.owner_id == owner_id)
        .order_by(ConversationSummary.id.desc())
        .limit(limit)
        .all()
    )
    
    summaries = []
    for row in rows:
        try:
            key_points = json.loads(row.key_points_json or "[]")
            open_loops = json.loads(row.open_loops_json or "[]")
        except json.JSONDecodeError:
            key_points = []
            open_loops = []
        
        summaries.append({
            "summary": row.summary,
            "key_points": key_points,
            "open_loops": open_loops,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    
    return summaries


def prepare_messages_for_llm(
    db: Session,
    owner_id: int,
    recent_limit: int = 30,
) -> List[Dict[str, Any]]:
    """Prepare messages for LLM context window."""
    messages = get_conversation_history(db, owner_id, limit=recent_limit)
    
    # Add system message at start
    system_msg = {
        "role": "system",
        "content": "You are Mind Clone, a sovereign AI agent. Use tools as needed.",
    }
    
    return [system_msg] + messages


def store_lesson(
    db: Session,
    owner_id: int,
    lesson: str,
    context: str = "",
) -> bool:
    """Store a lesson as a MemoryVector entry."""
    from ..database.models import MemoryVector

    text = truncate_text(str(lesson or "").strip(), 800)
    if not text:
        return False
    try:
        row = MemoryVector(
            owner_id=owner_id,
            memory_type="lesson",
            text_preview=text,
            embedding=b"\x00",  # placeholder — real embeddings added by reindex
        )
        db.add(row)
        db.commit()
        return True
    except Exception as exc:
        logger.warning("store_lesson failed owner=%d: %s", owner_id, exc)
        db.rollback()
        return False


def reindex_owner_memory_vectors(owner_id: int, rebuild_lessons: bool = False) -> dict:
    """Re-index memory vectors for an owner (placeholder — no vector engine yet)."""
    from ..database.session import SessionLocal as _SL
    from ..database.models import MemoryVector

    db = _SL()
    try:
        count = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id).count()
        return {"ok": True, "owner_id": owner_id, "vectors": count, "reindexed": 0}
    finally:
        db.close()


def list_context_snapshots(owner_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """List conversation summaries as context snapshots."""
    from ..database.session import SessionLocal as _SL

    db = _SL()
    try:
        return get_conversation_summaries(db, owner_id, limit=limit)
    finally:
        db.close()


def get_context_snapshot(owner_id: int, snapshot_id: int) -> Optional[Dict[str, Any]]:
    """Get a single conversation summary by ID."""
    from ..database.session import SessionLocal as _SL

    db = _SL()
    try:
        row = db.query(ConversationSummary).filter(
            ConversationSummary.id == snapshot_id,
            ConversationSummary.owner_id == owner_id,
        ).first()
        if not row:
            return None
        try:
            key_points = json.loads(row.key_points_json or "[]")
            open_loops = json.loads(row.open_loops_json or "[]")
        except json.JSONDecodeError:
            key_points, open_loops = [], []
        return {
            "id": row.id,
            "summary": row.summary,
            "key_points": key_points,
            "open_loops": open_loops,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    finally:
        db.close()


def trim_context_window(
    messages: List[Dict[str, Any]],
    max_chars: int = 42000,
) -> List[Dict[str, Any]]:
    """Trim messages to fit within character budget."""
    if not messages:
        return messages
    
    # Keep system message
    system_msg = None
    other_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg
        else:
            other_msgs.append(msg)
    
    # Calculate total length
    total_chars = sum(len(str(msg.get("content", ""))) for msg in messages)
    
    if total_chars <= max_chars:
        return messages
    
    # Remove older messages until under budget
    result = [system_msg] if system_msg else []
    current_chars = len(str(system_msg.get("content", ""))) if system_msg else 0
    
    # Add messages from most recent
    for msg in reversed(other_msgs):
        msg_chars = len(str(msg.get("content", "")))
        if current_chars + msg_chars > max_chars:
            break
        result.append(msg)
        current_chars += msg_chars
    
    # Reverse to maintain order
    result = [m for m in [system_msg] if m] + list(reversed([m for m in result if m.get("role") != "system"]))
    
    return result

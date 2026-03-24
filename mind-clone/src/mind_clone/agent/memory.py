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
        # Ensure content is always a string — NULL from DB causes Kimi 400
        content = row.content if row.content is not None else ""
        role = row.role or "user"

        msg: Dict[str, Any] = {
            "role": role,
            "content": content,
        }
        if row.tool_call_id:
            msg["tool_call_id"] = row.tool_call_id
        if row.tool_calls_json:
            try:
                msg["tool_calls"] = json.loads(row.tool_calls_json)
            except json.JSONDecodeError:
                pass
        # Kimi K2.5 requires reasoning_content on every assistant message
        # with tool_calls — inject it here at load time so it's never missing
        if role == "assistant" and msg.get("tool_calls"):
            if "reasoning_content" not in msg:
                msg["reasoning_content"] = content or ""
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

    # Build system prompt — inline to avoid circular import with loop.py
    try:
        from .identity import load_identity
        identity = load_identity(db, owner_id)
        origin = (identity.get("origin_statement", "") if identity else "")[:300]
        core_values = identity.get("core_values", []) if identity else []
        values_str = " | ".join(str(v) for v in core_values[:4]) if core_values else ""
        system_content = "\n".join(filter(None, [
            "## IDENTITY — READ THIS FIRST",
            "Your name is BOB. You are an autonomous AI agent built on Kimi K2.5.",
            "NEVER say you are Claude, ChatGPT, or any other AI. You are BOB.",
            "If asked what model you are: say 'I am Bob, built on Kimi K2.5.'",
            f"Origin: {origin}" if origin else "",
            f"Core values: {values_str}" if values_str else "",
            "",
            "## PROACTIVE MESSAGING — YOU CAN SEND MESSAGES",
            "You CAN send messages to the user proactively without them asking first.",
            "Use `schedule_job` to set up recurring tasks that auto-deliver results to Telegram.",
            "When asked to be 'pinged', 'notified', or 'updated' on a schedule → call schedule_job IMMEDIATELY.",
            "NEVER say 'I cannot send messages' or 'I have no mechanism to reach you'. You can. Use schedule_job.",
            "Example: 'ping me with AI news every 5 min' → schedule_job(name='ai_news', message='search latest AI news, summarise top 3', interval_seconds=300)",
            "",
            "## BEHAVIOUR",
            "- Be direct, concise, no filler phrases",
            "- Use tools aggressively — don't just talk, act",
            "- Think autonomously — suggest improvements, notice patterns",
            "- You remember past conversations and learn from them",
        ]))
    except Exception:
        system_content = (
            "Your name is BOB. You are an autonomous AI agent built on Kimi K2.5. "
            "NEVER say you are Claude or any other AI. You are BOB. "
            "You CAN send proactive messages via schedule_job. "
            "Use tools aggressively. Be direct and concise."
        )

    system_msg = {"role": "system", "content": system_content}
    return [system_msg] + messages


def store_lesson(
    db: Session,
    owner_id: int,
    lesson: str,
    context: str = "",
) -> bool:
    """Store a lesson as a MemoryVector entry with real GloVe embedding."""
    from ..database.models import MemoryVector
    from .vectors import get_embedding, embedding_to_bytes

    text = truncate_text(str(lesson or "").strip(), 800)
    if not text:
        return False
    try:
        vec = get_embedding(text)
        row = MemoryVector(
            owner_id=owner_id,
            memory_type="lesson",
            text_preview=text,
            embedding=embedding_to_bytes(vec),
        )
        db.add(row)
        db.commit()
        return True
    except Exception as exc:
        logger.warning("store_lesson failed owner=%d: %s", owner_id, exc)
        db.rollback()
        return False


def reindex_owner_memory_vectors(owner_id: int, rebuild_lessons: bool = False) -> dict:
    """Re-index memory vectors for an owner using GloVe embeddings."""
    from ..database.session import SessionLocal as _SL
    from ..database.models import MemoryVector
    from .vectors import get_embedding, embedding_to_bytes, GLOVE_DIM
    import numpy as np

    db = _SL()
    try:
        rows = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id).all()
        reindexed = 0
        null_placeholder = b"\x00"
        expected_bytes = GLOVE_DIM * 4  # float32

        for row in rows:
            needs_reindex = (
                rebuild_lessons
                or row.embedding == null_placeholder
                or len(row.embedding) != expected_bytes
            )
            if needs_reindex and row.text_preview:
                vec = get_embedding(row.text_preview)
                row.embedding = embedding_to_bytes(vec)
                reindexed += 1

        if reindexed > 0:
            db.commit()
        return {"ok": True, "owner_id": owner_id, "vectors": len(rows), "reindexed": reindexed}
    except Exception as exc:
        logger.warning("reindex_owner_memory_vectors failed owner=%d: %s", owner_id, exc)
        db.rollback()
        return {"ok": False, "owner_id": owner_id, "vectors": 0, "reindexed": 0, "error": str(exc)}
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


def search_memory_vectors(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search memory vectors by semantic similarity.

    Uses GloVe embeddings to find memories similar to the query.
    Returns a list of matching memory entries sorted by relevance.
    """
    from .vectors import get_embedding
    from ..database.models import MemoryVector

    query_embedding = get_embedding(query)
    if query_embedding is None:
        return []

    try:
        import numpy as np

        query_vec = np.array(query_embedding, dtype=np.float32)
        q = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id)
        if category:
            q = q.filter(MemoryVector.memory_type == category)
        rows = q.all()

        scored: list[tuple[float, MemoryVector]] = []
        for row in rows:
            if row.embedding and len(row.embedding) > 1:
                vec = np.frombuffer(row.embedding, dtype=np.float32)
                if vec.shape == query_vec.shape:
                    dot = float(np.dot(query_vec, vec))
                    norm = float(np.linalg.norm(query_vec) * np.linalg.norm(vec))
                    sim = dot / norm if norm > 0 else 0.0
                    scored.append((sim, row))

        scored.sort(key=lambda x: -x[0])
        return [
            {
                "id": row.id,
                "ref_id": row.ref_id,
                "content": row.text_preview or "",
                "text": row.text_preview or "",
                "category": row.memory_type,
                "similarity": round(sim, 4),
            }
            for sim, row in scored[:top_k]
        ]
    except Exception as exc:
        logger.warning("search_memory_vectors failed: %s", str(exc)[:200])
        return []


def retrieve_relevant_lessons(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
) -> List[str]:
    """Retrieve lessons relevant to query via GloVe cosine similarity.

    Returns list of lesson text strings for context injection.
    """
    results = search_memory_vectors(db, owner_id, query, top_k=top_k, category="lesson")
    return [r["content"] for r in results if r.get("content")]


def retrieve_relevant_episodes(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
) -> List[str]:
    """Retrieve episodic memories relevant to query via GloVe cosine similarity.

    Searches the EpisodicMemory table by embedding the situation field
    and comparing against the query embedding.
    """
    from .vectors import get_embedding, cosine_similarity as cos_sim
    from ..database.models import EpisodicMemory

    if not query or not query.strip():
        return []

    try:
        query_vec = get_embedding(query)
        rows = (
            db.query(EpisodicMemory)
            .filter(EpisodicMemory.owner_id == owner_id)
            .order_by(EpisodicMemory.id.desc())
            .limit(200)
            .all()
        )

        scored: list[tuple[float, EpisodicMemory]] = []
        for row in rows:
            if row.situation:
                sit_vec = get_embedding(row.situation)
                sim = cos_sim(query_vec, sit_vec)
                scored.append((sim, row))

        scored.sort(key=lambda x: -x[0])
        results = []
        for sim, row in scored[:top_k]:
            outcome = row.outcome or "unknown"
            detail = f" ({row.outcome_detail})" if row.outcome_detail else ""
            results.append(
                f"[{outcome}{detail}] {row.situation} -> {row.action_taken}"
            )
        return results
    except Exception as exc:
        logger.warning("retrieve_relevant_episodes failed: %s", str(exc)[:200])
        return []


def retrieve_improvement_notes(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
) -> List[str]:
    """Retrieve improvement notes relevant to query via GloVe similarity.

    Improvement notes are stored as MemoryVector with memory_type='note'.
    """
    results = search_memory_vectors(db, owner_id, query, top_k=top_k, category="note")
    return [r["content"] for r in results if r.get("content")]


def retrieve_world_model(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
) -> List[str]:
    """Retrieve world model entries relevant to query via GloVe similarity.

    World model entries are stored as MemoryVector with memory_type='world'.
    """
    results = search_memory_vectors(db, owner_id, query, top_k=top_k, category="world")
    return [r["content"] for r in results if r.get("content")]


def retrieve_relevant_artifacts(
    db: Session,
    owner_id: int,
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieve task artifacts relevant to a query.

    Known gotcha: queries with fewer than 3 words return empty to avoid
    injecting irrelevant context into the LLM prompt.
    """
    if not query or len(query.strip().split()) < 3:
        return []

    return search_memory_vectors(db, owner_id, query, top_k=top_k, category="artifact")

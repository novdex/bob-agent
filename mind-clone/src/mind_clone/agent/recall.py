"""
Long-Term Memory Recall — Bob actually uses what he's stored.

Searches across ALL memory stores and injects the most relevant
context before each LLM call:

  - SelfImprovementNotes  (lessons Bob wrote about himself)
  - EpisodicMemories      (past situations + outcomes)
  - MemoryVectors         (semantic search over stored facts/lessons)
  - ResearchNotes         (research Bob has done)

Without this, Bob stores memories but never reads them back.
This bridges the gap between storage and use.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.models import (
    SelfImprovementNote,
    ResearchNote,
    ConversationSummary,
)
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.agent.recall")

MAX_RECALL_CHARS = 1500  # Total chars to inject — keep context lean


# ---------------------------------------------------------------------------
# Individual store searches
# ---------------------------------------------------------------------------


def _search_self_improvement_notes(db: Session, owner_id: int, query: str, limit: int = 2) -> List[str]:
    """Find open self-improvement notes relevant to this query."""
    try:
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
        query_words = set(query.lower().split())
        scored = []
        for n in notes:
            text = f"{n.title} {n.summary}".lower()
            overlap = sum(1 for w in query_words if w in text)
            if overlap > 0:
                scored.append((overlap, n))

        scored.sort(key=lambda x: -x[0])
        return [
            f"Self-note: {n.title} — {truncate_text(n.summary, 150)}"
            for _, n in scored[:limit]
        ]
    except Exception as e:
        logger.debug("RECALL_SELF_NOTES_FAIL: %s", str(e)[:100])
        return []


def _search_research_notes(db: Session, owner_id: int, query: str, limit: int = 2) -> List[str]:
    """Find research notes relevant to this query."""
    try:
        notes = (
            db.query(ResearchNote)
            .filter(ResearchNote.owner_id == owner_id)
            .order_by(ResearchNote.created_at.desc())
            .limit(30)
            .all()
        )
        query_words = set(query.lower().split())
        scored = []
        for n in notes:
            text = f"{n.topic} {n.summary}".lower()
            overlap = sum(1 for w in query_words if w in text)
            if overlap > 1:  # higher bar for research — require 2+ matching words
                scored.append((overlap, n))

        scored.sort(key=lambda x: -x[0])
        return [
            f"Research ({n.topic}): {truncate_text(n.summary, 150)}"
            for _, n in scored[:limit]
        ]
    except Exception as e:
        logger.debug("RECALL_RESEARCH_FAIL: %s", str(e)[:100])
        return []


def _search_conversation_summaries(db: Session, owner_id: int, query: str, limit: int = 1) -> List[str]:
    """Find relevant conversation summaries."""
    try:
        summaries = (
            db.query(ConversationSummary)
            .filter(ConversationSummary.owner_id == owner_id)
            .order_by(ConversationSummary.id.desc())
            .limit(10)
            .all()
        )
        query_words = set(query.lower().split())
        scored = []
        for s in summaries:
            text = s.summary.lower()
            overlap = sum(1 for w in query_words if w in text)
            if overlap > 1:
                scored.append((overlap, s))

        scored.sort(key=lambda x: -x[0])
        return [
            f"Past conversation: {truncate_text(s.summary, 200)}"
            for _, s in scored[:limit]
        ]
    except Exception as e:
        logger.debug("RECALL_SUMMARIES_FAIL: %s", str(e)[:100])
        return []


def _search_memory_vectors(db: Session, owner_id: int, query: str, limit: int = 3) -> List[str]:
    """Semantic search over MemoryVectors (lessons + world facts)."""
    try:
        from .memory import search_memory_vectors
        results = search_memory_vectors(db, owner_id, query, top_k=limit)
        return [
            f"Memory: {truncate_text(r.get('text', ''), 150)}"
            for r in results
            if r.get("text")
        ]
    except Exception as e:
        logger.debug("RECALL_VECTORS_FAIL: %s", str(e)[:100])
        return []


# ---------------------------------------------------------------------------
# Main recall function
# ---------------------------------------------------------------------------


def build_recall_context(
    db: Session,
    owner_id: int,
    user_message: str,
) -> Optional[str]:
    """Search all memory stores and build a recall context string.

    Returns None if nothing relevant found.
    Returns a system message string if relevant memories found.
    """
    # Skip recall for very short/trivial messages
    if len(user_message.strip().split()) < 3:
        return None

    # Skip internal system messages
    if user_message.startswith("[") and "]" in user_message[:30]:
        return None

    snippets: List[str] = []

    # Search each store
    snippets += _search_self_improvement_notes(db, owner_id, user_message, limit=2)
    snippets += _search_memory_vectors(db, owner_id, user_message, limit=3)
    snippets += _search_research_notes(db, owner_id, user_message, limit=2)
    snippets += _search_conversation_summaries(db, owner_id, user_message, limit=1)

    if not snippets:
        return None

    # Trim to fit within char budget
    selected = []
    total_chars = 0
    for s in snippets:
        if total_chars + len(s) > MAX_RECALL_CHARS:
            break
        selected.append(s)
        total_chars += len(s)

    if not selected:
        return None

    return (
        "[LONG-TERM MEMORY] Relevant things you know and have experienced:\n" +
        "\n".join(f"• {s}" for s in selected) +
        "\nUse this context naturally in your response when relevant."
    )


def get_recall_context_block(db: Session, owner_id: int, user_message: str) -> str:
    """Return recall context as a string block."""
    try:
        return build_recall_context(db, owner_id, user_message) or ""
    except Exception:
        return ""


def inject_recall_context(
    db: Session,
    owner_id: int,
    user_message: str,
    messages: List[dict],
) -> bool:
    """Inject long-term memory recall into messages before LLM call.

    Returns True if context was injected.
    """
    try:
        context = build_recall_context(db, owner_id, user_message)
        if context:
            messages.append({"role": "system", "content": context})
            logger.debug("RECALL_INJECTED owner=%d chars=%d", owner_id, len(context))
            return True
    except Exception as e:
        logger.warning("RECALL_INJECT_FAIL: %s", str(e)[:200])
    return False

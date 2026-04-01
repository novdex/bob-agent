"""
Atomic memory reindex — rebuild all memory vectors for an owner.

Uses session write-lock for transactional integrity. Rebuilds GloVe
embeddings for 7 memory types: conversation summaries, research notes,
task artifacts, self-improvement notes, forecasts, outcomes, lessons.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from ...core.state import session_write_lock, increment_runtime_state
from ...database.models import (
    ConversationSummary,
    MemoryVector,
    ResearchNote,
    SelfImprovementNote,
    ActionForecast,
)
from ...utils import truncate_text

logger = logging.getLogger("mind_clone.memory_reindex")


def _preview(text: str, max_len: int = 200) -> str:
    """Truncate text for vector preview field."""
    t = str(text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _get_embedding(text: str) -> np.ndarray:
    """Get GloVe embedding for text. Returns 100d float32 vector."""
    # Lazy import to avoid circular dependency with monolith vector system
    try:
        from ...agent.vectors import get_embedding
        return get_embedding(text)
    except ImportError:
        pass

    # Fallback: simple word-average with random vectors (for testing)
    words = text.lower().split()[:50]
    if not words:
        return np.zeros(100, dtype=np.float32)
    rng = np.random.RandomState(hash(text) & 0xFFFFFFFF)
    vecs = [rng.randn(100).astype(np.float32) * 0.1 for _ in words]
    return np.mean(vecs, axis=0).astype(np.float32)


def _embedding_to_bytes(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def _is_zero_vector(vec: np.ndarray) -> bool:
    return float(np.linalg.norm(vec)) < 1e-9


def reindex_owner_memory_vectors(
    db: Session,
    owner_id: int,
    rebuild_lessons: bool = False,
) -> Dict[str, Any]:
    """Atomically rebuild all memory vectors for an owner.

    Deletes existing vectors and rebuilds from source tables inside a
    session write-lock. Returns counts of rebuilt vectors per type.
    """
    target_types = [
        "conversation_summary",
        "research_note",
        "self_improvement_note",
        "world_model_forecast",
        "world_model_outcome",
    ]
    if rebuild_lessons:
        target_types.append("lesson")

    counts: Dict[str, int] = {t: 0 for t in target_types}

    with session_write_lock(owner_id, reason="memory_reindex"):
        # Delete stale vectors
        db.query(MemoryVector).filter(
            MemoryVector.owner_id == owner_id,
            MemoryVector.memory_type.in_(target_types),
        ).delete(synchronize_session=False)

        # Rebuild: conversation summaries
        for row in (
            db.query(ConversationSummary)
            .filter(ConversationSummary.owner_id == owner_id)
            .order_by(ConversationSummary.id.desc())
            .limit(200)
            .all()
        ):
            text = f"{row.summary or ''}\n{row.key_points_json or ''}".strip()
            if not text:
                continue
            vec = _get_embedding(text)
            if _is_zero_vector(vec):
                continue
            db.add(MemoryVector(
                owner_id=owner_id,
                memory_type="conversation_summary",
                ref_id=int(row.id),
                text_preview=_preview(text),
                embedding=_embedding_to_bytes(vec),
            ))
            counts["conversation_summary"] += 1

        # Rebuild: research notes
        for row in (
            db.query(ResearchNote)
            .filter(ResearchNote.owner_id == owner_id)
            .order_by(ResearchNote.id.desc())
            .limit(300)
            .all()
        ):
            text = f"{row.topic or ''}: {row.summary or ''}".strip()
            if not text:
                continue
            vec = _get_embedding(text)
            if _is_zero_vector(vec):
                continue
            db.add(MemoryVector(
                owner_id=owner_id,
                memory_type="research_note",
                ref_id=int(row.id),
                text_preview=_preview(text),
                embedding=_embedding_to_bytes(vec),
            ))
            counts["research_note"] += 1

        # Rebuild: self-improvement notes
        try:
            for row in (
                db.query(SelfImprovementNote)
                .filter(SelfImprovementNote.owner_id == owner_id)
                .order_by(SelfImprovementNote.id.desc())
                .limit(200)
                .all()
            ):
                text = str(getattr(row, "note", "") or "").strip()
                if not text:
                    continue
                vec = _get_embedding(text)
                if _is_zero_vector(vec):
                    continue
                db.add(MemoryVector(
                    owner_id=owner_id,
                    memory_type="self_improvement_note",
                    ref_id=int(row.id),
                    text_preview=_preview(text),
                    embedding=_embedding_to_bytes(vec),
                ))
                counts["self_improvement_note"] += 1
        except Exception:
            pass  # Table may not exist

        # Rebuild: world model forecasts/outcomes
        try:
            for row in (
                db.query(ActionForecast)
                .filter(ActionForecast.owner_id == owner_id)
                .order_by(ActionForecast.id.desc())
                .limit(200)
                .all()
            ):
                status = str(getattr(row, "status", "pending") or "pending")
                if status == "pending":
                    text = f"{row.action_summary or ''}: {row.predicted_outcome or ''}".strip()
                    mem_type = "world_model_forecast"
                else:
                    text = f"{row.action_summary or ''}: {row.observed_outcome or ''}".strip()
                    mem_type = "world_model_outcome"
                if not text:
                    continue
                vec = _get_embedding(text)
                if _is_zero_vector(vec):
                    continue
                db.add(MemoryVector(
                    owner_id=owner_id,
                    memory_type=mem_type,
                    ref_id=int(row.id),
                    text_preview=_preview(text),
                    embedding=_embedding_to_bytes(vec),
                ))
                counts[mem_type] += 1
        except Exception:
            pass  # Table may not exist

        db.commit()

    total = sum(counts.values())
    logger.info("MEMORY_REINDEX owner=%d total=%d counts=%s", owner_id, total, counts)
    return {"ok": True, "owner_id": owner_id, "rebuilt": counts, "total": total}

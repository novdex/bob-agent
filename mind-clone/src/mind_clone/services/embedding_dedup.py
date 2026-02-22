"""
Embedding deduplication — detect and remove near-duplicate memory vectors.

Uses cosine similarity to find vectors that are too close together
(above a configurable threshold) and removes the older duplicate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np
from sqlalchemy.orm import Session

from ..core.state import session_write_lock
from ..database.models import MemoryVector

logger = logging.getLogger("mind_clone.embedding_dedup")

# Default cosine similarity threshold for dedup (0.95 = very similar)
DEDUP_COSINE_THRESHOLD = 0.95


def _bytes_to_embedding(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32).copy()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def find_duplicate_vectors(
    db: Session,
    owner_id: int,
    memory_type: str = "",
    threshold: float = DEDUP_COSINE_THRESHOLD,
    limit: int = 500,
) -> List[Tuple[int, int, float]]:
    """Find near-duplicate vector pairs.

    Returns list of ``(keep_id, remove_id, similarity)`` tuples.
    The newer vector (higher id) is kept; older duplicate is marked for removal.
    """
    q = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id)
    if memory_type:
        q = q.filter(MemoryVector.memory_type == memory_type)
    rows = q.order_by(MemoryVector.id.desc()).limit(limit).all()

    if len(rows) < 2:
        return []

    # Load embeddings
    vectors: List[Tuple[int, np.ndarray]] = []
    for row in rows:
        try:
            vec = _bytes_to_embedding(row.embedding)
            if np.linalg.norm(vec) >= 1e-9:
                vectors.append((row.id, vec))
        except Exception:
            continue

    duplicates: List[Tuple[int, int, float]] = []
    seen_remove: set = set()

    # O(n^2) pairwise comparison — acceptable for limit=500
    for i in range(len(vectors)):
        id_a, vec_a = vectors[i]
        if id_a in seen_remove:
            continue
        for j in range(i + 1, len(vectors)):
            id_b, vec_b = vectors[j]
            if id_b in seen_remove:
                continue
            sim = _cosine_similarity(vec_a, vec_b)
            if sim >= threshold:
                # Keep newer (higher id), remove older
                keep_id = max(id_a, id_b)
                remove_id = min(id_a, id_b)
                duplicates.append((keep_id, remove_id, sim))
                seen_remove.add(remove_id)

    return duplicates


def deduplicate_memory_vectors(
    db: Session,
    owner_id: int,
    memory_type: str = "",
    threshold: float = DEDUP_COSINE_THRESHOLD,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Find and optionally remove near-duplicate memory vectors.

    Args:
        dry_run: If True, report duplicates without deleting them.
    """
    with session_write_lock(owner_id, reason="embedding_dedup"):
        pairs = find_duplicate_vectors(db, owner_id, memory_type, threshold)

        if not pairs:
            return {"ok": True, "duplicates_found": 0, "removed": 0}

        remove_ids = [remove_id for _, remove_id, _ in pairs]

        if dry_run:
            return {
                "ok": True,
                "duplicates_found": len(pairs),
                "removed": 0,
                "dry_run": True,
                "pairs": [
                    {"keep": k, "remove": r, "similarity": round(s, 4)}
                    for k, r, s in pairs[:20]
                ],
            }

        deleted = (
            db.query(MemoryVector)
            .filter(MemoryVector.id.in_(remove_ids))
            .delete(synchronize_session=False)
        )
        db.commit()

    logger.info(
        "EMBEDDING_DEDUP owner=%d found=%d removed=%d threshold=%.3f",
        owner_id, len(pairs), deleted, threshold,
    )
    return {"ok": True, "duplicates_found": len(pairs), "removed": deleted}

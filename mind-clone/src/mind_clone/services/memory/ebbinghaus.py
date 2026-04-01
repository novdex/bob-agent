"""
Ebbinghaus Forgetting Curve — memory decay + spaced repetition (SAGE, 2025).

KEY INSIGHT: Human memory doesn't store everything equally. Important, frequently
recalled memories stay sharp. Trivial, never-recalled memories fade. This makes
retrieval faster and more accurate — noise fades, signal strengthens.

Bob's memory has the same problem: flat lists of equal-weight memories mean
retrieving anything relevant requires wading through noise.

Ebbinghaus model:
  importance(t) = importance_0 * e^(-decay_rate * t)

  Where:
  - t = days since last recall (or creation)
  - decay_rate depends on memory type (facts decay slower than episodes)
  - Recalling a memory RESETS its timer and BOOSTS its importance

Three actions:
1. decay() — reduce importance of old, unrecalled memories
2. boost() — increase importance when a memory is recalled
3. prune() — archive memories whose importance drops below threshold

Result: Bob's memory stays clean. Critical lessons stay sharp forever.
Noise from old failed attempts fades automatically.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ...database.models import EpisodicMemory, SelfImprovementNote
from ...database.session import SessionLocal
from ...utils import utc_now_iso

logger = logging.getLogger("mind_clone.services.ebbinghaus")

# Decay rates (higher = faster forgetting)
_DECAY_RATES = {
    "episodic": 0.05,       # episodes decay faster (context-specific)
    "improvement": 0.02,    # lessons decay slowly (general knowledge)
    "research": 0.03,       # research notes moderate decay
}

_PRUNE_THRESHOLD = 0.1      # archive if importance drops below this
_BOOST_ON_RECALL = 0.3      # importance boost when memory is recalled
_MAX_IMPORTANCE = 1.0
_MIN_IMPORTANCE = 0.01

# How many days before we start applying decay
_GRACE_PERIOD_DAYS = 1


def _ebbinghaus_decay(
    importance: float,
    days_since_recall: float,
    decay_rate: float,
) -> float:
    """Apply Ebbinghaus forgetting curve formula."""
    if days_since_recall <= _GRACE_PERIOD_DAYS:
        return importance
    effective_days = days_since_recall - _GRACE_PERIOD_DAYS
    decayed = importance * math.exp(-decay_rate * effective_days)
    return max(_MIN_IMPORTANCE, round(decayed, 4))


def decay_memories(db: Session, owner_id: int) -> dict:
    """Apply Ebbinghaus decay to all memories. Run daily."""
    now = datetime.now(timezone.utc)
    episodic_updated = 0
    improvement_updated = 0

    # Decay episodic memories
    episodes = (
        db.query(EpisodicMemory)
        .filter(EpisodicMemory.owner_id == owner_id)
        .all()
    )
    for ep in episodes:
        ref_time = ep.last_recalled_at or ep.created_at
        if not ref_time:
            continue
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        days = (now - ref_time).total_seconds() / 86400
        old_imp = float(ep.importance or 1.0)
        new_imp = _ebbinghaus_decay(old_imp, days, _DECAY_RATES["episodic"])
        if new_imp != old_imp:
            ep.importance = new_imp
            episodic_updated += 1

    # Decay self-improvement notes
    notes = (
        db.query(SelfImprovementNote)
        .filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.status == "open",
        )
        .all()
    )
    for note in notes:
        ref_time = note.last_recalled_at or note.created_at
        if not ref_time:
            continue
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        days = (now - ref_time).total_seconds() / 86400
        old_imp = float(note.importance or 1.0)
        new_imp = _ebbinghaus_decay(old_imp, days, _DECAY_RATES["improvement"])
        if new_imp != old_imp:
            note.importance = new_imp
            improvement_updated += 1

    db.commit()
    logger.info(
        "EBBINGHAUS_DECAY episodic=%d improvement=%d",
        episodic_updated, improvement_updated,
    )
    return {
        "ok": True,
        "episodic_updated": episodic_updated,
        "improvement_updated": improvement_updated,
    }


def boost_memory(
    db: Session,
    memory_type: str,  # "episodic" | "improvement"
    memory_id: int,
) -> bool:
    """Boost importance when a memory is recalled (spaced repetition effect)."""
    now = datetime.now(timezone.utc)

    if memory_type == "episodic":
        mem = db.query(EpisodicMemory).filter(EpisodicMemory.id == memory_id).first()
        if mem:
            mem.importance = min(_MAX_IMPORTANCE, float(mem.importance or 0.5) + _BOOST_ON_RECALL)
            mem.recall_count = int(mem.recall_count or 0) + 1
            mem.last_recalled_at = now
            db.commit()
            return True
    elif memory_type == "improvement":
        note = db.query(SelfImprovementNote).filter(SelfImprovementNote.id == memory_id).first()
        if note:
            note.importance = min(_MAX_IMPORTANCE, float(note.importance or 0.5) + _BOOST_ON_RECALL)
            note.recall_count = int(note.recall_count or 0) + 1
            note.last_recalled_at = now
            db.commit()
            return True

    return False


def prune_faded_memories(db: Session, owner_id: int) -> dict:
    """Archive memories whose importance has decayed below threshold."""
    pruned_episodic = 0
    pruned_improvement = 0

    # Prune old low-importance episodic memories (keep minimum 50)
    total_episodic = db.query(EpisodicMemory).filter(
        EpisodicMemory.owner_id == owner_id
    ).count()

    if total_episodic > 50:
        faded = (
            db.query(EpisodicMemory)
            .filter(
                EpisodicMemory.owner_id == owner_id,
                EpisodicMemory.importance < _PRUNE_THRESHOLD,
            )
            .order_by(EpisodicMemory.importance.asc())
            .limit(total_episodic - 50)  # keep at least 50
            .all()
        )
        for ep in faded:
            db.delete(ep)
            pruned_episodic += 1

    # Archive old low-importance improvement notes (don't delete — archive)
    faded_notes = (
        db.query(SelfImprovementNote)
        .filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.status == "open",
            SelfImprovementNote.importance < _PRUNE_THRESHOLD,
        )
        .all()
    )
    for note in faded_notes:
        note.status = "archived"
        pruned_improvement += 1

    if pruned_episodic or pruned_improvement:
        db.commit()

    logger.info(
        "EBBINGHAUS_PRUNE episodic_deleted=%d improvement_archived=%d",
        pruned_episodic, pruned_improvement,
    )
    return {
        "ok": True,
        "episodic_pruned": pruned_episodic,
        "improvement_archived": pruned_improvement,
    }


def get_important_memories(
    db: Session,
    owner_id: int,
    memory_type: str = "improvement",
    limit: int = 5,
    min_importance: float = 0.3,
) -> list:
    """Get highest-importance memories (importance-weighted retrieval)."""
    if memory_type == "episodic":
        return (
            db.query(EpisodicMemory)
            .filter(
                EpisodicMemory.owner_id == owner_id,
                EpisodicMemory.importance >= min_importance,
            )
            .order_by(EpisodicMemory.importance.desc())
            .limit(limit)
            .all()
        )
    elif memory_type == "improvement":
        return (
            db.query(SelfImprovementNote)
            .filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.status == "open",
                SelfImprovementNote.importance >= min_importance,
            )
            .order_by(SelfImprovementNote.importance.desc())
            .limit(limit)
            .all()
        )
    return []


def run_daily_memory_maintenance(owner_id: int = 1) -> dict:
    """Run full Ebbinghaus maintenance: decay → prune. Called daily."""
    db = SessionLocal()
    try:
        decay_result = decay_memories(db, owner_id)
        prune_result = prune_faded_memories(db, owner_id)
        try:
            from mind_clone.services.embedding_dedup import deduplicate_memory_vectors
            deduplicate_memory_vectors(db, owner_id)
        except Exception:
            pass
        return {
            "ok": True,
            "decay": decay_result,
            "prune": prune_result,
        }
    except Exception as e:
        logger.error("EBBINGHAUS_MAINTENANCE_FAIL: %s", e)
        return {"ok": False, "error": str(e)[:200]}
    finally:
        db.close()

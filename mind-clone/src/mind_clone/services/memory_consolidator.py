"""
Memory Consolidation Engine — Agent Zero-inspired deduplication.

Over time Bob accumulates duplicate and near-duplicate memories:
- Research notes on the same topic
- Self-improvement notes with overlapping summaries
- Episodic memories describing the same situation

This module finds and merges duplicates using keyword overlap ratios,
keeping the richest version and deleting redundant copies.

Inspired by Agent Zero's memory consolidation loop that runs periodically
to keep the knowledge base clean and non-redundant.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..database.session import SessionLocal
from ..database.models import (
    ResearchNote,
    SelfImprovementNote,
    EpisodicMemory,
)

logger = logging.getLogger("mind_clone.services.memory_consolidator")


# ---------------------------------------------------------------------------
# Keyword overlap utility
# ---------------------------------------------------------------------------


def _keyword_overlap(text_a: str, text_b: str, min_overlap: int = 3) -> float:
    """Calculate the keyword overlap ratio between two texts.

    Tokenises both texts into lowercase word sets, computes intersection
    over union (Jaccard similarity). Returns 0.0 if either text is too
    short or the intersection is below min_overlap.

    Args:
        text_a: First text.
        text_b: Second text.
        min_overlap: Minimum number of shared words required to consider
                     texts as overlapping at all.

    Returns:
        Float between 0.0 and 1.0 representing overlap ratio.
    """
    if not text_a or not text_b:
        return 0.0

    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    # Filter out very short tokens (articles, prepositions)
    words_a = {w for w in words_a if len(w) > 2}
    words_b = {w for w in words_b if len(w) > 2}

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    if len(intersection) < min_overlap:
        return 0.0

    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Research notes consolidation
# ---------------------------------------------------------------------------


def consolidate_research_notes(owner_id: int) -> Dict[str, int]:
    """Merge duplicate research notes for an owner (>50% keyword overlap).

    When duplicates are found, the longer/richer note is kept and the
    shorter one is deleted. Sources and tags from both are merged.

    Args:
        owner_id: Owner whose research notes to consolidate.

    Returns:
        Dict with keys: scanned, merged, remaining.
    """
    db = SessionLocal()
    try:
        notes: List[ResearchNote] = (
            db.query(ResearchNote)
            .filter(ResearchNote.owner_id == owner_id)
            .order_by(ResearchNote.id.asc())
            .all()
        )

        if len(notes) < 2:
            return {"scanned": len(notes), "merged": 0, "remaining": len(notes)}

        merged_count = 0
        deleted_ids: set[int] = set()

        for i in range(len(notes)):
            if notes[i].id in deleted_ids:
                continue
            for j in range(i + 1, len(notes)):
                if notes[j].id in deleted_ids:
                    continue

                # Compare summaries
                overlap = _keyword_overlap(
                    notes[i].summary or "", notes[j].summary or ""
                )
                if overlap < 0.50:
                    continue

                # Keep the longer note, merge sources/tags from the other
                keeper, victim = (
                    (notes[i], notes[j])
                    if len(notes[i].summary or "") >= len(notes[j].summary or "")
                    else (notes[j], notes[i])
                )

                # Merge sources
                try:
                    keeper_sources = json.loads(keeper.sources_json or "[]")
                    victim_sources = json.loads(victim.sources_json or "[]")
                    merged_sources = list(
                        {s for s in keeper_sources + victim_sources if s}
                    )
                    keeper.sources_json = json.dumps(merged_sources)
                except Exception:
                    pass

                # Merge tags
                try:
                    keeper_tags = json.loads(keeper.tags_json or "[]")
                    victim_tags = json.loads(victim.tags_json or "[]")
                    merged_tags = list({t for t in keeper_tags + victim_tags if t})
                    keeper.tags_json = json.dumps(merged_tags)
                except Exception:
                    pass

                db.delete(victim)
                deleted_ids.add(victim.id)
                merged_count += 1

        if merged_count > 0:
            db.commit()
            logger.info(
                "CONSOLIDATE_RESEARCH owner=%d merged=%d remaining=%d",
                owner_id, merged_count, len(notes) - merged_count,
            )

        return {
            "scanned": len(notes),
            "merged": merged_count,
            "remaining": len(notes) - merged_count,
        }
    except Exception as exc:
        db.rollback()
        logger.error("CONSOLIDATE_RESEARCH_FAIL owner=%d: %s", owner_id, exc)
        return {"scanned": 0, "merged": 0, "remaining": 0, "error": str(exc)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Self-improvement notes consolidation
# ---------------------------------------------------------------------------


def consolidate_improvement_notes(owner_id: int) -> Dict[str, int]:
    """Deduplicate SelfImprovementNote records (>50% overlap on 'summary').

    The 'summary' field is used for comparison (not 'content'). The note
    with higher priority or more actions is kept.

    Args:
        owner_id: Owner whose improvement notes to consolidate.

    Returns:
        Dict with keys: scanned, merged, remaining.
    """
    db = SessionLocal()
    try:
        notes: List[SelfImprovementNote] = (
            db.query(SelfImprovementNote)
            .filter(SelfImprovementNote.owner_id == owner_id)
            .order_by(SelfImprovementNote.id.asc())
            .all()
        )

        if len(notes) < 2:
            return {"scanned": len(notes), "merged": 0, "remaining": len(notes)}

        # Priority ranking for keeper selection
        priority_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}

        merged_count = 0
        deleted_ids: set[int] = set()

        for i in range(len(notes)):
            if notes[i].id in deleted_ids:
                continue
            for j in range(i + 1, len(notes)):
                if notes[j].id in deleted_ids:
                    continue

                # Compare on summary field
                overlap = _keyword_overlap(
                    notes[i].summary or "", notes[j].summary or ""
                )
                if overlap < 0.50:
                    continue

                # Keep the higher-priority or longer-summary note
                rank_i = priority_rank.get(notes[i].priority or "medium", 2)
                rank_j = priority_rank.get(notes[j].priority or "medium", 2)

                if rank_i > rank_j:
                    keeper, victim = notes[i], notes[j]
                elif rank_j > rank_i:
                    keeper, victim = notes[j], notes[i]
                else:
                    # Same priority — keep longer summary
                    if len(notes[i].summary or "") >= len(notes[j].summary or ""):
                        keeper, victim = notes[i], notes[j]
                    else:
                        keeper, victim = notes[j], notes[i]

                # Merge actions from victim into keeper
                try:
                    keeper_actions = json.loads(keeper.actions_json or "[]")
                    victim_actions = json.loads(victim.actions_json or "[]")
                    merged_actions = list(
                        dict.fromkeys(keeper_actions + victim_actions)
                    )
                    keeper.actions_json = json.dumps(merged_actions[:10])
                except Exception:
                    pass

                db.delete(victim)
                deleted_ids.add(victim.id)
                merged_count += 1

        if merged_count > 0:
            db.commit()
            logger.info(
                "CONSOLIDATE_IMPROVEMENT owner=%d merged=%d remaining=%d",
                owner_id, merged_count, len(notes) - merged_count,
            )

        return {
            "scanned": len(notes),
            "merged": merged_count,
            "remaining": len(notes) - merged_count,
        }
    except Exception as exc:
        db.rollback()
        logger.error("CONSOLIDATE_IMPROVEMENT_FAIL owner=%d: %s", owner_id, exc)
        return {"scanned": 0, "merged": 0, "remaining": 0, "error": str(exc)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Episodic memory consolidation
# ---------------------------------------------------------------------------


def consolidate_episodic_memories(owner_id: int) -> Dict[str, int]:
    """Merge similar episodic memories for an owner (>60% keyword overlap).

    Compares the 'situation' field. Keeps the memory with higher importance
    or more detail.

    Args:
        owner_id: Owner whose episodic memories to consolidate.

    Returns:
        Dict with keys: scanned, merged, remaining.
    """
    db = SessionLocal()
    try:
        memories: List[EpisodicMemory] = (
            db.query(EpisodicMemory)
            .filter(EpisodicMemory.owner_id == owner_id)
            .order_by(EpisodicMemory.id.asc())
            .all()
        )

        if len(memories) < 2:
            return {"scanned": len(memories), "merged": 0, "remaining": len(memories)}

        merged_count = 0
        deleted_ids: set[int] = set()

        for i in range(len(memories)):
            if memories[i].id in deleted_ids:
                continue
            for j in range(i + 1, len(memories)):
                if memories[j].id in deleted_ids:
                    continue

                # Compare situations (stricter threshold: 60%)
                overlap = _keyword_overlap(
                    memories[i].situation or "", memories[j].situation or ""
                )
                if overlap < 0.60:
                    continue

                # Keep the one with higher importance, or longer detail
                imp_i = getattr(memories[i], "importance", 1.0) or 1.0
                imp_j = getattr(memories[j], "importance", 1.0) or 1.0

                if imp_i > imp_j:
                    keeper, victim = memories[i], memories[j]
                elif imp_j > imp_i:
                    keeper, victim = memories[j], memories[i]
                else:
                    # Same importance — keep the one with more detail
                    detail_i = len(memories[i].outcome_detail or "")
                    detail_j = len(memories[j].outcome_detail or "")
                    if detail_i >= detail_j:
                        keeper, victim = memories[i], memories[j]
                    else:
                        keeper, victim = memories[j], memories[i]

                # Merge tools_used from victim
                try:
                    keeper_tools = json.loads(keeper.tools_used_json or "[]")
                    victim_tools = json.loads(victim.tools_used_json or "[]")
                    merged_tools = list(
                        dict.fromkeys(keeper_tools + victim_tools)
                    )
                    keeper.tools_used_json = json.dumps(merged_tools)
                except Exception:
                    pass

                # Append victim's outcome_detail if keeper's is shorter
                if (victim.outcome_detail or "") and not (keeper.outcome_detail or ""):
                    keeper.outcome_detail = victim.outcome_detail

                db.delete(victim)
                deleted_ids.add(victim.id)
                merged_count += 1

        if merged_count > 0:
            db.commit()
            logger.info(
                "CONSOLIDATE_EPISODIC owner=%d merged=%d remaining=%d",
                owner_id, merged_count, len(memories) - merged_count,
            )

        return {
            "scanned": len(memories),
            "merged": merged_count,
            "remaining": len(memories) - merged_count,
        }
    except Exception as exc:
        db.rollback()
        logger.error("CONSOLIDATE_EPISODIC_FAIL owner=%d: %s", owner_id, exc)
        return {"scanned": 0, "merged": 0, "remaining": 0, "error": str(exc)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Full consolidation run
# ---------------------------------------------------------------------------


def run_full_consolidation(owner_id: int) -> Dict[str, Dict[str, int]]:
    """Run all three consolidation passes for an owner.

    Args:
        owner_id: Owner whose memories to consolidate.

    Returns:
        Dict with keys: research, improvement, episodic — each containing
        scanned/merged/remaining counts.
    """
    logger.info("CONSOLIDATION_START owner=%d", owner_id)

    research = consolidate_research_notes(owner_id)
    improvement = consolidate_improvement_notes(owner_id)
    episodic = consolidate_episodic_memories(owner_id)

    total_merged = (
        research.get("merged", 0)
        + improvement.get("merged", 0)
        + episodic.get("merged", 0)
    )
    logger.info(
        "CONSOLIDATION_DONE owner=%d total_merged=%d (research=%d improvement=%d episodic=%d)",
        owner_id,
        total_merged,
        research.get("merged", 0),
        improvement.get("merged", 0),
        episodic.get("merged", 0),
    )

    return {
        "research": research,
        "improvement": improvement,
        "episodic": episodic,
    }


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


def tool_consolidate_memory(args: dict) -> dict:
    """Tool wrapper: run memory consolidation for an owner.

    Args (dict):
        owner_id (int): Owner ID (default 1).
        type (str): One of 'all', 'research', 'improvement', 'episodic'.
                    Default 'all'.

    Returns:
        Dict with consolidation results.
    """
    owner_id = int(args.get("owner_id", 1))
    consolidation_type = str(args.get("type", "all")).lower()

    try:
        if consolidation_type == "research":
            result = consolidate_research_notes(owner_id)
            return {"ok": True, "type": "research", **result}

        if consolidation_type == "improvement":
            result = consolidate_improvement_notes(owner_id)
            return {"ok": True, "type": "improvement", **result}

        if consolidation_type == "episodic":
            result = consolidate_episodic_memories(owner_id)
            return {"ok": True, "type": "episodic", **result}

        # Default: run all
        results = run_full_consolidation(owner_id)
        total_merged = sum(v.get("merged", 0) for v in results.values())
        return {
            "ok": True,
            "type": "all",
            "total_merged": total_merged,
            "details": results,
        }
    except Exception as exc:
        logger.error("tool_consolidate_memory error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}

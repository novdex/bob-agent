"""
Memory Graph service — A-MEM / MAGMA / Zettelkasten style.

Treats Bob's memories as a linked knowledge graph instead of flat lists.
When a new memory is saved, automatically links it to related existing memories.
New memories can also trigger updates to existing ones (memory evolution).

Three core operations:
1. link_memories(src, tgt, relation) — create a graph edge
2. auto_link(memory_type, memory_id) — auto-find and link related memories
3. graph_search(query) — traverse the graph from a starting point

Based on:
- A-MEM (NeurIPS 2025) — Zettelkasten interconnected knowledge networks
- MAGMA (Jan 2026) — multi-graph heterogeneous relational structure
- Anthropic context engineering — smallest high-signal token set
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..database.models import (
    MemoryLink,
    ResearchNote,
    EpisodicMemory,
    SelfImprovementNote,
    SkillProfile,
)
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.memory_graph")

# Valid node types
NODE_TYPES = {"research_note", "episodic", "improvement", "skill"}

# Valid relation types
RELATION_TYPES = {"related", "supports", "contradicts", "evolved_from", "caused_by", "learned_from"}

_MAX_AUTO_LINKS = 5  # max links created per auto_link call
_KEYWORD_MIN_LEN = 4


# ---------------------------------------------------------------------------
# Core link operations
# ---------------------------------------------------------------------------

def link_memories(
    db: Session,
    owner_id: int,
    src_type: str,
    src_id: int,
    tgt_type: str,
    tgt_id: int,
    relation: str = "related",
    weight: float = 1.0,
    note: Optional[str] = None,
) -> Optional[MemoryLink]:
    """Create a directed link between two memory nodes."""
    if src_type not in NODE_TYPES or tgt_type not in NODE_TYPES:
        logger.warning("Invalid node type: %s or %s", src_type, tgt_type)
        return None
    if src_type == tgt_type and src_id == tgt_id:
        return None  # no self-loops
    if relation not in RELATION_TYPES:
        relation = "related"

    # Check if link already exists
    existing = (
        db.query(MemoryLink)
        .filter(
            MemoryLink.owner_id == owner_id,
            MemoryLink.src_type == src_type,
            MemoryLink.src_id == src_id,
            MemoryLink.tgt_type == tgt_type,
            MemoryLink.tgt_id == tgt_id,
        )
        .first()
    )
    if existing:
        # Update weight if higher
        if weight > existing.weight:
            existing.weight = weight
            db.commit()
        return existing

    link = MemoryLink(
        owner_id=owner_id,
        src_type=src_type,
        src_id=src_id,
        tgt_type=tgt_type,
        tgt_id=tgt_id,
        relation=relation,
        weight=weight,
        note=truncate_text(note, 200) if note else None,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_links(
    db: Session,
    owner_id: int,
    node_type: str,
    node_id: int,
    direction: str = "both",  # "out" | "in" | "both"
    limit: int = 20,
) -> list[dict]:
    """Get all links for a memory node."""
    results = []

    if direction in ("out", "both"):
        out_links = (
            db.query(MemoryLink)
            .filter(
                MemoryLink.owner_id == owner_id,
                MemoryLink.src_type == node_type,
                MemoryLink.src_id == node_id,
            )
            .order_by(MemoryLink.weight.desc())
            .limit(limit)
            .all()
        )
        for l in out_links:
            results.append({
                "direction": "out",
                "relation": l.relation,
                "target_type": l.tgt_type,
                "target_id": l.tgt_id,
                "weight": l.weight,
                "note": l.note,
                "id": l.id,
            })

    if direction in ("in", "both"):
        in_links = (
            db.query(MemoryLink)
            .filter(
                MemoryLink.owner_id == owner_id,
                MemoryLink.tgt_type == node_type,
                MemoryLink.tgt_id == node_id,
            )
            .order_by(MemoryLink.weight.desc())
            .limit(limit)
            .all()
        )
        for l in in_links:
            results.append({
                "direction": "in",
                "relation": l.relation,
                "source_type": l.src_type,
                "source_id": l.src_id,
                "weight": l.weight,
                "note": l.note,
                "id": l.id,
            })

    return results


# ---------------------------------------------------------------------------
# Auto-linking (Zettelkasten style)
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text."""
    import re
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{3,}", text.lower())
    stopwords = {
        "this", "that", "with", "from", "have", "will", "been", "they",
        "when", "what", "which", "were", "also", "into", "more", "some",
        "than", "then", "them", "these", "there", "their", "about",
    }
    return {w for w in words if w not in stopwords}


def _get_node_text(db: Session, node_type: str, node_id: int) -> str:
    """Get the searchable text content of a memory node."""
    if node_type == "research_note":
        row = db.query(ResearchNote).filter(ResearchNote.id == node_id).first()
        if row:
            tags = json.loads(row.tags_json or "[]") if row.tags_json else []
            return f"{row.topic} {row.summary} {' '.join(tags)}"
    elif node_type == "episodic":
        row = db.query(EpisodicMemory).filter(EpisodicMemory.id == node_id).first()
        if row:
            return f"{row.situation} {getattr(row, 'outcome', '') or ''}"
    elif node_type == "improvement":
        row = db.query(SelfImprovementNote).filter(SelfImprovementNote.id == node_id).first()
        if row:
            return f"{row.title} {row.summary}"
    elif node_type == "skill":
        row = db.query(SkillProfile).filter(SkillProfile.id == node_id).first()
        if row:
            hints = json.loads(row.trigger_hints_json or "[]") if row.trigger_hints_json else []
            return f"{row.title} {row.intent or ''} {' '.join(hints)}"
    return ""


def auto_link(
    db: Session,
    owner_id: int,
    src_type: str,
    src_id: int,
    min_overlap: int = 2,
) -> list[dict]:
    """Auto-find related memories and create links (Zettelkasten style).

    Extracts keywords from the source node and finds other memories
    that share at least min_overlap keywords. Creates 'related' links.
    Returns list of created links.
    """
    src_text = _get_node_text(db, src_type, src_id)
    if not src_text:
        return []

    src_keywords = _extract_keywords(src_text)
    if len(src_keywords) < 2:
        return []

    created = []
    searched = 0

    # Search all other node types
    for tgt_type in NODE_TYPES:
        if searched >= _MAX_AUTO_LINKS:
            break

        if tgt_type == "research_note":
            rows = db.query(ResearchNote).filter(ResearchNote.owner_id == owner_id).order_by(ResearchNote.id.desc()).limit(50).all()
            candidates = [(tgt_type, r.id, f"{r.topic} {r.summary}") for r in rows if r.id != src_id or tgt_type != src_type]
        elif tgt_type == "improvement":
            rows = db.query(SelfImprovementNote).filter(SelfImprovementNote.owner_id == owner_id).order_by(SelfImprovementNote.id.desc()).limit(50).all()
            candidates = [(tgt_type, r.id, f"{r.title} {r.summary}") for r in rows]
        elif tgt_type == "skill":
            rows = db.query(SkillProfile).filter(SkillProfile.owner_id == owner_id, SkillProfile.status == "active").order_by(SkillProfile.id.desc()).limit(50).all()
            candidates = [(tgt_type, r.id, f"{r.title} {r.intent or ''}") for r in rows]
        else:
            continue  # skip episodic for now (too noisy)

        # Score each candidate by keyword overlap
        scored = []
        for ctype, cid, ctext in candidates:
            if ctype == src_type and cid == src_id:
                continue
            ckeys = _extract_keywords(ctext)
            overlap = len(src_keywords & ckeys)
            if overlap >= min_overlap:
                scored.append((overlap, ctype, cid))

        scored.sort(reverse=True)
        for overlap, tgt_type2, tgt_id in scored[:2]:
            if searched >= _MAX_AUTO_LINKS:
                break
            weight = min(1.0, overlap / 10.0)
            link = link_memories(db, owner_id, src_type, src_id, tgt_type2, tgt_id,
                                 relation="related", weight=weight)
            if link:
                created.append({"src": f"{src_type}:{src_id}", "tgt": f"{tgt_type2}:{tgt_id}", "overlap": overlap})
                searched += 1

    if created:
        logger.info("AUTO_LINKED src=%s:%d links=%d", src_type, src_id, len(created))
    return created


# ---------------------------------------------------------------------------
# Graph search / traversal
# ---------------------------------------------------------------------------

def graph_search(
    db: Session,
    owner_id: int,
    start_type: str,
    start_id: int,
    depth: int = 2,
    max_nodes: int = 10,
) -> dict:
    """BFS traversal from a starting memory node.

    Returns all reachable nodes within `depth` hops with their content previews.
    Useful for: 'what else does Bob know that's related to this memory?'
    """
    visited = set()
    queue = [(start_type, start_id, 0)]
    nodes = []

    while queue and len(nodes) < max_nodes:
        node_type, node_id, d = queue.pop(0)
        key = f"{node_type}:{node_id}"
        if key in visited:
            continue
        visited.add(key)

        # Get node content
        text = _get_node_text(db, node_type, node_id)
        if text:
            nodes.append({
                "type": node_type,
                "id": node_id,
                "preview": truncate_text(text, 150),
                "depth": d,
            })

        if d < depth:
            links = get_links(db, owner_id, node_type, node_id, direction="both", limit=5)
            for link in links:
                if link.get("direction") == "out":
                    nkey = f"{link['target_type']}:{link['target_id']}"
                    if nkey not in visited:
                        queue.append((link["target_type"], link["target_id"], d + 1))
                else:
                    nkey = f"{link['source_type']}:{link['source_id']}"
                    if nkey not in visited:
                        queue.append((link["source_type"], link["source_id"], d + 1))

    return {
        "start": f"{start_type}:{start_id}",
        "nodes_found": len(nodes),
        "depth": depth,
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# Context pruning (Anthropic context engineering)
# ---------------------------------------------------------------------------

def prune_context_for_prompt(
    memories: list[dict],
    max_tokens: int = 2000,
    avg_chars_per_token: int = 4,
) -> list[dict]:
    """Keep only highest-signal memories within token budget.

    Implements Anthropic's 'smallest possible set of high-signal tokens' principle.
    Sorts by relevance score desc, truncates to fit budget.
    """
    max_chars = max_tokens * avg_chars_per_token
    total_chars = 0
    pruned = []

    # Sort by weight/score descending if available
    sorted_mems = sorted(memories, key=lambda m: float(m.get("weight", m.get("score", 1.0))), reverse=True)

    for mem in sorted_mems:
        text = mem.get("preview", mem.get("text", mem.get("content", "")))
        char_len = len(str(text))
        if total_chars + char_len > max_chars:
            break
        pruned.append(mem)
        total_chars += char_len

    return pruned

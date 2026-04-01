"""
Memory export utilities — export agent memories to markdown or JSON.

Supports three memory types:
- Research notes (declarative knowledge)
- Conversation summaries (episodic memory)
- Lessons (learned patterns via MemoryVector)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...database.models import ConversationSummary, MemoryVector, ResearchNote
from ...utils import truncate_text

logger = logging.getLogger("mind_clone.memory_export")


def build_memory_export_payload(
    db: Session, owner_id: int
) -> Dict[str, Any]:
    """Build a JSON payload of all exportable memories for an owner."""
    from ...utils import utc_now_iso

    # Research notes
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.owner_id == owner_id)
        .order_by(ResearchNote.id.desc())
        .limit(500)
        .all()
    )
    notes_data = []
    for n in notes:
        try:
            sources = json.loads(n.sources_json or "[]")
        except Exception:
            sources = []
        try:
            tags = json.loads(n.tags_json or "[]")
        except Exception:
            tags = []
        notes_data.append({
            "topic": str(n.topic or ""),
            "summary": str(n.summary or ""),
            "sources": sources,
            "tags": tags,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        })

    # Conversation summaries
    summaries = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.owner_id == owner_id)
        .order_by(ConversationSummary.id.desc())
        .limit(200)
        .all()
    )
    summaries_data = []
    for s in summaries:
        try:
            key_points = json.loads(s.key_points_json or "[]")
        except Exception:
            key_points = []
        try:
            open_loops = json.loads(s.open_loops_json or "[]")
        except Exception:
            open_loops = []
        summaries_data.append({
            "summary": str(s.summary or ""),
            "key_points": key_points,
            "open_loops": open_loops,
            "start_message_id": s.start_message_id,
            "end_message_id": s.end_message_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    # Lessons (from MemoryVector with memory_type == "lesson")
    lessons_data: List[Dict[str, str]] = []
    try:
        lessons = (
            db.query(MemoryVector)
            .filter(
                MemoryVector.owner_id == owner_id,
                MemoryVector.memory_type == "lesson",
            )
            .order_by(MemoryVector.id.desc())
            .limit(300)
            .all()
        )
        for lsn in lessons:
            lessons_data.append({
                "lesson": str(lsn.text_preview or ""),
            })
    except Exception:
        pass  # MemoryVector may not exist in all DB schemas

    return {
        "exported_at": utc_now_iso(),
        "owner_id": owner_id,
        "research_notes": notes_data,
        "conversation_summaries": summaries_data,
        "lessons": lessons_data,
    }


def export_as_markdown(payload: Dict[str, Any]) -> str:
    """Convert a memory export payload to a readable MEMORY.md markdown file."""
    lines = [
        "# MEMORY.md",
        "",
        f"Exported at: {payload.get('exported_at', '?')}",
        f"Owner ID: {payload.get('owner_id', '?')}",
        "",
    ]

    # Lessons
    lessons = payload.get("lessons", [])
    if lessons:
        lines.append("## Lessons Learned")
        lines.append("")
        for i, lsn in enumerate(lessons, 1):
            text = lsn.get("lesson", "").strip()
            ctx = lsn.get("context", "").strip()
            lines.append(f"### Lesson {i}")
            lines.append("")
            lines.append(text)
            if ctx:
                lines.append(f"\n> Context: {ctx}")
            lines.append("")

    # Research Notes
    notes = payload.get("research_notes", [])
    if notes:
        lines.append("## Research Notes")
        lines.append("")
        for n in notes:
            topic = n.get("topic", "Untitled")
            summary = n.get("summary", "")
            sources = n.get("sources", [])
            tags = n.get("tags", [])
            created = n.get("created_at", "")
            lines.append(f"### {topic}")
            if created:
                lines.append(f"*{created}*")
            lines.append("")
            lines.append(summary)
            if tags:
                lines.append(f"\nTags: {', '.join(str(t) for t in tags)}")
            if sources:
                lines.append("\nSources:")
                for src in sources[:5]:
                    lines.append(f"- {src}")
            lines.append("")

    # Conversation Summaries
    summaries = payload.get("conversation_summaries", [])
    if summaries:
        lines.append("## Conversation Summaries")
        lines.append("")
        for s in summaries:
            summary = s.get("summary", "")
            key_points = s.get("key_points", [])
            open_loops = s.get("open_loops", [])
            created = s.get("created_at", "")
            lines.append(f"### Summary (messages {s.get('start_message_id', '?')}-{s.get('end_message_id', '?')})")
            if created:
                lines.append(f"*{created}*")
            lines.append("")
            lines.append(summary)
            if key_points:
                lines.append("\nKey points:")
                for kp in key_points:
                    lines.append(f"- {kp}")
            if open_loops:
                lines.append("\nOpen loops:")
                for ol in open_loops:
                    lines.append(f"- {ol}")
            lines.append("")

    # Stats
    lines.append("---")
    lines.append(f"Total: {len(lessons)} lessons, {len(notes)} research notes, {len(summaries)} summaries")
    lines.append("")

    return "\n".join(lines)


def export_as_json(payload: Dict[str, Any]) -> str:
    """Convert a memory export payload to formatted JSON."""
    return json.dumps(payload, indent=2, ensure_ascii=False)

"""Learning Engine - post-conversation reflection and lesson extraction. Pillar: Learning."""
from __future__ import annotations
import logging
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from ..core.state import increment_runtime_state, set_runtime_state_value
from ..utils import truncate_text, utc_now_iso
logger = logging.getLogger("mind_clone.agent.learning")
MIN_MESSAGES_FOR_REFLECTION = 4

def post_conversation_reflection(db: Session, owner_id: int, msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(msgs) < MIN_MESSAGES_FOR_REFLECTION:
        return {"ok": True, "lessons": 0, "reason": "conversation_too_short"}
    try:
        extracted = _extract_lessons(msgs)
        if not extracted: return {"ok": True, "lessons": 0, "reason": "no_lessons_found"}
        from .memory import store_lesson
        stored = sum(1 for t in extracted[:3] if store_lesson(db, owner_id, t))
        increment_runtime_state("learning_reflections_total")
        increment_runtime_state("learning_lessons_extracted", stored)
        set_runtime_state_value("learning_last_reflection_at", utc_now_iso())
        return {"ok": True, "lessons": stored}
    except Exception as exc:
        logger.warning("LEARNING_REFLECTION_FAIL owner=%d error=%s", owner_id, str(exc)[:200])
        return {"ok": False, "lessons": 0, "error": str(exc)[:200]}

def _extract_lessons(msgs):
    lessons, tc, fails, corr = [], {}, [], []
    for i, m in enumerate(msgs):
        role, content = m.get("role",""), str(m.get("content",""))
        if role == "assistant" and m.get("tool_calls"):
            for t in m["tool_calls"]: n = t.get("function",{}).get("name","?"); tc[n] = tc.get(n,0)+1
        if role == "tool" and any(k in content.lower() for k in ("error","failed",'"ok": false')): fails.append(content[:100])
        if role == "user" and i > 0 and any(s in content.lower() for s in ("no,","not that","actually","wrong","instead")): corr.append(content[:150])
    for n, c in sorted(tc.items(), key=lambda x: -x[1]):
        if c >= 3: lessons.append(f"Tool '{n}' used {c}x - key for this task.")
    if fails: lessons.append(f"{len(fails)} tool failures. First: {fails[0]}")
    for c in corr[:2]: lessons.append(f"User correction: {c}")
    return lessons

def consolidate_memory(db: Session, owner_id: int) -> Dict[str, Any]:
    from ..database.models import MemoryVector
    try:
        rows = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id).order_by(MemoryVector.id.desc()).limit(500).all()
        if len(rows) < 10: return {"ok": True, "pruned": 0, "reason": "too_few_entries"}
        pruned, seen, to_del = 0, [], []
        for row in rows:
            text = (row.text_preview or "").strip()
            if not text: to_del.append(row.id); pruned += 1; continue
            dup = False
            for s in seen:
                wa, wb = set(text.lower().split()), set(s.lower().split())
                if wa and wb and len(wa & wb) / len(wa | wb) > 0.85: dup = True; break
            if dup: to_del.append(row.id); pruned += 1
            else: seen.append(text)
        if to_del: db.query(MemoryVector).filter(MemoryVector.id.in_(to_del)).delete(synchronize_session="fetch"); db.commit()
        increment_runtime_state("memory_consolidations_total")
        set_runtime_state_value("memory_consolidation_last_at", utc_now_iso())
        return {"ok": True, "total": len(rows), "pruned": pruned}
    except Exception as exc:
        logger.warning("MEMORY_CONSOLIDATION_FAIL owner=%d error=%s", owner_id, str(exc)[:200])
        db.rollback()
        return {"ok": False, "pruned": 0, "error": str(exc)[:200]}

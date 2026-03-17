"""World Model - Bob's internal world state tracker. Pillar: World Understanding."""
from __future__ import annotations
import logging, re
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from ..core.state import increment_runtime_state, set_runtime_state_value
from ..database.models import MemoryVector
from ..utils import truncate_text, utc_now_iso
logger = logging.getLogger("mind_clone.agent.world_model")

def update_world_model(db: Session, owner_id: int, assistant_text: str, user_message: str) -> Dict[str, Any]:
    if not assistant_text or len(assistant_text.strip()) < 30:
        return {"ok": True, "stored": 0, "reason": "response_too_short"}
    try:
        facts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", assistant_text)
                 if 20 <= len(s.strip()) <= 300 and not s.strip().endswith("?")
                 and any(k in s.lower() for k in ("is","are","was","were","founded","created","located","currently"))][:5]
        if not facts:
            return {"ok": True, "stored": 0, "reason": "no_facts_found"}
        from .vectors import get_embedding, embedding_to_bytes
        stored = 0
        for fact in facts:
            text = truncate_text(fact, 500)
            db.add(MemoryVector(owner_id=owner_id, memory_type="world", text_preview=text, embedding=embedding_to_bytes(get_embedding(text))))
            stored += 1
        if stored:
            db.commit()
            increment_runtime_state("world_model_updates_total")
            increment_runtime_state("world_model_entities_tracked", stored)
            set_runtime_state_value("world_model_last_update_at", utc_now_iso())
        return {"ok": True, "stored": stored}
    except Exception as exc:
        logger.warning("WORLD_MODEL_UPDATE_FAIL owner=%d error=%s", owner_id, str(exc)[:200])
        db.rollback()
        return {"ok": False, "stored": 0, "error": str(exc)[:200]}

def query_world_model(db: Session, owner_id: int, query: str, top_k: int = 5):
    from .memory import search_memory_vectors
    return search_memory_vectors(db, owner_id, query, top_k=top_k, category="world")

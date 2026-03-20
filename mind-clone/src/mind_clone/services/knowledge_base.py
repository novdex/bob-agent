"""
Long-context RAG Knowledge Base — Bob never forgets.

Stores documents, conversations, research with vector embeddings.
Semantic search retrieves relevant chunks at query time.
Uses existing GloVe vectors + MemoryVector DB table.
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from ..database.models import MemoryVector, ResearchNote
from ..database.session import SessionLocal
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.knowledge_base")


def store_document(owner_id: int, text: str, doc_type: str = "document",
                   ref_id: int = 0, metadata: dict = None) -> bool:
    """Store a document chunk with its embedding."""
    try:
        from ..agent.vectors import get_embedding, embedding_to_bytes
        embedding = get_embedding(text[:500])
        vec_bytes = embedding_to_bytes(embedding)
        db = SessionLocal()
        try:
            mv = MemoryVector(
                owner_id=owner_id,
                memory_type=doc_type,
                ref_id=ref_id,
                text_preview=truncate_text(text, 200),
                embedding=vec_bytes,
            )
            db.add(mv); db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.debug("STORE_DOC_FAIL: %s", str(e)[:80])
        return False


def semantic_search(owner_id: int, query: str, top_k: int = 5,
                    doc_type: str = None) -> list[dict]:
    """Search knowledge base by semantic similarity."""
    try:
        from ..agent.vectors import get_embedding, cosine_similarity, bytes_to_embedding
        import numpy as np
        query_vec = get_embedding(query)
        db = SessionLocal()
        try:
            q = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id)
            if doc_type:
                q = q.filter(MemoryVector.memory_type == doc_type)
            rows = q.limit(500).all()
            scored = []
            for row in rows:
                try:
                    vec = bytes_to_embedding(row.embedding)
                    sim = cosine_similarity(query_vec, vec)
                    scored.append((sim, row))
                except Exception:
                    pass
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"text": r.text_preview, "type": r.memory_type,
                 "ref_id": r.ref_id, "similarity": round(sim, 3)}
                for sim, r in scored[:top_k]
            ]
        finally:
            db.close()
    except Exception as e:
        logger.debug("SEMANTIC_SEARCH_FAIL: %s", str(e)[:80])
        return []


def ingest_research_notes(owner_id: int) -> int:
    """Index all ResearchNotes into the knowledge base."""
    db = SessionLocal()
    try:
        notes = db.query(ResearchNote).filter(ResearchNote.owner_id == owner_id).all()
        count = 0
        for note in notes:
            text = f"{note.topic}: {note.summary}"
            if store_document(owner_id, text, "research_note", note.id):
                count += 1
        logger.info("RAG_INGESTED count=%d", count)
        return count
    finally:
        db.close()


def tool_rag_search(args: dict) -> dict:
    """Tool: Semantic search across Bob's knowledge base."""
    owner_id = int(args.get("_owner_id", 1))
    query = str(args.get("query", "")).strip()
    top_k = min(int(args.get("top_k", 5)), 20)
    doc_type = args.get("doc_type")
    if not query:
        return {"ok": False, "error": "query required"}
    results = semantic_search(owner_id, query, top_k, doc_type)
    return {"ok": True, "query": query, "results": results, "count": len(results)}


def tool_rag_ingest(args: dict) -> dict:
    """Tool: Index all ResearchNotes into the semantic knowledge base."""
    owner_id = int(args.get("_owner_id", 1))
    count = ingest_research_notes(owner_id)
    return {"ok": True, "indexed": count}


def tool_rag_store(args: dict) -> dict:
    """Tool: Store a document or text in the knowledge base."""
    owner_id = int(args.get("_owner_id", 1))
    text = str(args.get("text", "")).strip()
    doc_type = str(args.get("doc_type", "document"))
    if not text:
        return {"ok": False, "error": "text required"}
    ok = store_document(owner_id, text, doc_type)
    return {"ok": ok, "stored": ok}

"""
Memory and research tools (search, semantic search, PDF reading).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import or_

from ..database.models import ResearchNote
from ..database.session import SessionLocal
from ..utils import _safe_json_list, truncate_text

logger = logging.getLogger("mind_clone.tools.memory")


def tool_research_memory_search(args: dict) -> dict:
    """Search research notes by keyword."""
    query = str(args.get("query", "")).strip()
    top_k = int(args.get("top_k", 5))
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if not query:
        return {"ok": False, "error": "query is required"}

    db = SessionLocal()
    try:
        pattern = f"%{query}%"
        q = db.query(ResearchNote)
        if owner_id is not None:
            q = q.filter(ResearchNote.owner_id == int(owner_id))
        rows = (
            q.filter(or_(ResearchNote.topic.ilike(pattern), ResearchNote.summary.ilike(pattern)))
            .order_by(ResearchNote.id.desc())
            .limit(max(1, min(50, top_k)))
            .all()
        )
        results = []
        for row in rows:
            results.append(
                {
                    "id": int(row.id),
                    "topic": str(row.topic),
                    "summary": truncate_text(str(row.summary or ""), 1200),
                    "sources": _safe_json_list(row.sources_json, []),
                    "tags": _safe_json_list(row.tags_json, []),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return {"ok": True, "query": query, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def tool_semantic_memory_search(args: dict) -> dict:
    """Lightweight semantic-like search using token overlap across research notes."""
    query = str(args.get("query", "")).strip()
    top_k = int(args.get("top_k", 5))
    memory_type = args.get("memory_type", "all")
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if not query:
        return {"ok": False, "error": "query is required"}

    query_terms = {t for t in query.lower().split() if t}
    if not query_terms:
        return {"ok": True, "query": query, "memory_type": memory_type, "results": []}

    db = SessionLocal()
    try:
        q = db.query(ResearchNote)
        if owner_id is not None:
            q = q.filter(ResearchNote.owner_id == int(owner_id))
        rows = q.order_by(ResearchNote.id.desc()).limit(200).all()
        scored = []
        for row in rows:
            corpus = f"{row.topic or ''} {row.summary or ''}".lower()
            corpus_terms = {t for t in corpus.split() if t}
            if not corpus_terms:
                continue
            overlap = len(query_terms & corpus_terms)
            if overlap <= 0:
                continue
            score = overlap / max(1, len(query_terms))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, row in scored[: max(1, min(50, top_k))]:
            results.append(
                {
                    "id": int(row.id),
                    "memory_type": "research_note",
                    "topic": str(row.topic),
                    "summary": truncate_text(str(row.summary or ""), 1200),
                    "score": round(float(score), 4),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return {"ok": True, "query": query, "memory_type": memory_type, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def tool_read_pdf_url(args: dict) -> dict:
    """Read text from a PDF URL."""
    url = str(args.get("url", "")).strip()
    max_pages = int(args.get("max_pages", 20))

    if not url:
        return {"ok": False, "error": "url is required"}

    from ..core.security import apply_url_safety_guard, circuit_allow_call, circuit_record_success, circuit_record_failure
    allowed, cb_reason = circuit_allow_call("web_fetch")
    if not allowed:
        return {"ok": False, "error": cb_reason, "url": url}
    safe_ok, safe_reason = apply_url_safety_guard(url, source="read_pdf_url")
    if not safe_ok:
        return {"ok": False, "error": safe_reason, "url": url}

    try:
        import requests
        from io import BytesIO

        try:
            from pypdf import PdfReader
        except ImportError:
            return {"ok": False, "error": "pypdf is not installed"}

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        pdf_file = BytesIO(response.content)
        reader = PdfReader(pdf_file)

        text_parts = []
        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text()
            if text:
                text_parts.append(f"--- Page {i + 1} ---\n{text}")

        full_text = "\n\n".join(text_parts)

        circuit_record_success("web_fetch")
        return {
            "ok": True,
            "url": url,
            "pages_read": min(len(reader.pages), max_pages),
            "total_pages": len(reader.pages),
            "text": full_text[:50000],  # Limit output
        }
    except Exception as e:
        circuit_record_failure("web_fetch", str(e))
        return {"ok": False, "error": str(e)}


def tool_save_research_note(args: dict) -> dict:
    """Save a research note to memory."""
    topic = str(args.get("topic", "")).strip()
    summary = str(args.get("summary", "")).strip()
    source_url = str(args.get("source_url", "")).strip()
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if not topic or not summary:
        return {"ok": False, "error": "topic and summary are required"}

    db = SessionLocal()
    try:
        source_items = []
        if source_url:
            source_items.append(source_url)
        note = ResearchNote(
            owner_id=int(owner_id or 1),
            topic=truncate_text(topic, 200),
            summary=truncate_text(summary, 8000),
            sources_json=json.dumps(source_items),
            tags_json="[]",
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return {
            "ok": True,
            "saved": True,
            "note_id": int(note.id),
            "topic": str(note.topic),
        }
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()

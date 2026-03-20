"""
Continuous Learning from Internet — Bob learns autonomously.

Monitors: arXiv, GitHub trending, Hacker News, tech news.
Extracts insights, stores in knowledge graph.
Runs every 6 hours. Never stops learning.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone, timedelta
from ..database.models import ResearchNote, ScheduledJob
from ..database.session import SessionLocal
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.continuous_learner")

_LEARNING_SOURCES = [
    {"name": "arXiv AI", "query": "arxiv.org AI agents 2026 new paper"},
    {"name": "GitHub Trending", "query": "github.com trending AI repositories this week"},
    {"name": "HN Tech", "query": "site:news.ycombinator.com AI agents autonomous 2026"},
]


def learn_from_source(source: dict, owner_id: int = 1) -> Optional[dict]:
    """Fetch and learn from a single source."""
    from ..tools.basic import tool_search_web
    from ..agent.llm import call_llm

    results = tool_search_web({"query": source["query"], "num_results": 4})
    if not results.get("ok"):
        return None
    items = results.get("results", [])[:3]
    if not items:
        return None

    snippets = "\n".join(f"- {r.get('title','')}: {r.get('snippet','')[:150]}" for r in items)
    prompt = [{"role": "user", "content":
        f"Extract the 2-3 most important new learnings from these search results.\n"
        f"Source: {source['name']}\n\nResults:\n{snippets}\n\n"
        f"Write 2-3 bullet points of specific new knowledge. Be concrete."}]
    try:
        result = call_llm(prompt, temperature=0.3)
        insights = ""
        if isinstance(result, dict) and result.get("ok"):
            insights = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                insights = choices[0].get("message", {}).get("content", insights)
        if not insights or len(insights) < 20:
            return None

        # Store as ResearchNote
        db = SessionLocal()
        try:
            note = ResearchNote(
                owner_id=owner_id,
                topic=f"Auto-learned: {source['name']} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                summary=truncate_text(insights, 1000),
                sources_json=json.dumps([r.get("url", "") for r in items]),
                tags_json=json.dumps(["continuous_learning", source["name"]]),
            )
            db.add(note); db.commit(); db.refresh(note)
            # Auto-link in memory graph
            try:
                from .memory_graph import auto_link
                auto_link(db, owner_id, "research_note", note.id)
            except Exception:
                pass
            return {"source": source["name"], "note_id": note.id, "insights_preview": insights[:100]}
        finally:
            db.close()
    except Exception as e:
        logger.debug("LEARN_SOURCE_FAIL: %s", str(e)[:80])
        return None


def run_learning_cycle(owner_id: int = 1) -> dict:
    """Run one learning cycle across all sources."""
    learned = []
    for source in _LEARNING_SOURCES:
        result = learn_from_source(source, owner_id)
        if result:
            learned.append(result)
    logger.info("LEARNING_CYCLE learned=%d sources", len(learned))
    return {"ok": True, "sources_processed": len(_LEARNING_SOURCES), "new_learnings": len(learned), "details": learned}


def ensure_learning_job(db, owner_id: int = 1) -> None:
    """Ensure 6-hourly learning job exists."""
    existing = db.query(ScheduledJob).filter(
        ScheduledJob.name == "continuous_learning", ScheduledJob.owner_id == owner_id
    ).first()
    if existing:
        return
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    job = ScheduledJob(
        owner_id=owner_id, name="continuous_learning",
        message="Run continuous learning cycle: learn from arXiv, GitHub trending, and tech news. Store insights as ResearchNotes.",
        lane="cron", interval_seconds=21600,
        next_run_at=now + timedelta(hours=6), enabled=1, run_count=0,
    )
    db.add(job); db.commit()
    logger.info("LEARNING_JOB created")


def tool_run_learning(args: dict) -> dict:
    """Tool: Run a continuous learning cycle right now."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        return run_learning_cycle(owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


from typing import Optional

"""
Proactive Autonomous Research — Bob researches without being asked.

Every morning Bob:
1. Reads user's interests from profile
2. Searches for latest news/developments on each topic
3. Compiles a personalised briefing
4. Sends it to Telegram proactively

Also: when Bob notices a gap in his knowledge during a task,
he researches it immediately and stores the findings.
"""
from __future__ import annotations
import json
import logging
import threading
from datetime import datetime, timezone
from ..database.session import SessionLocal
from ..database.models import ScheduledJob, ResearchNote
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.autonomous_research")

_DEFAULT_TOPICS = ["AI agents", "autonomous systems", "open source AI", "machine learning research"]


def research_topic_live(topic: str, owner_id: int = 1) -> Optional[str]:
    """Research a topic right now and return a summary."""
    from ..tools.basic import tool_search_web, tool_read_webpage
    results = tool_search_web({"query": f"{topic} latest 2026", "num_results": 4})
    if not results.get("ok"):
        return None
    items = results.get("results", [])[:3]
    if not items:
        return None
    snippets = "\n".join(f"- {r.get('title','')}: {r.get('snippet','')[:150]}" for r in items)
    return truncate_text(snippets, 600)


def run_morning_briefing(owner_id: int = 1) -> dict:
    """Run the morning research briefing and send to Telegram."""
    from .user_profile import _load_profile
    from .proactive import send_telegram_message
    from ..agent.llm import call_llm

    profile = _load_profile(owner_id)
    topics = profile.get("interests", _DEFAULT_TOPICS)[:4]

    sections = []
    for topic in topics:
        summary = research_topic_live(topic, owner_id)
        if summary:
            sections.append(f"*{topic}:*\n{summary}")
            # Save as ResearchNote
            db = SessionLocal()
            try:
                note = ResearchNote(
                    owner_id=owner_id,
                    topic=f"Morning briefing: {topic}",
                    summary=summary,
                    sources_json=json.dumps([]),
                    tags_json=json.dumps(["morning_briefing", topic]),
                )
                db.add(note); db.commit()
            except Exception:
                pass
            finally:
                db.close()

    if not sections:
        return {"ok": False, "error": "No research results"}

    now = datetime.now(timezone.utc).strftime("%A %B %d, %Y")
    msg = f"🌅 *Morning Research Briefing — {now}*\n\n" + "\n\n".join(sections)
    send_telegram_message(owner_id, truncate_text(msg, 3000))
    return {"ok": True, "topics_researched": len(sections)}


def ensure_morning_briefing_job(db, owner_id: int = 1) -> None:
    """Create daily 7am morning briefing job if it doesn't exist."""
    from datetime import timedelta
    existing = db.query(ScheduledJob).filter(
        ScheduledJob.name == "morning_briefing",
        ScheduledJob.owner_id == owner_id,
    ).first()
    if existing:
        return
    now = datetime.now(timezone.utc)
    next_7am = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if next_7am <= now:
        next_7am += timedelta(days=1)
    job = ScheduledJob(
        owner_id=owner_id,
        name="morning_briefing",
        message="Run the morning research briefing: search for latest news on my interests and send a summary to Telegram using the proactive briefing system.",
        lane="cron",
        interval_seconds=86400,
        next_run_at=next_7am,
        enabled=1,
        run_count=0,
    )
    db.add(job); db.commit()
    logger.info("MORNING_BRIEFING_JOB created next_run=%s", next_7am.isoformat())


def tool_run_briefing(args: dict) -> dict:
    """Tool: Run the morning research briefing right now."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        return run_morning_briefing(owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


from typing import Optional

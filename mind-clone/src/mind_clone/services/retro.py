"""
Self-Awareness Retro Engine — Bob reviews himself.

Garry Tan's /retro gives stats (LOC, commits, net delta).
Bob's retro does the same for his own mind:

- How many conversations? How many messages?
- Which tools did he use most? Which failed?
- What corrections did Arsh make? (patterns of being wrong)
- What did he learn? (self-improvement notes)
- What goals ran? What completed vs failed?
- What should he change about himself?

The retro runs daily as a scheduled job, generates a rich
analysis via Kimi K2.5, saves SelfImprovementNote records,
and sends the summary to Arsh's Telegram.

Also callable by Bob directly when asked: "run your retro"
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from ..database.models import (
    ConversationMessage,
    SelfImprovementNote,
    ScheduledJob,
    ToolPerformanceLog,
    EpisodicMemory,
    ResearchNote,
    User,
)
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.retro")

RETRO_DEFAULT_OWNER_ID = int(os.getenv("RETRO_DEFAULT_OWNER_ID", "1"))
RETRO_INTERVAL_HOURS = int(os.getenv("RETRO_INTERVAL_HOURS", "24"))
RETRO_JOB_NAME = "daily_retro"
RETRO_JOB_MESSAGE = (
    "[RETRO] Run your daily self-awareness retro. Review your recent performance, "
    "identify patterns, extract lessons, and report what you found. "
    "Be honest about what worked and what didn't."
)

# ---------------------------------------------------------------------------
# Raw stats collection
# ---------------------------------------------------------------------------


def collect_stats(db: Session, owner_id: int, hours: int = 24) -> Dict[str, Any]:
    """Collect raw performance stats for the retro window."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Message counts
    total_msgs = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.owner_id == owner_id)
        .count()
    )
    recent_msgs = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.owner_id == owner_id,
            ConversationMessage.created_at >= since,
        )
        .count()
    )
    user_msgs = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.owner_id == owner_id,
            ConversationMessage.role == "user",
            ConversationMessage.created_at >= since,
        )
        .count()
    )
    assistant_msgs = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.owner_id == owner_id,
            ConversationMessage.role == "assistant",
            ConversationMessage.created_at >= since,
        )
        .count()
    )

    # Tool usage
    tool_rows = (
        db.query(ToolPerformanceLog)
        .filter(
            ToolPerformanceLog.owner_id == owner_id,
            ToolPerformanceLog.created_at >= since,
        )
        .all()
    )
    tool_counts: Dict[str, int] = {}
    tool_failures: Dict[str, int] = {}
    for row in tool_rows:
        tool_counts[row.tool_name] = tool_counts.get(row.tool_name, 0) + 1
        if not row.success:
            tool_failures[row.tool_name] = tool_failures.get(row.tool_name, 0) + 1

    top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
    top_failures = sorted(tool_failures.items(), key=lambda x: -x[1])[:3]

    # Self-improvement notes (open ones = things still to fix)
    open_notes = (
        db.query(SelfImprovementNote)
        .filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.status == "open",
        )
        .order_by(SelfImprovementNote.created_at.desc())
        .limit(5)
        .all()
    )

    # Research notes created recently
    research_count = (
        db.query(ResearchNote)
        .filter(
            ResearchNote.owner_id == owner_id,
            ResearchNote.created_at >= since,
        )
        .count()
    )

    # Episodic memories (outcomes)
    episodes = (
        db.query(EpisodicMemory)
        .filter(
            EpisodicMemory.owner_id == owner_id,
            EpisodicMemory.created_at >= since,
        )
        .all()
    )
    success_episodes = sum(1 for e in episodes if e.outcome == "success")
    fail_episodes = sum(1 for e in episodes if e.outcome == "failure")

    # User corrections (messages containing correction phrases)
    recent_user_msgs = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.owner_id == owner_id,
            ConversationMessage.role == "user",
            ConversationMessage.created_at >= since,
        )
        .order_by(ConversationMessage.id.desc())
        .limit(100)
        .all()
    )
    correction_phrases = ("no,", "not that", "actually", "wrong", "instead", "that's not", "you're wrong", "incorrect")
    corrections = [
        truncate_text(m.content or "", 150)
        for m in recent_user_msgs
        if any(p in (m.content or "").lower() for p in correction_phrases)
    ][:5]

    # Scheduled jobs (proactive work done)
    cron_jobs = (
        db.query(ScheduledJob)
        .filter(ScheduledJob.owner_id == owner_id)
        .all()
    )
    total_cron_runs = sum(j.run_count or 0 for j in cron_jobs)

    return {
        "window_hours": hours,
        "total_messages_alltime": total_msgs,
        "recent_messages": recent_msgs,
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "top_tools": [{"tool": t, "uses": c} for t, c in top_tools],
        "tool_failures": [{"tool": t, "failures": c} for t, c in top_failures],
        "open_self_improvement_notes": [
            {"title": n.title, "priority": n.priority, "summary": truncate_text(n.summary, 200)}
            for n in open_notes
        ],
        "research_notes_created": research_count,
        "episodes_success": success_episodes,
        "episodes_fail": fail_episodes,
        "user_corrections": corrections,
        "total_cron_runs": total_cron_runs,
    }


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

_RETRO_SYSTEM = (
    "You are Bob, an autonomous AI agent. You are running your daily self-awareness retro. "
    "Be honest, direct, and analytical. This is for your own growth — not for show."
)

_RETRO_PROMPT = """Here are your performance stats for the last {hours} hours:

{stats_json}

Based on these stats, write a self-awareness retro report covering:

1. **What I did** — brief summary of activity (messages, tools, research)
2. **What worked** — tools/approaches that performed well
3. **What didn't work** — failures, corrections from Arsh, gaps
4. **Patterns I notice** — anything repeating (good or bad)
5. **What I'm changing** — 2-3 concrete action items for improvement
6. **Open loops** — things still outstanding from previous retros

Be specific. Use numbers from the stats. Keep it under 400 words.
Format with the numbered headers above."""


def _build_retro_prompt(stats: Dict[str, Any]) -> str:
    return _RETRO_PROMPT.format(
        hours=stats.get("window_hours", 24),
        stats_json=json.dumps(stats, indent=2),
    )


def run_retro_analysis(stats: Dict[str, Any]) -> Optional[str]:
    """Run the retro analysis via Kimi K2.5."""
    try:
        from ..agent.llm import call_llm
        result = call_llm(
            messages=[
                {"role": "system", "content": _RETRO_SYSTEM},
                {"role": "user", "content": _build_retro_prompt(stats)},
            ],
            timeout=90,
        )
        if result.get("ok"):
            return (result.get("content") or "").strip()
        logger.warning("RETRO_LLM_FAIL: %s", result.get("error", "unknown"))
        return None
    except Exception as e:
        logger.error("RETRO_ANALYSIS_FAIL: %s", str(e)[:200])
        return None


# ---------------------------------------------------------------------------
# Save findings as SelfImprovementNote
# ---------------------------------------------------------------------------


def save_retro_note(db: Session, owner_id: int, analysis: str, stats: Dict[str, Any]) -> bool:
    """Save the retro analysis as a SelfImprovementNote."""
    try:
        now = datetime.now(timezone.utc)
        title = f"Daily Retro — {now.strftime('%Y-%m-%d %H:%M UTC')}"

        # Extract action items (lines starting with numbers under section 5)
        actions = []
        in_actions = False
        for line in analysis.split("\n"):
            stripped = line.strip()
            if "what i'm changing" in stripped.lower() or "5." in stripped:
                in_actions = True
                continue
            if in_actions and stripped.startswith("6."):
                break
            if in_actions and stripped and len(stripped) > 10:
                actions.append(stripped[:200])

        note = SelfImprovementNote(
            owner_id=owner_id,
            title=title,
            summary=truncate_text(analysis, 2000),
            actions_json=json.dumps(actions[:5]),
            evidence_json=json.dumps({
                "window_hours": stats.get("window_hours"),
                "messages": stats.get("recent_messages"),
                "corrections": len(stats.get("user_corrections", [])),
                "tool_failures": len(stats.get("tool_failures", [])),
            }),
            priority="medium",
            status="open",
        )
        db.add(note)
        db.commit()
        logger.info("RETRO_NOTE_SAVED owner=%d title=%s", owner_id, title)
        return True
    except Exception as e:
        db.rollback()
        logger.error("RETRO_NOTE_SAVE_FAIL: %s", str(e)[:200])
        return False


# ---------------------------------------------------------------------------
# Full retro run
# ---------------------------------------------------------------------------


async def run_full_retro(owner_id: int, send_to_telegram: bool = True) -> Dict[str, Any]:
    """Run the full retro: collect stats → analyse → save → report.

    Returns:
        Dict with keys: ok, analysis, stats, sent
    """
    db = SessionLocal()
    try:
        stats = collect_stats(db, owner_id, hours=RETRO_INTERVAL_HOURS)
    finally:
        db.close()

    logger.info(
        "RETRO_START owner=%d msgs=%d tools=%d corrections=%d",
        owner_id,
        stats.get("recent_messages", 0),
        len(stats.get("top_tools", [])),
        len(stats.get("user_corrections", [])),
    )

    analysis = run_retro_analysis(stats)
    if not analysis:
        return {"ok": False, "error": "LLM analysis failed"}

    db = SessionLocal()
    try:
        save_retro_note(db, owner_id, analysis, stats)
    finally:
        db.close()

    sent = False
    if send_to_telegram:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        message = (
            f"🧠 *Bob — Daily Retro* ({now})\n\n"
            f"{truncate_text(analysis, 3500)}\n\n"
            f"_Stats: {stats['recent_messages']} msgs · "
            f"{stats['episodes_success']}✅ {stats['episodes_fail']}❌ episodes · "
            f"{stats['research_notes_created']} research notes_"
        )
        try:
            from .proactive import send_proactive_message
            sent = await send_proactive_message(owner_id, message, context="retro")
        except Exception as e:
            logger.warning("RETRO_SEND_FAIL: %s", str(e)[:200])

    return {"ok": True, "analysis": analysis, "stats": stats, "sent": sent}


# ---------------------------------------------------------------------------
# Seed the daily retro scheduled job
# ---------------------------------------------------------------------------


def ensure_retro_job_seeded(owner_id: int = RETRO_DEFAULT_OWNER_ID) -> bool:
    """Seed the daily retro scheduled job if it doesn't exist."""
    db = SessionLocal()
    try:
        existing = (
            db.query(ScheduledJob)
            .filter(
                ScheduledJob.owner_id == owner_id,
                ScheduledJob.name == RETRO_JOB_NAME,
                ScheduledJob.enabled.is_(True),
            )
            .first()
        )
        if existing:
            return False

        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            return False
        try:
            if abs(int(user.telegram_chat_id)) < 10000:
                return False
        except ValueError:
            return False

        now = datetime.now(timezone.utc)
        interval = RETRO_INTERVAL_HOURS * 3600
        # First retro fires at midnight UTC tonight
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        job = ScheduledJob(
            owner_id=owner_id,
            name=RETRO_JOB_NAME,
            message=RETRO_JOB_MESSAGE,
            lane="cron",
            interval_seconds=interval,
            enabled=True,
            run_count=0,
            next_run_at=tomorrow_midnight,
        )
        db.add(job)
        db.commit()
        logger.info(
            "RETRO_JOB_SEEDED owner=%d interval_hours=%d first_run=%s",
            owner_id,
            RETRO_INTERVAL_HOURS,
            tomorrow_midnight.isoformat(),
        )
        return True
    except Exception as e:
        db.rollback()
        logger.error("RETRO_JOB_SEED_FAIL: %s", str(e)[:200])
        return False
    finally:
        db.close()

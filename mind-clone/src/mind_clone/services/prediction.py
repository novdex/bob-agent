"""
Predictive Intelligence Engine — Bob anticipates before being asked.

This is the gap between reactive (responds to prompts) and predictive
(notices patterns, anticipates needs, acts ahead of time).

Three components:

1. PatternTracker — analyses conversation history to find recurring
   topics, interests, and needs. Runs after each message.

2. PredictiveContextInjector — before Bob replies, injects a hint
   about the user's known patterns so he can proactively offer more.

3. PredictiveScheduler — seeds scheduled jobs for things Arsh asks
   about repeatedly (e.g. Iran war 5x → auto-create news alert job).

This hooks into the agent loop at two points:
- Before LLM call: inject pattern context
- After assistant reply: update pattern tracker
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database.models import ConversationMessage, SelfImprovementNote, ScheduledJob, User
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.prediction")

PREDICTION_ENABLED: bool = os.getenv("PREDICTION_ENABLED", "true").lower() in {"1", "true", "yes"}
PATTERN_WINDOW_MESSAGES = int(os.getenv("PATTERN_WINDOW_MESSAGES", "200"))
PATTERN_REPEAT_THRESHOLD = int(os.getenv("PATTERN_REPEAT_THRESHOLD", "3"))  # 3+ = notable pattern
AUTO_SCHEDULE_THRESHOLD = int(os.getenv("AUTO_SCHEDULE_THRESHOLD", "4"))    # 4+ = auto-schedule

# ---------------------------------------------------------------------------
# Topic classification
# ---------------------------------------------------------------------------

TOPIC_PATTERNS: List[Tuple[str, List[str]]] = [
    ("iran_war",        ["iran", "war with usa", "middle east conflict"]),
    ("ai_news",         ["ai news", "artificial intelligence", "llm", "openai", "anthropic", "gemini", "gpt"]),
    ("crypto",          ["crypto", "bitcoin", "ethereum", "trading", "price alert"]),
    ("bob_project",     ["bob", "agi", "mind clone", "autonomous agent"]),
    ("news_alerts",     ["news", "alert", "update", "every 5 minutes", "notify me"]),
    ("cron_jobs",       ["cron", "scheduled", "every hour", "daily", "remind me"]),
    ("coding",          ["build", "code", "implement", "debug", "fix", "script"]),
    ("research",        ["research", "find out", "look up", "search", "what is"]),
    ("business",        ["revenue", "money", "startup", "product", "market"]),
    ("health",          ["sleep", "exercise", "diet", "health", "tired"]),
]


def classify_topics(text: str) -> List[str]:
    """Return list of topic labels that match the text."""
    text_lower = text.lower()
    matched = []
    for topic, keywords in TOPIC_PATTERNS:
        if any(kw in text_lower for kw in keywords):
            matched.append(topic)
    return matched


# ---------------------------------------------------------------------------
# Pattern Tracker
# ---------------------------------------------------------------------------


def get_user_patterns(db: Session, owner_id: int, window: int = PATTERN_WINDOW_MESSAGES) -> Dict[str, Any]:
    """Analyse recent conversation history for recurring topics and interests.

    Returns:
        Dict with keys:
        - topic_counts: {topic: count}
        - top_topics: [(topic, count)] sorted descending
        - notable: topics that exceed PATTERN_REPEAT_THRESHOLD
        - auto_schedulable: topics that exceed AUTO_SCHEDULE_THRESHOLD
        - recent_requests: last 5 user messages (raw)
    """
    msgs = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.owner_id == owner_id,
            ConversationMessage.role == "user",
        )
        .order_by(ConversationMessage.id.desc())
        .limit(window)
        .all()
    )

    topic_counts: Dict[str, int] = {}
    recent_requests = []

    for msg in msgs:
        text = msg.content or ""
        # Skip system/internal messages
        if text.startswith("[") and "]" in text[:30]:
            continue
        topics = classify_topics(text)
        for t in topics:
            topic_counts[t] = topic_counts.get(t, 0) + 1
        if len(recent_requests) < 5 and text.strip():
            recent_requests.append(truncate_text(text, 120))

    top_topics = sorted(topic_counts.items(), key=lambda x: -x[1])
    notable = [(t, c) for t, c in top_topics if c >= PATTERN_REPEAT_THRESHOLD]
    auto_schedulable = [(t, c) for t, c in top_topics if c >= AUTO_SCHEDULE_THRESHOLD]

    return {
        "topic_counts": topic_counts,
        "top_topics": top_topics[:8],
        "notable": notable,
        "auto_schedulable": auto_schedulable,
        "recent_requests": list(reversed(recent_requests)),
    }


def save_pattern_note(db: Session, owner_id: int, patterns: Dict[str, Any]) -> bool:
    """Save pattern insights as a SelfImprovementNote if notable patterns exist."""
    notable = patterns.get("notable", [])
    if not notable:
        return False

    try:
        title = f"Pattern Update — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

        # Check if we already saved a pattern note today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        existing = (
            db.query(SelfImprovementNote)
            .filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.title.like("Pattern Update%"),
                SelfImprovementNote.created_at >= today_start,
            )
            .first()
        )
        if existing:
            return False

        top_str = ", ".join(f"{t}({c}x)" for t, c in notable[:5])
        summary = (
            f"Arsh's recurring interests detected: {top_str}. "
            f"These topics appear consistently — consider proactive monitoring or alerts."
        )
        actions = [
            f"Monitor '{t}' topic proactively (asked {c}x)" for t, c in notable[:3]
        ]

        note = SelfImprovementNote(
            owner_id=owner_id,
            title=title,
            summary=summary,
            actions_json=json.dumps(actions),
            evidence_json=json.dumps({"topic_counts": patterns["topic_counts"]}),
            priority="high" if len(notable) >= 3 else "medium",
            status="open",
        )
        db.add(note)
        db.commit()
        logger.info("PATTERN_NOTE_SAVED owner=%d topics=%s", owner_id, top_str)
        return True
    except Exception as e:
        db.rollback()
        logger.warning("PATTERN_NOTE_FAIL: %s", str(e)[:200])
        return False


# ---------------------------------------------------------------------------
# Predictive Context Injector
# ---------------------------------------------------------------------------


def build_predictive_context(patterns: Dict[str, Any]) -> Optional[str]:
    """Build a context hint to inject before Bob's LLM call.

    Tells Bob what Arsh cares about most so he can be more relevant.
    Returns None if no strong patterns found.
    """
    notable = patterns.get("notable", [])
    if not notable:
        return None

    top = notable[:3]
    topics_str = ", ".join(f"'{t}' ({c}x)" for t, c in top)
    recent = patterns.get("recent_requests", [])
    recent_str = "; ".join(recent[-3:]) if recent else "none"

    return (
        f"[PREDICTIVE CONTEXT] Arsh's recurring interests from conversation history: {topics_str}. "
        f"Recent messages: {recent_str}. "
        f"Where relevant, proactively offer to set up monitoring, alerts, or follow-ups for these topics. "
        f"Don't mention this system hint explicitly."
    )


def inject_predictive_context(
    db: Session,
    owner_id: int,
    user_message: str,
    messages: List[dict],
) -> bool:
    """Inject predictive context into the message list before LLM call.

    Returns True if context was injected.
    """
    if not PREDICTION_ENABLED:
        return False

    try:
        patterns = get_user_patterns(db, owner_id)
        context = build_predictive_context(patterns)
        if context:
            messages.append({"role": "system", "content": context})
            logger.debug("PREDICTIVE_CONTEXT_INJECTED owner=%d topics=%d",
                         owner_id, len(patterns.get("notable", [])))
            return True
    except Exception as e:
        logger.warning("PREDICTIVE_INJECT_FAIL: %s", str(e)[:200])
    return False


# ---------------------------------------------------------------------------
# Predictive Scheduler — auto-create jobs for repeated requests
# ---------------------------------------------------------------------------

TOPIC_JOB_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "iran_war": {
        "name": "iran_war_updates",
        "message": "Search for the latest news about the Iran-USA conflict and tensions in the Middle East. Summarise key developments in 3-4 bullet points.",
        "interval_seconds": 6 * 3600,  # every 6 hours
        "description": "Iran war news updates (auto-scheduled from pattern)",
    },
    "ai_news": {
        "name": "ai_news_updates",
        "message": "Search for the latest AI news: new models, research breakthroughs, company updates (OpenAI, Anthropic, Google, xAI). Summarise in 4-5 bullet points.",
        "interval_seconds": 8 * 3600,  # every 8 hours
        "description": "AI news updates (auto-scheduled from pattern)",
    },
    "crypto": {
        "name": "crypto_alerts",
        "message": "Check the latest Bitcoin and Ethereum prices and major market movements. Report if there are significant moves (>3%) or notable news.",
        "interval_seconds": 4 * 3600,  # every 4 hours
        "description": "Crypto price monitoring (auto-scheduled from pattern)",
    },
}


def maybe_auto_schedule_topics(db: Session, owner_id: int, patterns: Dict[str, Any]) -> List[str]:
    """Auto-create scheduled jobs for topics Arsh asks about repeatedly.

    Returns list of job names that were created.
    """
    if not PREDICTION_ENABLED:
        return []

    auto_schedulable = patterns.get("auto_schedulable", [])
    created = []

    for topic, count in auto_schedulable:
        template = TOPIC_JOB_TEMPLATES.get(topic)
        if not template:
            continue

        job_name = template["name"]

        # Check if job already exists
        existing = (
            db.query(ScheduledJob)
            .filter(
                ScheduledJob.owner_id == owner_id,
                ScheduledJob.name == job_name,
                ScheduledJob.enabled.is_(True),
            )
            .first()
        )
        if existing:
            continue

        # Verify owner has real Telegram chat_id
        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            continue
        try:
            if abs(int(user.telegram_chat_id)) < 10000:
                continue
        except ValueError:
            continue

        try:
            now = datetime.now(timezone.utc)
            job = ScheduledJob(
                owner_id=owner_id,
                name=job_name,
                message=template["message"],
                lane="cron",
                interval_seconds=template["interval_seconds"],
                enabled=True,
                run_count=0,
                next_run_at=now + timedelta(minutes=5),  # first run in 5 min
            )
            db.add(job)
            db.commit()
            created.append(job_name)
            logger.info(
                "PREDICTIVE_JOB_CREATED name=%s topic=%s count=%d owner=%d",
                job_name, topic, count, owner_id,
            )
        except Exception as e:
            db.rollback()
            logger.warning("PREDICTIVE_JOB_FAIL topic=%s error=%s", topic, str(e)[:200])

    return created


# ---------------------------------------------------------------------------
# Full pattern update — call after each conversation turn
# ---------------------------------------------------------------------------


def update_patterns_after_turn(owner_id: int, user_message: str) -> None:
    """Update pattern analysis after a conversation turn.

    - Analyses recent history
    - Saves pattern notes if notable
    - Auto-schedules jobs for high-frequency topics
    - Non-blocking (catches all exceptions)
    """
    if not PREDICTION_ENABLED:
        return

    # Skip internal/system messages
    if user_message.startswith("[") and "]" in user_message[:30]:
        return

    try:
        db = SessionLocal()
        try:
            patterns = get_user_patterns(db, owner_id)

            # Save pattern note if notable patterns found
            save_pattern_note(db, owner_id, patterns)

            # Auto-schedule jobs for repeated topics
            created = maybe_auto_schedule_topics(db, owner_id, patterns)
            if created:
                logger.info(
                    "PREDICTIVE_AUTO_SCHEDULED owner=%d jobs=%s",
                    owner_id, created,
                )
        finally:
            db.close()
    except Exception as e:
        logger.warning("PATTERN_UPDATE_FAIL owner=%d error=%s", owner_id, str(e)[:200])


# ---------------------------------------------------------------------------
# Pattern summary — readable string for Bob to include in responses
# ---------------------------------------------------------------------------


def get_pattern_summary(owner_id: int) -> str:
    """Get a human-readable summary of Arsh's patterns for Bob to use."""
    try:
        db = SessionLocal()
        try:
            patterns = get_user_patterns(db, owner_id)
        finally:
            db.close()

        notable = patterns.get("notable", [])
        if not notable:
            return "No strong patterns detected yet."

        lines = ["Arsh's recurring interests:"]
        for topic, count in notable[:5]:
            lines.append(f"  • {topic.replace('_', ' ').title()}: {count} mentions")

        auto = patterns.get("auto_schedulable", [])
        if auto:
            lines.append(f"\nAuto-monitoring active for: {', '.join(t for t, _ in auto)}")

        return "\n".join(lines)
    except Exception as e:
        return f"Pattern analysis unavailable: {str(e)[:100]}"

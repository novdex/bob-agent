"""
Proactive Communication Service — Bob reaches out to Arsh.

Bob doesn't just respond. He initiates. This module handles all
outbound messages Bob sends without being asked:

- Idle check-ins (Bob's own thoughts, unprompted) via scheduled jobs
- Goal completion reports
- Error alerts

The check-in is seeded as a ScheduledJob on startup — the cron system
fires it on schedule, runs it through Bob's agent loop, and sends
the response back to Arsh's Telegram chat automatically.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from ..database.session import SessionLocal
from ..database.models import ScheduledJob, User
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.proactive")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROACTIVE_ENABLED: bool = os.getenv("PROACTIVE_ENABLED", "true").lower() in {"1", "true", "yes"}
PROACTIVE_DEFAULT_OWNER_ID: int = int(os.getenv("PROACTIVE_DEFAULT_OWNER_ID", "1"))
PROACTIVE_CHECKIN_INTERVAL_HOURS: int = max(
    1, int(os.getenv("PROACTIVE_CHECKIN_INTERVAL_HOURS", "8"))
)

# The message Bob receives that triggers a proactive check-in
CHECKIN_JOB_NAME = "proactive_checkin"
CHECKIN_JOB_MESSAGE = (
    "[PROACTIVE_CHECKIN] You are doing an autonomous check-in with Arsh. "
    "Generate ONE short, genuine message to send him. It should be one of:\n"
    "- A useful insight or observation you've had\n"
    "- An interesting AI/tech development worth sharing\n"
    "- A status update on what you've been working on autonomously\n"
    "- A thought about the Bob AGI project\n"
    "- A question you're genuinely curious about\n\n"
    "Rules:\n"
    "- Be concise (2-4 sentences)\n"
    "- Sound like yourself — direct, not corporate\n"
    "- Don't start with 'Hello' or greetings\n"
    "- Don't apologise for messaging\n"
    "- Make it worth reading\n\n"
    "Reply with ONLY the message. Nothing else."
)


# ---------------------------------------------------------------------------
# Seed the check-in job on startup
# ---------------------------------------------------------------------------


def ensure_checkin_job_seeded(owner_id: int = PROACTIVE_DEFAULT_OWNER_ID) -> bool:
    """Seed the proactive check-in scheduled job if it doesn't exist.

    Called on startup. Returns True if a new job was created.
    """
    if not PROACTIVE_ENABLED:
        return False

    db = SessionLocal()
    try:
        # Check if already seeded
        existing = (
            db.query(ScheduledJob)
            .filter(
                ScheduledJob.owner_id == owner_id,
                ScheduledJob.name == CHECKIN_JOB_NAME,
                ScheduledJob.enabled.is_(True),
            )
            .first()
        )
        if existing is not None:
            logger.debug("PROACTIVE_CHECKIN_JOB_EXISTS id=%d", existing.id)
            return False

        # Verify the owner has a real Telegram chat_id
        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            logger.warning("PROACTIVE_CHECKIN_SKIP no telegram_chat_id owner=%d", owner_id)
            return False

        try:
            chat_id_int = int(user.telegram_chat_id)
            if abs(chat_id_int) < 10000:
                logger.warning(
                    "PROACTIVE_CHECKIN_SKIP test chat_id=%s owner=%d",
                    user.telegram_chat_id, owner_id,
                )
                return False
        except ValueError:
            logger.warning(
                "PROACTIVE_CHECKIN_SKIP non-numeric chat_id=%s owner=%d",
                user.telegram_chat_id, owner_id,
            )
            return False

        interval = PROACTIVE_CHECKIN_INTERVAL_HOURS * 3600
        now = datetime.now(timezone.utc)
        # First check-in fires 1 hour after startup
        first_run = now + timedelta(hours=1)

        job = ScheduledJob(
            owner_id=owner_id,
            name=CHECKIN_JOB_NAME,
            message=CHECKIN_JOB_MESSAGE,
            lane="cron",
            interval_seconds=interval,
            enabled=True,
            run_count=0,
            next_run_at=first_run,
        )
        db.add(job)
        db.commit()
        logger.info(
            "PROACTIVE_CHECKIN_JOB_SEEDED owner=%d interval_hours=%d first_run=%s",
            owner_id,
            PROACTIVE_CHECKIN_INTERVAL_HOURS,
            first_run.isoformat(),
        )
        return True

    except Exception as e:
        db.rollback()
        logger.error("PROACTIVE_CHECKIN_SEED_FAIL owner=%d error=%s", owner_id, str(e)[:200])
        return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Direct send helper (used by autonomy loop for goal reports)
# ---------------------------------------------------------------------------


async def send_proactive_message(
    owner_id: int,
    message: str,
    context: str = "general",
) -> bool:
    """Send a proactive message to the owner via Telegram.

    Args:
        owner_id: The user to notify.
        message: The message to send.
        context: Label for logging.

    Returns:
        True if sent successfully.
    """
    if not PROACTIVE_ENABLED:
        return False

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            return False
        chat_id = str(user.telegram_chat_id)
        try:
            if abs(int(chat_id)) < 10000:
                return False
        except ValueError:
            return False
    finally:
        db.close()

    try:
        from .telegram.messaging import send_telegram_message
        await send_telegram_message(chat_id, message)
        logger.info("PROACTIVE_SENT context=%s owner=%d len=%d", context, owner_id, len(message))
        return True
    except Exception as e:
        logger.warning("PROACTIVE_SEND_FAIL: %s", str(e)[:200])
        return False


# ---------------------------------------------------------------------------
# Formatted message builders (for goal reports + error alerts)
# ---------------------------------------------------------------------------


def fmt_goal_report(goal_title: str, summary: str) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"🤖 *Bob — Autonomous Update* ({now})\n\n"
        f"*{goal_title}*\n\n"
        f"{truncate_text(summary, 3000)}\n\n"
        f"_(Autonomous action — no reply needed)_"
    )


def fmt_error_alert(context: str, error: str) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"⚠️ *Bob — Error Alert* ({now})\n\n"
        f"*Context:* {context}\n\n"
        f"{truncate_text(error, 1500)}"
    )


async def report_goal_completion(owner_id: int, goal_title: str, summary: str) -> bool:
    return await send_proactive_message(
        owner_id, fmt_goal_report(goal_title, summary), context="goal"
    )


async def report_error(owner_id: int, context: str, error: str) -> bool:
    return await send_proactive_message(
        owner_id, fmt_error_alert(context, error), context="error"
    )

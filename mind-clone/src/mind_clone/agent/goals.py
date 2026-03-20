"""
Autonomous Goal Engine — makes Bob proactive.

Manages recurring goals that Bob pursues on his own schedule without
waiting for user input. Each goal has a title, description, priority,
interval, and next_run_at timestamp. The engine checks for due goals,
executes them via the agent loop, and stores results.

Serves the AUTONOMY pillar of the AGI vision.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.models import ResearchNote

# AutonomousGoal is not in the DB schema — using ScheduledJob for autonomous goals instead.
# This class is kept for API compatibility but uses a stub model.
class AutonomousGoal:
    """Stub matching the expected interface. Real goals use ScheduledJob."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
from ..database.session import SessionLocal

logger = logging.getLogger("mind_clone.agent.goals")

# ---------------------------------------------------------------------------
# Default goal definitions — seeded on first startup
# ---------------------------------------------------------------------------

DEFAULT_GOALS: List[Dict[str, Any]] = [
    {
        "goal_key": "daily_research",
        "title": "Research Trending AI/Tech Topics",
        "description": (
            "Search for and summarize the latest developments in AI, machine learning, "
            "and technology. Focus on breakthroughs, new models, open-source releases, "
            "and industry trends. Save findings as research notes."
        ),
        "priority": 60,
        "interval_seconds": 6 * 3600,  # every 6 hours
    },
    {
        "goal_key": "self_review",
        "title": "Review Conversations & Identify Improvements",
        "description": (
            "Review recent conversations and interactions. Identify patterns where "
            "responses could be improved, tools that were misused or unavailable, "
            "and areas where knowledge gaps exist. Create self-improvement notes."
        ),
        "priority": 50,
        "interval_seconds": 12 * 3600,  # every 12 hours
    },
    {
        "goal_key": "knowledge_consolidation",
        "title": "Consolidate & Organize Learned Knowledge",
        "description": (
            "Review accumulated research notes, lessons learned, and self-improvement "
            "notes. Summarize key themes, remove duplicates, and create a consolidated "
            "knowledge summary. This helps maintain an organized memory."
        ),
        "priority": 40,
        "interval_seconds": 24 * 3600,  # every 24 hours
    },
    {
        "goal_key": "proactive_checkin",
        "title": "Proactive Check-in with Arsh",
        "description": (
            "Generate a genuine, unprompted check-in message for Arsh. Share an insight, "
            "interesting AI development, autonomous work update, or thought about the Bob "
            "project. Be concise and worth reading. Send via Telegram."
        ),
        "priority": 70,
        "interval_seconds": 8 * 3600,  # every 8 hours
    },
]


class GoalEngine:
    """Manages autonomous recurring goals.

    Goals are stored in the ``autonomous_goals`` table and checked
    periodically by the autonomy loop. The engine handles:

    - Seeding default goals on first startup
    - Querying for due goals (next_run_at <= now)
    - Marking goals complete and scheduling the next run
    - Tracking failures and auto-disabling broken goals
    """

    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    # ------------------------------------------------------------------
    # Seed / Init
    # ------------------------------------------------------------------

    def ensure_default_goals(self, db: Session) -> int:
        """Create default goals if they don't exist yet.

        Returns:
            Count of newly created goals.
        """
        created = 0
        now = datetime.now(timezone.utc)

        for defn in DEFAULT_GOALS:
            existing = (
                db.query(AutonomousGoal)
                .filter(
                    AutonomousGoal.owner_id == self.owner_id,
                    AutonomousGoal.goal_key == defn["goal_key"],
                )
                .first()
            )
            if existing is not None:
                continue

            goal = AutonomousGoal(
                owner_id=self.owner_id,
                goal_key=defn["goal_key"],
                title=defn["title"],
                description=defn["description"],
                priority=defn["priority"],
                interval_seconds=defn["interval_seconds"],
                enabled=True,
                next_run_at=now + timedelta(seconds=60),  # first run in 1 minute
            )
            db.add(goal)
            created += 1
            logger.info(
                "AUTONOMY_GOAL_CREATED key=%s interval=%ds owner=%d",
                defn["goal_key"],
                defn["interval_seconds"],
                self.owner_id,
            )

        if created:
            db.commit()

        return created

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_due_goals(self, db: Session, limit: int = 3) -> List[AutonomousGoal]:
        """Return goals that are due to run (next_run_at <= now), ordered by priority desc."""
        now = datetime.now(timezone.utc)
        return (
            db.query(AutonomousGoal)
            .filter(
                AutonomousGoal.owner_id == self.owner_id,
                AutonomousGoal.enabled.is_(True),
                AutonomousGoal.next_run_at <= now,
            )
            .order_by(AutonomousGoal.priority.desc())
            .limit(limit)
            .all()
        )

    def get_all_goals(self, db: Session, include_disabled: bool = False) -> List[AutonomousGoal]:
        """Return all goals for this owner."""
        q = db.query(AutonomousGoal).filter(AutonomousGoal.owner_id == self.owner_id)
        if not include_disabled:
            q = q.filter(AutonomousGoal.enabled.is_(True))
        return q.order_by(AutonomousGoal.priority.desc()).all()

    def get_goal(self, db: Session, goal_key: str) -> Optional[AutonomousGoal]:
        """Get a specific goal by key."""
        return (
            db.query(AutonomousGoal)
            .filter(
                AutonomousGoal.owner_id == self.owner_id,
                AutonomousGoal.goal_key == goal_key,
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Store / Create
    # ------------------------------------------------------------------

    def store_goal(
        self,
        db: Session,
        goal_key: str,
        title: str,
        description: str = "",
        priority: int = 50,
        interval_seconds: int = 21600,
    ) -> AutonomousGoal:
        """Create or update an autonomous goal."""
        existing = self.get_goal(db, goal_key)
        now = datetime.now(timezone.utc)

        if existing:
            existing.title = title
            existing.description = description
            existing.priority = priority
            existing.interval_seconds = interval_seconds
            existing.enabled = True
            db.commit()
            db.refresh(existing)
            return existing

        goal = AutonomousGoal(
            owner_id=self.owner_id,
            goal_key=goal_key,
            title=title,
            description=description,
            priority=priority,
            interval_seconds=interval_seconds,
            enabled=True,
            next_run_at=now + timedelta(seconds=60),
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return goal

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def mark_goal_complete(
        self,
        db: Session,
        goal: AutonomousGoal,
        result_summary: str,
    ) -> None:
        """Mark a goal run as complete, schedule next run."""
        now = datetime.now(timezone.utc)
        goal.last_run_at = now
        goal.last_result = (result_summary or "")[:2000]
        goal.last_error = None
        goal.run_count += 1
        goal.consecutive_failures = 0
        goal.next_run_at = now + timedelta(seconds=goal.interval_seconds)
        db.commit()

        logger.info(
            "AUTONOMY_GOAL_COMPLETE key=%s run_count=%d next_run=%s",
            goal.goal_key,
            goal.run_count,
            goal.next_run_at.isoformat(),
        )

    def mark_goal_failed(
        self,
        db: Session,
        goal: AutonomousGoal,
        error: str,
    ) -> None:
        """Record a goal execution failure. Auto-disables after max consecutive failures."""
        now = datetime.now(timezone.utc)
        goal.last_run_at = now
        goal.last_error = (error or "unknown")[:2000]
        goal.run_count += 1
        goal.consecutive_failures += 1

        if goal.consecutive_failures >= goal.max_failures_before_disable:
            goal.enabled = False
            logger.warning(
                "AUTONOMY_GOAL_AUTO_DISABLED key=%s after %d consecutive failures",
                goal.goal_key,
                goal.consecutive_failures,
            )
        else:
            # Back off: double the interval for the next attempt (capped at 24h)
            backoff = min(goal.interval_seconds * 2, 86400)
            goal.next_run_at = now + timedelta(seconds=backoff)

        db.commit()

    # ------------------------------------------------------------------
    # Goal prompt builder
    # ------------------------------------------------------------------

    def build_goal_prompt(self, goal: AutonomousGoal) -> str:
        """Build the user-message prompt that drives goal execution via the agent loop."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        prompt = (
            f"[AUTONOMOUS GOAL — {now_iso}]\n"
            f"Goal: {goal.title}\n"
            f"Description: {goal.description}\n\n"
            "Instructions:\n"
            "1. Execute this goal using your available tools.\n"
            "2. For research goals, use deep_research or web search tools.\n"
            "3. Save any findings as research notes using save_research_note.\n"
            "4. For self-review goals, reflect on recent conversations and create "
            "self-improvement notes.\n"
            "5. For knowledge consolidation, review and summarize existing notes.\n"
            "6. Be thorough but concise. This is autonomous work — no human is waiting.\n"
            "7. Respond with a brief summary of what you accomplished.\n"
        )

        if goal.last_result:
            prompt += f"\nLast run result: {goal.last_result[:500]}\n"

        return prompt

"""
Autonomy Engine — Bob's proactive behavior loop.

Runs as a background async task, periodically waking up to:
1. Check for due autonomous goals
2. Execute each goal via the agent loop (LLM + tools)
3. Decide if results are worth reporting to the user
4. Send proactive reports via Telegram when warranted

This is the AUTONOMY pillar of the AGI vision — Bob doesn't just
react, he initiates.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ..agent.goals import GoalEngine
from ..agent.llm import call_llm
from ..core.state import (
    RUNTIME_STATE,
    increment_runtime_state,
    set_runtime_state_value,
)
from ..database.models import User
from ..agent.goals import AutonomousGoal  # stub model
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.autonomy")

# ---------------------------------------------------------------------------
# Config (read from env with sane defaults)
# ---------------------------------------------------------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


AUTONOMY_ENGINE_ENABLED: bool = _env_flag("AUTONOMY_ENGINE_ENABLED", True)
AUTONOMY_LOOP_INTERVAL_SECONDS: int = max(60, int(os.getenv("AUTONOMY_LOOP_INTERVAL_SECONDS", "1800")))
AUTONOMY_DEFAULT_OWNER_ID: int = int(os.getenv("AUTONOMY_DEFAULT_OWNER_ID", "1"))
AUTONOMY_MAX_GOALS_PER_TICK: int = max(1, int(os.getenv("AUTONOMY_MAX_GOALS_PER_TICK", "3")))
AUTONOMY_REPORT_VIA_TELEGRAM: bool = _env_flag("AUTONOMY_REPORT_VIA_TELEGRAM", True)
AUTONOMY_LLM_TIMEOUT_SECONDS: int = max(30, int(os.getenv("AUTONOMY_LLM_TIMEOUT_SECONDS", "120")))


# ---------------------------------------------------------------------------
# Core execution: run a single goal through the agent loop
# ---------------------------------------------------------------------------

def _execute_goal_via_llm(goal: AutonomousGoal, engine: GoalEngine) -> str:
    """Execute a goal by sending its prompt through the agent reasoning loop.

    Uses the full agent loop (with tools) for maximum capability.
    Falls back to a simple LLM call if the agent loop fails.

    Args:
        goal: The autonomous goal to execute.
        engine: GoalEngine instance for prompt building.

    Returns:
        Result summary string from the agent.
    """
    prompt = engine.build_goal_prompt(goal)
    owner_id = goal.owner_id

    # Try the full agent loop first (has tool access)
    try:
        from ..agent.loop import run_agent_loop
        result = run_agent_loop(owner_id, prompt)
        return result or "(no response)"
    except Exception as loop_err:
        logger.warning(
            "AUTONOMY_AGENT_LOOP_FAIL goal=%s error=%s — falling back to simple LLM",
            goal.goal_key,
            str(loop_err)[:200],
        )

    # Fallback: simple LLM call without tools
    try:
        messages = [
            {"role": "system", "content": (
                "You are Bob, an autonomous AI agent. Execute the following goal "
                "and return a concise summary of your findings or actions."
            )},
            {"role": "user", "content": prompt},
        ]
        result = call_llm(messages, timeout=AUTONOMY_LLM_TIMEOUT_SECONDS)
        if result.get("ok"):
            return result.get("content", "(empty LLM response)")
        return f"LLM error: {result.get('error', 'unknown')}"
    except Exception as llm_err:
        raise RuntimeError(f"Both agent loop and LLM fallback failed: {llm_err}") from llm_err


# ---------------------------------------------------------------------------
# Worth-reporting decision
# ---------------------------------------------------------------------------

_WORTH_REPORTING_PROMPT = (
    "You just completed an autonomous background task. Here is the result:\n\n"
    "{result}\n\n"
    "Should this be reported to the user? Answer YES only if:\n"
    "- You found genuinely important or time-sensitive information\n"
    "- You completed a significant piece of research with actionable insights\n"
    "- You discovered a critical issue or error that needs attention\n"
    "- You have an important recommendation\n\n"
    "Answer NO if the result is routine, unremarkable, or the user wouldn't care.\n\n"
    "Reply with exactly one word: YES or NO"
)


def _is_worth_reporting(result_summary: str) -> bool:
    """Ask the LLM whether a goal's result is worth telling the user about.

    Args:
        result_summary: The result text from goal execution.

    Returns:
        True if the result should be reported to the user.
    """
    if not result_summary or len(result_summary.strip()) < 20:
        return False

    try:
        messages = [
            {"role": "system", "content": "You are a filter. Answer YES or NO only."},
            {"role": "user", "content": _WORTH_REPORTING_PROMPT.format(
                result=truncate_text(result_summary, 2000),
            )},
        ]
        resp = call_llm(messages, timeout=30)
        if resp.get("ok"):
            answer = (resp.get("content") or "").strip().upper()
            return answer.startswith("YES")
    except Exception as e:
        logger.debug("AUTONOMY_WORTH_REPORTING_FAIL: %s", str(e)[:200])

    # Default to not reporting — don't spam the user
    return False


# ---------------------------------------------------------------------------
# Proactive reporting via Telegram
# ---------------------------------------------------------------------------

async def _send_proactive_report(owner_id: int, goal_title: str, summary: str) -> bool:
    """Send a proactive report to the user via Telegram.

    Args:
        owner_id: The owner to notify.
        goal_title: Title of the completed goal.
        summary: The result summary to send.

    Returns:
        True if the message was sent successfully.
    """
    if not AUTONOMY_REPORT_VIA_TELEGRAM:
        return False

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            logger.debug("AUTONOMY_REPORT_SKIP no telegram_chat_id for owner=%d", owner_id)
            return False

        chat_id = user.telegram_chat_id

        # Format the report
        report = (
            f"Autonomous Activity Report\n\n"
            f"Goal: {goal_title}\n\n"
            f"{truncate_text(summary, 3000)}\n\n"
            f"(This was an autonomous action — no response needed.)"
        )

        try:
            from ..services.telegram.messaging import send_telegram_message
            await send_telegram_message(chat_id, report)
            increment_runtime_state("autonomy_reports_sent")
            return True
        except Exception as e:
            logger.warning("AUTONOMY_TELEGRAM_SEND_FAIL: %s", str(e)[:200])
            return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Main autonomy loop
# ---------------------------------------------------------------------------

async def autonomy_loop() -> None:
    """Background loop that runs every AUTONOMY_LOOP_INTERVAL_SECONDS.

    On each tick:
    1. Queries for due autonomous goals
    2. Executes each goal via the agent loop
    3. Decides if results are worth reporting
    4. Sends proactive Telegram reports when warranted
    5. Updates runtime state metrics
    """
    logger.info(
        "AUTONOMY_ENGINE_START interval=%ds max_goals_per_tick=%d owner=%d",
        AUTONOMY_LOOP_INTERVAL_SECONDS,
        AUTONOMY_MAX_GOALS_PER_TICK,
        AUTONOMY_DEFAULT_OWNER_ID,
    )
    set_runtime_state_value("autonomy_engine_alive", True)

    engine = GoalEngine(AUTONOMY_DEFAULT_OWNER_ID)

    # Seed default goals on first startup
    try:
        db = SessionLocal()
        try:
            created = engine.ensure_default_goals(db)
            if created:
                logger.info("AUTONOMY_DEFAULT_GOALS_SEEDED count=%d", created)
        finally:
            db.close()
    except Exception as e:
        logger.error("AUTONOMY_GOAL_SEED_FAIL: %s", str(e)[:300])

    while not RUNTIME_STATE.get("shutting_down", False):
        try:
            await _autonomy_tick(engine)
        except asyncio.CancelledError:
            logger.info("AUTONOMY_ENGINE_CANCELLED")
            break
        except Exception as e:
            logger.error("AUTONOMY_TICK_ERROR: %s", str(e)[:300])
            set_runtime_state_value("autonomy_last_error", str(e)[:500])

        # Sleep until next tick (check shutting_down every 10s to exit promptly)
        for _ in range(AUTONOMY_LOOP_INTERVAL_SECONDS // 10):
            if RUNTIME_STATE.get("shutting_down", False):
                break
            await asyncio.sleep(10)

    set_runtime_state_value("autonomy_engine_alive", False)
    logger.info("AUTONOMY_ENGINE_STOPPED")


async def _autonomy_tick(engine: GoalEngine) -> None:
    """Execute one tick of the autonomy loop."""
    db = SessionLocal()
    try:
        due_goals = engine.get_due_goals(db, limit=AUTONOMY_MAX_GOALS_PER_TICK)
        if not due_goals:
            logger.debug("AUTONOMY_TICK no due goals")
            return

        logger.info("AUTONOMY_TICK due_goals=%d", len(due_goals))

        for goal in due_goals:
            if RUNTIME_STATE.get("shutting_down", False):
                break

            set_runtime_state_value("autonomy_last_goal", goal.goal_key)
            increment_runtime_state("autonomy_actions_total")

            try:
                # Special case: proactive check-in goal
                if goal.goal_key == "proactive_checkin":
                    from ..services.proactive import generate_and_send_checkin
                    sent = await generate_and_send_checkin(goal.owner_id)
                    engine.mark_goal_complete(db, goal, "check-in sent" if sent else "skipped")
                    increment_runtime_state("autonomy_goals_executed")
                    logger.info("AUTONOMY_CHECKIN_DONE owner=%d sent=%s", goal.owner_id, sent)
                    continue

                # Normal goal: run via agent loop in thread
                result = await asyncio.to_thread(_execute_goal_via_llm, goal, engine)
                engine.mark_goal_complete(db, goal, result)
                increment_runtime_state("autonomy_goals_executed")

                logger.info(
                    "AUTONOMY_GOAL_DONE key=%s result_len=%d",
                    goal.goal_key,
                    len(result or ""),
                )

                # Decide if worth reporting — use proactive module
                worth_it = await asyncio.to_thread(_is_worth_reporting, result)
                if worth_it:
                    from ..services.proactive import report_goal_completion
                    await report_goal_completion(goal.owner_id, goal.title, result)
                    increment_runtime_state("autonomy_reports_sent")

            except Exception as e:
                error_msg = str(e)[:500]
                engine.mark_goal_failed(db, goal, error_msg)
                increment_runtime_state("autonomy_goals_failed")
                set_runtime_state_value("autonomy_last_error", error_msg)
                logger.error(
                    "AUTONOMY_GOAL_FAIL key=%s error=%s",
                    goal.goal_key,
                    error_msg,
                )
                # Alert Arsh on repeated failures
                try:
                    from ..services.proactive import report_error
                    await report_error(goal.owner_id, f"Goal: {goal.goal_key}", error_msg)
                except Exception:
                    pass

        set_runtime_state_value(
            "autonomy_last_run_at",
            datetime.now(timezone.utc).isoformat(),
        )

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Supervisor alias (matches naming pattern in _shared.py)
# ---------------------------------------------------------------------------

async def autonomy_supervisor_loop() -> None:
    """Entry point for the autonomy background task (matches supervisor naming convention)."""
    await autonomy_loop()

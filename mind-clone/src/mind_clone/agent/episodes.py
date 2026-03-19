"""
Episodic Memory Engine — Bob remembers what happened and what it meant.

Every conversation turn gets recorded as an episode:
  situation  — what the user asked / what context Bob was in
  action_taken — what Bob did (tools used, approach taken)
  outcome    — success / failure / partial
  outcome_detail — what actually happened

Over time these episodes let Bob:
  - Recall similar past situations ("I've done this before")
  - Know which tools work for which tasks
  - Understand his own failure patterns
  - Feed the retro system with real data

Called at the end of every agent turn, in a background thread.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.models import EpisodicMemory
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.agent.episodes")

EPISODES_ENABLED: bool = os.getenv("EPISODES_ENABLED", "true").lower() in {"1", "true", "yes"}
MAX_EPISODES_PER_OWNER = int(os.getenv("MAX_EPISODES_PER_OWNER", "2000"))


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------


def _classify_outcome(
    user_message: str,
    assistant_response: str,
    tools_used: List[str],
    tool_failures: List[str],
) -> tuple[str, str]:
    """Classify the outcome of a turn as success/failure/partial.

    Returns: (outcome, detail)
    """
    response_lower = assistant_response.lower()

    # Hard failure signals
    if any(f in response_lower for f in [
        "llm error", "all llm providers failed", "http 400", "http 500",
        "i cannot", "unable to", "failed to",
    ]):
        return "failure", truncate_text(assistant_response, 200)

    # Tool failures
    if tool_failures:
        if len(tool_failures) == len(tools_used) and tools_used:
            return "failure", f"All {len(tool_failures)} tools failed"
        return "partial", f"{len(tool_failures)}/{len(tools_used)} tools failed"

    # Success signals
    if tools_used:
        return "success", f"Completed using: {', '.join(tools_used[:3])}"

    return "success", "Responded without tools"


def _extract_tools_from_messages(messages: List[dict]) -> tuple[List[str], List[str]]:
    """Extract tool names used and which ones failed from the message list."""
    tools_used = []
    tool_failures = []

    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc.get("function", {}).get("name", "")
                if name and name not in tools_used:
                    tools_used.append(name)

        if msg.get("role") == "tool":
            content = str(msg.get("content", ""))
            try:
                data = json.loads(content)
                if isinstance(data, dict) and not data.get("ok", True):
                    # Find which tool this belongs to — look backwards
                    tool_failures.append(content[:100])
            except Exception:
                if any(k in content.lower() for k in ("error", "failed", "exception")):
                    tool_failures.append(content[:100])

    return tools_used, tool_failures


# ---------------------------------------------------------------------------
# Core: save one episode
# ---------------------------------------------------------------------------


def save_episode(
    db: Session,
    owner_id: int,
    situation: str,
    action_taken: str,
    outcome: str,
    outcome_detail: str,
    tools_used: List[str],
    source_type: str = "chat",
    source_ref: Optional[str] = None,
) -> bool:
    """Save a single episode to the DB."""
    try:
        # Prune if at limit (keep most recent)
        count = db.query(EpisodicMemory).filter(
            EpisodicMemory.owner_id == owner_id
        ).count()
        if count >= MAX_EPISODES_PER_OWNER:
            oldest = (
                db.query(EpisodicMemory)
                .filter(EpisodicMemory.owner_id == owner_id)
                .order_by(EpisodicMemory.id.asc())
                .limit(50)
                .all()
            )
            for ep in oldest:
                db.delete(ep)

        episode = EpisodicMemory(
            owner_id=owner_id,
            situation=truncate_text(situation, 500),
            action_taken=truncate_text(action_taken, 500),
            outcome=outcome,
            outcome_detail=truncate_text(outcome_detail, 300),
            tools_used_json=json.dumps(tools_used[:10]),
            source_type=source_type,
            source_ref=source_ref,
        )
        db.add(episode)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning("EPISODE_SAVE_FAIL owner=%d error=%s", owner_id, str(e)[:200])
        return False


# ---------------------------------------------------------------------------
# Main entry point — called after each agent turn
# ---------------------------------------------------------------------------


def record_episode_from_turn(
    owner_id: int,
    user_message: str,
    assistant_response: str,
    messages_context: Optional[List[dict]] = None,
) -> None:
    """Record an episodic memory from a completed agent turn.

    Non-blocking — catches all exceptions. Safe to call from background thread.
    """
    if not EPISODES_ENABLED:
        return

    # Skip internal/system messages
    if user_message.startswith("[") and "]" in user_message[:30]:
        return

    # Skip very short interactions
    if len(user_message.strip()) < 3:
        return

    try:
        tools_used, tool_failures = [], []
        if messages_context:
            tools_used, tool_failures = _extract_tools_from_messages(messages_context)

        outcome, outcome_detail = _classify_outcome(
            user_message, assistant_response, tools_used, tool_failures
        )

        # Build situation summary
        situation = truncate_text(user_message, 300)

        # Build action summary
        if tools_used:
            action = f"Used {len(tools_used)} tools: {', '.join(tools_used[:5])}. Response: {truncate_text(assistant_response, 150)}"
        else:
            action = f"Direct response: {truncate_text(assistant_response, 200)}"

        db = SessionLocal()
        try:
            saved = save_episode(
                db=db,
                owner_id=owner_id,
                situation=situation,
                action_taken=action,
                outcome=outcome,
                outcome_detail=outcome_detail,
                tools_used=tools_used,
                source_type="chat",
            )
            if saved:
                logger.debug(
                    "EPISODE_RECORDED owner=%d outcome=%s tools=%d",
                    owner_id, outcome, len(tools_used),
                )
        finally:
            db.close()

    except Exception as e:
        logger.warning("EPISODE_RECORD_FAIL owner=%d error=%s", owner_id, str(e)[:200])


# ---------------------------------------------------------------------------
# Query: recall similar episodes
# ---------------------------------------------------------------------------


def recall_similar_episodes(
    owner_id: int,
    query: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Find past episodes similar to the current situation.

    Simple keyword matching for now — good enough for pattern recognition.
    Returns list of episode dicts sorted by recency.
    """
    try:
        db = SessionLocal()
        try:
            query_words = set(query.lower().split())
            episodes = (
                db.query(EpisodicMemory)
                .filter(EpisodicMemory.owner_id == owner_id)
                .order_by(EpisodicMemory.id.desc())
                .limit(200)
                .all()
            )

            scored = []
            for ep in episodes:
                ep_words = set((ep.situation or "").lower().split())
                if not ep_words:
                    continue
                overlap = len(query_words & ep_words) / max(len(query_words), 1)
                if overlap > 0.2:
                    scored.append((overlap, ep))

            scored.sort(key=lambda x: -x[0])
            return [
                {
                    "situation": ep.situation,
                    "action_taken": ep.action_taken,
                    "outcome": ep.outcome,
                    "outcome_detail": ep.outcome_detail,
                    "tools_used": json.loads(ep.tools_used_json or "[]"),
                    "created_at": ep.created_at.isoformat() if ep.created_at else None,
                    "similarity": round(score, 2),
                }
                for score, ep in scored[:limit]
            ]
        finally:
            db.close()
    except Exception as e:
        logger.warning("EPISODE_RECALL_FAIL: %s", str(e)[:200])
        return []


def get_episode_stats(owner_id: int) -> Dict[str, Any]:
    """Get episode statistics for the retro/self-awareness system."""
    try:
        db = SessionLocal()
        try:
            episodes = db.query(EpisodicMemory).filter(
                EpisodicMemory.owner_id == owner_id
            ).all()

            total = len(episodes)
            if total == 0:
                return {"total": 0, "success_rate": 0, "top_tools": [], "recent_failures": []}

            successes = sum(1 for e in episodes if e.outcome == "success")
            failures = sum(1 for e in episodes if e.outcome == "failure")

            # Count tool usage
            tool_counts: Dict[str, int] = {}
            for ep in episodes:
                for tool in json.loads(ep.tools_used_json or "[]"):
                    tool_counts[tool] = tool_counts.get(tool, 0) + 1

            top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]

            recent_failures = [
                {"situation": e.situation[:100], "detail": e.outcome_detail}
                for e in sorted(episodes, key=lambda x: x.id, reverse=True)
                if e.outcome == "failure"
            ][:3]

            return {
                "total": total,
                "success": successes,
                "failure": failures,
                "partial": total - successes - failures,
                "success_rate": round(successes / total * 100, 1),
                "top_tools": [{"tool": t, "uses": c} for t, c in top_tools],
                "recent_failures": recent_failures,
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning("EPISODE_STATS_FAIL: %s", str(e)[:200])
        return {"total": 0, "error": str(e)[:100]}

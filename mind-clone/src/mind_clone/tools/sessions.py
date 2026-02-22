"""
Session management tools (multi-agent sessions).

These tools allow the LLM to spawn, communicate with, list, and stop
sub-agent sessions within the team-mode framework.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..database.session import SessionLocal
from ..database.models import User, TeamAgent, ConversationMessage
from ..config import settings

logger = logging.getLogger("mind_clone.tools.sessions")


def tool_sessions_spawn(args: dict) -> dict:
    """Spawn a new agent session (team agent)."""
    agent_key = str(args.get("agent_key", "")).strip().lower()
    display_name = str(args.get("display_name", "")).strip() or agent_key
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    if not agent_key:
        return {"ok": False, "error": "agent_key is required"}
    if not owner_id:
        return {"ok": False, "error": "owner_id is required"}
    if not settings.team_mode_enabled:
        return {"ok": False, "error": "Team mode is disabled"}

    db = SessionLocal()
    try:
        # Check if agent already exists
        existing = (
            db.query(TeamAgent)
            .filter(TeamAgent.owner_id == owner_id, TeamAgent.agent_key == agent_key)
            .first()
        )
        if existing:
            if existing.status == "active":
                return {
                    "ok": True,
                    "agent_key": agent_key,
                    "already_exists": True,
                    "agent_owner_id": int(existing.agent_owner_id),
                }
            # Reactivate stopped agent
            existing.status = "active"
            db.commit()
            return {
                "ok": True,
                "agent_key": agent_key,
                "reactivated": True,
                "agent_owner_id": int(existing.agent_owner_id),
            }

        # Create a new user record for the agent
        agent_username = f"agent_{agent_key}_{owner_id}"
        agent_user = User(
            username=agent_username,
            telegram_chat_id=f"agent_{agent_key}_{owner_id}",
        )
        db.add(agent_user)
        db.flush()

        # Create the team agent record
        team_agent = TeamAgent(
            owner_id=owner_id,
            agent_owner_id=agent_user.id,
            agent_key=agent_key,
            display_name=display_name,
            workspace_root="",
            status="active",
        )
        db.add(team_agent)
        db.commit()

        logger.info("SESSION_SPAWNED agent_key=%s owner=%d", agent_key, owner_id)
        return {
            "ok": True,
            "agent_key": agent_key,
            "agent_owner_id": int(agent_user.id),
            "display_name": display_name,
        }
    except Exception as exc:
        db.rollback()
        logger.error("SESSION_SPAWN_FAIL: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def tool_sessions_send(args: dict) -> dict:
    """Send a message to a session (run agent loop for that agent)."""
    agent_key = str(args.get("agent_key", "")).strip().lower()
    message = str(args.get("message", "")).strip()
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    if not agent_key or not message:
        return {"ok": False, "error": "agent_key and message are required"}
    if not owner_id:
        return {"ok": False, "error": "owner_id is required"}

    db = SessionLocal()
    try:
        # Resolve the agent's owner_id
        team_agent = (
            db.query(TeamAgent)
            .filter(
                TeamAgent.owner_id == owner_id,
                TeamAgent.agent_key == agent_key,
                TeamAgent.status == "active",
            )
            .first()
        )
        if not team_agent:
            return {"ok": False, "error": f"Agent '{agent_key}' not found or not active"}

        agent_owner_id = int(team_agent.agent_owner_id)
    finally:
        db.close()

    # Run agent loop for the sub-agent
    try:
        from ..agent.loop import run_agent_loop
        response = run_agent_loop(agent_owner_id, message)
        return {
            "ok": True,
            "agent_key": agent_key,
            "response": str(response or ""),
        }
    except Exception as exc:
        logger.error("SESSION_SEND_FAIL agent=%s: %s", agent_key, exc)
        return {"ok": False, "error": str(exc)[:300]}


def tool_sessions_list(args: dict) -> dict:
    """List active sessions (team agents)."""
    include_stopped = bool(args.get("include_stopped", True))
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    db = SessionLocal()
    try:
        query = db.query(TeamAgent).filter(TeamAgent.owner_id == owner_id)
        if not include_stopped:
            query = query.filter(TeamAgent.status == "active")
        rows = query.order_by(TeamAgent.id.asc()).all()

        sessions = []
        for row in rows:
            sessions.append({
                "agent_key": row.agent_key,
                "display_name": row.display_name,
                "status": row.status,
                "agent_owner_id": int(row.agent_owner_id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            })
        return {"ok": True, "sessions": sessions, "count": len(sessions)}
    except Exception as exc:
        logger.error("SESSION_LIST_FAIL: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def tool_sessions_history(args: dict) -> dict:
    """Get session conversation history."""
    agent_key = str(args.get("agent_key", "")).strip().lower()
    limit = int(args.get("limit", 40))
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    if not agent_key:
        return {"ok": False, "error": "agent_key is required"}

    db = SessionLocal()
    try:
        # Resolve agent owner ID
        team_agent = (
            db.query(TeamAgent)
            .filter(TeamAgent.owner_id == owner_id, TeamAgent.agent_key == agent_key)
            .first()
        )
        if not team_agent:
            return {"ok": False, "error": f"Agent '{agent_key}' not found"}

        agent_owner_id = int(team_agent.agent_owner_id)

        # Fetch conversation history
        rows = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.owner_id == agent_owner_id)
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
            .all()
        )
        messages = [
            {
                "role": row.role,
                "content": (row.content or "")[:500],
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in reversed(rows)
        ]
        return {
            "ok": True,
            "agent_key": agent_key,
            "messages": messages,
            "count": len(messages),
        }
    except Exception as exc:
        logger.error("SESSION_HISTORY_FAIL: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def tool_sessions_stop(args: dict) -> dict:
    """Stop a session (set team agent status to stopped)."""
    agent_key = str(args.get("agent_key", "")).strip().lower()
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    if not agent_key:
        return {"ok": False, "error": "agent_key is required"}

    db = SessionLocal()
    try:
        team_agent = (
            db.query(TeamAgent)
            .filter(TeamAgent.owner_id == owner_id, TeamAgent.agent_key == agent_key)
            .first()
        )
        if not team_agent:
            return {"ok": False, "error": f"Agent '{agent_key}' not found"}

        team_agent.status = "stopped"
        db.commit()
        logger.info("SESSION_STOPPED agent_key=%s owner=%d", agent_key, owner_id)
        return {"ok": True, "agent_key": agent_key, "stopped": True}
    except Exception as exc:
        db.rollback()
        logger.error("SESSION_STOP_FAIL: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()

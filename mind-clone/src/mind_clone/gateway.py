"""Bob Gateway -- manages connections, routes messages, survives agent crashes.

The gateway sits between channel adapters and the agent.  It assigns
sessions, routes messages through the agent, catches crashes, and keeps
the overall process alive even if individual agent calls fail.

Usage:
    from mind_clone.gateway import process_message, start_gateway, get_gateway_status

    msg = BobMessage(source="telegram", chat_id="123", owner_id=1, text="Hello")
    response = process_message(msg)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any

from mind_clone.core.message import BobMessage
from mind_clone.core.sessions import (
    get_or_create_session,
    increment_session_errors,
    cleanup_stale_sessions,
    list_active_sessions,
    session_count,
)

logger = logging.getLogger("mind_clone.gateway")

# Gateway state
_gateway_started = False
_gateway_start_time: Optional[float] = None
_adapters: Dict[str, Any] = {}
_message_count = 0
_error_count = 0


# ---------------------------------------------------------------------------
# Core message processing
# ---------------------------------------------------------------------------

def process_message(msg: BobMessage) -> str:
    """Process a BobMessage through the agent.

    This is the main entry point.  It:
    1. Assigns / retrieves an isolated session.
    2. Runs the agent inside a try/except so crashes don't kill the gateway.
    3. Returns the agent's text response, or a polite error fallback.

    Args:
        msg: A normalised BobMessage from any adapter.

    Returns:
        Agent's text response, or an error message.
    """
    global _message_count, _error_count

    _message_count += 1

    # Ensure a session
    try:
        session_id = get_or_create_session(msg.owner_id, msg.source, msg.chat_id)
        msg.session_id = session_id
    except Exception as exc:
        logger.error("Session creation failed: %s", exc)
        session_id = "unknown"
        msg.session_id = session_id

    try:
        response = _run_agent_for_message(msg)
        return response

    except Exception as exc:
        # Agent crashed but the gateway survives
        _error_count += 1
        logger.error(
            "Agent error in session %s (source=%s, owner=%d): %s",
            session_id[:12], msg.source, msg.owner_id, exc,
        )
        increment_session_errors(session_id)
        return "Sorry, I encountered an error. Please try again."


def _run_agent_for_message(msg: BobMessage) -> str:
    """Call the actual agent loop for a message.

    Isolated in its own function so we can swap implementations or
    add middleware (rate limiting, logging, etc.) later.

    Args:
        msg: The BobMessage with session already assigned.

    Returns:
        Agent text response.
    """
    try:
        from mind_clone.services.telegram.dispatch import run_agent_loop_serialized

        response = run_agent_loop_serialized(msg.owner_id, msg.text)
        return response
    except ImportError:
        logger.warning("Agent loop not available -- returning fallback")
        return "I'm still starting up. Please try again in a moment."
    except Exception as exc:
        # Re-raise so the outer handler catches it
        raise


# ---------------------------------------------------------------------------
# Gateway lifecycle
# ---------------------------------------------------------------------------

def start_gateway() -> dict:
    """Initialise adapters and session management.

    Safe to call multiple times (idempotent).

    Returns:
        A status dict with the adapters loaded.
    """
    global _gateway_started, _gateway_start_time

    if _gateway_started:
        return {"ok": True, "status": "already_started", "adapters": list(_adapters.keys())}

    logger.info("Starting Bob Gateway...")

    # Load adapters safely
    _load_adapters()

    # Clean up any leftover sessions from a previous run
    try:
        cleaned = cleanup_stale_sessions(max_age_hours=0)
        if cleaned:
            logger.info("Cleared %d leftover sessions from previous run", cleaned)
    except Exception as exc:
        logger.warning("Session cleanup on start failed: %s", exc)

    _gateway_started = True
    _gateway_start_time = time.monotonic()

    logger.info(
        "Bob Gateway started with adapters: %s",
        ", ".join(_adapters.keys()) or "(none)",
    )

    return {
        "ok": True,
        "status": "started",
        "adapters": list(_adapters.keys()),
    }


def _load_adapters() -> None:
    """Load available channel adapters into the registry."""
    try:
        from mind_clone.adapters.telegram_adapter import TelegramAdapter
        _adapters["telegram"] = TelegramAdapter()
    except Exception as exc:
        logger.warning("Failed to load TelegramAdapter: %s", exc)

    try:
        from mind_clone.adapters.cron_adapter import CronAdapter
        _adapters["cron"] = CronAdapter()
    except Exception as exc:
        logger.warning("Failed to load CronAdapter: %s", exc)


def get_adapter(name: str) -> Optional[Any]:
    """Retrieve a loaded adapter by channel name.

    Args:
        name: Channel name (e.g. "telegram", "cron").

    Returns:
        The adapter instance, or None if not loaded.
    """
    return _adapters.get(name)


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

def get_gateway_status() -> dict:
    """Return gateway health information.

    Returns:
        A dict with uptime, adapter count, message stats, and session info.
    """
    uptime = 0.0
    if _gateway_start_time is not None:
        uptime = round(time.monotonic() - _gateway_start_time, 1)

    return {
        "ok": _gateway_started,
        "uptime_seconds": uptime,
        "adapters_loaded": list(_adapters.keys()),
        "adapter_count": len(_adapters),
        "messages_processed": _message_count,
        "errors": _error_count,
        "active_sessions": len(list_active_sessions()),
        "total_sessions": session_count(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "process_message",
    "start_gateway",
    "get_gateway_status",
    "get_adapter",
]

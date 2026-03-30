"""Persistent Channel Binding — saves and restores Telegram connection state.

When Bob restarts, the Telegram chat_id-to-owner mapping is lost.  This
module persists channel state to ``~/.mind-clone/channels.json`` so it
can be restored on startup without requiring the user to send ``/start``
again.

Lifecycle:
- On every incoming message: ``save_channel_state()`` writes to disk.
- On startup: ``load_channel_state()`` restores the mapping.
- Quick accessors ``get_saved_chat_id()`` / ``get_saved_owner_id()``
  let other modules retrieve the last-known Telegram identifiers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.services.channel_state")

# Canonical location for the state file
_STATE_DIR = Path.home() / ".mind-clone"
_STATE_FILE = _STATE_DIR / "channels.json"


def save_channel_state(
    chat_id: str,
    username: str,
    owner_id: int,
    last_update_id: int = 0,
) -> None:
    """Persist Telegram channel state to disk.

    Creates ``~/.mind-clone/`` if it doesn't exist.  Updates the
    ``connected_at`` timestamp on first write and ``last_message_at``
    on every subsequent call.

    Args:
        chat_id: Telegram chat ID string.
        username: Telegram username.
        owner_id: Internal Bob owner ID.
        last_update_id: Telegram update ID for resume (default 0).
    """
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()

        existing = _read_state_file()
        telegram_block = existing.get("telegram", {})

        # Preserve connected_at from first connection
        connected_at = telegram_block.get("connected_at", now_iso)

        state: dict[str, Any] = {
            "telegram": {
                "chat_id": str(chat_id),
                "username": str(username or ""),
                "owner_id": int(owner_id),
                "last_update_id": int(last_update_id),
                "connected_at": connected_at,
                "last_message_at": now_iso,
            }
        }

        _STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug(
            "Channel state saved: chat_id=%s owner_id=%d", chat_id, owner_id
        )
    except Exception as exc:
        logger.warning("Failed to save channel state: %s", exc)


def load_channel_state() -> dict[str, Any] | None:
    """Load channel state from disk.

    Returns:
        The full state dict (with a ``telegram`` key), or ``None`` if the
        file doesn't exist or is corrupt.
    """
    try:
        data = _read_state_file()
        if data and "telegram" in data:
            logger.info(
                "Channel state loaded: chat_id=%s owner_id=%s",
                data["telegram"].get("chat_id"),
                data["telegram"].get("owner_id"),
            )
            return data
        return None
    except Exception as exc:
        logger.warning("Failed to load channel state: %s", exc)
        return None


def get_saved_chat_id() -> str | None:
    """Quick accessor for the last-known Telegram chat ID.

    Returns:
        The chat_id string, or ``None`` if no state has been saved.
    """
    state = load_channel_state()
    if state and "telegram" in state:
        return state["telegram"].get("chat_id")
    return None


def get_saved_owner_id() -> int | None:
    """Quick accessor for the last-known owner ID.

    Returns:
        The owner_id integer, or ``None`` if no state has been saved.
    """
    state = load_channel_state()
    if state and "telegram" in state:
        owner = state["telegram"].get("owner_id")
        return int(owner) if owner is not None else None
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_state_file() -> dict[str, Any]:
    """Read and parse the state file, returning an empty dict on failure."""
    if not _STATE_FILE.exists():
        return {}
    try:
        raw = _STATE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt channel state file: %s", exc)
        return {}

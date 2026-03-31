"""Unified message format for Bob AI agent.

Every channel (Telegram, WhatsApp, cron, API, voice) normalizes its
raw input into a BobMessage before handing it to the agent.  This
decouples the transport layer from the reasoning layer so adding a new
channel never requires touching agent code.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("mind_clone.core.message")


@dataclass
class BobMessage:
    """Universal message format -- every channel converts to this."""

    source: str  # "telegram", "whatsapp", "cron", "api", "voice"
    chat_id: str
    owner_id: int
    text: str
    session_id: str = ""  # unique per conversation session
    message_id: str = ""
    username: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Optional attachments
    image_bytes: Optional[bytes] = None
    voice_bytes: Optional[bytes] = None
    caption: str = ""

    # Metadata
    is_command: bool = False
    is_voice: bool = False
    is_photo: bool = False
    reply_with_voice: bool = False  # If True, agent should reply with voice note too

    def to_dict(self) -> dict:
        """Serialise the message to a plain dict (no binary data)."""
        return {
            "source": self.source,
            "chat_id": self.chat_id,
            "owner_id": self.owner_id,
            "text": self.text,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "username": self.username,
            "is_voice": self.is_voice,
            "is_photo": self.is_photo,
            "is_command": self.is_command,
            "reply_with_voice": self.reply_with_voice,
            "caption": self.caption,
            "timestamp": self.timestamp.isoformat(),
        }

    @staticmethod
    def generate_message_id() -> str:
        """Create a unique message ID."""
        return uuid.uuid4().hex[:16]

    def __repr__(self) -> str:
        return (
            f"BobMessage(source={self.source!r}, chat_id={self.chat_id!r}, "
            f"owner_id={self.owner_id}, text={self.text[:40]!r}...)"
        )


__all__ = ["BobMessage"]

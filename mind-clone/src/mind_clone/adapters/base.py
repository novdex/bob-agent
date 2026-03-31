"""Base adapter interface for all channel adapters.

Every channel (Telegram, WhatsApp, cron, API, etc.) implements this
interface so the gateway can treat them uniformly.
"""

from __future__ import annotations

import logging
from typing import Any

from mind_clone.core.message import BobMessage

logger = logging.getLogger("mind_clone.adapters.base")


class BaseAdapter:
    """Base class for all channel adapters.

    Subclasses MUST override ``name``, ``normalize``, and ``send``.
    ``send_voice`` is optional -- not all channels support voice replies.
    """

    name: str = "base"

    def normalize(self, raw_message: dict[str, Any]) -> BobMessage:
        """Convert a raw channel message into a BobMessage.

        Args:
            raw_message: Channel-specific dict (e.g. Telegram Update).

        Returns:
            A normalised BobMessage ready for the agent.

        Raises:
            NotImplementedError: Subclass must implement this.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.normalize()")

    def send(self, chat_id: str, text: str) -> bool:
        """Send a text reply back through this channel.

        Args:
            chat_id: The channel-specific chat identifier.
            text: The message body to send.

        Returns:
            True if the message was sent successfully.

        Raises:
            NotImplementedError: Subclass must implement this.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.send()")

    def send_voice(self, chat_id: str, audio_bytes: bytes) -> bool:
        """Send a voice reply (optional, not all channels support it).

        Args:
            chat_id: The channel-specific chat identifier.
            audio_bytes: Raw audio data (MP3 or OGG).

        Returns:
            True if sent, False if unsupported or failed.
        """
        logger.debug(
            "%s.send_voice() not implemented -- voice replies unsupported",
            self.__class__.__name__,
        )
        return False

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


__all__ = ["BaseAdapter"]

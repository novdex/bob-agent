"""Telegram channel adapter.

Converts raw Telegram Update dicts into BobMessage and delegates
sending back through the existing Telegram messaging helpers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mind_clone.core.message import BobMessage
from .base import BaseAdapter

logger = logging.getLogger("mind_clone.adapters.telegram")


class TelegramAdapter(BaseAdapter):
    """Adapter for the Telegram Bot API channel."""

    name: str = "telegram"

    # ------------------------------------------------------------------
    # Normalise
    # ------------------------------------------------------------------

    def normalize(self, raw_message: dict[str, Any]) -> BobMessage:
        """Convert a Telegram message/update dict to BobMessage.

        Handles text messages, voice messages, and photo messages.
        The *raw_message* should be the ``message`` object from a
        Telegram Update (not the full Update wrapper).

        Args:
            raw_message: Telegram message dict with keys like
                ``chat``, ``text``, ``voice``, ``photo``, ``from``, etc.

        Returns:
            A normalised BobMessage.
        """
        try:
            chat = raw_message.get("chat", {})
            from_user = raw_message.get("from", {})

            chat_id = str(chat.get("id", ""))
            username = from_user.get("username", "")
            message_id = str(raw_message.get("message_id", ""))

            # Determine owner_id -- try to resolve, fall back to 0
            owner_id = self._resolve_owner(chat_id, username)

            # Text
            text = raw_message.get("text", "") or ""
            caption = raw_message.get("caption", "") or ""

            # Flags
            is_command = text.startswith("/") if text else False
            is_voice = "voice" in raw_message
            is_photo = "photo" in raw_message

            # If the message is a voice/photo with a caption, use caption as text
            if not text and caption:
                text = caption

            msg = BobMessage(
                source="telegram",
                chat_id=chat_id,
                owner_id=owner_id,
                text=text,
                message_id=message_id,
                username=username,
                caption=caption,
                is_command=is_command,
                is_voice=is_voice,
                is_photo=is_photo,
                reply_with_voice=is_voice,  # Reply with voice if they sent voice
            )

            logger.debug(
                "Normalised Telegram message: chat=%s user=%s voice=%s photo=%s",
                chat_id, username, is_voice, is_photo,
            )
            return msg

        except Exception as exc:
            logger.error("TelegramAdapter.normalize() error: %s", exc)
            # Return a minimal message so processing can continue
            return BobMessage(
                source="telegram",
                chat_id=str(raw_message.get("chat", {}).get("id", "unknown")),
                owner_id=0,
                text=raw_message.get("text", "[parse error]"),
            )

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(self, chat_id: str, text: str) -> bool:
        """Send a text reply through Telegram.

        Uses the existing ``send_telegram_message`` async helper,
        running it in the current event loop if one exists or creating
        a new one otherwise.

        Args:
            chat_id: Telegram chat ID.
            text: Message body.

        Returns:
            True on success, False on failure.
        """
        try:
            from mind_clone.services.telegram.messaging import send_telegram_message

            self._run_async(send_telegram_message(chat_id, text))
            return True
        except Exception as exc:
            logger.error("TelegramAdapter.send() failed: %s", exc)
            return False

    def send_voice(self, chat_id: str, audio_bytes: bytes) -> bool:
        """Send a voice note through Telegram.

        Args:
            chat_id: Telegram chat ID.
            audio_bytes: MP3 or OGG audio data.

        Returns:
            True on success, False on failure.
        """
        try:
            from mind_clone.services.telegram.messaging import send_telegram_voice

            self._run_async(send_telegram_voice(chat_id, audio_bytes))
            return True
        except Exception as exc:
            logger.error("TelegramAdapter.send_voice() failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_owner(chat_id: str, username: str) -> int:
        """Resolve the owner_id from the Telegram chat, returning 0 on failure."""
        try:
            from mind_clone.agent.identity import resolve_owner_id

            return resolve_owner_id(chat_id, username)
        except Exception:
            return 0

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Run an async coroutine from sync context safely."""
        try:
            loop = asyncio.get_running_loop()
            # Already in an async context -- schedule as a task
            return asyncio.ensure_future(coro)
        except RuntimeError:
            # No running loop -- create one
            return asyncio.run(coro)


__all__ = ["TelegramAdapter"]

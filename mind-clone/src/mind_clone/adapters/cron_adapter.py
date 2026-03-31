"""Cron job channel adapter.

Converts scheduled / cron job payloads into BobMessage with source="cron"
and routes replies back through the owner's Telegram chat.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mind_clone.core.message import BobMessage
from .base import BaseAdapter

logger = logging.getLogger("mind_clone.adapters.cron")


class CronAdapter(BaseAdapter):
    """Adapter for cron / scheduled-job messages."""

    name: str = "cron"

    def normalize(self, raw_message: dict[str, Any]) -> BobMessage:
        """Convert a cron job payload into a BobMessage.

        Expected keys in *raw_message*:
            - ``owner_id`` (int): The user who owns the job.
            - ``chat_id`` (str): Where to send the result.
            - ``text`` or ``prompt`` (str): The instruction to execute.
            - ``job_name`` (str, optional): Name of the cron job.
            - ``username`` (str, optional): Username for context.

        Args:
            raw_message: Cron job payload dict.

        Returns:
            A normalised BobMessage with source="cron".
        """
        try:
            owner_id = int(raw_message.get("owner_id", 0))
            chat_id = str(raw_message.get("chat_id", ""))
            text = str(
                raw_message.get("text", "")
                or raw_message.get("prompt", "")
                or raw_message.get("instruction", "")
            )
            job_name = str(raw_message.get("job_name", "cron"))
            username = str(raw_message.get("username", ""))

            msg = BobMessage(
                source="cron",
                chat_id=chat_id,
                owner_id=owner_id,
                text=text,
                message_id=f"cron-{job_name}-{BobMessage.generate_message_id()}",
                username=username,
                is_command=False,
                is_voice=False,
                is_photo=False,
            )

            logger.debug(
                "Normalised cron message: owner=%d job=%s text=%.60s",
                owner_id, job_name, text,
            )
            return msg

        except Exception as exc:
            logger.error("CronAdapter.normalize() error: %s", exc)
            return BobMessage(
                source="cron",
                chat_id=str(raw_message.get("chat_id", "")),
                owner_id=int(raw_message.get("owner_id", 0)),
                text="[cron parse error]",
            )

    def send(self, chat_id: str, text: str) -> bool:
        """Send a cron job result to the owner's Telegram chat.

        Cron jobs have no native reply channel so results are delivered
        through the owner's Telegram.

        Args:
            chat_id: Owner's Telegram chat ID.
            text: Result text to deliver.

        Returns:
            True on success, False on failure.
        """
        try:
            from mind_clone.services.telegram.messaging import send_telegram_message

            self._run_async(send_telegram_message(chat_id, text))
            return True
        except Exception as exc:
            logger.error("CronAdapter.send() failed: %s", exc)
            return False

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Run an async coroutine from sync context safely."""
        try:
            loop = asyncio.get_running_loop()
            return asyncio.ensure_future(coro)
        except RuntimeError:
            return asyncio.run(coro)


__all__ = ["CronAdapter"]

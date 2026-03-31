"""Channel adapters for Bob AI agent.

Each adapter normalises a channel's raw messages into BobMessage and
provides send / send_voice methods for replying through that channel.

Usage:
    from mind_clone.adapters import TelegramAdapter, CronAdapter

Adapters are independent -- if one fails to import the others still work.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("mind_clone.adapters")

# Import adapters safely so one broken adapter doesn't prevent the rest
try:
    from .telegram_adapter import TelegramAdapter  # noqa: F401
except Exception as exc:
    _log.warning("TelegramAdapter unavailable: %s", exc)

try:
    from .cron_adapter import CronAdapter  # noqa: F401
except Exception as exc:
    _log.warning("CronAdapter unavailable: %s", exc)

from .base import BaseAdapter  # noqa: F401

__all__ = ["BaseAdapter", "TelegramAdapter", "CronAdapter"]

"""
Discord Bot Adapter for Mind Clone Agent.

Routes Discord messages through the same agent loop as Telegram/API.
Requires ``discord.py`` (pip install discord.py).  If the library is not
installed the adapter gracefully degrades — ``start_discord_bot()`` returns
immediately and logs a warning.

Usage:
    import asyncio
    from mind_clone.services.discord_adapter import start_discord_bot
    asyncio.run(start_discord_bot())
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from ..config import settings

logger = logging.getLogger("mind_clone.discord")

# Optional import — allows the codebase to compile without discord.py
try:
    import discord
    from discord import Intents, Message

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False
    discord = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------
CHANNEL_NAME = "discord"
MAX_DISCORD_MESSAGE_LEN = 2000  # Discord's hard limit


def _chunk_response(text: str, limit: int = MAX_DISCORD_MESSAGE_LEN) -> list[str]:
    """Split a long response into Discord-safe chunks."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at newline
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------------------
# Bot implementation
# ---------------------------------------------------------------------------

class MindCloneDiscordBot:
    """Thin wrapper that maps Discord events to the agent loop."""

    def __init__(self) -> None:
        if not _DISCORD_AVAILABLE:
            raise RuntimeError("discord.py is not installed")

        intents = Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        @self.client.event
        async def on_ready():
            logger.info(
                "Discord bot ready: %s (id=%s)",
                self.client.user,
                self.client.user.id if self.client.user else "?",
            )

        @self.client.event
        async def on_message(message: "Message"):
            # Ignore own messages
            if message.author == self.client.user:
                return
            # Ignore messages not mentioning the bot (unless DM)
            is_dm = message.guild is None
            is_mention = self.client.user in message.mentions if self.client.user else False
            if not is_dm and not is_mention:
                return

            text = message.content.strip()
            # Strip the bot mention from the message
            if self.client.user and not is_dm:
                text = text.replace(f"<@{self.client.user.id}>", "").strip()
                text = text.replace(f"<@!{self.client.user.id}>", "").strip()
            if not text:
                return

            chat_id = f"discord_{message.channel.id}"
            username = str(message.author)

            # Route through agent loop
            try:
                response = await self._dispatch(
                    chat_id=chat_id,
                    username=username,
                    text=text,
                )
            except Exception as e:
                logger.error("Discord dispatch error: %s", e, exc_info=True)
                response = f"Error: {str(e)[:200]}"

            # Send response (chunked if needed)
            for chunk in _chunk_response(response or "(no response)"):
                await message.channel.send(chunk)

    async def _dispatch(
        self, chat_id: str, username: str, text: str
    ) -> str:
        """Route a message through the agent loop."""
        from ..agent.loop import run_agent_loop
        from ..database.session import SessionLocal
        from ..database.models import User

        # Resolve or create owner
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                user = User(username=username, source="discord")
                db.add(user)
                db.commit()
                db.refresh(user)
            owner_id = user.id
        finally:
            db.close()

        # Run agent loop in executor (blocking call)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_agent_loop, owner_id, text)
        return str(result or "")

    async def start(self, token: str) -> None:
        await self.client.start(token)

    async def close(self) -> None:
        if self.client and not self.client.is_closed():
            await self.client.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def start_discord_bot() -> None:
    """Start the Discord bot if configured and available."""
    if not _DISCORD_AVAILABLE:
        logger.warning("discord.py not installed — Discord adapter disabled")
        return

    token = getattr(settings, "discord_bot_token", "") or ""
    if not token:
        logger.info("DISCORD_BOT_TOKEN not set — Discord adapter disabled")
        return

    bot = MindCloneDiscordBot()
    logger.info("Starting Discord bot...")
    try:
        await bot.start(token)
    except Exception as e:
        logger.error("Discord bot failed: %s", e, exc_info=True)
    finally:
        await bot.close()

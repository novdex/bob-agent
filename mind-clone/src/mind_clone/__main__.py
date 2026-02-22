"""
Entry point for Mind Clone Agent.

Usage:
    python -m mind_clone
    python -m mind_clone --web
    python -m mind_clone --telegram-poll
    python -m mind_clone --run "task"

Environment Variables:
    KIMI_API_KEY - Moonshot AI API key
    TELEGRAM_BOT_TOKEN - Telegram bot token
    WEBHOOK_BASE_URL - Public URL for webhooks
"""

from __future__ import annotations

from .runner import main

if __name__ == "__main__":
    main()

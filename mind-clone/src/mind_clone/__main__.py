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

import os
from pathlib import Path


def _load_dotenv_from_package() -> None:
    """Find and load .env from the mind-clone project root.

    Pydantic's env_file=".env" only works relative to cwd.
    This ensures .env is loaded regardless of where the user runs
    ``python -m mind_clone`` from.

    Search order:
      1. cwd (already handled by Pydantic, but we pre-load for safety)
      2. mind-clone/ project root (two dirs up from this file)
      3. The repo root (three dirs up: mind-clone/src/mind_clone/__main__.py)
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv not installed — fall back to manual load
        _manual_load_env()
        return

    # This file lives at mind-clone/src/mind_clone/__main__.py
    this_dir = Path(__file__).resolve().parent          # .../mind_clone/
    src_dir = this_dir.parent                            # .../src/
    project_dir = src_dir.parent                         # .../mind-clone/
    repo_dir = project_dir.parent                        # .../ai-agent-platform/

    for candidate in [Path.cwd(), project_dir, repo_dir]:
        env_path = candidate / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            return


def _manual_load_env() -> None:
    """Minimal .env loader when python-dotenv is not installed."""
    this_dir = Path(__file__).resolve().parent
    project_dir = this_dir.parent.parent  # mind-clone/

    for candidate in [Path.cwd(), project_dir, project_dir.parent]:
        env_path = candidate / ".env"
        if env_path.is_file():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Don't override existing env vars
                    if key and key not in os.environ:
                        os.environ[key] = value
            return


# Load .env BEFORE any mind_clone imports that trigger Settings()
_load_dotenv_from_package()

from .runner import main

if __name__ == "__main__":
    main()

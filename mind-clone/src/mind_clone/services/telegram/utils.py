"""Telegram adapter utility functions."""
from __future__ import annotations

from ._imports import *  # noqa: F401,F403
from ._imports import (
    datetime,
    timezone,
    timedelta,
    re,
    Any,
    log,
)


# ============================================================================
# Utility Functions
# ============================================================================


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def iso_after_seconds(seconds: float) -> str:
    """Return ISO timestamp after specified seconds."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))
    return dt.isoformat()


def _normalize_schedule_lane(lane: str) -> str:
    """Normalize schedule lane to a valid value."""
    valid_lanes = {"default", "interactive", "background", "cron", "agent", "research"}
    lane = (lane or "cron").strip().lower()
    return lane if lane in valid_lanes else "cron"


def _compute_next_run_at_time(run_at_time: str | None) -> datetime | None:
    """Compute next run time from a time string (HH:MM)."""
    if not run_at_time:
        return None
    try:
        now = datetime.now(timezone.utc)
        parts = str(run_at_time).split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target
    except Exception:
        return None


def clamp_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    """Clamp integer value to range."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except Exception:
        return default


def parse_approval_token(text: str, command_name: str) -> str | None:
    """Parse approval token from command text."""
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    if parts[0].strip().lower() != command_name.strip().lower():
        return None
    token = parts[1].strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", token):
        return None
    return token


def parse_command_id(text: str, command_name: str) -> int | None:
    """Parse command ID from text (e.g., /cancel 123)."""
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0] != command_name:
        return None
    try:
        return int(parts[1].strip())
    except Exception:
        return None

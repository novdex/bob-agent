"""
Command queue utilities with steer/followup mode support.
"""

import logging
from typing import Dict, Any

from ..config import COMMAND_QUEUE_MODE
from .state import OWNER_QUEUE_COUNTS, OWNER_STATE_LOCK

logger = logging.getLogger("mind_clone.queue")

COMMAND_QUEUE_WORKER_COUNT = 2

# Valid queue modes matching the monolith
VALID_QUEUE_MODES = {"off", "on", "auto", "steer", "followup", "collect"}

# Lane definitions matching the monolith
VALID_LANES = {"default", "interactive", "background", "batch", "cron", "research", "api", "telegram", "task"}

# Max queue capacity per owner (hard limit to prevent unbounded growth)
MAX_QUEUE_CAPACITY_PER_OWNER = 1000


def command_queue_enabled() -> bool:
    return COMMAND_QUEUE_MODE != "off"


def effective_command_queue_mode(owner_id: int = None) -> str:
    return COMMAND_QUEUE_MODE


def classify_message_lane(source: str = "", message: str = "") -> str:
    """Classify a message into a processing lane (matches monolith logic)."""
    src = str(source or "").lower()
    text = str(message or "").lower()

    if src == "cron" or src == "scheduler":
        return "cron"
    if src == "telegram":
        return "telegram"
    if src == "api":
        return "api"
    if "deep_research" in text or "research" in src:
        return "research"
    if "/task" in text:
        return "task"
    if any(kw in text for kw in ("urgent", "asap", "critical", "emergency")):
        return "interactive"
    return "default"


def normalize_queue_lane(lane: str) -> str:
    return lane if lane in VALID_LANES else "default"


def should_enqueue_message(
    mode: str, source: str, message: str, owner_id: int
) -> bool:
    """Decide whether to enqueue a message based on the current queue mode.

    Modes:
    - ``off``      — never queue (direct routing)
    - ``on``       — always queue
    - ``steer``    — queue only research/cron lanes
    - ``followup`` — queue only if owner is backlogged
    - ``collect``  — always queue (with collection window)
    - ``auto``     — queue when backpressure detected
    """
    m = str(mode or "auto").lower()
    if m == "off":
        return False
    if m in ("on", "collect"):
        return True
    if m == "steer":
        lane = classify_message_lane(source, message)
        return lane in ("research", "cron", "task")
    if m == "followup":
        return is_owner_busy_or_backlogged(owner_id)
    # auto — queue when owner is backlogged
    return is_owner_busy_or_backlogged(owner_id)


def is_owner_busy_or_backlogged(owner_id: int) -> bool:
    with OWNER_STATE_LOCK:
        return OWNER_QUEUE_COUNTS.get(owner_id, 0) > 0


def increment_owner_queue(owner_id: int) -> int:
    """Increment queue count for owner, with bounds checking.

    Raises:
        ValueError: If queue is at max capacity
    """
    with OWNER_STATE_LOCK:
        current = OWNER_QUEUE_COUNTS.get(owner_id, 0)
        if current >= MAX_QUEUE_CAPACITY_PER_OWNER:
            logger.warning(
                "increment_owner_queue: max capacity reached owner_id=%d current=%d",
                owner_id, current
            )
            raise ValueError(
                f"Queue at max capacity ({MAX_QUEUE_CAPACITY_PER_OWNER}) for owner {owner_id}"
            )
        OWNER_QUEUE_COUNTS[owner_id] = current + 1
        return OWNER_QUEUE_COUNTS[owner_id]


def decrement_owner_queue(owner_id: int) -> int:
    with OWNER_STATE_LOCK:
        current = OWNER_QUEUE_COUNTS.get(owner_id, 0)
        if current > 0:
            OWNER_QUEUE_COUNTS[owner_id] = current - 1
        return OWNER_QUEUE_COUNTS.get(owner_id, 0)


def owner_active_count(owner_id: int) -> int:
    with OWNER_STATE_LOCK:
        return OWNER_QUEUE_COUNTS.get(owner_id, 0)


def owner_backlog_count(owner_id: int) -> int:
    """Return queued item count for an owner from the database."""
    try:
        from ..database.session import SessionLocal
        from ..database.models import Task
        db = SessionLocal()
        try:
            count = db.query(Task).filter(
                Task.owner_id == owner_id,
                Task.status.in_(["queued", "running"]),
            ).count()
            return count
        finally:
            db.close()
    except Exception:
        return 0


def active_command_queue_worker_count() -> int:
    from .state import COMMAND_QUEUE_WORKER_TASKS

    return len(COMMAND_QUEUE_WORKER_TASKS)


async def ensure_command_queue_workers_running():
    pass


async def cancel_command_queue_workers():
    pass


def set_owner_queue_mode(owner_id: int, mode: str) -> str:
    return mode


def _collect_buffer_append(owner_id: int, key: str, value):
    from .state import _collect_buffers

    if owner_id not in _collect_buffers:
        _collect_buffers[owner_id] = {}
    if key not in _collect_buffers[owner_id]:
        _collect_buffers[owner_id][key] = []
    _collect_buffers[owner_id][key].append(value)


def _collect_buffer_pop(owner_id: int, key: str):
    from .state import _collect_buffers

    if owner_id in _collect_buffers and key in _collect_buffers[owner_id]:
        return _collect_buffers[owner_id].pop(key, None)
    return None


def pop_expired_collect_buffers():
    """Pop and return collect buffers that have expired (older than 60s)."""
    import time as _time
    from .state import _collect_buffers

    expired = {}
    now = _time.monotonic()
    for owner_id, buffers in list(_collect_buffers.items()):
        for key, entries in list(buffers.items()):
            if isinstance(entries, list) and len(entries) > 0:
                # Check timestamp of first entry if available
                first = entries[0] if entries else None
                if isinstance(first, dict) and first.get("_ts", 0) < now - 60:
                    expired.setdefault(owner_id, {})[key] = _collect_buffer_pop(owner_id, key)
    return expired


def get_lane_semaphore(lane: str):
    """Get or create an asyncio-style semaphore for a processing lane."""
    import asyncio as _asyncio
    from .state import COMMAND_QUEUE_LANE_SEMAPHORES

    lane = normalize_queue_lane(lane)
    if lane not in COMMAND_QUEUE_LANE_SEMAPHORES:
        # Default concurrency: 2 for interactive, 1 for research/batch, 3 for others
        concurrency = {"interactive": 2, "research": 1, "batch": 1}.get(lane, 3)
        try:
            COMMAND_QUEUE_LANE_SEMAPHORES[lane] = _asyncio.Semaphore(concurrency)
        except RuntimeError:
            # No event loop running — return None (caller should handle)
            return None
    return COMMAND_QUEUE_LANE_SEMAPHORES.get(lane)


def queue_stats() -> Dict[str, Any]:
    """Get queue statistics across all owners.

    Returns:
        Dict with keys: owner_count, total_queued, max_capacity, owners_at_capacity
    """
    with OWNER_STATE_LOCK:
        owner_count = len(OWNER_QUEUE_COUNTS)
        total_queued = sum(OWNER_QUEUE_COUNTS.values())
        owners_at_capacity = sum(
            1 for count in OWNER_QUEUE_COUNTS.values()
            if count >= MAX_QUEUE_CAPACITY_PER_OWNER
        )
    return {
        "owner_count": owner_count,
        "total_queued": total_queued,
        "max_capacity": MAX_QUEUE_CAPACITY_PER_OWNER,
        "owners_at_capacity": owners_at_capacity,
    }


__all__ = [
    "command_queue_enabled",
    "effective_command_queue_mode",
    "classify_message_lane",
    "normalize_queue_lane",
    "is_owner_busy_or_backlogged",
    "increment_owner_queue",
    "decrement_owner_queue",
    "owner_active_count",
    "owner_backlog_count",
    "ensure_command_queue_workers_running",
    "cancel_command_queue_workers",
    "set_owner_queue_mode",
    "queue_stats",
    "COMMAND_QUEUE_MODE",
    "COMMAND_QUEUE_WORKER_COUNT",
    "MAX_QUEUE_CAPACITY_PER_OWNER",
]

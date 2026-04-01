"""
Runtime state management, background task handles, and global locks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from ....core.state import (
    RUNTIME_STATE,
    get_runtime_state,
    get_runtime_metrics,
    RUNTIME_STATE_LOCK,
)


# Global background task handles (module level)
TASK_WORKER_TASK: Optional[asyncio.Task] = None
WEBHOOK_RETRY_TASK: Optional[asyncio.Task] = None
WEBHOOK_SUPERVISOR_TASK: Optional[asyncio.Task] = None
SPINE_SUPERVISOR_TASK: Optional[asyncio.Task] = None
COMMAND_QUEUE_WORKER_TASK: Optional[asyncio.Task] = None
CRON_SUPERVISOR_TASK: Optional[asyncio.Task] = None
HEARTBEAT_SUPERVISOR_TASK: Optional[asyncio.Task] = None
HEARTBEAT_WAKE_EVENT: Optional[asyncio.Event] = None

# Global locks and state mirrors (for compatibility)
OWNER_STATE_LOCK = RUNTIME_STATE_LOCK
OWNER_QUEUE_COUNTS: Dict[int, int] = {}
OWNER_ACTIVE_RUNS: Dict[int, int] = {}
COMMAND_QUEUE_WORKER_TASKS: List[asyncio.Task] = []
NODE_CONTROL_LOCK = RUNTIME_STATE_LOCK
NODE_HEARTBEAT_MAP: Dict[str, Dict] = {}
PROTOCOL_SCHEMA_LOCK = RUNTIME_STATE_LOCK
PROTOCOL_SCHEMA_REGISTRY: Dict[str, Any] = {}
CANARY_STATE: Dict[str, Any] = {}

from .constants import _env_flag

CANARY_ROUTER_ENABLED = _env_flag("CANARY_ROUTER_ENABLED", False)


def runtime_metrics() -> Dict[str, Any]:
    """Get runtime metrics (wrapper for get_runtime_metrics)."""
    return get_runtime_metrics()


def runtime_uptime_seconds() -> float:
    """Get runtime uptime in seconds."""
    start = RUNTIME_STATE.get("app_start_monotonic")
    if start is None:
        return 0.0
    return time.monotonic() - float(start)

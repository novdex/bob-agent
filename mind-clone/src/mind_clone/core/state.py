"""
Runtime state management for Mind Clone Agent.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

# Global runtime state dictionary
RUNTIME_STATE: Dict[str, Any] = {
    "app_start_monotonic": None,
    "shutting_down": False,
    "worker_alive": False,
    "llm_primary_model": "kimi-k2.5",
    "llm_fallback_model": None,
    "llm_failover_enabled": False,
    "llm_last_model_used": None,
    "llm_last_attempt_at": None,
    "llm_last_success_at": None,
    "llm_last_error": None,
    "llm_failover_count": 0,
    "llm_primary_failures": 0,
    "llm_fallback_failures": 0,
    "autonomy_mode": "openclaw_max",
    "autonomy_openclaw_max": True,
    "policy_pack": "dev",
    "budget_governor_enabled": True,
    "budget_governor_mode": "degrade",
    "budget_runs_started": 0,
    "budget_runs_stopped": 0,
    "budget_runs_degraded": 0,
    "budget_last_scope": None,
    "budget_last_reason": None,
    "budget_last_usage": {},
    "command_queue_mode": "auto",
    "command_queue_worker_target": 2,
    "command_queue_worker_alive": False,
    "command_queue_worker_alive_count": 0,
    "command_queue_enqueued": 0,
    "command_queue_processed": 0,
    "command_queue_dropped": 0,
    "session_soft_trim_count": 0,
    "session_hard_clear_count": 0,
    "tool_policy_profile": "balanced",
    "tool_policy_blocks": 0,
    "workspace_diff_gate_enabled": True,
    "workspace_diff_gate_blocks": 0,
    "workspace_diff_gate_approvals": 0,
    "workspace_diff_gate_warns": 0,
    "secret_guardrail_enabled": True,
    "secret_redactions_total": 0,
    "execution_sandbox_profile": "default",
    "execution_sandbox_blocks": 0,
    "approval_gate_mode": "balanced",
    "approval_required_count": 0,
    "approval_pending_count": 0,
    "approval_approved_count": 0,
    "approval_rejected_count": 0,
    "task_graph_branches_created": 0,
    "task_graph_resume_events": 0,
    "circuit_blocked_calls": 0,
    "circuit_open_events": 0,
    "task_artifacts_stored": 0,
    "desktop_control_enabled": True,
    "desktop_actions_total": 0,
    "desktop_session_active": False,
    "memory_last_retrieved_total": 0,
    "world_model_forecasts_total": 0,
    "self_improve_notes_total": 0,
    "blackbox_events_total": 0,
    "spine_supervisor_alive": False,
    "startup_preflight_ok": False,
    "db_healthy": False,
    "webhook_registered": False,
    "cron_supervisor_alive": False,
    "plugin_tools_loaded": 0,
    "remote_nodes_loaded": 0,
    "node_control_plane_enabled": True,
    "ops_auth_enabled": False,
    "team_mode_enabled": True,
    "usage_ledger_events": 0,
    "usage_ledger_cost_usd": 0.0,
    "ssrf_blocked_requests": 0,
    "session_write_locks_active": 0,
    "session_write_lock_waits": 0,
    "session_tool_result_guard_blocks": 0,
    "session_tool_result_guard_truncations": 0,
    "skills_total": 0,
    "skills_prompt_injections": 0,
    "skills_autocreated": 0,
    "custom_tools_loaded": 0,
    "custom_tools_created": 0,
    "custom_tool_gap_hints": 0,
    "sandbox_registry_count": 0,
    "sandbox_registry_created": 0,
    "sandbox_registry_reused": 0,
    "sandbox_registry_cleanups": 0,
    "sandbox_registry_last_context": None,
    "stt_transcriptions": 0,
    "stt_failures": 0,
}

# Thread-safe state lock
RUNTIME_STATE_LOCK = threading.Lock()

# Owner-specific state management
OWNER_STATE_LOCK = threading.Lock()
OWNER_QUEUE_COUNTS: Dict[int, int] = {}
OWNER_ACTIVE_RUNS: Dict[int, Any] = {}

# Per-owner session write lock (transcript write-lock)
SESSION_WRITE_LOCK_GUARD = threading.Lock()
SESSION_WRITE_LOCKS: Dict[int, threading.Lock] = {}

# Per-owner execution lock (serializes agent loop per owner)
OWNER_EXECUTION_LOCK_GUARD = threading.Lock()
OWNER_EXECUTION_LOCKS: Dict[int, threading.Lock] = {}

# Context X-Ray
CONTEXT_XRAY_LOCK = threading.Lock()
CONTEXT_XRAY_SNAPSHOTS: Dict[int, Any] = {}
CONTEXT_XRAY_SEQ = 0

# Model router
MODEL_ROUTER_LOCK = threading.Lock()
MODEL_PROFILE_STICKY: Dict[str, str] = {}
MODEL_PROFILE_COOLDOWNS: Dict[str, float] = {}
MODEL_PROFILE_HEALTH: Dict[str, Any] = {}

# Sandbox registry
SANDBOX_REGISTRY_LOCK = threading.Lock()
SANDBOX_REGISTRY: Dict[str, Any] = {}

# Task guard
TASK_GUARD_LOCK = threading.Lock()
ACTIVE_TASK_EXECUTIONS: Dict[int, Any] = {}
TASK_GUARD_ORPHAN_RECOVERIES = 0

# Node control
NODE_CONTROL_LOCK = threading.Lock()
NODE_SCHEDULER_STATS: Dict[str, Any] = {}

# Circuit breaker
CIRCUIT_LOCK = threading.Lock()
PROVIDER_CIRCUITS: Dict[str, Any] = {}
CIRCUIT_STATE_DEFAULT = {"failures": 0, "last_failure": None, "open": False}

# Queues
COMMAND_QUEUE: Any = None
COMMAND_QUEUE_WORKER_TASK: Any = None
COMMAND_QUEUE_WORKER_TASKS: List[Any] = []
COMMAND_QUEUE_LANE_SEMAPHORES: Dict[str, Any] = {}
TASK_QUEUE: Any = None
TASK_QUEUE_IDS: set = set()

# Events
HEARTBEAT_WAKE_EVENT: Any = None
WEBHOOK_RETRY_TASK: Any = None

# Canary
CANARY_STATE: Dict[str, Any] = {}

# Internal tracking
_task_progress_last_send: Dict[int, float] = {}
_collect_buffers: Dict[str, Any] = {}
_self_improve_last_time: float = 0.0


def get_runtime_state() -> Dict[str, Any]:
    """Get a copy of the current runtime state."""
    with RUNTIME_STATE_LOCK:
        return dict(RUNTIME_STATE)


def set_runtime_state_value(key: str, value: Any) -> None:
    """Set a value in the runtime state."""
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE[key] = value


def increment_runtime_state(key: str, delta: int = 1) -> int:
    """Increment a counter in the runtime state."""
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE[key] = int(RUNTIME_STATE.get(key, 0)) + delta
        return RUNTIME_STATE[key]


def update_runtime_state(updates: Dict[str, Any]) -> None:
    """Update multiple values in the runtime state."""
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE.update(updates)


def get_runtime_metrics() -> Dict[str, Any]:
    """Get key runtime metrics for monitoring."""
    return {
        "worker_alive": RUNTIME_STATE.get("worker_alive", False),
        "llm_failover_enabled": RUNTIME_STATE.get("llm_failover_enabled", False),
        "command_queue_mode": RUNTIME_STATE.get("command_queue_mode", "auto"),
        "command_queue_worker_alive": RUNTIME_STATE.get("command_queue_worker_alive", False),
        "approval_pending_count": RUNTIME_STATE.get("approval_pending_count", 0),
        "db_healthy": RUNTIME_STATE.get("db_healthy", False),
        "webhook_registered": RUNTIME_STATE.get("webhook_registered", False),
    }


def runtime_keys() -> list:
    """Return a list of all currently set keys in RUNTIME_STATE."""
    with RUNTIME_STATE_LOCK:
        return list(RUNTIME_STATE.keys())


def get_runtime_value(key: str, default: Any = None) -> Any:
    """Get a value from RUNTIME_STATE with logging on unknown keys.

    Args:
        key: The state key to retrieve
        default: Default value if key not found

    Returns:
        The value from RUNTIME_STATE or the default
    """
    with RUNTIME_STATE_LOCK:
        if key not in RUNTIME_STATE:
            _state_logger.warning(
                "get_runtime_value: unknown key '%s' (returning default=%r)",
                key, default
            )
            return default
        return RUNTIME_STATE[key]


def set_runtime_value(key: str, value: Any) -> None:
    """Set a value in RUNTIME_STATE, logging warnings on unknown keys.

    Args:
        key: The state key to set
        value: The value to set
    """
    with RUNTIME_STATE_LOCK:
        if key not in RUNTIME_STATE:
            _state_logger.warning(
                "set_runtime_value: unknown key '%s' (setting to %r)",
                key, value
            )
        RUNTIME_STATE[key] = value


def increment_owner_queue(owner_id: int) -> int:
    """Increment queue count for an owner."""
    with OWNER_STATE_LOCK:
        OWNER_QUEUE_COUNTS[owner_id] = OWNER_QUEUE_COUNTS.get(owner_id, 0) + 1
        return OWNER_QUEUE_COUNTS[owner_id]


def decrement_owner_queue(owner_id: int) -> int:
    """Decrement queue count for an owner."""
    with OWNER_STATE_LOCK:
        current = OWNER_QUEUE_COUNTS.get(owner_id, 0)
        if current > 0:
            OWNER_QUEUE_COUNTS[owner_id] = current - 1
        return OWNER_QUEUE_COUNTS.get(owner_id, 0)


import contextlib
import logging

_state_logger = logging.getLogger("mind_clone.state")


def get_session_write_lock(owner_id: int) -> threading.Lock:
    """Get or create a per-owner session write lock."""
    with SESSION_WRITE_LOCK_GUARD:
        lock = SESSION_WRITE_LOCKS.get(owner_id)
        if lock is None:
            lock = threading.Lock()
            SESSION_WRITE_LOCKS[owner_id] = lock
        return lock


@contextlib.contextmanager
def session_write_lock(owner_id: int, reason: str = ""):
    """Context manager for per-owner transcript write-lock.

    Prevents concurrent writes to the same owner's conversation history.
    Matches the monolith's ``session_write_lock()`` contract.
    """
    lock = get_session_write_lock(owner_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        increment_runtime_state("session_write_lock_waits")
        _state_logger.debug(
            "session_write_lock WAIT owner=%s reason=%s", owner_id, reason
        )
        lock.acquire()  # blocking wait
    increment_runtime_state("session_write_locks_active")
    try:
        yield
    finally:
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE["session_write_locks_active"] = max(
                0, int(RUNTIME_STATE.get("session_write_locks_active", 1)) - 1
            )
        lock.release()


def get_owner_execution_lock(owner_id: int) -> threading.Lock:
    """Get or create a per-owner execution lock (serializes agent loop)."""
    with OWNER_EXECUTION_LOCK_GUARD:
        lock = OWNER_EXECUTION_LOCKS.get(owner_id)
        if lock is None:
            lock = threading.Lock()
            OWNER_EXECUTION_LOCKS[owner_id] = lock
        return lock


class MetricsCollector:
    """Collect and aggregate runtime metrics."""

    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def record(self, name: str, value: Any) -> None:
        """Record a metric value."""
        with self._lock:
            self._metrics[name] = value

    def increment(self, name: str, delta: int = 1) -> None:
        """Increment a counter metric."""
        with self._lock:
            self._metrics[name] = self._metrics.get(name, 0) + delta

    def get(self, name: str, default: Any = None) -> Any:
        """Get a metric value."""
        with self._lock:
            return self._metrics.get(name, default)

    def get_all(self) -> Dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            return dict(self._metrics)

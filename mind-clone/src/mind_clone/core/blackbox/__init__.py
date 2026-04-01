"""
Blackbox event logging and diagnostics package — backward-compatible re-exports.

Split from a single ``blackbox.py`` into three submodules:

- ``recorder.py``    — event logging, session capture, DB persistence, cache
- ``assertions.py``  — recovery planning, session analysis
- ``reporting.py``   — report generation, export, route adapters

All public names are re-exported here so existing imports work unchanged.
"""

from __future__ import annotations

# --- recorder.py ---
from .recorder import (
    BlackboxEvent,
    log_blackbox_event,
    get_blackbox_events,
    get_blackbox_event,
    prune_blackbox_events,
    replay_blackbox_session,
    get_blackbox_sessions,
    clear_blackbox,
    fetch_blackbox_events_after,
    # Event type constants
    EVENT_TYPE_SYSTEM,
    EVENT_TYPE_TASK,
    EVENT_TYPE_TOOL,
    EVENT_TYPE_ERROR,
    EVENT_TYPE_LLM,
    EVENT_TYPE_USER,
    EVENT_TYPE_STATE,
    EVENT_TYPE_DIAGNOSTIC,
)

# --- assertions.py ---
from .assertions import (
    build_recovery_plan,
)

# --- reporting.py ---
from .reporting import (
    export_blackbox_events,
    fetch_blackbox_report,
    fetch_blackbox_events,
    blackbox_event_stream_generator,
    build_blackbox_replay,
    list_blackbox_sessions,
    build_blackbox_session_report,
    build_blackbox_recovery_plan,
    build_blackbox_export_bundle,
)

__all__ = [
    # Event classes
    "BlackboxEvent",
    # Core functions
    "log_blackbox_event",
    "get_blackbox_events",
    "get_blackbox_event",
    "prune_blackbox_events",
    "export_blackbox_events",
    "replay_blackbox_session",
    "get_blackbox_sessions",
    "clear_blackbox",
    "fetch_blackbox_events_after",
    "fetch_blackbox_report",
    # Recovery
    "build_recovery_plan",
    # Route adapters
    "fetch_blackbox_events",
    "blackbox_event_stream_generator",
    "build_blackbox_replay",
    "list_blackbox_sessions",
    "build_blackbox_session_report",
    "build_blackbox_recovery_plan",
    "build_blackbox_export_bundle",
    # Constants
    "EVENT_TYPE_SYSTEM",
    "EVENT_TYPE_TASK",
    "EVENT_TYPE_TOOL",
    "EVENT_TYPE_ERROR",
    "EVENT_TYPE_LLM",
    "EVENT_TYPE_USER",
    "EVENT_TYPE_STATE",
    "EVENT_TYPE_DIAGNOSTIC",
]

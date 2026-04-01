"""
Test assertions, validation, and recovery planning.

Handles session analysis, error detection, and building recovery plans
from blackbox event data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from .recorder import (
    replay_blackbox_session,
    EVENT_TYPE_ERROR,
    EVENT_TYPE_TASK,
)
from ...utils import utc_now_iso

logger = logging.getLogger("mind_clone.core.blackbox.assertions")


def build_recovery_plan(session_id: str) -> Dict[str, Any]:
    """Build a recovery plan from a failed session.

    Analyzes session events to identify errors and failed tasks,
    then produces recommendations and a list of recoverable tasks.

    Args:
        session_id: The session ID to analyze

    Returns:
        Recovery plan dictionary
    """
    events = replay_blackbox_session(session_id)

    if not events:
        return {"ok": False, "error": "Session not found"}

    # Find errors and failures
    errors = [e for e in events if e.get("type") == EVENT_TYPE_ERROR]
    failed_tasks = [
        e for e in events
        if e.get("type") == EVENT_TYPE_TASK
        and e.get("data", {}).get("status") == "failed"
    ]

    # Build plan
    plan = {
        "ok": True,
        "session_id": session_id,
        "analysis": {
            "total_events": len(events),
            "error_count": len(errors),
            "failed_task_count": len(failed_tasks),
            "time_span_minutes": _calculate_time_span(events),
        },
        "recommendations": [],
        "recoverable_tasks": [],
    }

    # Add recommendations
    if errors:
        plan["recommendations"].append("Review error events for root cause")
    if failed_tasks:
        plan["recommendations"].append("Retry failed tasks after fixing issues")

    # Identify recoverable tasks
    for task_event in failed_tasks:
        task_data = task_event.get("data", {})
        plan["recoverable_tasks"].append({
            "task_id": task_data.get("task_id"),
            "title": task_data.get("title"),
            "error": task_data.get("error"),
        })

    # Update runtime state
    from ...core.state import increment_runtime_state, set_runtime_state_value
    increment_runtime_state("blackbox_recovery_plans_built")
    set_runtime_state_value("blackbox_last_recovery_plan_at", utc_now_iso())

    return plan


def _calculate_time_span(events: List[Dict]) -> Optional[float]:
    """Calculate time span in minutes for a list of events."""
    if len(events) < 2:
        return None

    try:
        timestamps = []
        for e in events:
            ts = e.get("timestamp")
            if ts:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                timestamps.append(dt)

        if len(timestamps) >= 2:
            return (max(timestamps) - min(timestamps)).total_seconds() / 60
    except Exception:
        pass

    return None

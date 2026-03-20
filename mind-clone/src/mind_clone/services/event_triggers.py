"""
Event-Driven Triggers — Huginn style autonomous reactivity.

Bob monitors signals and reacts proactively when conditions are met.
Instead of only running on schedules, Bob fires when something HAPPENS.

Trigger types:
- ERROR_SPIKE: tool error rate exceeds threshold → investigate + fix
- PATTERN_THRESHOLD: user interest exceeds count → auto-create monitor
- EXPERIMENT_STALE: no experiment in 48h → nudge to run one
- MEMORY_BLOAT: too many low-importance memories → trigger Ebbinghaus
- TOOL_DEGRADED: specific tool success rate drops → trigger optimisation

Based on Huginn (47k stars) — event-action rules engine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..database.session import SessionLocal
from ..database.models import (
    ToolPerformanceLog, ExperimentLog, EpisodicMemory,
    SelfImprovementNote, ScheduledJob,
)
from sqlalchemy import func as sqlfunc

logger = logging.getLogger("mind_clone.services.event_triggers")


def _check_error_spike(db, owner_id: int, threshold: float = 0.4) -> Optional[dict]:
    """Detect if tool error rate has spiked recently."""
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = (
        db.query(ToolPerformanceLog)
        .filter(
            ToolPerformanceLog.owner_id == owner_id,
            ToolPerformanceLog.created_at >= since,
        )
        .all()
    )
    if len(rows) < 5:
        return None
    failures = sum(1 for r in rows if r.success == 0)
    rate = failures / len(rows)
    if rate >= threshold:
        return {
            "trigger": "error_spike",
            "severity": "high",
            "message": f"Tool error rate spiked to {rate:.0%} in last hour ({failures}/{len(rows)} failures). Investigate and fix.",
            "action": "run_retro",
        }
    return None


def _check_experiment_stale(db, owner_id: int, max_hours: int = 48) -> Optional[dict]:
    """Check if no experiment has run recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
    last = (
        db.query(ExperimentLog)
        .filter(ExperimentLog.owner_id == owner_id)
        .order_by(ExperimentLog.id.desc())
        .first()
    )
    if not last or (last.created_at and last.created_at.replace(tzinfo=timezone.utc) < cutoff):
        return {
            "trigger": "experiment_stale",
            "severity": "low",
            "message": f"No self-improvement experiment in {max_hours}h. Consider running run_experiment.",
            "action": "run_experiment",
        }
    return None


def _check_memory_bloat(db, owner_id: int, threshold: int = 200) -> Optional[dict]:
    """Check if episodic memory has too many low-importance entries."""
    low_imp = (
        db.query(EpisodicMemory)
        .filter(
            EpisodicMemory.owner_id == owner_id,
            EpisodicMemory.importance < 0.3,
        )
        .count()
    )
    if low_imp > threshold:
        return {
            "trigger": "memory_bloat",
            "severity": "medium",
            "message": f"Memory bloat detected: {low_imp} low-importance episodes. Running Ebbinghaus decay.",
            "action": "memory_decay",
        }
    return None


def _check_tool_degraded(db, owner_id: int, threshold: float = 0.5) -> Optional[dict]:
    """Check if any specific tool has degraded recently."""
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    rows = (
        db.query(
            ToolPerformanceLog.tool_name,
            sqlfunc.avg(ToolPerformanceLog.success).label("avg_success"),
            sqlfunc.count(ToolPerformanceLog.id).label("calls"),
        )
        .filter(
            ToolPerformanceLog.owner_id == owner_id,
            ToolPerformanceLog.created_at >= since,
        )
        .group_by(ToolPerformanceLog.tool_name)
        .having(sqlfunc.count(ToolPerformanceLog.id) >= 3)
        .all()
    )
    degraded = [(r.tool_name, float(r.avg_success)) for r in rows if float(r.avg_success) < threshold]
    if degraded:
        worst = min(degraded, key=lambda x: x[1])
        return {
            "trigger": "tool_degraded",
            "severity": "medium",
            "message": f"Tool '{worst[0]}' degraded to {worst[1]:.0%} success rate. Consider optimise_prompts.",
            "action": "optimise_prompts",
        }
    return None


def scan_triggers(owner_id: int = 1) -> list[dict]:
    """Scan all triggers and return list of fired events."""
    db = SessionLocal()
    fired = []
    try:
        checks = [
            _check_error_spike(db, owner_id),
            _check_experiment_stale(db, owner_id),
            _check_memory_bloat(db, owner_id),
            _check_tool_degraded(db, owner_id),
        ]
        fired = [c for c in checks if c is not None]
        if fired:
            logger.info("EVENT_TRIGGERS_FIRED count=%d", len(fired))
    except Exception as e:
        logger.error("TRIGGER_SCAN_FAIL: %s", e)
    finally:
        db.close()
    return fired


def tool_scan_triggers(args: dict) -> dict:
    """Tool: Scan event triggers and return any that have fired (errors, staleness, bloat)."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        fired = scan_triggers(owner_id)
        return {
            "ok": True,
            "triggers_fired": len(fired),
            "events": fired,
            "message": f"{len(fired)} trigger(s) fired" if fired else "All clear, no triggers fired",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

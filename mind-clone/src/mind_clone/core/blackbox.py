"""
Blackbox event logging and diagnostics.

Provides persistent event storage in SQLite, event filtering and querying,
and export and replay functionality for session diagnostics.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from sqlalchemy.orm import Session

from ..database.models import ExecutionEvent
from ..database.session import SessionLocal
from ..config import settings, BLACKBOX_READ_MAX_LIMIT as _BLACKBOX_READ_MAX_LIMIT
from ..utils import utc_now_iso, truncate_text, generate_uuid

logger = logging.getLogger("mind_clone.core.blackbox")

# Event type constants
EVENT_TYPE_SYSTEM = "system"
EVENT_TYPE_TASK = "task"
EVENT_TYPE_TOOL = "tool"
EVENT_TYPE_ERROR = "error"
EVENT_TYPE_LLM = "llm"
EVENT_TYPE_USER = "user"
EVENT_TYPE_STATE = "state"
EVENT_TYPE_DIAGNOSTIC = "diagnostic"

# In-memory cache for recent events
_blackbox_cache: List[Dict[str, Any]] = []
_blackbox_cache_lock = threading.Lock()
_blackbox_cache_max_size = 1000

# Event counter for IDs
_event_counter = 0
_event_counter_lock = threading.Lock()

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


class BlackboxEvent:
    """Represents a blackbox event."""
    
    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any],
        owner_id: int = 0,
        session_id: Optional[str] = None,
        source_type: str = "runtime",
        source_ref: Optional[str] = None,
    ):
        global _event_counter
        
        with _event_counter_lock:
            _event_counter += 1
            self.event_id = _event_counter
        
        self.event_type = event_type
        self.data = data
        self.owner_id = owner_id
        self.session_id = session_id or generate_uuid()
        self.source_type = source_type
        self.source_ref = source_ref
        self.timestamp = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "id": self.event_id,
            "type": self.event_type,
            "data": self.data,
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_db_model(cls, event: ExecutionEvent) -> "BlackboxEvent":
        """Create from database model."""
        instance = cls.__new__(cls)
        instance.event_id = event.id
        instance.event_type = event.event_type
        instance.data = json.loads(event.payload_json or "{}")
        instance.owner_id = event.owner_id
        instance.session_id = event.session_id
        instance.source_type = event.source_type
        instance.source_ref = event.source_ref
        instance.timestamp = event.created_at
        return instance


def log_blackbox_event(
    event_type: str,
    data: Dict[str, Any],
    owner_id: int = 0,
    session_id: Optional[str] = None,
    source_type: str = "runtime",
    source_ref: Optional[str] = None,
    persist: bool = True,
) -> int:
    """
    Log an event to the blackbox.
    
    Args:
        event_type: Type of event (system, task, tool, error, etc.)
        data: Event data payload
        owner_id: Optional owner ID
        session_id: Optional session ID
        source_type: Source type (runtime, task, user, etc.)
        source_ref: Reference to source object
        persist: Whether to persist to database
        
    Returns:
        Event ID
    """
    if not settings.BLACKBOX_ENABLED:
        return -1
    
    try:
        # Truncate data if too large
        data_str = json.dumps(data)
        if len(data_str) > settings.blackbox_payload_max_chars:
            data = {"_truncated": True, "_original_size": len(data_str)}
        
        # Create event
        event = BlackboxEvent(
            event_type=event_type,
            data=data,
            owner_id=owner_id,
            session_id=session_id,
            source_type=source_type,
            source_ref=source_ref,
        )
        
        # Add to cache
        with _blackbox_cache_lock:
            _blackbox_cache.append(event.to_dict())
            # Trim cache if too large
            if len(_blackbox_cache) > _blackbox_cache_max_size:
                _blackbox_cache = _blackbox_cache[-_blackbox_cache_max_size:]
        
        # Persist to database
        if persist:
            _persist_event(event)
        
        # Update runtime state
        from ..core.state import increment_runtime_state
        increment_runtime_state("blackbox_events_total")
        
        return event.event_id
        
    except Exception as e:
        logger.error(f"Failed to log blackbox event: {e}")
        return -1


def _persist_event(event: BlackboxEvent) -> bool:
    """Persist event to database."""
    db = SessionLocal()
    try:
        db_event = ExecutionEvent(
            owner_id=event.owner_id,
            session_id=event.session_id,
            source_type=event.source_type,
            source_ref=event.source_ref,
            event_type=event.event_type,
            payload_json=json.dumps(event.data),
            created_at=event.timestamp,
        )
        db.add(db_event)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to persist event: {e}")
        return False
    finally:
        db.close()


def get_blackbox_events(
    event_type: Optional[str] = None,
    owner_id: Optional[int] = None,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    use_cache: bool = False,
) -> List[Dict[str, Any]]:
    """
    Get blackbox events with filtering.
    
    Args:
        event_type: Filter by event type
        owner_id: Filter by owner
        session_id: Filter by session
        source_type: Filter by source type
        start_time: Filter events after this time (ISO format)
        end_time: Filter events before this time (ISO format)
        limit: Maximum results (capped at BLACKBOX_READ_MAX_LIMIT)
        offset: Pagination offset
        use_cache: Use in-memory cache instead of database
        
    Returns:
        List of event dictionaries
    """
    if use_cache:
        return _get_events_from_cache(event_type, limit, offset)
    
    # Cap limit
    limit = min(limit, _BLACKBOX_READ_MAX_LIMIT)
    
    db = SessionLocal()
    try:
        query = db.query(ExecutionEvent)
        
        if event_type:
            query = query.filter(ExecutionEvent.event_type == event_type)
        if owner_id:
            query = query.filter(ExecutionEvent.owner_id == owner_id)
        if session_id:
            query = query.filter(ExecutionEvent.session_id == session_id)
        if source_type:
            query = query.filter(ExecutionEvent.source_type == source_type)
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                query = query.filter(ExecutionEvent.created_at >= start_dt)
            except ValueError:
                pass
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                query = query.filter(ExecutionEvent.created_at <= end_dt)
            except ValueError:
                pass
        
        events = query.order_by(ExecutionEvent.created_at.desc()).offset(offset).limit(limit).all()
        
        return [_db_event_to_dict(e) for e in events]
    finally:
        db.close()


def _get_events_from_cache(
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Get events from in-memory cache."""
    with _blackbox_cache_lock:
        events = list(_blackbox_cache)
    
    if event_type:
        events = [e for e in events if e.get("type") == event_type]
    
    # Sort by timestamp descending
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    
    return events[offset:offset + limit]


def get_blackbox_event(event_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a specific blackbox event by ID.
    
    Args:
        event_id: The event ID
        
    Returns:
        Event dictionary or None
    """
    # Check cache first
    with _blackbox_cache_lock:
        for event in _blackbox_cache:
            if event.get("id") == event_id:
                return event
    
    # Query database
    db = SessionLocal()
    try:
        event = db.query(ExecutionEvent).filter(ExecutionEvent.id == event_id).first()
        return _db_event_to_dict(event) if event else None
    finally:
        db.close()


def prune_blackbox_events(older_than_hours: int = 24) -> int:
    """
    Prune old blackbox events from database.
    
    Args:
        older_than_hours: Delete events older than this
        
    Returns:
        Number of events pruned
    """
    if not settings.BLACKBOX_PRUNE_ENABLED:
        return 0
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    
    db = SessionLocal()
    try:
        events = db.query(ExecutionEvent).filter(ExecutionEvent.created_at < cutoff).all()
        count = len(events)
        
        for event in events:
            db.delete(event)
        
        db.commit()
        
        if count > 0:
            logger.info(f"Pruned {count} old blackbox events")
            
            # Update runtime state
            from ..core.state import increment_runtime_state, set_runtime_state_value
            increment_runtime_state("blackbox_events_pruned", count)
            set_runtime_state_value("blackbox_last_prune_at", utc_now_iso())
            set_runtime_state_value("blackbox_last_prune_reason", f"age > {older_than_hours}h")
            set_runtime_state_value("blackbox_last_prune_count", count)
        
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune blackbox events: {e}")
        return 0
    finally:
        db.close()


def export_blackbox_events(
    format: str = "json",
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> Union[str, Path]:
    """
    Export blackbox events to file or string.
    
    Args:
        format: Export format (json, csv)
        event_type: Optional event type filter
        start_time: Optional start time filter
        end_time: Optional end time filter
        output_path: Optional output file path
        
    Returns:
        Export string or file path
    """
    events = get_blackbox_events(
        event_type=event_type,
        start_time=start_time,
        end_time=end_time,
        limit=_BLACKBOX_READ_MAX_LIMIT,
    )
    
    if format.lower() == "json":
        output = json.dumps(events, indent=2, default=str)
    elif format.lower() == "csv":
        output = _events_to_csv(events)
    else:
        raise ValueError(f"Unsupported format: {format}")
    
    if output_path:
        output_path = Path(output_path)
        output_path.write_text(output, encoding="utf-8")
        
        # Update runtime state
        from ..core.state import increment_runtime_state, set_runtime_state_value
        increment_runtime_state("blackbox_exports_built")
        set_runtime_state_value("blackbox_last_export_at", utc_now_iso())
        
        return output_path
    
    return output


def _events_to_csv(events: List[Dict]) -> str:
    """Convert events to CSV format."""
    import csv
    import io
    
    if not events:
        return "id,type,timestamp,data\n"
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "type", "timestamp", "session_id", "owner_id", "source_type", "data"])
    
    for event in events:
        writer.writerow([
            event.get("id", ""),
            event.get("type", ""),
            event.get("timestamp", ""),
            event.get("session_id", ""),
            event.get("owner_id", ""),
            event.get("source_type", ""),
            json.dumps(event.get("data", {})),
        ])
    
    return output.getvalue()


def replay_blackbox_session(session_id: str) -> List[Dict[str, Any]]:
    """
    Replay events from a session in chronological order.
    
    Args:
        session_id: The session ID to replay
        
    Returns:
        List of events in chronological order
    """
    db = SessionLocal()
    try:
        events = db.query(ExecutionEvent).filter(
            ExecutionEvent.session_id == session_id,
        ).order_by(ExecutionEvent.created_at.asc()).all()
        
        return [_db_event_to_dict(e) for e in events]
    finally:
        db.close()


def get_blackbox_sessions(
    owner_id: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get list of session IDs in blackbox.
    
    Args:
        owner_id: Optional owner filter
        limit: Maximum results
        
    Returns:
        List of session information
    """
    db = SessionLocal()
    try:
        query = db.query(
            ExecutionEvent.session_id,
            ExecutionEvent.created_at,
            ExecutionEvent.owner_id,
        ).distinct(ExecutionEvent.session_id)
        
        if owner_id:
            query = query.filter(ExecutionEvent.owner_id == owner_id)
        
        results = query.order_by(ExecutionEvent.created_at.desc()).limit(limit).all()
        
        sessions = []
        for session_id, created_at, owner in results:
            # Count events in session
            event_count = db.query(ExecutionEvent).filter(
                ExecutionEvent.session_id == session_id,
            ).count()
            
            sessions.append({
                "session_id": session_id,
                "created_at": created_at.isoformat() if created_at else None,
                "owner_id": owner,
                "event_count": event_count,
            })
        
        return sessions
    finally:
        db.close()


def clear_blackbox(confirm: bool = False) -> Dict[str, Any]:
    """
    Clear all blackbox events (use with caution).
    
    Args:
        confirm: Must be True to actually clear
        
    Returns:
        Result dictionary
    """
    if not confirm:
        return {"ok": False, "error": "confirm=True required to clear blackbox"}
    
    db = SessionLocal()
    try:
        count = db.query(ExecutionEvent).count()
        db.query(ExecutionEvent).delete()
        db.commit()
        
        # Clear cache
        with _blackbox_cache_lock:
            _blackbox_cache.clear()
        
        logger.warning(f"Blackbox cleared ({count} events deleted)")
        return {"ok": True, "deleted_count": count}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to clear blackbox: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def fetch_blackbox_events_after(
    event_id: int,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Fetch events after a specific event ID.
    
    Args:
        event_id: Starting event ID
        limit: Maximum results
        
    Returns:
        List of events
    """
    db = SessionLocal()
    try:
        events = db.query(ExecutionEvent).filter(
            ExecutionEvent.id > event_id,
        ).order_by(ExecutionEvent.id.asc()).limit(limit).all()
        
        return [_db_event_to_dict(e) for e in events]
    finally:
        db.close()


def fetch_blackbox_report(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a comprehensive blackbox report.
    
    Args:
        start_time: Optional start time filter
        end_time: Optional end time filter
        
    Returns:
        Report dictionary
    """
    db = SessionLocal()
    try:
        query = db.query(ExecutionEvent)
        
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                query = query.filter(ExecutionEvent.created_at >= start_dt)
            except ValueError:
                pass
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                query = query.filter(ExecutionEvent.created_at <= end_dt)
            except ValueError:
                pass
        
        events = query.all()
        
        # Aggregate statistics
        event_types = {}
        sources = {}
        sessions = set()
        owners = set()
        
        for event in events:
            event_types[event.event_type] = event_types.get(event.event_type, 0) + 1
            sources[event.source_type] = sources.get(event.source_type, 0) + 1
            sessions.add(event.session_id)
            owners.add(event.owner_id)
        
        return {
            "total_events": len(events),
            "event_types": event_types,
            "source_types": sources,
            "unique_sessions": len(sessions),
            "unique_owners": len(owners),
            "time_range": {
                "start": start_time,
                "end": end_time,
            },
        }
    finally:
        db.close()


def build_recovery_plan(session_id: str) -> Dict[str, Any]:
    """
    Build a recovery plan from a failed session.
    
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
    from ..core.state import increment_runtime_state, set_runtime_state_value
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


def _db_event_to_dict(event: ExecutionEvent) -> Dict[str, Any]:
    """Convert database ExecutionEvent to dictionary."""
    return {
        "id": event.id,
        "type": event.event_type,
        "data": json.loads(event.payload_json or "{}"),
        "owner_id": event.owner_id,
        "session_id": event.session_id,
        "source_type": event.source_type,
        "source_ref": event.source_ref,
        "timestamp": event.created_at.isoformat() if event.created_at else None,
    }


# ---------------------------------------------------------------------------
# Aliases expected by routes.py
# ---------------------------------------------------------------------------

def fetch_blackbox_events(
    owner_id: int,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Adapter around get_blackbox_events matching routes.py signature."""
    return get_blackbox_events(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )


async def blackbox_event_stream_generator(
    owner_id: int,
    session_id: Optional[str],
    source_type: Optional[str],
    after_event_id: int,
    poll_seconds: float,
    batch_size: int,
):
    """Server-Sent Events generator for blackbox event streaming."""
    import asyncio as _asyncio

    last_id = after_event_id
    while True:
        events = get_blackbox_events(
            owner_id=owner_id,
            session_id=session_id,
            source_type=source_type,
            limit=batch_size,
        )
        new_events = [e for e in events if e.get("id", 0) > last_id]
        for ev in new_events:
            last_id = max(last_id, ev.get("id", 0))
            payload = json.dumps(ev, ensure_ascii=False)
            yield f"data: {payload}\n\n".encode("utf-8")
        await _asyncio.sleep(poll_seconds)


def build_blackbox_replay(
    owner_id: int,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 600,
) -> Dict[str, Any]:
    """Build a replay bundle for a session."""
    if session_id:
        events = replay_blackbox_session(session_id)
    else:
        events = get_blackbox_events(
            owner_id=owner_id, source_type=source_type, limit=limit,
        )
    return {"ok": True, "owner_id": owner_id, "events": events, "count": len(events)}


def list_blackbox_sessions(
    owner_id: int, limit: int = 20, source_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Alias for get_blackbox_sessions matching routes.py signature."""
    return get_blackbox_sessions(owner_id=owner_id, limit=limit)


def build_blackbox_session_report(
    owner_id: int,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 300,
    include_timeline: bool = False,
) -> Dict[str, Any]:
    """Build a session report (adapter around fetch_blackbox_report)."""
    report = fetch_blackbox_report()
    report["ok"] = True
    report["owner_id"] = owner_id
    if include_timeline and session_id:
        report["timeline"] = replay_blackbox_session(session_id)
    return report


def build_blackbox_recovery_plan(
    owner_id: int,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 300,
) -> Dict[str, Any]:
    """Alias for build_recovery_plan matching routes.py signature."""
    if not session_id:
        return {"ok": False, "error": "session_id is required for recovery plan"}
    return build_recovery_plan(session_id)


def build_blackbox_export_bundle(
    owner_id: int,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 600,
    include_timeline: bool = True,
    include_raw_events: bool = False,
) -> Dict[str, Any]:
    """Build an export bundle for blackbox events."""
    events = get_blackbox_events(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    bundle: Dict[str, Any] = {
        "ok": True,
        "owner_id": owner_id,
        "count": len(events),
        "events_summary": [
            {"id": e.get("id"), "type": e.get("type"), "timestamp": e.get("timestamp")}
            for e in events
        ],
    }
    if include_raw_events:
        bundle["events"] = events
    if include_timeline and session_id:
        bundle["timeline"] = replay_blackbox_session(session_id)
    return bundle

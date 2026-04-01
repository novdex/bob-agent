"""
Report generation, formatting, and export for blackbox events.

Handles exporting events to files, generating reports, and providing
route-compatible adapters for the API layer.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from ...config import BLACKBOX_READ_MAX_LIMIT as _BLACKBOX_READ_MAX_LIMIT
from ...utils import utc_now_iso

from .recorder import (
    get_blackbox_events,
    get_blackbox_sessions,
    replay_blackbox_session,
)
from .assertions import build_recovery_plan

logger = logging.getLogger("mind_clone.core.blackbox.reporting")


def export_blackbox_events(
    format: str = "json",
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> Union[str, Path]:
    """Export blackbox events to file or string.

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
        from ...core.state import increment_runtime_state, set_runtime_state_value
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


def fetch_blackbox_report(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a comprehensive blackbox report.

    Args:
        start_time: Optional start time filter
        end_time: Optional end time filter

    Returns:
        Report dictionary
    """
    from ...database.session import SessionLocal
    from ...database.models import ExecutionEvent

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

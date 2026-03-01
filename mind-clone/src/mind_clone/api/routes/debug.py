"""Debug and blackbox diagnostic routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ._shared import (
    BLACKBOX_ENABLED,
    EVENT_STREAM_BATCH_SIZE,
    EVENT_STREAM_POLL_SECONDS,
    blackbox_event_stream_generator,
    build_blackbox_export_bundle,
    build_blackbox_recovery_plan,
    build_blackbox_replay,
    build_blackbox_session_report,
    fetch_blackbox_events,
    list_blackbox_sessions,
    prune_blackbox_events,
    require_ops_auth,
    utc_now_iso,
)

router = APIRouter()


@router.get("/debug/blackbox")
def debug_blackbox_events(
    owner_id: int,
    limit: int = 100,
    session_id: str | None = None,
    source_type: str | None = None,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    events = fetch_blackbox_events(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    return {
        "ok": True,
        "enabled": True,
        "owner_id": owner_id,
        "session_id": session_id,
        "source_type": source_type,
        "count": len(events),
        "events": events,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/stream")
async def debug_blackbox_stream(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    after_event_id: int = 0,
    poll_seconds: float = EVENT_STREAM_POLL_SECONDS,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        raise HTTPException(status_code=400, detail="owner_id must be > 0")
    if not BLACKBOX_ENABLED:
        raise HTTPException(status_code=400, detail="blackbox disabled")

    stream = blackbox_event_stream_generator(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        after_event_id=after_event_id,
        poll_seconds=poll_seconds,
        batch_size=EVENT_STREAM_BATCH_SIZE,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/debug/blackbox/replay")
def debug_blackbox_replay(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 600,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}
    replay = build_blackbox_replay(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    if not replay.get("ok"):
        return replay
    return {**replay, "enabled": True, "timestamp": utc_now_iso()}


@router.get("/debug/blackbox/sessions")
def debug_blackbox_sessions(
    owner_id: int,
    limit: int = 20,
    source_type: str | None = None,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    sessions = list_blackbox_sessions(
        owner_id=owner_id,
        limit=limit,
        source_type=source_type,
    )
    return {
        "ok": True,
        "enabled": True,
        "owner_id": owner_id,
        "source_type": source_type,
        "count": len(sessions),
        "sessions": sessions,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/session_report")
def debug_blackbox_session_report(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 300,
    include_timeline: bool = False,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    report = build_blackbox_session_report(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
        include_timeline=bool(include_timeline),
    )
    if not report.get("ok"):
        return report

    return {
        **report,
        "enabled": True,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/recovery_plan")
def debug_blackbox_recovery_plan(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 300,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    plan = build_blackbox_recovery_plan(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    if not plan.get("ok"):
        return plan

    return {
        **plan,
        "enabled": True,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/export_bundle")
def debug_blackbox_export_bundle(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 600,
    include_timeline: bool = True,
    include_raw_events: bool = False,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    bundle = build_blackbox_export_bundle(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
        include_timeline=bool(include_timeline),
        include_raw_events=bool(include_raw_events),
    )
    if not bundle.get("ok"):
        return bundle
    bundle["timestamp"] = utc_now_iso()
    return bundle


@router.post("/debug/blackbox/prune")
def debug_blackbox_prune(
    owner_id: int | None = None,
    reason: str = "manual_api",
    _ops=Depends(require_ops_auth),
):
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}
    if owner_id is not None and int(owner_id) <= 0:
        return {"ok": False, "error": "owner_id must be > 0 when provided"}

    return prune_blackbox_events(owner_id=owner_id, reason=reason)

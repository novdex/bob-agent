"""Health and heartbeat routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ._shared import (
    HEARTBEAT_WAKE_EVENT,
    KIMI_MODEL,
    RUNTIME_STATE,
    protocol_validate_payload,
    require_ops_auth,
    runtime_metrics,
    runtime_uptime_seconds,
    utc_now_iso,
)

router = APIRouter()


@router.get("/heartbeat")
def heartbeat():
    payload = {
        "status": "alive",
        "agent": "Mind Clone",
        "model": KIMI_MODEL,
        **runtime_metrics(),
        "timestamp": utc_now_iso(),
    }
    protocol_validate_payload("runtime.metrics.response", payload, direction="response")
    return payload


@router.get("/status/runtime")
def status_runtime():
    payload = runtime_metrics()
    payload["uptime_seconds"] = runtime_uptime_seconds()
    payload["timestamp"] = utc_now_iso()
    protocol_validate_payload("runtime.metrics.response", payload, direction="response")
    return payload


@router.post("/heartbeat/wake")
def heartbeat_wake(_ops=Depends(require_ops_auth)):
    if HEARTBEAT_WAKE_EVENT is not None:
        HEARTBEAT_WAKE_EVENT.set()
    return {
        "ok": True,
        "wakeup_requested": True,
        "next_tick_at": RUNTIME_STATE.get("heartbeat_next_tick_at"),
        "timestamp": utc_now_iso(),
    }

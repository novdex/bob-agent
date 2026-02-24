"""Desktop session management tool functions."""
from __future__ import annotations

import time

from ._shared import (
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_REPLAY_MAX_STEPS,
    DESKTOP_REQUIRE_ACTIVE_SESSION,
    RUNTIME_STATE,
    logger,
    truncate_text,
    DESKTOP_TOOL_LOCK,
    _desktop_import_modules,
    _desktop_mark_action,
    _desktop_get_active_session,
    _desktop_start_session,
    _desktop_stop_session,
    _desktop_session_status,
    _desktop_record_action,
    _desktop_load_session_actions,
    _desktop_screen_size,
    _desktop_mouse_position,
    _desktop_clip_point,
)


def tool_desktop_session_start(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    label = args.get("label")

    if not DESKTOP_CONTROL_ENABLED:
        return {"ok": False, "error": "Desktop control is disabled by configuration."}
    current = _desktop_get_active_session(owner_id)
    if current:
        return {
            "ok": True,
            "already_active": True,
            "session_id": str(current.get("session_id") or ""),
            "log_path": str(current.get("log_path") or ""),
            "actions_count": int(current.get("actions_count", 0)),
        }
    return _desktop_start_session(owner_id, label=label)


def tool_desktop_session_status(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    return _desktop_session_status(owner_id)


def tool_desktop_session_stop(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    reason = args.get("reason", "manual")
    return _desktop_stop_session(owner_id, reason=reason)


def tool_desktop_session_replay(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    session_id = args.get("session_id")
    start_index = args.get("start_index", 0)
    max_steps = args.get("max_steps", 120)
    dry_run = args.get("dry_run", False)
    speed = args.get("speed", 1.0)

    sid = str(session_id or "").strip()
    if not sid:
        active = _desktop_get_active_session(owner_id)
        if active:
            sid = str(active.get("session_id") or "")
    if not sid:
        return {"ok": False, "error": "session_id is required (or start a session first)."}

    ok, err, actions, log_path = _desktop_load_session_actions(
        owner_id, sid, start_index=start_index, max_steps=max_steps
    )
    if not ok:
        return {"ok": False, "error": err, "log_path": log_path}

    if not actions:
        return {
            "ok": True,
            "session_id": sid,
            "log_path": log_path,
            "executed": 0,
            "dry_run": bool(dry_run),
            "results": [],
        }

    replay_speed = max(0.1, min(5.0, float(speed)))
    results: list[dict] = []

    from ..registry import TOOL_DISPATCH

    for idx, row in enumerate(actions, 1):
        name = str(row.get("tool_name") or "").strip().lower()
        tool_args = dict(row.get("args") or {})
        if dry_run:
            results.append({"step": idx, "tool_name": name, "ok": True, "dry_run": True})
            continue

        if name not in TOOL_DISPATCH:
            results.append({"step": idx, "tool_name": name, "ok": False, "error": "Tool not found"})
            continue

        try:
            tool_args["_owner_id"] = owner_id
            step_result = TOOL_DISPATCH[name](tool_args)
            results.append(
                {
                    "step": idx,
                    "tool_name": name,
                    "ok": bool(step_result.get("ok", False))
                    if isinstance(step_result, dict)
                    else False,
                    "error": None
                    if not isinstance(step_result, dict)
                    else step_result.get("error"),
                }
            )
        except Exception as e:
            results.append({"step": idx, "tool_name": name, "ok": False, "error": str(e)})

        if replay_speed != 1.0:
            time.sleep(max(0.0, 0.12 / replay_speed))

    RUNTIME_STATE["desktop_sessions_replayed"] = (
        int(RUNTIME_STATE.get("desktop_sessions_replayed", 0)) + 1
    )
    return {
        "ok": True,
        "session_id": sid,
        "log_path": log_path,
        "executed": len(results),
        "dry_run": bool(dry_run),
        "results": results,
    }



"""
Desktop automation tools (mouse, keyboard, screen, windows, sessions).

Requires: pyautogui, pygetwindow, pyperclip (optional), pywinauto (optional)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from ..config import (
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_FAILSAFE_ENABLED,
    DESKTOP_ACTION_PAUSE_SECONDS,
    DESKTOP_DEFAULT_MOVE_DURATION,
    DESKTOP_DEFAULT_TYPE_INTERVAL,
    DESKTOP_SCREENSHOT_DIR,
    DESKTOP_SESSION_DIR,
    DESKTOP_REQUIRE_ACTIVE_SESSION,
    DESKTOP_REPLAY_MAX_STEPS,
    DESKTOP_IMAGE_MATCH_THRESHOLD,
    DESKTOP_UITREE_DEFAULT_LIMIT,
    APP_DIR,
)
from ..core.state import RUNTIME_STATE
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.tools.desktop")

# Thread locks
DESKTOP_TOOL_LOCK = threading.Lock()
DESKTOP_SESSION_LOCK = threading.Lock()
DESKTOP_ACTIVE_SESSIONS: dict[int, dict] = {}

# Tool names that require active session
DESKTOP_MUTATING_TOOL_NAMES = {
    "desktop_click",
    "desktop_drag_mouse",
    "desktop_type_text",
    "desktop_key_press",
    "desktop_hotkey",
    "desktop_scroll",
    "desktop_launch_app",
    "desktop_set_clipboard",
}

DESKTOP_SESSION_CONTROL_TOOL_NAMES = {
    "desktop_session_start",
    "desktop_session_stop",
    "desktop_session_status",
    "desktop_session_replay",
}


def _desktop_import_modules() -> tuple[object | None, object | None, object | None, str | None]:
    if not DESKTOP_CONTROL_ENABLED:
        return None, None, None, "Desktop control is disabled by configuration."
    try:
        import pyautogui
    except Exception as e:
        return None, None, None, f"pyautogui is not available: {e}"
    try:
        import pygetwindow as gw
    except Exception:
        gw = None
    try:
        import pyperclip
    except Exception:
        pyperclip = None

    try:
        pyautogui.FAILSAFE = bool(DESKTOP_FAILSAFE_ENABLED)
        pyautogui.PAUSE = float(DESKTOP_ACTION_PAUSE_SECONDS)
    except Exception:
        pass
    return pyautogui, gw, pyperclip, None


def _desktop_mark_action(action: str, error: str | None = None):
    RUNTIME_STATE["desktop_actions_total"] = int(RUNTIME_STATE.get("desktop_actions_total", 0)) + 1
    RUNTIME_STATE["desktop_last_action"] = str(action or "")
    RUNTIME_STATE["desktop_last_error"] = truncate_text(str(error or ""), 240) if error else None


def _desktop_screen_size(pyautogui_mod) -> tuple[int, int]:
    width, height = pyautogui_mod.size()
    return int(width), int(height)


def _desktop_mouse_position(pyautogui_mod) -> tuple[int, int]:
    x, y = pyautogui_mod.position()
    return int(x), int(y)


def _desktop_clip_point(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    safe_x = max(0, min(int(width) - 1, int(x)))
    safe_y = max(0, min(int(height) - 1, int(y)))
    return safe_x, safe_y


def _desktop_workspace_root(owner_id: int | None, workspace_root: str | None = None) -> Path:
    candidate = str(workspace_root or "").strip()
    if candidate:
        try:
            return Path(candidate).expanduser().resolve(strict=False)
        except Exception:
            pass
    if owner_id:
        try:
            from ..database.session import owner_workspace_root

            return owner_workspace_root(int(owner_id))
        except Exception:
            pass
    return DESKTOP_SCREENSHOT_DIR


def _desktop_resolve_screenshot_path(
    owner_id: int | None, file_path: str | None, workspace_root: str | None = None
) -> Path:
    root = _desktop_workspace_root(owner_id, workspace_root=workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = str(file_path or "").strip()
    if not raw_path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return (root / f"desktop_{stamp}_{uuid.uuid4().hex[:6]}.png").resolve(strict=False)
    target = Path(os.path.expandvars(raw_path)).expanduser()
    if not target.suffix:
        target = target.with_suffix(".png")
    if not target.is_absolute():
        target = (root / target).resolve(strict=False)
    else:
        target = target.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _desktop_resolve_asset_path(
    owner_id: int | None, asset_path: str, workspace_root: str | None = None
) -> Path:
    raw = str(asset_path or "").strip()
    if not raw:
        raise ValueError("image_path is required.")
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        root = _desktop_workspace_root(owner_id, workspace_root=workspace_root)
        candidate = (root / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    if not candidate.exists():
        raise FileNotFoundError(f"Asset file not found: {candidate}")
    return candidate


def _desktop_normalize_region(
    region: dict | None, screen_w: int, screen_h: int
) -> tuple[int, int, int, int] | None:
    if not isinstance(region, dict) or not region:
        return None
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    x, y = _desktop_clip_point(x, y, screen_w, screen_h)
    width = max(1, min(width, screen_w - x))
    height = max(1, min(height, screen_h - y))
    return (x, y, width, height)


def _desktop_box_to_dict(box) -> dict | None:
    if box is None:
        return None
    left = top = width = height = None
    try:
        left = int(getattr(box, "left"))
        top = int(getattr(box, "top"))
        width = int(getattr(box, "width"))
        height = int(getattr(box, "height"))
    except Exception:
        try:
            left = int(box[0])
            top = int(box[1])
            width = int(box[2])
            height = int(box[3])
        except Exception:
            return None
    center_x = int(left + (width / 2))
    center_y = int(top + (height / 2))
    return {
        "left": int(left),
        "top": int(top),
        "width": int(width),
        "height": int(height),
        "center_x": int(center_x),
        "center_y": int(center_y),
    }


def _desktop_owner_key(owner_id: int | None) -> int:
    try:
        return int(owner_id or 0)
    except Exception:
        return 0


def _desktop_sessions_root(owner_id: int | None) -> Path:
    if owner_id:
        try:
            from ..database.session import owner_workspace_root

            base = owner_workspace_root(int(owner_id))
            return (base / ".desktop_sessions").resolve(strict=False)
        except Exception:
            pass
    return DESKTOP_SESSION_DIR


def _desktop_session_log_path(owner_id: int | None, session_id: str) -> Path:
    root = _desktop_sessions_root(owner_id)
    root.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(session_id or ""))[:80] or uuid.uuid4().hex[:12]
    return (root / f"{safe_id}.jsonl").resolve(strict=False)


def _desktop_get_active_session(owner_id: int | None) -> dict | None:
    key = _desktop_owner_key(owner_id)
    with DESKTOP_SESSION_LOCK:
        row = DESKTOP_ACTIVE_SESSIONS.get(key)
        if not row:
            return None
        return dict(row)


def _desktop_set_active_session(owner_id: int | None, state: dict | None):
    key = _desktop_owner_key(owner_id)
    with DESKTOP_SESSION_LOCK:
        if state is None:
            DESKTOP_ACTIVE_SESSIONS.pop(key, None)
        else:
            DESKTOP_ACTIVE_SESSIONS[key] = dict(state)
    active = _desktop_get_active_session(owner_id)
    RUNTIME_STATE["desktop_session_active"] = bool(active)
    RUNTIME_STATE["desktop_session_id"] = str(active.get("session_id")) if active else None
    RUNTIME_STATE["desktop_last_session_path"] = (
        str(active.get("log_path")) if active else RUNTIME_STATE.get("desktop_last_session_path")
    )


def _desktop_start_session(owner_id: int | None, label: str | None = None) -> dict:
    owner_key = _desktop_owner_key(owner_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    session_id = f"ds_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    log_path = _desktop_session_log_path(owner_id, session_id)
    state = {
        "owner_id": owner_key,
        "session_id": session_id,
        "label": truncate_text(str(label or ""), 120),
        "started_at": now_iso,
        "updated_at": now_iso,
        "actions_count": 0,
        "log_path": str(log_path),
        "active": True,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "event": "session_started",
        "session_id": session_id,
        "owner_id": owner_key,
        "label": state["label"],
        "timestamp": now_iso,
    }
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
    _desktop_set_active_session(owner_id, state)
    RUNTIME_STATE["desktop_sessions_started"] = (
        int(RUNTIME_STATE.get("desktop_sessions_started", 0)) + 1
    )
    return {
        "ok": True,
        "session_id": session_id,
        "log_path": str(log_path),
        "started_at": now_iso,
        "label": state["label"],
    }


def _desktop_stop_session(owner_id: int | None, reason: str = "manual") -> dict:
    current = _desktop_get_active_session(owner_id)
    if not current:
        return {"ok": False, "error": "No active desktop session."}
    now_iso = datetime.now(timezone.utc).isoformat()
    log_path = Path(str(current.get("log_path") or "")).expanduser().resolve(strict=False)
    trailer = {
        "event": "session_stopped",
        "session_id": current.get("session_id"),
        "owner_id": _desktop_owner_key(owner_id),
        "timestamp": now_iso,
        "reason": truncate_text(str(reason or "manual"), 120),
        "actions_count": int(current.get("actions_count", 0)),
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trailer, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _desktop_set_active_session(owner_id, None)
    RUNTIME_STATE["desktop_sessions_completed"] = (
        int(RUNTIME_STATE.get("desktop_sessions_completed", 0)) + 1
    )
    RUNTIME_STATE["desktop_last_session_path"] = str(log_path)
    return {
        "ok": True,
        "session_id": str(current.get("session_id") or ""),
        "log_path": str(log_path),
        "actions_count": int(current.get("actions_count", 0)),
        "stopped_at": now_iso,
        "reason": trailer["reason"],
    }


def _desktop_session_status(owner_id: int | None) -> dict:
    current = _desktop_get_active_session(owner_id)
    if not current:
        return {"ok": True, "active": False, "session": None}
    return {
        "ok": True,
        "active": True,
        "session": {
            "session_id": str(current.get("session_id") or ""),
            "label": str(current.get("label") or ""),
            "started_at": current.get("started_at"),
            "updated_at": current.get("updated_at"),
            "actions_count": int(current.get("actions_count", 0)),
            "log_path": str(current.get("log_path") or ""),
        },
    }


def _desktop_action_args_for_log(args: dict | None) -> dict:
    data = {}
    for key, value in dict(args or {}).items():
        k = str(key or "")
        if k.startswith("_"):
            continue
        data[k] = value
    return _blackbox_sanitize(data)


def _blackbox_sanitize(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 500:
            result[k] = v[:500] + "...[TRUNCATED]"
        else:
            result[k] = v
    return result


def _desktop_record_action(
    owner_id: int | None, tool_name: str, args: dict | None, result: dict | None
):
    if str(tool_name or "") in DESKTOP_SESSION_CONTROL_TOOL_NAMES:
        return
    current = _desktop_get_active_session(owner_id)
    if not current:
        return
    log_path = Path(str(current.get("log_path") or "")).expanduser().resolve(strict=False)
    now_iso = datetime.now(timezone.utc).isoformat()
    event = {
        "event": "action",
        "timestamp": now_iso,
        "session_id": str(current.get("session_id") or ""),
        "tool_name": str(tool_name or ""),
        "args": _desktop_action_args_for_log(args),
        "result": _blackbox_sanitize(result or {}),
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        current["actions_count"] = int(current.get("actions_count", 0)) + 1
        current["updated_at"] = now_iso
        _desktop_set_active_session(owner_id, current)
    except Exception:
        pass


def _desktop_load_session_actions(
    owner_id: int | None, session_id: str, start_index: int = 0, max_steps: int = 200
) -> tuple[bool, str, list[dict], str]:
    log_path = _desktop_session_log_path(owner_id, session_id)
    if not log_path.exists():
        return False, f"Session log not found: {log_path}", [], str(log_path)
    items: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                row = str(line or "").strip()
                if not row:
                    continue
                try:
                    parsed = json.loads(row)
                except Exception:
                    continue
                if str(parsed.get("event") or "") != "action":
                    continue
                items.append(parsed)
    except Exception as e:
        return False, f"Failed reading session log: {e}", [], str(log_path)

    safe_start = max(0, int(start_index))
    safe_max = max(1, min(DESKTOP_REPLAY_MAX_STEPS, int(max_steps)))
    sliced = items[safe_start : safe_start + safe_max]
    return True, "", sliced, str(log_path)


def _desktop_locate_image(
    pyautogui_mod,
    image_path: Path,
    confidence: float | None,
    grayscale: bool,
    region_tuple: tuple[int, int, int, int] | None,
) -> tuple[object | None, str | None, bool]:
    kwargs: dict = {"grayscale": bool(grayscale)}
    if region_tuple is not None:
        kwargs["region"] = region_tuple
    conf_value = None
    if confidence is not None:
        conf_value = max(0.5, min(0.99, float(confidence)))
        kwargs["confidence"] = conf_value
    try:
        box = pyautogui_mod.locateOnScreen(str(image_path), **kwargs)
        return box, None, False
    except TypeError as e:
        text = str(e)
        if "confidence" in text.lower() and conf_value is not None:
            kwargs.pop("confidence", None)
            try:
                box = pyautogui_mod.locateOnScreen(str(image_path), **kwargs)
                return box, None, True
            except Exception as inner:
                return None, str(inner), True
        return None, text, False
    except Exception as e:
        return None, str(e), False


# ============================================================================
# TOOL FUNCTIONS
# ============================================================================


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

    from .registry import TOOL_DISPATCH

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


def tool_desktop_screen_state(args: dict) -> dict:
    action = "desktop_screen_state"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    try:
        with DESKTOP_TOOL_LOCK:
            width, height = _desktop_screen_size(pyautogui_mod)
            mouse_x, mouse_y = _desktop_mouse_position(pyautogui_mod)
        _desktop_mark_action(action)
        return {
            "ok": True,
            "screen": {"width": width, "height": height},
            "mouse": {"x": mouse_x, "y": mouse_y},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_screenshot(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    file_path = args.get("file_path")
    region = args.get("region")
    workspace_root = args.get("workspace_root") or args.get("_workspace_root")

    action = "desktop_screenshot"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    try:
        region_tuple = None
        with DESKTOP_TOOL_LOCK:
            screen_w, screen_h = _desktop_screen_size(pyautogui_mod)
            if isinstance(region, dict) and region:
                x = int(region.get("x", 0))
                y = int(region.get("y", 0))
                width = max(1, int(region.get("width", 1)))
                height = max(1, int(region.get("height", 1)))
                x, y = _desktop_clip_point(x, y, screen_w, screen_h)
                width = max(1, min(width, screen_w - x))
                height = max(1, min(height, screen_h - y))
                region_tuple = (x, y, width, height)
        target_path = _desktop_resolve_screenshot_path(
            owner_id, file_path, workspace_root=workspace_root
        )

        shot_w = 0
        shot_h = 0
        pyautogui_error = None
        try:
            shot = pyautogui_mod.screenshot(region=region_tuple)
            shot.save(str(target_path))
            shot_w, shot_h = shot.size
        except Exception as inner_exc:
            pyautogui_error = str(inner_exc)
            try:
                import mss
                import mss.tools

                with mss.mss() as sct:
                    monitor = (
                        {
                            "left": int(region_tuple[0]),
                            "top": int(region_tuple[1]),
                            "width": int(region_tuple[2]),
                            "height": int(region_tuple[3]),
                        }
                        if region_tuple
                        else dict(sct.monitors[1])
                    )
                    frame = sct.grab(monitor)
                    mss.tools.to_png(frame.rgb, frame.size, output=str(target_path))
                    shot_w, shot_h = int(frame.size.width), int(frame.size.height)
            except Exception as mss_exc:
                raise RuntimeError(
                    f"screenshot failed via pyautogui ({pyautogui_error}); mss fallback failed ({mss_exc})"
                )

        _desktop_mark_action(action)
        screenshot_b64 = ""
        try:
            with open(str(target_path), "rb") as f:
                screenshot_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass

        return {
            "ok": True,
            "path": str(target_path),
            "width": int(shot_w),
            "height": int(shot_h),
            "region": {
                "x": int(region_tuple[0]),
                "y": int(region_tuple[1]),
                "width": int(region_tuple[2]),
                "height": int(region_tuple[3]),
            }
            if region_tuple
            else None,
            "_screenshot_base64": screenshot_b64,
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_list_windows(args: dict) -> dict:
    limit = args.get("limit", 30)
    action = "desktop_list_windows"
    _, gw_mod, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    if gw_mod is None:
        msg = "pygetwindow is not available; install PyGetWindow for window introspection."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        rows = []
        for win in gw_mod.getAllWindows():
            title = str(getattr(win, "title", "") or "").strip()
            if not title:
                continue
            rows.append(
                {
                    "title": title,
                    "left": int(getattr(win, "left", 0) or 0),
                    "top": int(getattr(win, "top", 0) or 0),
                    "width": int(getattr(win, "width", 0) or 0),
                    "height": int(getattr(win, "height", 0) or 0),
                    "is_active": bool(getattr(win, "isActive", False)),
                }
            )
        rows = rows[: max(1, min(200, int(limit)))]
        _desktop_mark_action(action)
        return {"ok": True, "windows": rows, "count": len(rows)}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_uia_tree(args: dict) -> dict:
    title = args.get("title")
    exact = args.get("exact", False)
    limit = args.get("limit", DESKTOP_UITREE_DEFAULT_LIMIT)

    action = "desktop_uia_tree"
    _, gw_mod, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    safe_limit = max(5, min(500, int(limit)))
    needle = str(title or "").strip()
    try:
        from pywinauto import Desktop as UIADesktop

        desktop = UIADesktop(backend="uia")
        top_windows = list(desktop.windows())
        target = None
        if needle:
            if exact:
                target = next(
                    (w for w in top_windows if str(w.window_text() or "").strip() == needle), None
                )
            else:
                low = needle.lower()
                target = next(
                    (w for w in top_windows if low in str(w.window_text() or "").lower()), None
                )
        if target is None and top_windows:
            target = top_windows[0]
        if target is None:
            _desktop_mark_action(action, "No UIA windows available.")
            return {"ok": False, "error": "No UIA windows available."}

        nodes: list[dict] = []
        queue_items: list[tuple[object, int]] = [(target, 0)]
        while queue_items and len(nodes) < safe_limit:
            ctrl, depth = queue_items.pop(0)
            try:
                elem = getattr(ctrl, "element_info", None)
                rect = getattr(elem, "rectangle", None)
                node = {
                    "depth": int(depth),
                    "name": truncate_text(str(ctrl.window_text() or ""), 240),
                    "control_type": str(getattr(elem, "control_type", "") or ""),
                    "automation_id": str(getattr(elem, "automation_id", "") or ""),
                    "class_name": str(getattr(elem, "class_name", "") or ""),
                    "rectangle": {
                        "left": int(getattr(rect, "left", 0) or 0),
                        "top": int(getattr(rect, "top", 0) or 0),
                        "right": int(getattr(rect, "right", 0) or 0),
                        "bottom": int(getattr(rect, "bottom", 0) or 0),
                    },
                }
                nodes.append(node)
            except Exception:
                continue
            if depth >= 6:
                continue
            try:
                for child in list(ctrl.children()):
                    if len(nodes) + len(queue_items) >= safe_limit * 2:
                        break
                    queue_items.append((child, depth + 1))
            except Exception:
                continue

        _desktop_mark_action(action)
        return {
            "ok": True,
            "backend": "pywinauto",
            "target_title": truncate_text(str(target.window_text() or ""), 240),
            "count": len(nodes),
            "nodes": nodes,
        }
    except Exception:
        if gw_mod is None:
            msg = "pywinauto is not available; install pywinauto for UI tree inspection."
            _desktop_mark_action(action, msg)
            return {"ok": False, "error": msg}
        try:
            windows = []
            for win in gw_mod.getAllWindows():
                title_text = str(getattr(win, "title", "") or "").strip()
                if not title_text:
                    continue
                if needle:
                    if exact and title_text != needle:
                        continue
                    if (not exact) and (needle.lower() not in title_text.lower()):
                        continue
                windows.append(
                    {
                        "depth": 0,
                        "name": truncate_text(title_text, 240),
                        "control_type": "Window",
                        "automation_id": "",
                        "class_name": "",
                        "rectangle": {
                            "left": int(getattr(win, "left", 0) or 0),
                            "top": int(getattr(win, "top", 0) or 0),
                            "right": int(
                                (getattr(win, "left", 0) or 0) + (getattr(win, "width", 0) or 0)
                            ),
                            "bottom": int(
                                (getattr(win, "top", 0) or 0) + (getattr(win, "height", 0) or 0)
                            ),
                        },
                    }
                )
                if len(windows) >= safe_limit:
                    break
            _desktop_mark_action(action)
            return {
                "ok": True,
                "backend": "pygetwindow_fallback",
                "warning": "pywinauto not available; returning top-level windows only.",
                "count": len(windows),
                "nodes": windows,
            }
        except Exception as e:
            _desktop_mark_action(action, str(e))
            return {"ok": False, "error": str(e)}


def tool_desktop_locate_on_screen(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    image_path = args.get("image_path", "")
    confidence = args.get("confidence", DESKTOP_IMAGE_MATCH_THRESHOLD)
    grayscale = args.get("grayscale", True)
    region = args.get("region")
    workspace_root = args.get("workspace_root") or args.get("_workspace_root")

    action = "desktop_locate_on_screen"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    try:
        template_path = _desktop_resolve_asset_path(
            owner_id, image_path, workspace_root=workspace_root
        )
        with DESKTOP_TOOL_LOCK:
            screen_w, screen_h = _desktop_screen_size(pyautogui_mod)
            region_tuple = _desktop_normalize_region(region, screen_w, screen_h)
            box, locate_err, confidence_fallback = _desktop_locate_image(
                pyautogui_mod,
                template_path,
                confidence=confidence,
                grayscale=bool(grayscale),
                region_tuple=region_tuple,
            )
        if locate_err:
            _desktop_mark_action(action, locate_err)
            return {"ok": False, "error": locate_err}
        box_payload = _desktop_box_to_dict(box)
        _desktop_mark_action(action)
        if box_payload is None:
            return {
                "ok": True,
                "found": False,
                "image_path": str(template_path),
                "confidence_fallback": bool(confidence_fallback),
            }
        return {
            "ok": True,
            "found": True,
            "image_path": str(template_path),
            "match": box_payload,
            "confidence_fallback": bool(confidence_fallback),
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_click_image(args: dict) -> dict:
    owner_id = args.get("owner_id") or args.get("_owner_id")
    image_path = args.get("image_path", "")
    confidence = args.get("confidence", DESKTOP_IMAGE_MATCH_THRESHOLD)
    grayscale = args.get("grayscale", True)
    region = args.get("region")
    button = args.get("button", "left")
    clicks = args.get("clicks", 1)
    interval = args.get("interval", 0.0)
    move_duration = args.get("move_duration")
    offset_x = args.get("offset_x", 0)
    offset_y = args.get("offset_y", 0)
    workspace_root = args.get("workspace_root") or args.get("_workspace_root")

    action = "desktop_click_image"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    button_name = str(button or "left").strip().lower()
    if button_name not in {"left", "right", "middle"}:
        button_name = "left"
    try:
        template_path = _desktop_resolve_asset_path(
            owner_id, image_path, workspace_root=workspace_root
        )
        with DESKTOP_TOOL_LOCK:
            screen_w, screen_h = _desktop_screen_size(pyautogui_mod)
            region_tuple = _desktop_normalize_region(region, screen_w, screen_h)
            box, locate_err, confidence_fallback = _desktop_locate_image(
                pyautogui_mod,
                template_path,
                confidence=confidence,
                grayscale=bool(grayscale),
                region_tuple=region_tuple,
            )
            if locate_err:
                raise RuntimeError(locate_err)
            match = _desktop_box_to_dict(box)
            if match is None:
                _desktop_mark_action(action, "Image not found on screen.")
                return {
                    "ok": False,
                    "found": False,
                    "error": "Image not found on screen.",
                    "image_path": str(template_path),
                    "confidence_fallback": bool(confidence_fallback),
                }
            target_x, target_y = _desktop_clip_point(
                int(match["center_x"]) + int(offset_x),
                int(match["center_y"]) + int(offset_y),
                screen_w,
                screen_h,
            )
            move_secs = float(
                DESKTOP_DEFAULT_MOVE_DURATION if move_duration is None else move_duration
            )
            move_secs = max(0.0, min(5.0, move_secs))
            pyautogui_mod.moveTo(target_x, target_y, duration=move_secs)
            pyautogui_mod.click(
                x=target_x,
                y=target_y,
                clicks=max(1, min(10, int(clicks))),
                interval=max(0.0, min(1.0, float(interval))),
                button=button_name,
            )
        _desktop_mark_action(action)
        return {
            "ok": True,
            "found": True,
            "image_path": str(template_path),
            "match": match,
            "clicked_x": int(target_x),
            "clicked_y": int(target_y),
            "button": button_name,
            "clicks": max(1, min(10, int(clicks))),
            "confidence_fallback": bool(confidence_fallback),
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_focus_window(args: dict) -> dict:
    title = args.get("title", "")
    exact = args.get("exact", False)

    action = "desktop_focus_window"
    _, gw_mod, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    if gw_mod is None:
        msg = "pygetwindow is not available; install PyGetWindow for window focus control."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}

    needle = str(title or "").strip()
    if not needle:
        msg = "title is required."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        if exact:
            candidates = [
                w
                for w in gw_mod.getAllWindows()
                if str(getattr(w, "title", "") or "").strip() == needle
            ]
        else:
            low = needle.lower()
            candidates = [
                w
                for w in gw_mod.getAllWindows()
                if low in str(getattr(w, "title", "") or "").lower()
            ]
        if not candidates:
            msg = f"No window matched '{needle}'."
            _desktop_mark_action(action, msg)
            return {"ok": False, "error": msg}
        win = candidates[0]
        try:
            if bool(getattr(win, "isMinimized", False)):
                win.restore()
        except Exception:
            pass
        win.activate()
        _desktop_mark_action(action)
        return {
            "ok": True,
            "matched_title": str(getattr(win, "title", "") or ""),
            "matches": len(candidates),
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_move_mouse(args: dict) -> dict:
    x = args.get("x", 0)
    y = args.get("y", 0)
    duration = args.get("duration")

    action = "desktop_move_mouse"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    try:
        with DESKTOP_TOOL_LOCK:
            width, height = _desktop_screen_size(pyautogui_mod)
            target_x, target_y = _desktop_clip_point(int(x), int(y), width, height)
            move_duration = float(DESKTOP_DEFAULT_MOVE_DURATION if duration is None else duration)
            move_duration = max(0.0, min(5.0, move_duration))
            pyautogui_mod.moveTo(target_x, target_y, duration=move_duration)
        _desktop_mark_action(action)
        return {"ok": True, "x": target_x, "y": target_y}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_click(args: dict) -> dict:
    x = args.get("x", 0)
    y = args.get("y", 0)
    button = args.get("button", "left")
    clicks = args.get("clicks", 1)
    interval = args.get("interval", 0.0)
    move_duration = args.get("move_duration")

    action = "desktop_click"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    button_name = str(button or "left").strip().lower()
    if button_name not in {"left", "right", "middle"}:
        button_name = "left"
    try:
        with DESKTOP_TOOL_LOCK:
            width, height = _desktop_screen_size(pyautogui_mod)
            target_x, target_y = _desktop_clip_point(int(x), int(y), width, height)
            move_secs = float(
                DESKTOP_DEFAULT_MOVE_DURATION if move_duration is None else move_duration
            )
            move_secs = max(0.0, min(5.0, move_secs))
            pyautogui_mod.moveTo(target_x, target_y, duration=move_secs)
            pyautogui_mod.click(
                x=target_x,
                y=target_y,
                clicks=max(1, min(10, int(clicks))),
                interval=max(0.0, min(1.0, float(interval))),
                button=button_name,
            )
        _desktop_mark_action(action)
        return {
            "ok": True,
            "x": target_x,
            "y": target_y,
            "button": button_name,
            "clicks": max(1, min(10, int(clicks))),
        }
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_drag_mouse(args: dict) -> dict:
    x = args.get("x", 0)
    y = args.get("y", 0)
    button = args.get("button", "left")
    duration = args.get("duration", 0.25)

    action = "desktop_drag_mouse"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    button_name = str(button or "left").strip().lower()
    if button_name not in {"left", "right", "middle"}:
        button_name = "left"
    try:
        with DESKTOP_TOOL_LOCK:
            width, height = _desktop_screen_size(pyautogui_mod)
            target_x, target_y = _desktop_clip_point(int(x), int(y), width, height)
            drag_secs = max(0.0, min(8.0, float(duration)))
            pyautogui_mod.dragTo(target_x, target_y, duration=drag_secs, button=button_name)
        _desktop_mark_action(action)
        return {"ok": True, "x": target_x, "y": target_y, "button": button_name}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_scroll(args: dict) -> dict:
    clicks = args.get("clicks", 0)
    x = args.get("x")
    y = args.get("y")

    action = "desktop_scroll"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    try:
        with DESKTOP_TOOL_LOCK:
            width, height = _desktop_screen_size(pyautogui_mod)
            if x is not None and y is not None:
                target_x, target_y = _desktop_clip_point(int(x), int(y), width, height)
                pyautogui_mod.moveTo(target_x, target_y, duration=0.0)
            pyautogui_mod.scroll(int(clicks))
        _desktop_mark_action(action)
        return {"ok": True, "clicks": int(clicks)}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_type_text(args: dict) -> dict:
    text = args.get("text", "")
    interval = args.get("interval")
    press_enter = args.get("press_enter", False)

    action = "desktop_type_text"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    blob = str(text or "")
    if not blob:
        msg = "text is required."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    if len(blob) > 5000:
        blob = blob[:5000]
    try:
        with DESKTOP_TOOL_LOCK:
            key_interval = float(DESKTOP_DEFAULT_TYPE_INTERVAL if interval is None else interval)
            key_interval = max(0.0, min(0.5, key_interval))
            pyautogui_mod.write(blob, interval=key_interval)
            if bool(press_enter):
                pyautogui_mod.press("enter")
        _desktop_mark_action(action)
        return {"ok": True, "typed_chars": len(blob), "press_enter": bool(press_enter)}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_key_press(args: dict) -> dict:
    key = args.get("key", "")
    presses = args.get("presses", 1)
    interval = args.get("interval", 0.05)

    action = "desktop_key_press"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    key_name = str(key or "").strip().lower()
    if not key_name:
        msg = "key is required."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        with DESKTOP_TOOL_LOCK:
            pyautogui_mod.press(
                key_name,
                presses=max(1, min(50, int(presses))),
                interval=max(0.0, min(1.0, float(interval))),
            )
        _desktop_mark_action(action)
        return {"ok": True, "key": key_name, "presses": max(1, min(50, int(presses)))}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_hotkey(args: dict) -> dict:
    keys = args.get("keys", [])

    action = "desktop_hotkey"
    pyautogui_mod, _, _, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    combo = [str(k or "").strip().lower() for k in (keys or []) if str(k or "").strip()]
    if not combo:
        msg = "keys list is required."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    combo = combo[:5]
    try:
        with DESKTOP_TOOL_LOCK:
            pyautogui_mod.hotkey(*combo)
        _desktop_mark_action(action)
        return {"ok": True, "keys": combo}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_launch_app(args: dict) -> dict:
    command = args.get("command", "")

    action = "desktop_launch_app"
    if not DESKTOP_CONTROL_ENABLED:
        msg = "Desktop control is disabled by configuration."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    cmd = str(command or "").strip()
    if not cmd:
        msg = "command is required."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        proc = subprocess.Popen(cmd, shell=True)
        _desktop_mark_action(action)
        return {"ok": True, "command": cmd, "pid": int(proc.pid)}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e), "command": cmd}


def tool_desktop_wait(args: dict) -> dict:
    seconds = args.get("seconds", 1.0)

    action = "desktop_wait"
    try:
        wait_secs = max(0.0, min(30.0, float(seconds)))
    except Exception:
        wait_secs = 1.0
    try:
        time.sleep(wait_secs)
        _desktop_mark_action(action)
        return {"ok": True, "slept_seconds": wait_secs}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_get_clipboard(args: dict) -> dict:
    action = "desktop_get_clipboard"
    _, _, pyperclip_mod, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    if pyperclip_mod is None:
        msg = "pyperclip is not available; install pyperclip for clipboard operations."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        content = str(pyperclip_mod.paste() or "")
        _desktop_mark_action(action)
        return {"ok": True, "content": content}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}


def tool_desktop_set_clipboard(args: dict) -> dict:
    text = args.get("text", "")

    action = "desktop_set_clipboard"
    _, _, pyperclip_mod, err = _desktop_import_modules()
    if err:
        _desktop_mark_action(action, err)
        return {"ok": False, "error": err}
    if pyperclip_mod is None:
        msg = "pyperclip is not available; install pyperclip for clipboard operations."
        _desktop_mark_action(action, msg)
        return {"ok": False, "error": msg}
    try:
        blob = str(text or "")
        pyperclip_mod.copy(blob)
        _desktop_mark_action(action)
        return {"ok": True, "chars": len(blob)}
    except Exception as e:
        _desktop_mark_action(action, str(e))
        return {"ok": False, "error": str(e)}

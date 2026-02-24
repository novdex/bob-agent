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

from ...config import (
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
from ...core.state import RUNTIME_STATE
from ...utils import truncate_text

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
            from ...database.session import owner_workspace_root

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
            from ...database.session import owner_workspace_root

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


"""Desktop mouse, keyboard, clipboard, and app launch tools."""
from __future__ import annotations

import subprocess
import time

from ._shared import (
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_REQUIRE_ACTIVE_SESSION,
    DESKTOP_DEFAULT_MOVE_DURATION,
    DESKTOP_DEFAULT_TYPE_INTERVAL,
    RUNTIME_STATE,
    logger,
    truncate_text,
    DESKTOP_TOOL_LOCK,
    DESKTOP_MUTATING_TOOL_NAMES,
    _desktop_import_modules,
    _desktop_mark_action,
    _desktop_screen_size,
    _desktop_mouse_position,
    _desktop_clip_point,
    _desktop_get_active_session,
    _desktop_record_action,
)


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

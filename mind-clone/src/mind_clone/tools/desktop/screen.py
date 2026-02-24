"""Desktop screen, window, and image tools."""
from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone

from ._shared import (
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_REQUIRE_ACTIVE_SESSION,
    DESKTOP_IMAGE_MATCH_THRESHOLD,
    DESKTOP_UITREE_DEFAULT_LIMIT,
    DESKTOP_DEFAULT_MOVE_DURATION,
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
    _desktop_resolve_screenshot_path,
    _desktop_resolve_asset_path,
    _desktop_normalize_region,
    _desktop_box_to_dict,
    _desktop_get_active_session,
    _desktop_record_action,
    _desktop_locate_image,
)


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



"""Desktop automation tools (mouse, keyboard, screen, windows, sessions)."""

from .sessions import (
    tool_desktop_session_start,
    tool_desktop_session_status,
    tool_desktop_session_stop,
    tool_desktop_session_replay,
)
from .screen import (
    tool_desktop_screen_state,
    tool_desktop_screenshot,
    tool_desktop_list_windows,
    tool_desktop_uia_tree,
    tool_desktop_locate_on_screen,
    tool_desktop_click_image,
)
from .actions import (
    tool_desktop_focus_window,
    tool_desktop_move_mouse,
    tool_desktop_click,
    tool_desktop_drag_mouse,
    tool_desktop_scroll,
    tool_desktop_type_text,
    tool_desktop_key_press,
    tool_desktop_hotkey,
    tool_desktop_launch_app,
    tool_desktop_wait,
    tool_desktop_get_clipboard,
    tool_desktop_set_clipboard,
)

__all__ = [
    # Sessions
    "tool_desktop_session_start",
    "tool_desktop_session_status",
    "tool_desktop_session_stop",
    "tool_desktop_session_replay",
    # Screen / windows / image
    "tool_desktop_screen_state",
    "tool_desktop_screenshot",
    "tool_desktop_list_windows",
    "tool_desktop_uia_tree",
    "tool_desktop_locate_on_screen",
    "tool_desktop_click_image",
    # Actions (mouse, keyboard, clipboard, app)
    "tool_desktop_focus_window",
    "tool_desktop_move_mouse",
    "tool_desktop_click",
    "tool_desktop_drag_mouse",
    "tool_desktop_scroll",
    "tool_desktop_type_text",
    "tool_desktop_key_press",
    "tool_desktop_hotkey",
    "tool_desktop_launch_app",
    "tool_desktop_wait",
    "tool_desktop_get_clipboard",
    "tool_desktop_set_clipboard",
]

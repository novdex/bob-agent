"""
Tool implementations.
"""

from .basic import (
    tool_read_file,
    tool_write_file,
    tool_list_directory,
    tool_run_command,
    tool_execute_python,
    tool_search_web,
    tool_read_webpage,
    tool_deep_research,
    tool_send_email,
    tool_save_research_note,
)
from .browser import (
    tool_browser_open,
    tool_browser_get_text,
    tool_browser_click,
    tool_browser_type,
    tool_browser_screenshot,
    tool_browser_execute_js,
    tool_browser_close,
)
from .desktop import (
    tool_desktop_session_start,
    tool_desktop_session_status,
    tool_desktop_session_stop,
    tool_desktop_session_replay,
    tool_desktop_screen_state,
    tool_desktop_screenshot,
    tool_desktop_list_windows,
    tool_desktop_uia_tree,
    tool_desktop_locate_on_screen,
    tool_desktop_click_image,
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
from .memory import (
    tool_research_memory_search,
    tool_semantic_memory_search,
    tool_read_pdf_url,
)
from .scheduler import (
    tool_schedule_job,
    tool_list_scheduled_jobs,
    tool_disable_scheduled_job,
)
from .nodes import (
    tool_list_execution_nodes,
    tool_run_command_node,
)
from .sessions import (
    tool_sessions_spawn,
    tool_sessions_send,
    tool_sessions_list,
    tool_sessions_history,
    tool_sessions_stop,
)
from .custom import (
    tool_list_plugin_tools,
    tool_create_tool,
    tool_list_custom_tools,
    tool_disable_custom_tool,
    tool_llm_structured_task,
)
from .registry import execute_tool, get_available_tools, get_tool_definitions
from .schemas import get_tool_schemas, get_tool_schema_by_name

__all__ = [
    # Basic tools
    "tool_read_file",
    "tool_write_file",
    "tool_list_directory",
    "tool_run_command",
    "tool_execute_python",
    "tool_search_web",
    "tool_read_webpage",
    "tool_deep_research",
    "tool_send_email",
    "tool_save_research_note",
    # Browser tools
    "tool_browser_open",
    "tool_browser_get_text",
    "tool_browser_click",
    "tool_browser_type",
    "tool_browser_screenshot",
    "tool_browser_execute_js",
    "tool_browser_close",
    # Desktop tools
    "tool_desktop_session_start",
    "tool_desktop_session_status",
    "tool_desktop_session_stop",
    "tool_desktop_session_replay",
    "tool_desktop_screen_state",
    "tool_desktop_screenshot",
    "tool_desktop_list_windows",
    "tool_desktop_uia_tree",
    "tool_desktop_locate_on_screen",
    "tool_desktop_click_image",
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
    # Memory tools
    "tool_research_memory_search",
    "tool_semantic_memory_search",
    "tool_read_pdf_url",
    # Scheduler tools
    "tool_schedule_job",
    "tool_list_scheduled_jobs",
    "tool_disable_scheduled_job",
    # Node tools
    "tool_list_execution_nodes",
    "tool_run_command_node",
    # Session tools
    "tool_sessions_spawn",
    "tool_sessions_send",
    "tool_sessions_list",
    "tool_sessions_history",
    "tool_sessions_stop",
    # Custom tools
    "tool_list_plugin_tools",
    "tool_create_tool",
    "tool_list_custom_tools",
    "tool_disable_custom_tool",
    "tool_llm_structured_task",
    # Registry
    "execute_tool",
    "get_available_tools",
    "get_tool_definitions",
    "get_tool_schemas",
    "get_tool_schema_by_name",
]

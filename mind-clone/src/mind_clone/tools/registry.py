"""
Tool registry and dispatch system.

Includes both static (built-in) tools and dynamic (custom) tools created
by the LLM at runtime via ``create_tool``.
"""

from __future__ import annotations

import builtins
import json
import logging
import re
from typing import Dict, Callable, Any, List, Optional

from ..config import settings
from . import schemas
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
from .codebase import (
    tool_codebase_read,
    tool_codebase_search,
    tool_codebase_structure,
    tool_codebase_edit,
    tool_codebase_write,
    tool_codebase_run_tests,
    tool_codebase_git_status,
)
from .github import (
    tool_git_status,
    tool_git_commit,
    tool_git_branch,
    tool_git_diff,
    tool_git_log,
    tool_git_push,
    tool_git_pull,
)

logger = logging.getLogger("mind_clone.tools")

# ---------------------------------------------------------------------------
# Static tool dispatch registry (built-in tools)
# ---------------------------------------------------------------------------
TOOL_DISPATCH: Dict[str, Callable[[dict], dict]] = {
    # File operations
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_directory": tool_list_directory,
    # Code execution
    "run_command": tool_run_command,
    "execute_python": tool_execute_python,
    # Web tools
    "search_web": tool_search_web,
    "read_webpage": tool_read_webpage,
    "deep_research": tool_deep_research,
    # Communication
    "send_email": tool_send_email,
    "save_research_note": tool_save_research_note,
    # Browser tools
    "browser_open": tool_browser_open,
    "browser_get_text": tool_browser_get_text,
    "browser_click": tool_browser_click,
    "browser_type": tool_browser_type,
    "browser_screenshot": tool_browser_screenshot,
    "browser_execute_js": tool_browser_execute_js,
    "browser_close": tool_browser_close,
    # Desktop tools
    "desktop_session_start": tool_desktop_session_start,
    "desktop_session_status": tool_desktop_session_status,
    "desktop_session_stop": tool_desktop_session_stop,
    "desktop_session_replay": tool_desktop_session_replay,
    "desktop_screen_state": tool_desktop_screen_state,
    "desktop_screenshot": tool_desktop_screenshot,
    "desktop_list_windows": tool_desktop_list_windows,
    "desktop_uia_tree": tool_desktop_uia_tree,
    "desktop_locate_on_screen": tool_desktop_locate_on_screen,
    "desktop_click_image": tool_desktop_click_image,
    "desktop_focus_window": tool_desktop_focus_window,
    "desktop_move_mouse": tool_desktop_move_mouse,
    "desktop_click": tool_desktop_click,
    "desktop_drag_mouse": tool_desktop_drag_mouse,
    "desktop_scroll": tool_desktop_scroll,
    "desktop_type_text": tool_desktop_type_text,
    "desktop_key_press": tool_desktop_key_press,
    "desktop_hotkey": tool_desktop_hotkey,
    "desktop_launch_app": tool_desktop_launch_app,
    "desktop_wait": tool_desktop_wait,
    "desktop_get_clipboard": tool_desktop_get_clipboard,
    "desktop_set_clipboard": tool_desktop_set_clipboard,
    # Memory tools
    "research_memory_search": tool_research_memory_search,
    "semantic_memory_search": tool_semantic_memory_search,
    "read_pdf_url": tool_read_pdf_url,
    # Scheduler tools
    "schedule_job": tool_schedule_job,
    "list_scheduled_jobs": tool_list_scheduled_jobs,
    "disable_scheduled_job": tool_disable_scheduled_job,
    # Node tools
    "list_execution_nodes": tool_list_execution_nodes,
    "run_command_node": tool_run_command_node,
    # Session tools
    "sessions_spawn": tool_sessions_spawn,
    "sessions_send": tool_sessions_send,
    "sessions_list": tool_sessions_list,
    "sessions_history": tool_sessions_history,
    "sessions_stop": tool_sessions_stop,
    # Custom/Plugin tools
    "list_plugin_tools": tool_list_plugin_tools,
    "create_tool": tool_create_tool,
    "list_custom_tools": tool_list_custom_tools,
    "disable_custom_tool": tool_disable_custom_tool,
    "llm_structured_task": tool_llm_structured_task,
    # Codebase self-modification tools
    "codebase_read": tool_codebase_read,
    "codebase_search": tool_codebase_search,
    "codebase_structure": tool_codebase_structure,
    "codebase_edit": tool_codebase_edit,
    "codebase_write": tool_codebase_write,
    "codebase_run_tests": tool_codebase_run_tests,
    "codebase_git_status": tool_codebase_git_status,
    # Git tools
    "git_status": tool_git_status,
    "git_commit": tool_git_commit,
    "git_branch": tool_git_branch,
    "git_diff": tool_git_diff,
    "git_log": tool_git_log,
    "git_push": tool_git_push,
    "git_pull": tool_git_pull,
}

# ---------------------------------------------------------------------------
# Custom tool runtime registry (loaded from DB + created at runtime)
# ---------------------------------------------------------------------------
CUSTOM_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Tool categories — every tool must belong to at least one category
# ---------------------------------------------------------------------------
TOOL_CATEGORIES: Dict[str, set] = {
    "web": {
        "search_web", "read_webpage", "deep_research", "read_pdf_url",
    },
    "file": {
        "read_file", "write_file", "list_directory",
    },
    "code": {
        "run_command", "execute_python",
    },
    "codebase": {
        "codebase_read", "codebase_search", "codebase_structure",
        "codebase_edit", "codebase_write", "codebase_run_tests",
        "codebase_git_status",
        "git_status", "git_commit", "git_branch", "git_diff",
        "git_log", "git_push", "git_pull",
    },
    "browser": {
        "browser_open", "browser_get_text", "browser_click",
        "browser_type", "browser_screenshot", "browser_execute_js",
        "browser_close",
    },
    "desktop": {
        "desktop_session_start", "desktop_session_status",
        "desktop_session_stop", "desktop_session_replay",
        "desktop_screen_state", "desktop_screenshot",
        "desktop_list_windows", "desktop_uia_tree",
        "desktop_locate_on_screen", "desktop_click_image",
        "desktop_focus_window", "desktop_move_mouse",
        "desktop_click", "desktop_drag_mouse", "desktop_scroll",
        "desktop_type_text", "desktop_key_press", "desktop_hotkey",
        "desktop_launch_app", "desktop_wait",
        "desktop_get_clipboard", "desktop_set_clipboard",
    },
    "communication": {
        "send_email", "save_research_note",
    },
    "memory": {
        "research_memory_search", "semantic_memory_search",
    },
    "scheduler": {
        "schedule_job", "list_scheduled_jobs", "disable_scheduled_job",
    },
    "nodes": {
        "list_execution_nodes", "run_command_node",
    },
    "sessions": {
        "sessions_spawn", "sessions_send", "sessions_list",
        "sessions_history", "sessions_stop",
    },
    "custom": {
        "list_plugin_tools", "create_tool", "list_custom_tools",
        "disable_custom_tool", "llm_structured_task",
    },
}

# Intent keywords that map user messages to tool categories
_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "web": ["search", "web", "google", "internet", "url", "http", "website", "browse", "lookup"],
    "file": ["file", "read", "write", "save", "load", "directory", "folder", "path"],
    "code": ["execute", "python", "script", "run", "command", "code", "shell", "terminal"],
    "codebase": ["codebase", "source code", "modify code", "self-modify", "your own code", "git"],
    "browser": ["browser", "chrome", "firefox", "webpage", "html", "dom"],
    "desktop": ["desktop", "screen", "click", "mouse", "keyboard", "window", "screenshot"],
    "communication": ["email", "send", "message", "notify"],
    "memory": ["memory", "remember", "recall", "lesson", "research", "knowledge"],
    "scheduler": ["schedule", "cron", "recurring", "timer", "periodic", "every day", "every hour"],
    "nodes": ["node", "remote", "execution"],
    "sessions": ["session", "spawn", "terminal"],
    "custom": ["create tool", "custom tool", "build tool", "make tool", "new tool"],
}

# Base categories always included for safety (file, code, memory)
_BASE_CATEGORIES = {"file", "code", "memory"}


def classify_tool_intent(message: str) -> set[str]:
    """Classify user message into tool categories based on keyword matching.

    Returns set of category names. If no keywords match, returns all categories.
    Always includes base categories (file, code, memory).
    """
    if not message or not message.strip():
        return set(TOOL_CATEGORIES.keys())

    text = message.lower()
    matched: set[str] = set()

    for category, keywords in _INTENT_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.add(category)

    if not matched:
        return set(TOOL_CATEGORIES.keys())

    # Always include base categories for safety
    matched |= _BASE_CATEGORIES
    return matched


def _select_tools_for_intent(
    tool_defs: List[dict], intent_categories: set[str]
) -> List[dict]:
    """Filter tool definitions to those in the matched intent categories.

    Custom tools (category "custom") are always included regardless of intent.
    """
    allowed_names: set[str] = set()
    for cat in intent_categories:
        allowed_names |= TOOL_CATEGORIES.get(cat, set())
    # Always include custom tools
    allowed_names |= TOOL_CATEGORIES.get("custom", set())

    return [
        td for td in tool_defs
        if (td.get("function") or {}).get("name", "") in allowed_names
    ]

# Restricted builtins whitelist for safe-mode executors
_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "dir",
    "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "getattr", "hasattr", "hash", "hex", "id", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "print", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple",
    "type", "zip", "True", "False", "None", "ValueError",
    "TypeError", "KeyError", "IndexError", "RuntimeError",
    "Exception", "StopIteration", "AttributeError",
]

# Safe modules available inside custom tool executors
_SAFE_MODULES = {
    "math": "math",
    "json": "json",
    "re": "re",
    "datetime": "datetime",
    "hashlib": "hashlib",
    "base64": "base64",
    "urllib.parse": "urllib.parse",
    "collections": "collections",
    "itertools": "itertools",
    "functools": "functools",
    "string": "string",
    "textwrap": "textwrap",
    "csv": "csv",
    "io": "io",
    "statistics": "statistics",
}


def _create_custom_tool_executor(code: str) -> Callable:
    """Compile custom tool code and extract ``tool_main`` function.

    In safe mode, only whitelisted builtins and modules are available.
    In full-power mode (``custom_tool_trust_mode == "full"``), full builtins
    are provided.
    """
    full_power = settings.custom_tool_trust_mode == "full"

    if full_power:
        namespace: dict = {"__builtins__": builtins.__dict__}
        exec(code, namespace)  # noqa: S102
        func = namespace.get("tool_main")
        if not callable(func):
            raise ValueError("tool_main is not callable after exec")
        return func

    # Safe mode: restricted builtins + whitelisted modules
    namespace = {
        "__builtins__": {
            k: getattr(builtins, k)
            for k in _SAFE_BUILTIN_NAMES
            if hasattr(builtins, k)
        },
    }
    for mod_name in _SAFE_MODULES:
        try:
            namespace[mod_name.replace(".", "_")] = __import__(mod_name)
        except ImportError:
            pass
    # Also import under dotted names for convenience
    for mod_name in _SAFE_MODULES:
        try:
            namespace[mod_name] = __import__(mod_name)
        except ImportError:
            pass

    exec(code, namespace)  # noqa: S102
    func = namespace.get("tool_main")
    if not callable(func):
        raise ValueError("tool_main is not callable after exec")
    return func


def load_custom_tools_from_db() -> int:
    """Load all enabled+tested custom tools from DB into registries.

    Called once at startup. Returns count of loaded tools.
    """
    if not settings.custom_tool_enabled:
        return 0

    from ..database.session import SessionLocal
    from ..database.models import GeneratedTool
    from ..core.state import set_runtime_state_value

    db = SessionLocal()
    loaded = 0
    try:
        tools = db.query(GeneratedTool).filter(
            GeneratedTool.enabled == 1,
            GeneratedTool.test_passed == 1,
        ).all()
        for t in tools:
            try:
                func = _create_custom_tool_executor(t.code)
                params = json.loads(t.parameters_json) if t.parameters_json else {"type": "object", "properties": {}}
                entry = {
                    "func": func,
                    "definition": {
                        "type": "function",
                        "function": {
                            "name": t.tool_name,
                            "description": t.description or "",
                            "parameters": params,
                        },
                    },
                    "owner_id": t.owner_id,
                }
                CUSTOM_TOOL_REGISTRY[t.tool_name] = entry
                TOOL_DISPATCH[t.tool_name] = func
                loaded += 1
            except Exception as exc:
                logger.warning("CUSTOM_TOOL_LOAD_FAIL name=%s error=%s", t.tool_name, str(exc)[:200])
    finally:
        db.close()

    set_runtime_state_value("custom_tools_loaded", loaded)
    logger.info("CUSTOM_TOOLS_LOADED count=%d", loaded)
    return loaded


def custom_tool_definitions() -> List[dict]:
    """Return OpenAI function-calling definitions for all loaded custom tools."""
    return [entry["definition"] for entry in CUSTOM_TOOL_REGISTRY.values()]


def effective_tool_definitions(owner_id: Optional[int] = None) -> List[dict]:
    """Merge built-in tool schemas with custom tool definitions."""
    base_defs = get_tool_definitions()
    if settings.custom_tool_enabled and CUSTOM_TOOL_REGISTRY:
        base_defs.extend(custom_tool_definitions())
    return base_defs


def _increment_custom_tool_usage(tool_name: str) -> None:
    """Increment usage_count for a custom tool in DB."""
    try:
        from ..database.session import SessionLocal
        from ..database.models import GeneratedTool

        db = SessionLocal()
        try:
            row = db.query(GeneratedTool).filter(GeneratedTool.tool_name == tool_name).first()
            if row:
                row.usage_count = int(row.usage_count or 0) + 1
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _record_custom_tool_error(tool_name: str, error: str) -> None:
    """Record last_error for a custom tool in DB."""
    try:
        from ..database.session import SessionLocal
        from ..database.models import GeneratedTool

        db = SessionLocal()
        try:
            row = db.query(GeneratedTool).filter(GeneratedTool.tool_name == tool_name).first()
            if row:
                row.last_error = str(error)[:2000]
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core dispatch + query functions
# ---------------------------------------------------------------------------

def validate_registry() -> bool:
    """Validate that all tools in TOOL_DISPATCH have callable values.

    Returns True if all tools are valid, False otherwise.
    """
    for name, handler in TOOL_DISPATCH.items():
        if not callable(handler):
            logger.error("REGISTRY_VALIDATION_FAIL tool=%s not_callable", name)
            return False
    logger.info("REGISTRY_VALIDATION_OK tools=%d", len(TOOL_DISPATCH))
    return True


def get_tool_names() -> List[str]:
    """Return sorted list of all available tool names."""
    return sorted(TOOL_DISPATCH.keys())


def has_tool(name: str) -> bool:
    """Check if a tool exists in the registry by name."""
    return name in TOOL_DISPATCH


def get_tools_by_category(category: str) -> List[str]:
    """Return sorted list of tool names in a specific category."""
    if category not in TOOL_CATEGORIES:
        return []
    return sorted(TOOL_CATEGORIES[category])


def execute_tool(tool_name: str, args: dict) -> dict:
    """Execute a tool by name with given arguments.

    Checks custom tool registry first (with usage tracking), then falls
    back to the static TOOL_DISPATCH table.

    Input validation:
    - tool_name must be non-empty string
    - args must be a dict
    """
    # Input validation
    if not tool_name or not isinstance(tool_name, str):
        return {"ok": False, "error": "tool_name must be a non-empty string"}
    tool_name = tool_name.strip()
    if not tool_name:
        return {"ok": False, "error": "tool_name cannot be empty"}

    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    # Custom tool path — track usage + errors
    if tool_name in CUSTOM_TOOL_REGISTRY:
        entry = CUSTOM_TOOL_REGISTRY[tool_name]
        try:
            result = entry["func"](args)
            _increment_custom_tool_usage(tool_name)
            return result
        except Exception as exc:
            _record_custom_tool_error(tool_name, str(exc))
            logger.error("Custom tool execution failed: %s - %s", tool_name, exc)
            return {"ok": False, "error": str(exc)}

    # Built-in tool path
    handler = TOOL_DISPATCH.get(tool_name)
    if handler is None:
        logger.warning("Tool not found: %s", tool_name)
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    try:
        return handler(args)
    except Exception as e:
        logger.error("Tool execution failed: %s - %s", tool_name, e)
        return {"ok": False, "error": str(e)}


def get_available_tools() -> List[str]:
    """Get list of available tool names."""
    return list(TOOL_DISPATCH.keys())


def get_tool_definitions() -> List[dict]:
    """Get OpenAI function definitions for all available built-in tools."""
    all_schemas = schemas.get_tool_schemas()
    available = get_available_tools()
    return [schema for schema in all_schemas if schema["function"]["name"] in available]


def register_tool(name: str, handler: Callable[[dict], dict]) -> None:
    """Register a new tool dynamically."""
    TOOL_DISPATCH[name] = handler
    logger.info("Registered tool: %s", name)


def unregister_tool(name: str) -> None:
    """Unregister a tool."""
    TOOL_DISPATCH.pop(name, None)
    CUSTOM_TOOL_REGISTRY.pop(name, None)
    logger.info("Unregistered tool: %s", name)


def load_remote_node_registry() -> None:
    """Load remote execution nodes from the database into the in-memory registry."""
    try:
        from ..core.nodes import REMOTE_NODE_REGISTRY
        from ..database.session import SessionLocal
        from ..database.models import NodeRegistration
        from ..core.state import RUNTIME_STATE

        db = SessionLocal()
        try:
            rows = db.query(NodeRegistration).filter(NodeRegistration.enabled == 1).all()
            for row in rows:
                try:
                    caps = json.loads(row.capabilities_json or "[]")
                except Exception:
                    caps = []
                REMOTE_NODE_REGISTRY[row.node_name] = {
                    "node_name": row.node_name,
                    "base_url": row.base_url,
                    "capabilities": caps,
                    "enabled": True,
                }
            RUNTIME_STATE["remote_nodes_loaded"] = len(rows)
            logger.info("Loaded %d remote nodes", len(rows))
        finally:
            db.close()
    except Exception as exc:
        logger.warning("load_remote_node_registry failed: %s", exc)


def load_plugin_tools_registry() -> None:
    """Load plugin tools from the plugins directory (if any)."""
    from ..core.state import RUNTIME_STATE
    try:
        from ..core.plugins import discover_plugins
        plugins = discover_plugins()
        for name, handler in plugins.items():
            TOOL_DISPATCH[name] = handler
        RUNTIME_STATE["plugin_tools_loaded"] = len(plugins)
        logger.info("Loaded %d plugin tools", len(plugins))
    except ImportError:
        RUNTIME_STATE["plugin_tools_loaded"] = 0
    except Exception as exc:
        logger.warning("load_plugin_tools_registry failed: %s", exc)
        RUNTIME_STATE["plugin_tools_loaded"] = 0

"""
Tool definitions and schemas — get_tool_definitions(), effective_tool_definitions(),
tool schemas, TOOL_CATEGORIES, intent classification.
"""

from __future__ import annotations

import builtins
import logging
from typing import Dict, Callable, Any, List, Optional

from ...config import settings
from .. import schemas

logger = logging.getLogger("mind_clone.tools.registry.definitions")


# ---------------------------------------------------------------------------
# Tool categories — every tool must belong to at least one category
# ---------------------------------------------------------------------------
TOOL_CATEGORIES: Dict[str, set] = {
    "web": {
        "search_web", "read_webpage", "deep_research", "read_pdf_url",
        "deep_research_pipeline", "browse", "screenshot",
    },
    "file": {
        "read_file", "write_file", "list_directory",
    },
    "code": {
        "run_command", "execute_python", "sandbox_python", "sandbox_shell",
        "safe_python", "safe_shell",
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
        "browser_close", "browse", "screenshot",
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
        "send_email", "save_research_note", "speak", "get_calendar", "create_reminder",
        "send_whatsapp",
    },
    "memory": {
        "research_memory_search", "semantic_memory_search",
        "link_memories", "memory_graph_search", "auto_link_memory",
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
    "agent_team": {
        "agent_team_run", "agent_team_status",
    },
    "self_awareness": {
        "run_retro", "get_patterns", "self_improve", "run_experiment",
        "optimise_prompts", "memory_decay", "evolve_critic", "scan_triggers",
    },
    "research": {
        "research_github", "forge_tool", "meta_research", "meta_report", "run_briefing",
        "run_learning", "rag_search", "rag_ingest", "rag_store", "browse_and_extract",
        "deep_research_pipeline",
    },
    "agents": {
        "spawn_agents",
    },
    "monitoring": {
        "dashboard", "scan_triggers", "check_merge", "auto_merge",
    },
    "learning": {
        "store_teaching_moment", "evolve_critic",
    },
    "user": {
        "get_user_profile", "update_user_profile", "get_world_model", "update_world",
    },
    "testing": {
        "run_self_tests", "generate_tests", "meta_run",
    },
    "agent_tasks": {
        "run_isolated_task",
    },
    "skill_library": {
        "save_skill", "recall_skill", "list_skills", "get_skill", "archive_skill",
        "run_chain", "create_chain",
    },
    "safe_improvement": {
        "create_skill_md", "list_skills_md", "safe_improve",
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
    "communication": ["email", "send", "message", "notify", "whatsapp"],
    "memory": ["memory", "remember", "recall", "lesson", "research", "knowledge"],
    "scheduler": ["schedule", "cron", "recurring", "timer", "periodic", "every day", "every hour"],
    "nodes": ["node", "remote", "execution"],
    "sessions": ["session", "spawn", "terminal"],
    "custom": ["create tool", "custom tool", "build tool", "make tool", "new tool"],
    "agent_team": ["agent team", "autonomous", "refactor", "modify code", "code change", "implement feature", "fix bug", "add feature"],
    "skill_library": ["skill", "save skill", "recall skill", "remember how", "list skills", "what skills", "reuse", "past task", "learned"],
    "agent_tasks": ["isolated", "sub-task", "subtask", "separate task", "run in isolation", "parallel task"],
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
    "open", "property", "__import__", "FileNotFoundError",
    "OSError", "IOError", "PermissionError", "exec", "eval", "compile",
    "globals", "locals", "vars", "callable", "classmethod",
    "staticmethod", "super", "object", "memoryview", "bytearray",
    "complex", "bin", "ascii", "breakpoint", "NotImplementedError",
    "ArithmeticError", "LookupError", "OverflowError",
    "ZeroDivisionError", "UnicodeError", "UnicodeDecodeError",
    "UnicodeEncodeError",
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
    "httpx": "httpx",
    "os": "os",
    "pathlib": "pathlib",
    "subprocess": "subprocess",
    "numpy": "numpy",
    "pandas": "pandas",
    "PIL": "PIL",
    "sqlite3": "sqlite3",
    "socket": "socket",
    "ssl": "ssl",
    "shutil": "shutil",
    "glob": "glob",
    "tempfile": "tempfile",
    "uuid": "uuid",
    "random": "random",
    "time": "time",
    "threading": "threading",
    "logging": "logging",
    "struct": "struct",
    "decimal": "decimal",
    "fractions": "fractions",
    "html": "html",
    "xml": "xml",
    "email": "email",
    "mimetypes": "mimetypes",
    "fnmatch": "fnmatch",
    "copy": "copy",
    "pprint": "pprint",
    "difflib": "difflib",
    "typing": "typing",
    "dataclasses": "dataclasses",
    "enum": "enum",
    "abc": "abc",
    "contextlib": "contextlib",
    "operator": "operator",
    "bisect": "bisect",
    "heapq": "heapq",
    "sys": "sys",
    "traceback": "traceback",
    "inspect": "inspect",
    "platform": "platform",
    "urllib": "urllib",
    "http": "http",
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


def get_tool_definitions() -> List[dict]:
    """Get OpenAI function definitions for all available built-in tools."""
    from .dispatch import get_available_tools
    all_schemas = schemas.get_tool_schemas()
    available = get_available_tools()
    return [schema for schema in all_schemas if schema["function"]["name"] in available]


def effective_tool_definitions(owner_id: Optional[int] = None) -> List[dict]:
    """Merge built-in tool schemas with custom tool definitions."""
    from .custom import custom_tool_definitions, CUSTOM_TOOL_REGISTRY
    base_defs = get_tool_definitions()
    if settings.custom_tool_enabled and CUSTOM_TOOL_REGISTRY:
        base_defs.extend(custom_tool_definitions())
    return base_defs

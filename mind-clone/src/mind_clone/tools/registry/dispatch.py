"""
Tool dispatch registry — TOOL_DISPATCH dict, execute_tool(), has_tool(), get_tool_names().

Central registry that maps tool names to their handler functions.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Callable, Any, List

from ...config import settings
from .. import schemas
from ..basic import (
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
from ..browser import (
    tool_browser_open,
    tool_browser_get_text,
    tool_browser_click,
    tool_browser_type,
    tool_browser_screenshot,
    tool_browser_execute_js,
    tool_browser_close,
)
from ..desktop import (
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
from ..memory import (
    tool_research_memory_search,
    tool_semantic_memory_search,
    tool_read_pdf_url,
)
from ..scheduler import (
    tool_schedule_job,
    tool_list_scheduled_jobs,
    tool_disable_scheduled_job,
)
from ..nodes import (
    tool_list_execution_nodes,
    tool_run_command_node,
)
from ..sessions import (
    tool_sessions_spawn,
    tool_sessions_send,
    tool_sessions_list,
    tool_sessions_history,
    tool_sessions_stop,
)
from ..custom import (
    tool_list_plugin_tools,
    tool_create_tool,
    tool_list_custom_tools,
    tool_disable_custom_tool,
    tool_llm_structured_task,
)
from ..codebase import (
    tool_codebase_read,
    tool_codebase_search,
    tool_codebase_structure,
    tool_codebase_edit,
    tool_codebase_write,
    tool_codebase_run_tests,
    tool_codebase_git_status,
)
from ..github import (
    tool_git_status,
    tool_git_commit,
    tool_git_branch,
    tool_git_diff,
    tool_git_log,
    tool_git_push,
    tool_git_pull,
)
from ..agent_team import (
    tool_agent_team_run,
    tool_agent_team_status,
)
from ..skill_library import (
    tool_save_skill,
    tool_recall_skill,
    tool_list_skills,
    tool_get_skill,
    tool_archive_skill,
)

from .wrappers import (
    tool_self_improve,
    tool_run_experiment,
    tool_create_skill_md,
    tool_list_skills_md,
    tool_safe_improve,
    tool_run_chain,
    tool_create_chain,
    tool_link_memories,
    tool_memory_graph_search,
    tool_browse_and_extract,
    tool_deep_research_pipeline,
    tool_browse,
    tool_screenshot,
    tool_send_whatsapp,
    tool_safe_python,
    tool_safe_shell,
    tool_rag_search,
    tool_rag_ingest,
    tool_rag_store,
    tool_spawn_agents,
    tool_run_learning,
    tool_sandbox_python,
    tool_sandbox_shell,
    tool_speak,
    tool_get_calendar,
    tool_send_email as tool_send_email_wrapper,
    tool_create_reminder,
    tool_dashboard,
    tool_auto_merge,
    tool_check_merge,
    tool_store_teaching_moment,
    tool_get_user_profile,
    tool_update_user_profile,
    tool_run_briefing,
    tool_run_self_tests,
    tool_generate_tests,
    tool_get_world_model,
    tool_update_world,
    tool_meta_research,
    tool_meta_report,
    tool_meta_run,
    tool_research_github,
    tool_forge_tool,
    tool_evolve_critic,
    tool_scan_triggers,
    tool_memory_decay,
    tool_optimise_prompts,
    tool_run_isolated_task,
    tool_auto_link_memory,
    tool_get_patterns,
    tool_run_retro,
)
from .custom import CUSTOM_TOOL_REGISTRY, _increment_custom_tool_usage, _record_custom_tool_error

logger = logging.getLogger("mind_clone.tools.registry.dispatch")


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
    # Agent team tools
    "agent_team_run": tool_agent_team_run,
    "agent_team_status": tool_agent_team_status,
    # Self-awareness
    "run_retro": tool_run_retro,
    # Predictive intelligence
    "get_patterns": tool_get_patterns,
    # Self-improvement
    "self_improve": tool_self_improve,
    # Karpathy experiment loop
    "run_experiment": tool_run_experiment,
    # Ebbinghaus memory decay
    "memory_decay": tool_memory_decay,
    # Browser agent
    "browse_and_extract": tool_browse_and_extract,
    # RAG knowledge base
    "rag_search": tool_rag_search,
    "rag_ingest": tool_rag_ingest,
    "rag_store": tool_rag_store,
    # Multi-agent spawning
    "spawn_agents": tool_spawn_agents,
    # Continuous learning
    "run_learning": tool_run_learning,
    # Code sandbox
    "sandbox_python": tool_sandbox_python,
    "sandbox_shell": tool_sandbox_shell,
    # Voice
    "speak": tool_speak,
    # Calendar + email
    "get_calendar": tool_get_calendar,
    "send_email": tool_send_email_wrapper,
    "create_reminder": tool_create_reminder,
    # Observability
    "dashboard": tool_dashboard,
    # Auto-merge
    "auto_merge": tool_auto_merge,
    "check_merge": tool_check_merge,
    # Bob teaches Bob
    "store_teaching_moment": tool_store_teaching_moment,
    # User profiling
    "get_user_profile": tool_get_user_profile,
    "update_user_profile": tool_update_user_profile,
    # Autonomous research briefing
    "run_briefing": tool_run_briefing,
    # Self-testing
    "run_self_tests": tool_run_self_tests,
    "generate_tests": tool_generate_tests,
    # World model
    "get_world_model": tool_get_world_model,
    "update_world": tool_update_world,
    # Meta-tools
    "meta_research": tool_meta_research,
    "meta_report": tool_meta_report,
    "meta_run": tool_meta_run,
    # GitHub research
    "research_github": tool_research_github,
    # On-the-fly tool creation
    "forge_tool": tool_forge_tool,
    # Co-evolving critic
    "evolve_critic": tool_evolve_critic,
    # Event-driven triggers
    "scan_triggers": tool_scan_triggers,
    # DSPy prompt optimisation
    "optimise_prompts": tool_optimise_prompts,
    # Sub-agent isolation (CORPGEN)
    "run_isolated_task": tool_run_isolated_task,
    # Memory graph (A-MEM / MAGMA / Zettelkasten)
    "link_memories": tool_link_memories,
    "memory_graph_search": tool_memory_graph_search,
    "auto_link_memory": tool_auto_link_memory,
    # Skill library (Voyager-style)
    "save_skill": tool_save_skill,
    "recall_skill": tool_recall_skill,
    "list_skills": tool_list_skills,
    "get_skill": tool_get_skill,
    "archive_skill": tool_archive_skill,
    # DeerFlow deep research pipeline
    "deep_research_pipeline": tool_deep_research_pipeline,
    # Browser automation (Selenium headless)
    "browse": tool_browse,
    "screenshot": tool_screenshot,
    # WhatsApp messaging
    "send_whatsapp": tool_send_whatsapp,
    # Sandboxed execution
    "safe_python": tool_safe_python,
    "safe_shell": tool_safe_shell,
    # Safe self-improvement (OpenClaw-style — NO source code modification)
    "create_skill_md": tool_create_skill_md,
    "list_skills_md": tool_list_skills_md,
    "safe_improve": tool_safe_improve,
    # Skill chaining — multi-skill pipelines
    "run_chain": tool_run_chain,
    "create_chain": tool_create_chain,
}


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
    from .definitions import TOOL_CATEGORIES
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
        from ...core.nodes import REMOTE_NODE_REGISTRY
        from ...database.session import SessionLocal
        from ...database.models import NodeRegistration
        from ...core.state import RUNTIME_STATE

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
    from ...core.state import RUNTIME_STATE
    try:
        from ...core.plugins import discover_plugins
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

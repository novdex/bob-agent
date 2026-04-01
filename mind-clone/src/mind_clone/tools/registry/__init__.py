"""
Tool registry package — backward-compatible re-exports.

This package was split from a single ``registry.py`` module into four
submodules for maintainability:

- ``dispatch.py``     — TOOL_DISPATCH dict, execute_tool(), has_tool(), get_tool_names()
- ``definitions.py``  — get_tool_definitions(), effective_tool_definitions(), schemas, TOOL_CATEGORIES
- ``custom.py``       — CUSTOM_TOOL_REGISTRY, load_custom_tools_from_db(), custom_tool_definitions()
- ``wrappers.py``     — all tool_xxx lazy-import wrapper functions

All public names are re-exported here so existing ``from ..tools.registry import X``
imports continue to work unchanged.
"""

from __future__ import annotations

# --- dispatch.py ---
from .dispatch import (
    TOOL_DISPATCH,
    validate_registry,
    get_tool_names,
    has_tool,
    get_tools_by_category,
    execute_tool,
    get_available_tools,
    register_tool,
    unregister_tool,
    load_remote_node_registry,
    load_plugin_tools_registry,
)

# --- definitions.py ---
from .definitions import (
    TOOL_CATEGORIES,
    _INTENT_KEYWORDS,
    _BASE_CATEGORIES,
    classify_tool_intent,
    _select_tools_for_intent,
    _SAFE_BUILTIN_NAMES,
    _SAFE_MODULES,
    _create_custom_tool_executor,
    get_tool_definitions,
    effective_tool_definitions,
)

# --- custom.py ---
from .custom import (
    CUSTOM_TOOL_REGISTRY,
    load_custom_tools_from_db,
    custom_tool_definitions,
    _increment_custom_tool_usage,
    _record_custom_tool_error,
)

# --- wrappers.py (all tool_xxx functions) ---
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
    tool_send_email,
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
    tool_safe_python,
    tool_safe_shell,
    tool_browse,
    tool_screenshot,
)

__all__ = [
    # Dispatch
    "TOOL_DISPATCH",
    "validate_registry",
    "get_tool_names",
    "has_tool",
    "get_tools_by_category",
    "execute_tool",
    "get_available_tools",
    "register_tool",
    "unregister_tool",
    "load_remote_node_registry",
    "load_plugin_tools_registry",
    # Definitions
    "TOOL_CATEGORIES",
    "classify_tool_intent",
    "get_tool_definitions",
    "effective_tool_definitions",
    # Custom
    "CUSTOM_TOOL_REGISTRY",
    "load_custom_tools_from_db",
    "custom_tool_definitions",
]

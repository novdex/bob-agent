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
from .agent_team import (
    tool_agent_team_run,
    tool_agent_team_status,
)
from .skill_library import (
    tool_save_skill,
    tool_recall_skill,
    tool_list_skills,
    tool_get_skill,
    tool_archive_skill,
)

logger = logging.getLogger("mind_clone.tools")


# ---------------------------------------------------------------------------
# Self-awareness retro tool
# ---------------------------------------------------------------------------

def tool_self_improve(args: dict) -> dict:
    """Tool: Bob fixes his top self-improvement opportunity using his own codebase tools."""
    try:
        from ..services.self_improve import tool_self_improve as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_experiment(args: dict) -> dict:
    """Tool: Run Bob's Karpathy-style nightly self-improvement experiment loop once."""
    try:
        from ..services.auto_research import tool_run_experiment as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Safe self-improvement tools (OpenClaw-style — NO source code modification)
# ---------------------------------------------------------------------------

def tool_create_skill_md(args: dict) -> dict:
    """Tool: Create a new markdown-based skill that teaches Bob a procedure."""
    try:
        from ..services.skill_manager import tool_create_skill as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_list_skills_md(args: dict) -> dict:
    """Tool: List all markdown-based skills available to Bob."""
    try:
        from ..services.skill_manager import tool_list_skills_md as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_improve(args: dict) -> dict:
    """Tool: Run safe nightly improvement — reviews performance, creates skills, tunes config. Never touches source code."""
    try:
        from ..services.safe_improve import tool_safe_improve as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_link_memories(args: dict) -> dict:
    """Tool: Create a graph link between two memory nodes."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ..services.memory_graph import link_memories
        from ..database.session import SessionLocal
        db = SessionLocal()
        try:
            link = link_memories(
                db, owner_id,
                src_type=str(args.get("src_type", "")),
                src_id=int(args.get("src_id", 0)),
                tgt_type=str(args.get("tgt_type", "")),
                tgt_id=int(args.get("tgt_id", 0)),
                relation=str(args.get("relation", "related")),
                weight=float(args.get("weight", 1.0)),
                note=args.get("note"),
            )
            if link:
                return {"ok": True, "link_id": link.id, "relation": link.relation}
            return {"ok": False, "error": "Could not create link (invalid types or self-loop)"}
        finally:
            db.close()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_memory_graph_search(args: dict) -> dict:
    """Tool: Traverse Bob's memory graph from a starting node to find related memories."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ..services.memory_graph import graph_search
        from ..database.session import SessionLocal
        db = SessionLocal()
        try:
            return graph_search(
                db, owner_id,
                start_type=str(args.get("start_type", "")),
                start_id=int(args.get("start_id", 0)),
                depth=min(int(args.get("depth", 2)), 3),
                max_nodes=min(int(args.get("max_nodes", 10)), 20),
            )
        finally:
            db.close()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_browse_and_extract(args: dict) -> dict:
    try:
        from ..services.browser_agent import tool_browse_and_extract as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_deep_research_pipeline(args: dict) -> dict:
    """Tool: Run DeerFlow-style deep multi-agent research pipeline."""
    try:
        from ..services.deep_research import tool_deep_research as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_browse(args: dict) -> dict:
    """Tool: Browse a URL with headless Selenium and optionally extract info."""
    try:
        from ..services.browser_automation import tool_browse as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_screenshot(args: dict) -> dict:
    """Tool: Take a screenshot of a URL via headless browser."""
    try:
        from ..services.browser_automation import tool_screenshot as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_send_whatsapp(args: dict) -> dict:
    """Tool: Send a WhatsApp message via the Cloud API."""
    try:
        from ..services.whatsapp_bridge import tool_send_whatsapp as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_python(args: dict) -> dict:
    """Tool: Run Python code in a sandboxed subprocess with timeout and blocklists."""
    try:
        from ..services.sandbox import tool_safe_python as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_shell(args: dict) -> dict:
    """Tool: Run a shell command in a sandboxed subprocess with timeout and blocklists."""
    try:
        from ..services.sandbox import tool_safe_shell as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_rag_search(args: dict) -> dict:
    try:
        from ..services.knowledge_base import tool_rag_search as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_rag_ingest(args: dict) -> dict:
    try:
        from ..services.knowledge_base import tool_rag_ingest as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_rag_store(args: dict) -> dict:
    try:
        from ..services.knowledge_base import tool_rag_store as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_spawn_agents(args: dict) -> dict:
    try:
        from ..services.agent_spawner import tool_spawn_agents as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_run_learning(args: dict) -> dict:
    try:
        from ..services.continuous_learner import tool_run_learning as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_sandbox_python(args: dict) -> dict:
    try:
        from ..services.code_sandbox import tool_sandbox_python as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_sandbox_shell(args: dict) -> dict:
    try:
        from ..services.code_sandbox import tool_sandbox_shell as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_speak(args: dict) -> dict:
    try:
        from ..services.voice_interface import tool_speak as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_get_calendar(args: dict) -> dict:
    try:
        from ..services.calendar_email import tool_get_calendar as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_send_email(args: dict) -> dict:
    try:
        from ..services.calendar_email import tool_send_email as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_create_reminder(args: dict) -> dict:
    try:
        from ..services.calendar_email import tool_create_reminder as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_dashboard(args: dict) -> dict:
    try:
        from ..services.observability import tool_dashboard as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_auto_merge(args: dict) -> dict:
    try:
        from ..services.auto_merge import tool_auto_merge as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_check_merge(args: dict) -> dict:
    try:
        from ..services.auto_merge import tool_check_merge as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_store_teaching_moment(args: dict) -> dict:
    try:
        from ..services.bob_teaches_bob import tool_store_teaching_moment as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_get_user_profile(args: dict) -> dict:
    try:
        from ..services.user_profile import tool_get_user_profile as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_update_user_profile(args: dict) -> dict:
    try:
        from ..services.user_profile import tool_update_user_profile as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_run_briefing(args: dict) -> dict:
    try:
        from ..services.autonomous_research import tool_run_briefing as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_run_self_tests(args: dict) -> dict:
    try:
        from ..services.self_tester import tool_run_self_tests as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_generate_tests(args: dict) -> dict:
    try:
        from ..services.self_tester import tool_generate_tests as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_get_world_model(args: dict) -> dict:
    try:
        from ..services.world_model import tool_get_world_model as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_update_world(args: dict) -> dict:
    try:
        from ..services.world_model import tool_update_world as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_meta_research(args: dict) -> dict:
    try:
        from ..services.meta_tools import meta_research_and_save
        return meta_research_and_save(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_meta_report(args: dict) -> dict:
    try:
        from ..services.meta_tools import meta_search_and_report
        return meta_search_and_report(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_meta_run(args: dict) -> dict:
    try:
        from ..services.meta_tools import meta_run_and_check
        return meta_run_and_check(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def tool_research_github(args: dict) -> dict:
    """Tool: Search GitHub for top repos on a topic, extract insights, save as ResearchNotes."""
    try:
        from ..services.github_research import tool_research_github as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_forge_tool(args: dict) -> dict:
    """Tool: Synthesize and register a new capability tool on the fly."""
    try:
        from ..services.tool_forge import tool_forge_tool as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_evolve_critic(args: dict) -> dict:
    """Tool: Evolve the critic's principles based on real failure history."""
    try:
        from ..services.co_critic import tool_evolve_critic as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_scan_triggers(args: dict) -> dict:
    """Tool: Scan event triggers and return any that have fired."""
    try:
        from ..services.event_triggers import tool_scan_triggers as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_memory_decay(args: dict) -> dict:
    """Tool: Run Ebbinghaus memory decay and pruning cycle."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ..services.ebbinghaus import run_daily_memory_maintenance
        return run_daily_memory_maintenance(owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_optimise_prompts(args: dict) -> dict:
    """Tool: Run DSPy-style prompt optimisation to improve Bob's tool usage hints."""
    try:
        from ..services.prompt_optimizer import tool_optimise_prompts as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_isolated_task(args: dict) -> dict:
    """Tool: Run a sub-task in an isolated context to prevent memory contamination."""
    try:
        from ..services.task_isolator import tool_run_isolated_task as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_auto_link_memory(args: dict) -> dict:
    """Tool: Auto-find and link related memories for a given memory node (Zettelkasten style)."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ..services.memory_graph import auto_link
        from ..database.session import SessionLocal
        db = SessionLocal()
        try:
            links = auto_link(
                db, owner_id,
                src_type=str(args.get("src_type", "")),
                src_id=int(args.get("src_id", 0)),
                min_overlap=int(args.get("min_overlap", 2)),
            )
            return {"ok": True, "links_created": len(links), "links": links}
        finally:
            db.close()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_get_patterns(args: dict) -> dict:
    """Return Arsh's conversation patterns and interests."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ..services.prediction import get_pattern_summary, get_user_patterns
        from ..database.session import SessionLocal
        db = SessionLocal()
        try:
            patterns = get_user_patterns(db, owner_id)
        finally:
            db.close()
        return {
            "ok": True,
            "top_topics": patterns.get("top_topics", []),
            "notable": patterns.get("notable", []),
            "auto_schedulable": patterns.get("auto_schedulable", []),
            "summary": get_pattern_summary(owner_id),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_retro(args: dict) -> dict:
    """Run Bob's self-awareness retro and return the analysis."""
    import asyncio
    owner_id = int(args.get("_owner_id", 1))
    send_telegram = bool(args.get("send_to_telegram", True))
    try:
        from ..services.retro import run_full_retro
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, run_full_retro(owner_id, send_telegram))
                    result = future.result(timeout=120)
            else:
                result = asyncio.run(run_full_retro(owner_id, send_telegram))
        except RuntimeError:
            result = asyncio.run(run_full_retro(owner_id, send_telegram))
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

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
    "send_email": tool_send_email,
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
        "deep_research_pipeline", "browse", "screenshot",
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
        "send_email", "save_research_note",
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
    "code": {
        "run_command", "execute_python", "sandbox_python", "sandbox_shell",
        "safe_python", "safe_shell",
    },
    "communication": {
        "send_email", "save_research_note", "speak", "get_calendar", "create_reminder",
        "send_whatsapp",
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

"""
Tool wrapper functions — lazy-import try/except wrappers.

Each function here wraps an implementation from another module using lazy
imports so the heavy service modules are only loaded when the tool is
actually called.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("mind_clone.tools.registry.wrappers")


# ---------------------------------------------------------------------------
# Self-awareness / retro
# ---------------------------------------------------------------------------

def tool_self_improve(args: dict) -> dict:
    """Tool: Bob fixes his top self-improvement opportunity using his own codebase tools."""
    try:
        from ...services.self_improve import tool_self_improve as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_experiment(args: dict) -> dict:
    """Tool: Run Bob's Karpathy-style nightly self-improvement experiment loop once."""
    try:
        from ...services.auto_research import tool_run_experiment as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Safe self-improvement tools (OpenClaw-style — NO source code modification)
# ---------------------------------------------------------------------------

def tool_create_skill_md(args: dict) -> dict:
    """Tool: Create a new markdown-based skill that teaches Bob a procedure."""
    try:
        from ...services.skills import tool_create_skill as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_list_skills_md(args: dict) -> dict:
    """Tool: List all markdown-based skills available to Bob."""
    try:
        from ...services.skills import tool_list_skills_md as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_improve(args: dict) -> dict:
    """Tool: Run safe nightly improvement — reviews performance, creates skills, tunes config. Never touches source code."""
    try:
        from ...services.self_improve import tool_safe_improve as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_chain(args: dict) -> dict:
    """Tool: Run a named skill chain — execute skills in sequence, piping output forward."""
    try:
        from ...services.skills import tool_run_chain as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_create_chain(args: dict) -> dict:
    """Tool: Create a new skill chain — define a pipeline of skills to run in sequence."""
    try:
        from ...services.skills import tool_create_chain as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Memory graph tools
# ---------------------------------------------------------------------------

def tool_link_memories(args: dict) -> dict:
    """Tool: Create a graph link between two memory nodes."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ...services.memory_graph import link_memories
        from ...database.session import SessionLocal
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
        from ...services.memory_graph import graph_search
        from ...database.session import SessionLocal
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
    """Tool: Browse a URL with browser agent and extract structured information."""
    try:
        from ...services.browser_agent import tool_browse_and_extract as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_deep_research_pipeline(args: dict) -> dict:
    """Tool: Run DeerFlow-style deep multi-agent research pipeline."""
    try:
        from ...services.deep_research import tool_deep_research as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_browse(args: dict) -> dict:
    """Tool: Browse a URL with headless Selenium and optionally extract info."""
    try:
        from ...services.browser_automation import tool_browse as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_screenshot(args: dict) -> dict:
    """Tool: Take a screenshot of a URL via headless browser."""
    try:
        from ...services.browser_automation import tool_screenshot as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_send_whatsapp(args: dict) -> dict:
    """Tool: Send a WhatsApp message via the Cloud API."""
    try:
        from ...services.whatsapp_bridge import tool_send_whatsapp as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_python(args: dict) -> dict:
    """Tool: Run Python code in a sandboxed subprocess with timeout and blocklists."""
    try:
        from ...services.sandbox import tool_safe_python as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_safe_shell(args: dict) -> dict:
    """Tool: Run a shell command in a sandboxed subprocess with timeout and blocklists."""
    try:
        from ...services.sandbox import tool_safe_shell as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_rag_search(args: dict) -> dict:
    """Tool: Search the RAG knowledge base."""
    try:
        from ...services.knowledge_base import tool_rag_search as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_rag_ingest(args: dict) -> dict:
    """Tool: Ingest a document into the RAG knowledge base."""
    try:
        from ...services.knowledge_base import tool_rag_ingest as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_rag_store(args: dict) -> dict:
    """Tool: Store a text chunk in the RAG knowledge base."""
    try:
        from ...services.knowledge_base import tool_rag_store as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_spawn_agents(args: dict) -> dict:
    """Tool: Spawn multiple sub-agents for parallel work."""
    try:
        from ...services.agent_spawner import tool_spawn_agents as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_learning(args: dict) -> dict:
    """Tool: Run a continuous learning cycle."""
    try:
        from ...services.continuous_learner import tool_run_learning as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_sandbox_python(args: dict) -> dict:
    """Tool: Run Python in a sandboxed environment."""
    try:
        from ...services.sandbox import tool_sandbox_python as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_sandbox_shell(args: dict) -> dict:
    """Tool: Run shell command in a sandboxed environment."""
    try:
        from ...services.sandbox import tool_sandbox_shell as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_speak(args: dict) -> dict:
    """Tool: Speak text using TTS voice interface."""
    try:
        from ...services.voice_interface import tool_speak as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_get_calendar(args: dict) -> dict:
    """Tool: Get calendar events."""
    try:
        from ...services.calendar_email import tool_get_calendar as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_send_email(args: dict) -> dict:
    """Tool: Send an email via configured provider."""
    try:
        from ...services.calendar_email import tool_send_email as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_create_reminder(args: dict) -> dict:
    """Tool: Create a calendar reminder."""
    try:
        from ...services.calendar_email import tool_create_reminder as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_dashboard(args: dict) -> dict:
    """Tool: Get observability dashboard data."""
    try:
        from ...services.observability import tool_dashboard as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_auto_merge(args: dict) -> dict:
    """Tool: Auto-merge approved pull requests."""
    try:
        from ...services.auto_merge import tool_auto_merge as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_check_merge(args: dict) -> dict:
    """Tool: Check merge readiness for a pull request."""
    try:
        from ...services.auto_merge import tool_check_merge as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_store_teaching_moment(args: dict) -> dict:
    """Tool: Store a teaching moment for Bob-teaches-Bob learning."""
    try:
        from ...services.bob_teaches_bob import tool_store_teaching_moment as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_get_user_profile(args: dict) -> dict:
    """Tool: Get the user profile data."""
    try:
        from ...services.user_profile import tool_get_user_profile as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_update_user_profile(args: dict) -> dict:
    """Tool: Update the user profile data."""
    try:
        from ...services.user_profile import tool_update_user_profile as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_briefing(args: dict) -> dict:
    """Tool: Run an autonomous research briefing."""
    try:
        from ...services.autonomous_research import tool_run_briefing as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_self_tests(args: dict) -> dict:
    """Tool: Run Bob's self-tests."""
    try:
        from ...services.self_improve import tool_run_self_tests as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_generate_tests(args: dict) -> dict:
    """Tool: Auto-generate tests for Bob's capabilities."""
    try:
        from ...services.self_improve import tool_generate_tests as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_get_world_model(args: dict) -> dict:
    """Tool: Get the world model state."""
    try:
        from ...services.world_model import tool_get_world_model as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_update_world(args: dict) -> dict:
    """Tool: Update the world model."""
    try:
        from ...services.world_model import tool_update_world as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_meta_research(args: dict) -> dict:
    """Tool: Run meta-research and save results."""
    try:
        from ...services.meta_tools import meta_research_and_save
        return meta_research_and_save(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_meta_report(args: dict) -> dict:
    """Tool: Run meta-search and generate a report."""
    try:
        from ...services.meta_tools import meta_search_and_report
        return meta_search_and_report(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_meta_run(args: dict) -> dict:
    """Tool: Run a meta-tool and check results."""
    try:
        from ...services.meta_tools import meta_run_and_check
        return meta_run_and_check(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_research_github(args: dict) -> dict:
    """Tool: Search GitHub for top repos on a topic, extract insights, save as ResearchNotes."""
    try:
        from ...services.github_research import tool_research_github as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_forge_tool(args: dict) -> dict:
    """Tool: Synthesize and register a new capability tool on the fly."""
    try:
        from ...services.tool_forge import tool_forge_tool as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_evolve_critic(args: dict) -> dict:
    """Tool: Evolve the critic's principles based on real failure history."""
    try:
        from ...services.co_critic import tool_evolve_critic as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_scan_triggers(args: dict) -> dict:
    """Tool: Scan event triggers and return any that have fired."""
    try:
        from ...services.event_triggers import tool_scan_triggers as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_memory_decay(args: dict) -> dict:
    """Tool: Run Ebbinghaus memory decay and pruning cycle."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ...services.ebbinghaus import run_daily_memory_maintenance
        return run_daily_memory_maintenance(owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_optimise_prompts(args: dict) -> dict:
    """Tool: Run DSPy-style prompt optimisation to improve Bob's tool usage hints."""
    try:
        from ...services.prompt_optimizer import tool_optimise_prompts as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_isolated_task(args: dict) -> dict:
    """Tool: Run a sub-task in an isolated context to prevent memory contamination."""
    try:
        from ...services.task_isolator import tool_run_isolated_task as _impl
        return _impl(args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_auto_link_memory(args: dict) -> dict:
    """Tool: Auto-find and link related memories for a given memory node (Zettelkasten style)."""
    owner_id = int(args.get("_owner_id", 1))
    try:
        from ...services.memory_graph import auto_link
        from ...database.session import SessionLocal
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
        from ...services.prediction import get_pattern_summary, get_user_patterns
        from ...database.session import SessionLocal
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
        from ...services.retro import run_full_retro
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

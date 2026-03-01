"""
Bob tool: agent_team — launch the autonomous agent team.

Two tools:
  - agent_team_run({"task": "..."})   → kicks off Orchestrator pipeline
  - agent_team_status({})             → returns current run status
"""

from __future__ import annotations

import logging
import threading
import time

from ..core.state import RUNTIME_STATE, RUNTIME_STATE_LOCK

logger = logging.getLogger("mind_clone.tools.agent_team")

_AGENT_LOCK = threading.Lock()
_AGENT_RUNNING = False


def tool_agent_team_run(args) -> dict:
    """Launch the autonomous agent team on a coding task."""
    global _AGENT_RUNNING

    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    task = str(args.get("task", "")).strip()
    if not task:
        return {"ok": False, "error": "task is required — describe what you want changed"}
    if len(task) > 2000:
        return {"ok": False, "error": "task too long (max 2000 chars)"}

    with _AGENT_LOCK:
        if _AGENT_RUNNING:
            return {"ok": False, "error": "Agent team is already running a task. Wait for it to finish."}
        _AGENT_RUNNING = True

    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE["agent_team_status"] = "running"
        RUNTIME_STATE["agent_team_task"] = task

    t0 = time.time()
    try:
        from ..agents.config import AgentConfig
        from ..agents.orchestrator import Orchestrator

        config = AgentConfig()
        if not config.api_key:
            return {"ok": False, "error": "No API key configured. Set KIMI_API_KEY in .env"}
        if not config.repo_root:
            return {"ok": False, "error": "Could not detect repository root"}

        orch = Orchestrator(config)
        result = orch.run(task)
        elapsed = round(time.time() - t0, 2)

        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE["agent_team_status"] = "idle"
            RUNTIME_STATE["agent_team_task"] = ""
            RUNTIME_STATE["agent_team_last_result"] = result

        if result.get("ok"):
            tests = result.get("tests", {})
            tp = tests.get("tests_passed", 0)
            tf = tests.get("tests_failed", 0)
            summary = f"Done in {elapsed}s — {tp} passed, {tf} failed"
            return {
                "ok": True,
                "summary": summary,
                "branch": result.get("branch", ""),
                "duration_s": elapsed,
                "llm_stats": result.get("llm_stats", {}),
            }
        else:
            return {
                "ok": False,
                "error": result.get("error", "Unknown failure"),
                "branch": result.get("branch", ""),
                "duration_s": elapsed,
            }

    except Exception as e:
        logger.exception("Agent team crashed: %s", e)
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE["agent_team_status"] = "error"
        return {"ok": False, "error": f"Agent team crashed: {e}"}
    finally:
        with _AGENT_LOCK:
            _AGENT_RUNNING = False


def tool_agent_team_status(args) -> dict:
    """Return current agent team status."""
    with RUNTIME_STATE_LOCK:
        status = RUNTIME_STATE.get("agent_team_status", "idle")
        current_task = RUNTIME_STATE.get("agent_team_task", "")
        last_result = RUNTIME_STATE.get("agent_team_last_result", {})

    return {
        "ok": True,
        "status": status,
        "current_task": current_task,
        "last_result": last_result,
    }

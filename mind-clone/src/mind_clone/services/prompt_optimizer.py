"""
DSPy-style automatic prompt optimisation.

Based on Stanford DSPy (Declarative Self-improving Python) — treats prompts
as code that can be compiled and optimised, not just written once and forgotten.

KEY INSIGHT: Instead of manually tuning Bob's tool descriptions and reasoning
instructions, let Bob measure what's working and automatically improve his own
prompts based on real usage data.

How it works:
1. Track which tool calls succeed vs fail (already in ToolPerformanceLog)
2. Periodically identify prompts/instructions that correlate with failures
3. Use LLM to propose improved versions
4. A/B test: run improved version, measure, keep if better

Simpler than full DSPy (no gradient-based optimization) but same principle:
prompts are optimizable artifacts, not fixed text.

Proven result: GEPA optimizer took GPT-4.1 Mini from 46.6% → 56.6% on AIME 2025
just from prompt optimisation alone.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from ..database.models import ToolPerformanceLog, SelfImprovementNote
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.prompt_optimizer")

# Stored prompt variants (in-memory, persisted to SelfImprovementNote)
_PROMPT_STORE: dict[str, str] = {}
_BASELINE_TOOL_HINTS: dict[str, str] = {
    "search_web": "Search the web for current information. Use specific, focused queries.",
    "read_webpage": "Read and extract content from a URL. Provide the exact URL.",
    "save_research_note": "Save findings as a research note with topic, summary, sources, and tags.",
    "run_command": "Execute a shell command. Be precise and safe.",
    "execute_python": "Run Python code. Use for calculations, data processing, file operations.",
    "schedule_job": "Create a recurring scheduled job to run a task automatically.",
    "recall_skill": "Search Bob's skill library before starting complex tasks.",
    "save_skill": "Save a completed approach as a reusable skill after task completion.",
    "run_experiment": "Run the nightly self-improvement experiment loop.",
    "memory_graph_search": "Traverse the memory graph to find related knowledge.",
}


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

def get_tool_metrics(db: Session, owner_id: int, days: int = 7) -> list[dict]:
    """Get success/failure rates per tool over recent period."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            ToolPerformanceLog.tool_name,
            sqlfunc.count(ToolPerformanceLog.id).label("total"),
            sqlfunc.sum(ToolPerformanceLog.success).label("successes"),
            sqlfunc.avg(ToolPerformanceLog.duration_ms).label("avg_ms"),
        )
        .filter(
            ToolPerformanceLog.owner_id == owner_id,
            ToolPerformanceLog.created_at >= since,
        )
        .group_by(ToolPerformanceLog.tool_name)
        .having(sqlfunc.count(ToolPerformanceLog.id) >= 3)
        .order_by(sqlfunc.avg(ToolPerformanceLog.success).asc())
        .all()
    )
    return [
        {
            "tool": r.tool_name,
            "total_calls": int(r.total),
            "success_rate": round(float(r.successes or 0) / max(int(r.total), 1), 3),
            "avg_ms": round(float(r.avg_ms or 0), 0),
        }
        for r in rows
    ]


def get_weak_tools(db: Session, owner_id: int, threshold: float = 0.7) -> list[dict]:
    """Get tools with success rate below threshold."""
    metrics = get_tool_metrics(db, owner_id)
    return [m for m in metrics if m["success_rate"] < threshold]


# ---------------------------------------------------------------------------
# Prompt optimisation via LLM
# ---------------------------------------------------------------------------

def optimise_tool_hint(
    tool_name: str,
    current_hint: str,
    failure_examples: list[str],
) -> Optional[str]:
    """Use LLM to propose a better tool description/hint.

    Returns improved hint, or None if no improvement found.
    """
    from ..agent.llm import call_llm

    if not failure_examples:
        return None

    prompt = [
        {
            "role": "user",
            "content": (
                f"You are optimising an AI agent's tool usage instructions.\n\n"
                f"Tool: {tool_name}\n"
                f"Current description: {current_hint}\n\n"
                f"This tool has been failing. Recent failure reasons:\n"
                + "\n".join(f"- {e}" for e in failure_examples[:5])
                + "\n\nWrite an improved 1-2 sentence description for this tool that would help "
                f"the AI use it correctly and avoid these failures. "
                f"Be specific and actionable. Return ONLY the new description, nothing else."
            ),
        }
    ]

    try:
        result = call_llm(prompt, temperature=0.3)
        improved = ""
        if isinstance(result, dict) and result.get("ok"):
            improved = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                improved = choices[0].get("message", {}).get("content", improved)
        elif isinstance(result, str):
            improved = result

        improved = improved.strip()
        if improved and len(improved) > 20 and improved != current_hint:
            return truncate_text(improved, 300)
    except Exception as e:
        logger.debug("OPTIMISE_HINT_FAIL tool=%s err=%s", tool_name, str(e)[:80])

    return None


# ---------------------------------------------------------------------------
# Store and retrieve optimised hints
# ---------------------------------------------------------------------------

def save_optimised_hint(
    db: Session,
    owner_id: int,
    tool_name: str,
    old_hint: str,
    new_hint: str,
    success_rate_before: float,
) -> None:
    """Persist an optimised prompt hint as a SelfImprovementNote."""
    note = SelfImprovementNote(
        owner_id=owner_id,
        title=f"Optimised hint: {tool_name}",
        summary=f"OPTIMISED_HINT::{tool_name}::{new_hint}",
        actions_json=json.dumps([f"Use improved hint for {tool_name}"]),
        evidence_json=json.dumps({
            "tool": tool_name,
            "old_hint": old_hint[:200],
            "new_hint": new_hint[:200],
            "success_rate_before": success_rate_before,
            "source": "prompt_optimizer",
        }),
        priority="medium",
        status="open",
    )
    db.add(note)
    db.commit()
    _PROMPT_STORE[tool_name] = new_hint
    logger.info("PROMPT_OPTIMISED tool=%s", tool_name)


def load_optimised_hints(db: Session, owner_id: int) -> dict[str, str]:
    """Load previously optimised hints from DB into memory store."""
    rows = (
        db.query(SelfImprovementNote)
        .filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.summary.like("OPTIMISED_HINT::%"),
            SelfImprovementNote.status == "open",
        )
        .order_by(SelfImprovementNote.id.desc())
        .limit(50)
        .all()
    )
    hints = {}
    for row in rows:
        try:
            parts = row.summary.split("::", 2)
            if len(parts) == 3:
                tool_name = parts[1]
                hint = parts[2]
                if tool_name not in hints:  # keep most recent
                    hints[tool_name] = hint
        except Exception:
            pass
    _PROMPT_STORE.update(hints)
    return hints


def get_hint_for_tool(tool_name: str) -> Optional[str]:
    """Get the current (possibly optimised) hint for a tool."""
    return _PROMPT_STORE.get(tool_name) or _BASELINE_TOOL_HINTS.get(tool_name)


# ---------------------------------------------------------------------------
# Full optimisation run
# ---------------------------------------------------------------------------

def run_prompt_optimisation(db: Session, owner_id: int = 1) -> dict:
    """Run a full prompt optimisation pass.

    Finds weak tools, proposes improved hints, saves them.
    Called periodically (e.g. weekly) or manually via tool.
    """
    weak = get_weak_tools(db, owner_id, threshold=0.7)
    if not weak:
        return {"ok": True, "message": "All tools performing well, no optimisation needed.", "optimised": 0}

    optimised = []
    for tool_info in weak[:3]:  # max 3 per run
        tool_name = tool_info["tool"]
        current_hint = _BASELINE_TOOL_HINTS.get(tool_name, f"Use the {tool_name} tool.")

        # Get recent error categories for this tool
        recent_errors = (
            db.query(ToolPerformanceLog.error_category)
            .filter(
                ToolPerformanceLog.owner_id == owner_id,
                ToolPerformanceLog.tool_name == tool_name,
                ToolPerformanceLog.success == 0,
                ToolPerformanceLog.error_category.isnot(None),
            )
            .order_by(ToolPerformanceLog.id.desc())
            .limit(10)
            .all()
        )
        failure_examples = [r.error_category for r in recent_errors if r.error_category]

        new_hint = optimise_tool_hint(tool_name, current_hint, failure_examples)
        if new_hint:
            save_optimised_hint(db, owner_id, tool_name, current_hint, new_hint,
                              tool_info["success_rate"])
            optimised.append({"tool": tool_name, "success_rate_before": tool_info["success_rate"]})

    return {
        "ok": True,
        "weak_tools_found": len(weak),
        "optimised": len(optimised),
        "details": optimised,
    }


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------

def tool_optimise_prompts(args: dict) -> dict:
    """Tool: Run prompt optimisation to improve Bob's tool usage hints."""
    owner_id = int(args.get("_owner_id", 1))
    db = SessionLocal()
    try:
        # Load existing optimised hints first
        load_optimised_hints(db, owner_id)
        return run_prompt_optimisation(db, owner_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Inject optimised hints into system prompt (called from loop)
# ---------------------------------------------------------------------------

def build_tool_hints_block(db: Session, owner_id: int) -> str:
    """Build a system message block with optimised tool hints.

    Only returns hints for tools that have been optimised (better than baseline).
    Keeps context lean.
    """
    optimised = load_optimised_hints(db, owner_id)
    if not optimised:
        return ""
    lines = ["[OPTIMISED TOOL HINTS] Use these improved descriptions:"]
    for tool, hint in list(optimised.items())[:5]:  # max 5 to keep context lean
        lines.append(f"• {tool}: {hint}")
    return "\n".join(lines)

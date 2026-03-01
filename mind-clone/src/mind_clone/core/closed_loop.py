"""
Closed Loop Feedback Engine (Section 5B).

Six feedback loops that make Bob adapt from experience.
Feature-flagged with CLOSED_LOOP_ENABLED (default: True).

Loops:
  1+6  cl_filter_tools_by_performance  - Warn/block/reorder tools by success rate
  2    cl_track_lesson_usage           - Track if LLM references injected lessons
  3    cl_close_improvement_notes      - Mark notes applied/dismissed based on usage
  4    cl_adjust_for_forecast_confidence - Adjust task steps on low confidence
  5    cl_check_dead_letter_pattern    - Block strategies that fail 3+ times in 7 days

Serves Pillar 4 (Learning), Pillar 6 (Self-Awareness).
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func

from ..config import (
    CLOSED_LOOP_ENABLED,
    CLOSED_LOOP_TOOL_WARN_THRESHOLD,
    CLOSED_LOOP_TOOL_BLOCK_THRESHOLD,
    CLOSED_LOOP_TOOL_MIN_CALLS,
    CLOSED_LOOP_NOTE_MAX_RETRIEVALS,
    CLOSED_LOOP_DEAD_LETTER_BLOCK_COUNT,
    CLOSED_LOOP_FORECAST_LOW_CONFIDENCE,
)
from ..core.state import RUNTIME_STATE
from ..core.tools import get_tool_performance_stats
from ..database.session import SessionLocal
from ..database.models import SelfImprovementNote, TaskDeadLetter, MemoryVector
from ..agent.vectors import get_embedding, embedding_to_bytes
from ..utils import truncate_text

log = logging.getLogger("mind_clone")

__all__ = [
    "cl_filter_tools_by_performance",
    "cl_track_lesson_usage",
    "cl_close_improvement_notes",
    "cl_adjust_for_forecast_confidence",
    "cl_check_dead_letter_pattern",
    "_validate_owner_id",
    "_validate_confidence_value",
    "_safe_increment_counter",
]


# ---------------------------------------------------------------------------
# Defensive helpers - validators and boundary checks
# ---------------------------------------------------------------------------

def _validate_owner_id(owner_id: int | None) -> bool:
    """Check if owner_id is valid (non-None, positive integer)."""
    if owner_id is None:
        return False
    try:
        return None
    except (ValueError, TypeError):
        return False


def _validate_confidence_value(confidence: int) -> int:
    """Validate and bound confidence value to [0, 100]."""
    try:
        val = int(confidence)
        return max(0, min(100, val))
    except (ValueError, TypeError):
        return 50  # Default to neutral


def _safe_increment_counter(key: str, amount: int = 1) -> None:
    """Safely increment a RUNTIME_STATE counter (type-safe, bounds-safe)."""
    try:
        current = int(RUNTIME_STATE.get(key, 0))
        # Prevent unbounded growth
        RUNTIME_STATE[key] = min(current + amount, 999999)
    except (ValueError, TypeError):
        RUNTIME_STATE[key] = amount


def _truncate_for_reason(text: str | None, max_len: int = 100) -> str:
    """Safely truncate reason/text to max length."""
    if text is None:
        return None
    try:
        s = str(text)
        return s[:max_len]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Loop 1+6: Filter / reorder tools by performance
# ---------------------------------------------------------------------------

def cl_filter_tools_by_performance(tool_defs: list[dict], owner_id: int | None) -> list[dict]:
    """Loop 1+6: Warn/block/reorder tools based on success rate."""
    if not CLOSED_LOOP_ENABLED or not owner_id:
        return tool_defs
    stats = get_tool_performance_stats(owner_id, days=7)
    # stats returns {"tools": {"name": {"calls": N, "success_rate": X}}, ...}
    tools_dict = stats.get("tools", {}) if isinstance(stats, dict) else {}
    stats_map = {
        name: info for name, info in tools_dict.items()
        if info.get("calls", 0) >= CLOSED_LOOP_TOOL_MIN_CALLS
    }
    if not stats_map:
        return tool_defs

    filtered: list[dict] = []
    for td in tool_defs:
        name = (td.get("function") or {}).get("name", "")
        perf = stats_map.get(name)
        if perf:
            # success_rate is 0.0-1.0 from get_tool_performance_stats;
            # thresholds are 0-100 (percentage), so multiply to convert.
            rate_pct = perf["success_rate"] * 100
            if rate_pct < CLOSED_LOOP_TOOL_BLOCK_THRESHOLD:
                RUNTIME_STATE["cl_tools_blocked"] = int(RUNTIME_STATE.get("cl_tools_blocked", 0)) + 1
                log.info("CL_TOOL_BLOCKED tool=%s rate=%.0f%%", name, rate_pct)
                continue  # Remove from available tools
            if rate_pct < CLOSED_LOOP_TOOL_WARN_THRESHOLD:
                td = copy.deepcopy(td)
                desc = td["function"].get("description", "")
                td["function"]["description"] = f"[WARNING: {rate_pct:.0f}% success rate] {desc}"
                RUNTIME_STATE["cl_tools_warned"] = int(RUNTIME_STATE.get("cl_tools_warned", 0)) + 1
        filtered.append(td)

    # Loop 6: Reorder — high-performing tools appear first (LLMs prefer earlier tools)
    def _tool_sort_key(td: dict) -> float:
        name = (td.get("function") or {}).get("name", "")
        perf = stats_map.get(name)
        if perf:
            return -perf["success_rate"]  # Higher rate → earlier
        return -0.50  # Unknown tools get neutral position

    filtered.sort(key=_tool_sort_key)
    return filtered


# ---------------------------------------------------------------------------
# Loop 2: Track lesson usage
# ---------------------------------------------------------------------------

def cl_track_lesson_usage(lessons: list[str], response_text: str, owner_id: int) -> None:
    """Loop 2: Check if LLM actually referenced injected lessons."""
    if not CLOSED_LOOP_ENABLED or not lessons or not response_text:
        return
    response_lower = response_text.lower()
    for lesson in lessons:
        words = lesson.lower().split()
        key_phrases = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
        matched = any(phrase in response_lower for phrase in key_phrases[:5])
        if matched:
            RUNTIME_STATE["cl_lessons_used"] = int(RUNTIME_STATE.get("cl_lessons_used", 0)) + 1
        else:
            RUNTIME_STATE["cl_lessons_ignored"] = int(RUNTIME_STATE.get("cl_lessons_ignored", 0)) + 1
    RUNTIME_STATE["cl_loops_closed_total"] = int(RUNTIME_STATE.get("cl_loops_closed_total", 0)) + 1


# ---------------------------------------------------------------------------
# Loop 3: Close improvement notes
# ---------------------------------------------------------------------------

def cl_close_improvement_notes(notes: list[str], response_text: str, owner_id: int) -> None:
    """Loop 3: Mark improvement notes as applied or dismissed based on LLM usage."""
    if not CLOSED_LOOP_ENABLED or not notes or not response_text:
        return
    response_lower = response_text.lower()
    db = SessionLocal()
    try:
        for note_text in notes:
            preview = (note_text or "")[:80]
            if not preview:
                continue
            note_row = db.query(SelfImprovementNote).filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.status == "open",
                SelfImprovementNote.summary.contains(preview),
            ).first()
            if not note_row:
                continue

            # Check if response references the note's action items
            actions = json.loads(note_row.actions_json or "[]")
            action_text = " ".join(str(a) for a in actions).lower()
            action_words = action_text.split()
            key_phrases = [" ".join(action_words[i:i + 3]) for i in range(len(action_words) - 2)]
            matched = any(phrase in response_lower for phrase in key_phrases[:5])

            retrieval_count = int(note_row.retrieval_count or 0) + 1
            note_row.retrieval_count = retrieval_count

            if matched:
                note_row.status = "applied"
                RUNTIME_STATE["cl_notes_applied"] = int(RUNTIME_STATE.get("cl_notes_applied", 0)) + 1
                log.info("CL_NOTE_APPLIED note_id=%d title=%s", note_row.id, (note_row.title or "")[:60])
            elif retrieval_count >= CLOSED_LOOP_NOTE_MAX_RETRIEVALS:
                note_row.status = "dismissed"
                RUNTIME_STATE["cl_notes_dismissed"] = int(RUNTIME_STATE.get("cl_notes_dismissed", 0)) + 1
                log.info(
                    "CL_NOTE_DISMISSED note_id=%d title=%s retrievals=%d",
                    note_row.id, (note_row.title or "")[:60], retrieval_count,
                )
        db.commit()
    except Exception as e:
        log.debug("CL_NOTE_CLOSE_FAIL: %s", e)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Loop 4: Adjust for forecast confidence
# ---------------------------------------------------------------------------

def cl_adjust_for_forecast_confidence(confidence: int, step: dict) -> dict:
    """Loop 4: Modify execution strategy based on forecast confidence."""
    if not CLOSED_LOOP_ENABLED:
        return None
    if confidence < CLOSED_LOOP_FORECAST_LOW_CONFIDENCE:
        step["title"] = f"[LOW CONFIDENCE: {confidence}%] {step.get('title', '')}"
        step["_retry_budget_multiplier"] = 2
        RUNTIME_STATE["cl_forecasts_adjusted"] = int(RUNTIME_STATE.get("cl_forecasts_adjusted", 0)) + 1
        log.info("CL_FORECAST_ADJUSTED confidence=%d step=%s", confidence, str(step.get("title", ""))[:60])
    return step


# ---------------------------------------------------------------------------
# Loop 5: Dead letter pattern detection
# ---------------------------------------------------------------------------

def cl_check_dead_letter_pattern(db, owner_id: int, reason: str, task) -> None:
    """Loop 5: Block strategies that repeatedly fail (dead letter patterns)."""
    if not CLOSED_LOOP_ENABLED:
        return
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        reason_prefix = (reason or "")[:100]
        if not reason_prefix:
            return
        similar_count = db.query(func.count(TaskDeadLetter.id)).filter(
            TaskDeadLetter.owner_id == int(owner_id),
            TaskDeadLetter.reason.contains(reason_prefix),
            TaskDeadLetter.created_at >= cutoff,
        ).scalar() or 0

        if similar_count >= CLOSED_LOOP_DEAD_LETTER_BLOCK_COUNT:
            blocked_note = (
                f"BLOCKED STRATEGY: Task '{task.title}' has failed {similar_count}x "
                f"with reason: '{reason[:200]}'. Do NOT retry this approach. "
                "Try a fundamentally different strategy."
            )
            note = SelfImprovementNote(
                owner_id=int(owner_id),
                title=f"Blocked: {truncate_text(task.title, 100)}",
                summary=blocked_note,
                actions_json=json.dumps([
                    "Use alternative approach",
                    "Break into smaller steps",
                    "Skip if non-critical",
                ]),
                evidence_json=json.dumps({
                    "dead_letters": similar_count,
                    "reason": reason[:200],
                }),
                priority="critical",
                status="open",
            )
            db.add(note)
            emb = get_embedding(blocked_note)
            if emb is not None and np.linalg.norm(emb) > 1e-9:
                db.add(MemoryVector(
                    owner_id=int(owner_id),
                    memory_type="self_improvement_note",
                    ref_id=0,
                    text_preview=truncate_text(blocked_note, 200),
                    embedding=embedding_to_bytes(emb),
                ))
            RUNTIME_STATE["cl_strategies_blocked"] = int(RUNTIME_STATE.get("cl_strategies_blocked", 0)) + 1
            log.warning(
                "CL_STRATEGY_BLOCKED owner=%d task=%s reason=%s count=%d",
                int(owner_id), str(task.title)[:60], reason[:100], similar_count,
            )
    except Exception as e:
        log.debug("CL_DEAD_LETTER_PATTERN_FAIL: %s", e)

"""
Smart context engineering engine.

Dynamically decides what information to inject into Bob's context based on
task phase, message complexity, and relevance scoring.

Pillar: Reasoning, Memory
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mind_clone.core.context_engine")


# ---------------------------------------------------------------------------
# Task phases
# ---------------------------------------------------------------------------

class TaskPhase(Enum):
    """Phases of task execution."""
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    RESPONDING = "responding"


_PLAN_KEYWORDS = re.compile(
    r"\b(plan|steps?|first|second|third|approach|strategy|let me think|break down)\b",
    re.IGNORECASE,
)

_REVIEW_KEYWORDS = re.compile(
    r"\b(check|verify|test|result|output|error|success|passed|failed|review)\b",
    re.IGNORECASE,
)


def detect_task_phase(messages: List[dict], tool_loops: int) -> TaskPhase:
    """Infer the current task phase from message history and tool loop count."""
    if tool_loops == 0:
        # Check if last assistant message contains planning language
        for msg in reversed(messages[-5:]):
            if msg.get("role") == "assistant":
                content = str(msg.get("content", ""))
                if _PLAN_KEYWORDS.search(content):
                    _track("context_phase_detections")
                    return TaskPhase.PLANNING
                break
        _track("context_phase_detections")
        return TaskPhase.UNDERSTANDING

    # Check recent messages for review signals
    recent_tool_results = 0
    recent_tool_calls = 0
    for msg in messages[-10:]:
        if msg.get("role") == "tool":
            recent_tool_results += 1
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            recent_tool_calls += 1

    if tool_loops > 2 and recent_tool_results > 0 and recent_tool_calls == 0:
        _track("context_phase_detections")
        return TaskPhase.REVIEWING

    if tool_loops > 0:
        # Check if last assistant message has review keywords
        for msg in reversed(messages[-3:]):
            if msg.get("role") == "assistant":
                content = str(msg.get("content", ""))
                if _REVIEW_KEYWORDS.search(content) and not msg.get("tool_calls"):
                    _track("context_phase_detections")
                    return TaskPhase.RESPONDING
                break
        _track("context_phase_detections")
        return TaskPhase.EXECUTING

    _track("context_phase_detections")
    return TaskPhase.UNDERSTANDING


# ---------------------------------------------------------------------------
# Context budgets per phase
# ---------------------------------------------------------------------------

_PHASE_BUDGETS: Dict[TaskPhase, Dict[str, int]] = {
    TaskPhase.UNDERSTANDING: {"lessons": 4, "summaries": 2, "artifacts": 0, "episodes": 1, "notes": 0, "world": 3},
    TaskPhase.PLANNING:      {"lessons": 3, "summaries": 4, "artifacts": 2, "episodes": 3, "notes": 2, "world": 2},
    TaskPhase.EXECUTING:     {"lessons": 2, "summaries": 1, "artifacts": 5, "episodes": 1, "notes": 3, "world": 0},
    TaskPhase.REVIEWING:     {"lessons": 3, "summaries": 2, "artifacts": 3, "episodes": 4, "notes": 2, "world": 1},
    TaskPhase.RESPONDING:    {"lessons": 3, "summaries": 3, "artifacts": 2, "episodes": 2, "notes": 1, "world": 1},
}

_COMPLEXITY_MULTIPLIERS = {"simple": 0.3, "normal": 1.0, "complex": 1.5}


def compute_context_budget(phase: TaskPhase, complexity: str = "normal") -> Dict[str, int]:
    """Compute per-type context item limits based on phase and complexity."""
    base = _PHASE_BUDGETS.get(phase, _PHASE_BUDGETS[TaskPhase.UNDERSTANDING])
    multiplier = _COMPLEXITY_MULTIPLIERS.get(complexity, 1.0)
    return {k: max(0, math.ceil(v * multiplier)) for k, v in base.items()}


# ---------------------------------------------------------------------------
# Context priority
# ---------------------------------------------------------------------------

class ContextPriority(IntEnum):
    """Priority levels for context items."""
    BACKGROUND = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5


# Priority mapping for context types
_TYPE_PRIORITIES: Dict[str, ContextPriority] = {
    "system_prompt": ContextPriority.CRITICAL,
    "recent_messages": ContextPriority.HIGH,
    "tool_results": ContextPriority.HIGH,
    "lessons": ContextPriority.MEDIUM,
    "summaries": ContextPriority.MEDIUM,
    "artifacts": ContextPriority.MEDIUM,
    "episodes": ContextPriority.LOW,
    "notes": ContextPriority.LOW,
    "world": ContextPriority.BACKGROUND,
}


# ---------------------------------------------------------------------------
# Context window manager
# ---------------------------------------------------------------------------

@dataclass
class _ContextItem:
    priority: ContextPriority
    label: str
    text: str
    chars: int = 0

    def __post_init__(self):
        self.chars = len(self.text)


class ContextWindow:
    """Priority-aware context window manager."""

    def __init__(self, max_chars: int = 80000):
        self.max_chars = max_chars
        self._items: List[_ContextItem] = []
        self._used_chars: int = 0

    def remaining(self) -> int:
        """Remaining character budget."""
        return max(0, self.max_chars - self._used_chars)

    def can_fit(self, text: str) -> bool:
        """Check if text fits in remaining budget."""
        return len(text) <= self.remaining()

    def add(self, text: str, priority: ContextPriority, label: str) -> bool:
        """Add an item to the context window.

        Returns True if added, False if no space (even after compaction).
        """
        chars = len(text)
        if chars > self.remaining():
            freed = self.compact()
            if chars > self.remaining():
                return False

        item = _ContextItem(priority=priority, label=label, text=text)
        self._items.append(item)
        self._used_chars += chars
        return True

    def compact(self) -> int:
        """Evict lowest-priority items to free ~20% of window. Returns chars freed."""
        if not self._items:
            return 0

        target_free = int(self.max_chars * 0.2)
        freed = 0

        # Sort by priority ascending (lowest first for eviction)
        self._items.sort(key=lambda x: x.priority)

        while self._items and freed < target_free:
            item = self._items[0]
            if item.priority >= ContextPriority.HIGH:
                break  # Don't evict HIGH or CRITICAL
            self._items.pop(0)
            freed += item.chars
            self._used_chars -= item.chars
            _track("context_evictions")

        return freed

    def get_content(self) -> str:
        """Get all context items joined, highest priority first."""
        sorted_items = sorted(self._items, key=lambda x: -x.priority)
        return "\n\n".join(f"[{item.label}]\n{item.text}" for item in sorted_items)

    @property
    def item_count(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------

def rank_context_items(items: List[str], query: str) -> List[Tuple[str, float]]:
    """Score and rank context items by relevance to query.

    Returns list of (item, score) sorted by score descending.
    """
    if not items or not query:
        return [(item, 0.0) for item in items]

    query_words = set(query.lower().split())
    scored: List[Tuple[str, float]] = []

    for item in items:
        item_words = set(item.lower().split())
        if not item_words:
            scored.append((item, 0.0))
            continue
        overlap = len(query_words & item_words)
        union = len(query_words | item_words)
        score = overlap / union if union > 0 else 0.0
        scored.append((item, score))
        _track("context_items_ranked")

    scored.sort(key=lambda x: -x[1])
    return scored


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_smart_context(
    db: Any,
    owner_id: int,
    user_message: str,
    messages: List[dict],
    tool_loops: int = 0,
    complexity: str = "normal",
) -> Dict[str, Any]:
    """Build smart context injection based on task phase and relevance.

    This is the upgraded replacement for loop.py's _inject_context.

    Returns:
        Dict with injected metadata for closed-loop tracking.
    """
    phase = detect_task_phase(messages, tool_loops)
    budget = compute_context_budget(phase, complexity)

    injected: Dict[str, Any] = {"phase": phase.value, "lessons": [], "notes": []}

    window = ContextWindow(max_chars=80000)
    context_parts: List[str] = []

    # Retrieve and inject each context type based on budget
    if budget.get("lessons", 0) > 0:
        try:
            from ..agent.memory import retrieve_relevant_lessons
            lessons = retrieve_relevant_lessons(db, owner_id, user_message, top_k=budget["lessons"])
            if lessons:
                ranked = rank_context_items(lessons, user_message)
                top_lessons = [item for item, score in ranked[:budget["lessons"]]]
                injected["lessons"] = top_lessons
                text = "[LESSONS]\n" + "\n".join(f"- {l}" for l in top_lessons)
                window.add(text, _TYPE_PRIORITIES.get("lessons", ContextPriority.MEDIUM), "LESSONS")
        except Exception:
            pass

    if budget.get("summaries", 0) > 0:
        try:
            from ..agent.memory import get_conversation_summaries
            summaries = get_conversation_summaries(db, owner_id, limit=budget["summaries"])
            if summaries:
                parts = [s.get("summary", "") for s in summaries if s.get("summary")]
                if parts:
                    text = "[CONTEXT]\n" + "\n".join(parts[:budget["summaries"]])
                    window.add(text, _TYPE_PRIORITIES.get("summaries", ContextPriority.MEDIUM), "CONTEXT")
        except Exception:
            pass

    if budget.get("artifacts", 0) > 0:
        try:
            from ..agent.memory import retrieve_relevant_artifacts
            artifacts = retrieve_relevant_artifacts(db, owner_id, user_message, top_k=budget["artifacts"])
            if artifacts:
                ranked = rank_context_items(artifacts, user_message)
                top = [item for item, _ in ranked[:budget["artifacts"]]]
                text = "[ARTIFACTS]\n" + "\n".join(f"- {a}" for a in top)
                window.add(text, _TYPE_PRIORITIES.get("artifacts", ContextPriority.MEDIUM), "ARTIFACTS")
        except Exception:
            pass

    if budget.get("episodes", 0) > 0:
        try:
            from ..agent.memory import retrieve_relevant_episodes
            episodes = retrieve_relevant_episodes(db, owner_id, user_message, top_k=budget["episodes"])
            if episodes:
                text = "[EPISODES]\n" + "\n".join(f"- {e}" for e in episodes)
                window.add(text, _TYPE_PRIORITIES.get("episodes", ContextPriority.LOW), "EPISODES")
        except Exception:
            pass

    if budget.get("notes", 0) > 0:
        try:
            from ..agent.memory import retrieve_improvement_notes
            notes = retrieve_improvement_notes(db, owner_id, user_message, top_k=budget["notes"])
            if notes:
                injected["notes"] = notes
                text = "[NOTES]\n" + "\n".join(f"- {n}" for n in notes)
                window.add(text, _TYPE_PRIORITIES.get("notes", ContextPriority.LOW), "NOTES")
        except Exception:
            pass

    if budget.get("world", 0) > 0:
        try:
            from ..agent.memory import retrieve_world_model
            world = retrieve_world_model(db, owner_id, user_message, top_k=budget["world"])
            if world:
                text = "[WORLD]\n" + "\n".join(f"- {w}" for w in world)
                window.add(text, _TYPE_PRIORITIES.get("world", ContextPriority.BACKGROUND), "WORLD")
        except Exception:
            pass

    # Inject into messages
    content = window.get_content()
    if content:
        messages.append({
            "role": "system",
            "content": f"[SMART CONTEXT — Phase: {phase.value}]\n\n{content}",
        })
        try:
            from ..core.state import increment_runtime_state
            increment_runtime_state("context_injections_total")
        except Exception:
            pass

    injected["items_injected"] = window.item_count
    injected["chars_used"] = window.max_chars - window.remaining()
    return injected


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _track(key: str) -> None:
    try:
        from ..core.state import increment_runtime_state
        increment_runtime_state(key)
    except Exception:
        pass

"""Smart Context Engine — keeps important messages full, compresses casual chat.

This module is the MAIN context engine.  It includes:
  - Message compression with importance-aware summarisation  [original]
  - Phase-based context injection (TaskPhase, ContextWindow) [merged from core/context_engine]

Before each LLM call, this engine builds an optimized context window:
1. Recent messages (last N) — kept fully intact
2. Important messages (any age) — kept fully intact:
   - Tool calls and tool results
   - User corrections ("no", "wrong", "actually", "I meant")
   - Messages with code or structured output
   - Long messages (>500 chars)
3. Everything else — compressed into 1-2 sentence summaries per batch of 5
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Dict, List, Tuple

from ..agent.llm import call_llm
from ..agent.memory import get_conversation_history

logger = logging.getLogger("mind_clone.services.context_engine")

# Patterns that indicate a user correction — must be case-insensitive
_CORRECTION_PATTERNS: list[str] = [
    "no,",
    "no ",
    "wrong",
    "actually,",
    "actually ",
    "i meant",
    "not what i",
    "incorrect",
    "try again",
    "that's not",
]

# Compiled regex that matches any correction pattern at the start of content
_CORRECTION_RE = re.compile(
    "|".join(re.escape(p) for p in _CORRECTION_PATTERNS),
    re.IGNORECASE,
)


def is_important_message(msg: dict[str, Any]) -> bool:
    """Determine whether a message should be kept in full.

    Returns True if the message contains tool calls, tool results,
    user corrections, code blocks, or is longer than 500 characters.

    Args:
        msg: A single message dict with at least ``role`` and ``content`` keys.

    Returns:
        True if the message is considered important.
    """
    role = msg.get("role", "")
    content = str(msg.get("content", ""))

    # Tool-related messages are always important
    if role == "tool":
        return True
    if msg.get("tool_calls"):
        return True
    if msg.get("tool_call_id"):
        return True

    # Long messages are likely substantive
    if len(content) > 500:
        return True

    # User corrections are critical context
    if role == "user" and _CORRECTION_RE.search(content):
        return True

    # Messages containing code fences
    if "```" in content:
        return True

    return False


def compress_messages(
    messages: list[dict[str, Any]],
    keep_recent: int = 10,
) -> list[dict[str, Any]]:
    """Compress a message list using smart importance-aware summarisation.

    Keeps the last ``keep_recent`` messages fully intact.  Among older
    messages, any message flagged as important is also kept in full.
    The remaining old messages are batched into groups of 5 and each
    group is summarised into a 1-2 sentence system note via a cheap
    LLM call.

    Args:
        messages: Full chronological message list (no system prompt).
        keep_recent: Number of most-recent messages to always keep.

    Returns:
        A new list with recent and important messages intact and
        compressed summaries replacing casual older messages.
    """
    if len(messages) <= keep_recent:
        return list(messages)

    recent = messages[-keep_recent:]
    older = messages[:-keep_recent]

    # Partition older messages into important (kept) and compressible
    important: list[dict[str, Any]] = []
    compressible: list[dict[str, Any]] = []

    for msg in older:
        if is_important_message(msg):
            important.append(msg)
        else:
            compressible.append(msg)

    # Compress compressible messages in batches of 5
    summaries: list[dict[str, Any]] = []
    batch_size = 5
    for i in range(0, len(compressible), batch_size):
        batch = compressible[i : i + batch_size]
        summary_text = _summarise_batch(batch)
        summaries.append({
            "role": "system",
            "content": f"[Context summary] {summary_text}",
        })

    # Assemble: summaries first, then important old messages, then recent
    result = summaries + important + recent
    logger.info(
        "Context compressed: %d msgs -> %d (kept %d important, %d summaries, %d recent)",
        len(messages),
        len(result),
        len(important),
        len(summaries),
        len(recent),
    )
    return result


def _summarise_batch(batch: list[dict[str, Any]]) -> str:
    """Summarise a batch of messages into 1-2 sentences via a cheap LLM call.

    Falls back to a simple concatenation if the LLM call fails.

    Args:
        batch: A list of message dicts to summarise.

    Returns:
        A short summary string.
    """
    transcript_lines: list[str] = []
    for msg in batch:
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))[:300]
        if content.strip():
            transcript_lines.append(f"[{role}] {content}")

    transcript = "\n".join(transcript_lines)
    if not transcript.strip():
        return "No substantive content."

    try:
        result = call_llm(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize these conversation messages in 1-2 sentences. "
                        "Focus on key decisions and topics discussed."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            temperature=0.3,
        )
        if result.get("ok") and result.get("content"):
            return str(result["content"]).strip()
    except Exception as exc:
        logger.warning("Batch summarisation LLM call failed: %s", exc)

    # Fallback: first 200 chars of concatenated content
    fallback = " | ".join(
        str(m.get("content", ""))[:60] for m in batch if m.get("content")
    )
    return fallback[:200] or "General conversation."


def build_smart_context(
    db: Any,
    owner_id: int,
    recent_limit: int = 10,
) -> list[dict[str, Any]]:
    """Main entry point — load all messages and return optimised context.

    Loads the full conversation history from the database, applies
    smart compression (keeping recent and important messages, summarising
    the rest), and returns a list ready to be prepended with the system
    prompt and sent to the LLM.

    Args:
        db: SQLAlchemy Session instance.
        owner_id: The owner whose conversation to load.
        recent_limit: Number of most-recent messages to always keep in full.

    Returns:
        Optimised message list (without system prompt).
    """
    try:
        # Load ALL messages (high limit) so we can compress intelligently
        all_messages = get_conversation_history(db, owner_id, limit=9999)

        if not all_messages:
            return []

        compressed = compress_messages(all_messages, keep_recent=recent_limit)
        logger.info(
            "Smart context built for owner %d: %d raw -> %d compressed",
            owner_id,
            len(all_messages),
            len(compressed),
        )
        return compressed

    except Exception as exc:
        logger.error(
            "build_smart_context failed for owner %d, falling back to simple: %s",
            owner_id,
            exc,
        )
        # Fallback to simple recent-only history
        return get_conversation_history(db, owner_id, limit=recent_limit)


# ===========================================================================
# Phase-based context injection (merged from core/context_engine.py)
# ===========================================================================
# Dynamically decides what information to inject into Bob's context based
# on task phase, message complexity, and relevance scoring.
# ===========================================================================

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
        for msg in reversed(messages[-5:]):
            if msg.get("role") == "assistant":
                content = str(msg.get("content", ""))
                if _PLAN_KEYWORDS.search(content):
                    return TaskPhase.PLANNING
                break
        return TaskPhase.UNDERSTANDING

    recent_tool_results = 0
    recent_tool_calls = 0
    for msg in messages[-10:]:
        if msg.get("role") == "tool":
            recent_tool_results += 1
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            recent_tool_calls += 1

    if tool_loops > 2 and recent_tool_results > 0 and recent_tool_calls == 0:
        return TaskPhase.REVIEWING

    if tool_loops > 0:
        for msg in reversed(messages[-3:]):
            if msg.get("role") == "assistant":
                content = str(msg.get("content", ""))
                if _REVIEW_KEYWORDS.search(content) and not msg.get("tool_calls"):
                    return TaskPhase.RESPONDING
                break
        return TaskPhase.EXECUTING

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

        self._items.sort(key=lambda x: x.priority)

        while self._items and freed < target_free:
            item = self._items[0]
            if item.priority >= ContextPriority.HIGH:
                break
            self._items.pop(0)
            freed += item.chars
            self._used_chars -= item.chars

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

    scored.sort(key=lambda x: -x[1])
    return scored

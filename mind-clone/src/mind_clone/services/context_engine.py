"""Smart Context Engine — keeps important messages full, compresses casual chat.

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
import re
from typing import Any

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

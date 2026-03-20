"""
Adaptive Context Compression — keep context lean and focused.

As conversations grow, context fills with old turns that dilute attention.
This compressor:
1. Detects when context is getting too large
2. Summarises older turns into a compact digest
3. Keeps recent turns verbatim (most relevant)
4. Preserves system messages always

Based on Anthropic context engineering:
"Context rot: as tokens increase, model ability to recall decreases"
Goal: smallest possible set of high-signal tokens.
"""
from __future__ import annotations
import logging
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.context_compressor")

_TOKEN_THRESHOLD = 12000   # chars (~3000 tokens) before compression kicks in
_KEEP_RECENT_TURNS = 6     # always keep last N turns verbatim
_SUMMARY_MAX_CHARS = 400


def _estimate_chars(messages: list) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def _summarise_old_turns(turns: list) -> str:
    """Summarise old conversation turns into a compact digest."""
    from ..agent.llm import call_llm
    text = "\n".join(
        f"{m.get('role','?')}: {str(m.get('content',''))[:200]}"
        for m in turns
        if m.get("role") in ("user", "assistant")
    )
    if not text.strip():
        return ""
    prompt = [{"role": "user", "content":
        f"Summarise this conversation history in 3-4 sentences. "
        f"Keep: decisions made, key facts learned, tasks completed.\n\n{text[:2000]}"}]
    try:
        result = call_llm(prompt, temperature=0.2)
        summary = ""
        if isinstance(result, dict) and result.get("ok"):
            summary = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                summary = choices[0].get("message", {}).get("content", summary)
        elif isinstance(result, str):
            summary = result
        return truncate_text(summary.strip(), _SUMMARY_MAX_CHARS)
    except Exception:
        # Fallback: simple truncation summary
        lines = [m.get("content", "")[:80] for m in turns[-5:] if m.get("role") == "user"]
        return "Previous topics: " + "; ".join(lines[:3])


def compress_context(messages: list) -> list:
    """Compress messages if context is too large.

    Returns compressed message list.
    Preserves system messages + recent turns, summarises old ones.
    """
    total_chars = _estimate_chars(messages)
    if total_chars < _TOKEN_THRESHOLD:
        return messages  # No compression needed

    # Separate system messages from conversation
    system_msgs = [m for m in messages if m.get("role") == "system"]
    conv_msgs = [m for m in messages if m.get("role") != "system"]

    if len(conv_msgs) <= _KEEP_RECENT_TURNS:
        return messages  # Too few turns to compress

    # Split: old turns to summarise + recent turns to keep
    old_turns = conv_msgs[:-_KEEP_RECENT_TURNS]
    recent_turns = conv_msgs[-_KEEP_RECENT_TURNS:]

    summary = _summarise_old_turns(old_turns)

    compressed = system_msgs.copy()
    if summary:
        compressed.append({
            "role": "system",
            "content": f"[CONVERSATION SUMMARY] Earlier in this session: {summary}",
        })
    compressed.extend(recent_turns)

    new_chars = _estimate_chars(compressed)
    logger.info(
        "CONTEXT_COMPRESSED old=%d new=%d turns_summarised=%d",
        total_chars, new_chars, len(old_turns),
    )
    return compressed

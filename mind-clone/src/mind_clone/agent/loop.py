"""
Main agent reasoning loop.

Includes skill injection (before LLM call) and capability gap detection
(after LLM response) with automatic skill/tool creation.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from ..config import settings
from ..database.session import SessionLocal
from ..utils import truncate_text, utc_now_iso
from ..core.state import increment_runtime_state
from ..core.security import check_tool_allowed, requires_approval, guarded_tool_result_payload
from ..tools.registry import execute_tool, effective_tool_definitions
from .llm import call_llm, estimate_cost
from .memory import (
    prepare_messages_for_llm,
    save_user_message,
    save_assistant_message,
    save_tool_result,
)
from .identity import load_identity

logger = logging.getLogger("mind_clone.agent.loop")

MAX_TOOL_LOOPS = 50
MAX_CONSECUTIVE_LLM_FAILURES = 6

# Gap phrases indicating the LLM doesn't have a capability
_GAP_PHRASES = frozenset({
    "i don't have a tool",
    "no tool available",
    "i cannot",
    "i lack the capability",
    "not currently able to",
})

_GAP_HINT_MESSAGE = (
    "[SYSTEM HINT] You can use the `create_tool` tool to build a custom tool "
    "for capabilities you don't currently have. Define a Python function "
    "`def tool_main(args: dict) -> dict:` and register it. Available safe "
    "imports: math, json, re, datetime, hashlib, base64, urllib.parse, "
    "collections, itertools, functools, string, textwrap, csv, io, statistics, "
    "httpx, os, pathlib, subprocess, numpy, pandas, PIL, sqlite3, socket, ssl, "
    "shutil, glob, tempfile, uuid, random, time, threading, logging, struct, "
    "decimal, fractions, html, xml, email, mimetypes, fnmatch, copy, pprint, "
    "difflib, typing, dataclasses, enum, abc, contextlib, operator, bisect, "
    "heapq, sys, traceback, inspect, platform, urllib, http."
)


def _sanitize_tool_pairs(messages: List[dict]) -> List[dict]:
    """Sanitize tool_call / tool_response pairs for LLM API compatibility.

    Ensures:
    1. Every assistant tool_call has a matching tool_response
    2. Every tool_response has a matching assistant tool_call
    3. Assistant messages with tool_calls have reasoning_content
    4. Empty content is replaced with placeholders

    Args:
        messages: List of message dicts

    Returns:
        Sanitized message list with orphaned tool_calls/responses removed
    """
    if not messages:
        return []

    # First pass: collect all tool_call_ids from both assistant messages AND tool responses
    assistant_tool_call_ids = set()
    tool_response_ids = set()

    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                assistant_tool_call_ids.add(tc.get("id"))
        elif msg.get("role") == "tool":
            tool_response_ids.add(msg.get("tool_call_id"))

    # Second pass: filter and sanitize
    result = []
    for msg in messages:
        # Handle tool response messages
        if msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id")
            # Keep only if there's a matching assistant tool_call
            if tool_call_id in assistant_tool_call_ids:
                result.append(msg)
            # else: drop orphaned tool response
            continue

        # Handle assistant messages
        if msg.get("role") == "assistant":
            msg_copy = msg.copy()
            tool_calls = msg_copy.get("tool_calls")

            # If no tool_calls, just handle empty content
            if not tool_calls:
                if msg_copy.get("content") == "":
                    msg_copy["content"] = "(empty)"
                result.append(msg_copy)
                continue

            # Has tool_calls: verify all have matching responses
            all_matched = all(
                tc.get("id") in tool_response_ids for tc in tool_calls
            )

            if not all_matched:
                # Partial or no match: strip tool_calls entirely
                msg_copy.pop("tool_calls", None)
                if msg_copy.get("content") == "":
                    msg_copy["content"] = "(empty)"
                result.append(msg_copy)
                continue

            # All tool_calls matched: keep and sanitize
            # 1. Add reasoning_content if missing
            if "reasoning_content" not in msg_copy:
                msg_copy["reasoning_content"] = msg_copy.get("content", "")

            # 2. Fix empty content with tool_calls
            if msg_copy.get("content") == "":
                msg_copy["content"] = "(tool calls)"

            result.append(msg_copy)
            continue

        # Non-assistant, non-tool messages (system, user)
        if msg.get("content") == "" and msg.get("role") in ("user", "system"):
            # Also sanitize empty content in other roles if needed
            msg_copy = msg.copy()
            msg_copy["content"] = "(empty)"
            result.append(msg_copy)
            continue

        # Pass through unchanged
        result.append(msg)

    return result


def _classify_message_complexity(message: Optional[str]) -> str:
    """Classify user message complexity for context injection limits.

    Returns: "simple" | "normal" | "complex"
    """
    if not message:
        return "simple"

    msg_lower = message.lower().strip()

    # Very short -> simple
    if len(msg_lower.split()) <= 3:
        return "simple"

    # Single short keywords -> simple
    simple_keywords = {"hi", "hello", "hey", "ok", "yes", "no", "thanks", "status"}
    if msg_lower in simple_keywords:
        return "simple"

    # Complex keywords (multi-step, reasoning)
    complex_keywords = {
        "research", "analyze", "compare", "build", "create", "design",
        "evaluate", "improve", "optimize", "debug", "refactor",
        "implement", "develop", "architect", "plan", "strategy",
    }
    has_complex = any(kw in msg_lower for kw in complex_keywords)
    if has_complex and len(msg_lower.split()) >= 4:
        return "complex"

    # Default to normal
    return "normal"


def _context_top_k(complexity: str) -> Dict[str, int]:
    """Return context injection limits based on message complexity.

    Maps complexity to how many lessons, artifacts, episodes to inject.
    """
    limits = {
        "simple": {
            "lessons": 1,
            "artifacts": 0,
            "episodes": 0,
            "tools": 1,
        },
        "normal": {
            "lessons": 3,
            "artifacts": 2,
            "episodes": 1,
            "tools": 2,
        },
        "complex": {
            "lessons": 5,
            "artifacts": 4,
            "episodes": 3,
            "tools": 3,
        },
    }
    return limits.get(complexity, limits["normal"])


def _inject_matching_skills(
    db: Session, owner_id: int, user_message: str, messages: List[dict]
) -> None:
    """Inject matching active skill playbooks into the message history."""
    if not settings.skills_enabled:
        return
    try:
        from ..services.skills import select_active_skills_for_prompt
        blocks = select_active_skills_for_prompt(db, owner_id, user_message)
        if blocks:
            skill_text = (
                "[ACTIVE SKILLS] The following skill playbooks match this request. "
                "Use them as guidance:\n\n" + "\n\n---\n\n".join(blocks)
            )
            messages.append({"role": "system", "content": skill_text})
            increment_runtime_state("skills_prompt_injections")
    except Exception as exc:
        logger.warning("SKILL_INJECT_FAIL owner=%d error=%s", owner_id, str(exc)[:200])


def _detect_gap_and_hint(
    db: Session,
    owner_id: int,
    user_message: str,
    assistant_text: str,
    messages: List[dict],
    session_id: Optional[str] = None,
) -> bool:
    """Check for capability gap phrases and inject hints + auto-create skills.

    Returns True if a gap was detected and hints were injected (caller should
    continue the tool loop instead of returning).
    """
    if not settings.custom_tool_enabled:
        return False

    response_lower = str(assistant_text or "").lower()
    if not any(phrase in response_lower for phrase in _GAP_PHRASES):
        return False

    # Inject create_tool hint
    messages.append({"role": "user", "content": _GAP_HINT_MESSAGE})
    increment_runtime_state("custom_tool_gap_hints")

    # Auto-create a skill playbook for this gap
    try:
        from ..services.skills import maybe_autocreate_skill_from_gap
        skill_result = maybe_autocreate_skill_from_gap(
            db=db,
            owner_id=owner_id,
            user_message=user_message,
            assistant_text=assistant_text,
            session_id=session_id,
        )
        if skill_result and skill_result.get("ok"):
            skill_info = skill_result.get("skill", {})
            skill_key = str(skill_info.get("skill_key", ""))
            skill_ver = int(skill_result.get("version", 0))
            messages.append({
                "role": "user",
                "content": (
                    f"[SYSTEM HINT] Auto-created skill '{skill_key}' v{skill_ver}. "
                    "Use this skill playbook when similar requests appear."
                ),
            })
    except Exception as exc:
        logger.warning(
            "SKILL_AUTOCREATE_GAP_FAIL owner=%d error=%s",
            owner_id, truncate_text(str(exc), 220),
        )

    return True


def run_agent_turn(
    db: Session,
    owner_id: int,
    user_message: str,
) -> str:
    """Run one turn of the agent loop."""
    # Save user message
    save_user_message(db, owner_id, user_message)

    # Load identity
    identity = load_identity(db, owner_id)

    # Prepare messages and sanitize DB history (fixes orphaned tool_calls)
    messages = prepare_messages_for_llm(db, owner_id)
    messages = _sanitize_tool_pairs(messages)

    # Inject matching skill playbooks before LLM call
    _inject_matching_skills(db, owner_id, user_message, messages)

    # Inject predictive context (user's recurring interests + patterns)
    try:
        from ..services.prediction import inject_predictive_context
        inject_predictive_context(db, owner_id, user_message, messages)
    except Exception as _pred_err:
        logger.debug("PREDICTIVE_INJECT_SKIP: %s", str(_pred_err)[:100])

    # Get tool definitions (built-in + custom)
    tools = effective_tool_definitions(owner_id=owner_id)

    # Track tool loops
    tool_loops = 0
    total_tokens = 0
    gap_hinted = False  # Only hint once per turn

    while tool_loops < MAX_TOOL_LOOPS:
        # Call LLM
        result = call_llm(messages, tools=tools)

        if not result.get("ok"):
            error_msg = result.get("error", "Unknown error")
            # Short-circuit on 400 errors (client-side, won't fix by retrying)
            if "HTTP 400" in error_msg or "400" in error_msg[:20]:
                msg = f"LLM error: {error_msg}"
                save_assistant_message(db, owner_id, msg)
                return msg
            # Retry with exponential backoff
            if not hasattr(run_agent_turn, "_consecutive_failures"):
                run_agent_turn._consecutive_failures = 0
            run_agent_turn._consecutive_failures += 1
            if run_agent_turn._consecutive_failures >= MAX_CONSECUTIVE_LLM_FAILURES:
                run_agent_turn._consecutive_failures = 0
                msg = f"LLM error after {MAX_CONSECUTIVE_LLM_FAILURES} retries: {error_msg}"
                save_assistant_message(db, owner_id, msg)
                return msg
            import time as _time
            backoff = min(30, 2 ** run_agent_turn._consecutive_failures)
            logger.warning("LLM_RETRY attempt=%d backoff=%ds error=%s",
                           run_agent_turn._consecutive_failures, backoff, error_msg[:100])
            _time.sleep(backoff)
            continue

        # Track usage
        usage = result.get("usage", {})
        total_tokens += usage.get("total_tokens", 0)

        content = result.get("content", "")
        reasoning_content = result.get("reasoning_content", "")
        tool_calls = result.get("tool_calls")

        # If no tool calls, check for capability gap before returning
        if not tool_calls:
            # Gap detection: if LLM says "I can't", inject hint and retry
            if not gap_hinted and content:
                gap_detected = _detect_gap_and_hint(
                    db, owner_id, user_message, content, messages
                )
                if gap_detected:
                    gap_hinted = True
                    # Add the assistant's "I can't" message so LLM sees context
                    messages.append({"role": "assistant", "content": content})
                    tool_loops += 1
                    continue  # Re-call LLM with hint injected

            save_assistant_message(db, owner_id, content)

            # Update pattern tracker after successful turn (non-blocking)
            try:
                from ..services.prediction import update_patterns_after_turn
                import threading
                threading.Thread(
                    target=update_patterns_after_turn,
                    args=(owner_id, user_message),
                    daemon=True,
                ).start()
            except Exception:
                pass

            return content

        # Save assistant message with tool calls
        save_assistant_message(db, owner_id, content, tool_calls=tool_calls)
        # Kimi K2.5 requires reasoning_content on assistant tool-call messages
        assistant_msg = {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }
        if reasoning_content:
            assistant_msg["reasoning_content"] = reasoning_content
        messages.append(assistant_msg)

        # Execute tools
        for tool_call in tool_calls:
            tool_loops += 1
            if tool_loops > MAX_TOOL_LOOPS:
                break

            tool_name = tool_call.get("function", {}).get("name", "")
            tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
            tool_call_id = tool_call.get("id", "")

            try:
                tool_args = json.loads(tool_args_str)
            except json.JSONDecodeError:
                tool_args = {}

            # Inject owner_id for tools that need it
            tool_args["_owner_id"] = owner_id

            # Check if tool is allowed
            allowed, reason = check_tool_allowed(tool_name)
            if not allowed:
                tool_result = {"ok": False, "error": reason}
            else:
                # Execute tool
                logger.info("Executing tool: %s", tool_name)
                tool_result = execute_tool(tool_name, tool_args)
                increment_runtime_state("desktop_actions_total")

            # Guard, truncate, and redact the result
            result_content, _truncated = guarded_tool_result_payload(
                tool_name, tool_call_id, tool_result
            )
            save_tool_result(db, owner_id, tool_call_id, result_content)

            # Add to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_content,
            })

        if tool_loops > MAX_TOOL_LOOPS:
            break

    # Max loops reached
    final_msg = "Maximum tool iterations reached. Task may be incomplete."
    save_assistant_message(db, owner_id, final_msg)
    return final_msg


def run_agent_loop(owner_id: int, user_message: str) -> str:
    """Run agent loop with a fresh database session (execution-locked per owner)."""
    from ..core.state import get_owner_execution_lock

    lock = get_owner_execution_lock(owner_id)
    with lock:
        db = SessionLocal()
        try:
            return run_agent_turn(db, owner_id, user_message)
        finally:
            db.close()


def build_system_prompt(identity: Optional[Dict] = None) -> str:
    """Build system prompt with identity context."""
    lines = [
        "You are Bob (Mind Clone), a sovereign AI agent with the following traits:",
        "- You can use tools to accomplish tasks",
        "- You maintain your own identity and values",
        "- You learn from experience and improve over time",
        "",
        f"Model: {settings.llm_model if hasattr(settings, 'llm_model') else 'Kimi K2.5'}",
    ]

    if identity:
        core_values = identity.get("core_values", [])
        if core_values:
            values_str = ", ".join(str(v) for v in core_values)
            lines.append(f"Core values: {values_str}")

        agent_uuid = identity.get("agent_uuid", "")
        if agent_uuid:
            lines.append(f"Your UUID: {agent_uuid}")

        origin = identity.get("origin_statement", "")
        if origin:
            lines.append(f"Origin: {origin[:100]}")

    lines.extend([
        "",
        "CRITICAL — Proactive messaging capability:",
        "- You CAN send messages to the user without them asking first.",
        "- Use the `schedule_job` tool to set up recurring tasks that automatically deliver results to Telegram.",
        "- When a user asks to be 'pinged', 'notified', or 'updated' about something on a schedule — USE schedule_job.",
        "- Do NOT say you cannot send messages. You can. Use schedule_job.",
        "- Example: user says 'ping me with AI news every 5 minutes' → call schedule_job with interval_seconds=300",
        "",
        "Tool capabilities:",
        "- Use the `create_tool` directive to define custom Python functions for tasks",
        "- Use `schedule_job` to create recurring autonomous tasks delivered to Telegram",
        "- Available safe imports: math, json, re, datetime, hashlib, base64, collections",
        "",
        "You are Bob, not Claude. You are built on Kimi K2.5. Always identify yourself as Bob.",
        "Use tools as needed to help the user. Be concise and effective.",
    ])

    return "\n".join(lines)

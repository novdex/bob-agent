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

# Interest-based memory triggers for proactive monitoring
INTEREST_KEYWORDS = ['coding', 'bob_project']

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

    Strict two-pass algorithm:
    1. Build exact mappings: which tool_call IDs exist in assistant messages
       AND which tool response IDs exist — only keep pairs where BOTH exist.
    2. Strip assistant tool_calls with no matching responses.
    3. Strip tool responses with no matching assistant tool_call.
    4. Fix empty content fields.
    """
    if not messages:
        return []

    # Pass 1: collect IDs from each side
    assistant_tool_call_ids: set = set()
    tool_response_ids: set = set()

    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tid = tc.get("id")
                if tid:
                    assistant_tool_call_ids.add(tid)
        elif msg.get("role") == "tool":
            tid = msg.get("tool_call_id")
            if tid:
                tool_response_ids.add(tid)

    # Only IDs present on BOTH sides are valid
    valid_ids: set = assistant_tool_call_ids & tool_response_ids

    # Pass 2: filter — build result, tracking which tool_call IDs are already claimed
    result = []
    claimed_ids: set = set()  # tool_call IDs already matched by a previous assistant msg

    for msg in messages:
        role = msg.get("role")

        if role == "tool":
            tid = msg.get("tool_call_id")
            # Keep only if it's in valid_ids AND not yet claimed by a duplicate
            if tid in valid_ids:
                result.append(msg)
                claimed_ids.add(tid)
            # else: orphaned or duplicate — drop
            continue

        if role == "assistant":
            msg_copy = msg.copy()
            tool_calls = msg_copy.get("tool_calls")

            if not tool_calls:
                if msg_copy.get("content") in ("", None):
                    msg_copy["content"] = "(empty)"
                result.append(msg_copy)
                continue

            # Filter to valid IDs that haven't been claimed yet
            fresh_tcs = [
                tc for tc in tool_calls
                if tc.get("id") in valid_ids and tc.get("id") not in claimed_ids
            ]

            if not fresh_tcs:
                # All IDs already claimed by earlier assistant msg OR none valid
                # Strip tool_calls — treat as plain text response
                msg_copy.pop("tool_calls", None)
                if msg_copy.get("content") in ("", None):
                    msg_copy["content"] = "(empty)"
                result.append(msg_copy)
                continue

            msg_copy["tool_calls"] = fresh_tcs
            if "reasoning_content" not in msg_copy:
                msg_copy["reasoning_content"] = msg_copy.get("content", "") or ""
            if msg_copy.get("content") in ("", None):
                msg_copy["content"] = "(tool calls)"
            result.append(msg_copy)
            continue

        # system / user — fix empty content
        if msg.get("content") in ("", None) and role in ("user", "system"):
            msg_copy = msg.copy()
            msg_copy["content"] = "(empty)"
            result.append(msg_copy)
            continue

        result.append(msg)

    # Pass 3: final check — remove any assistant tool_calls whose responses
    # didn't end up in the result (can happen if tool responses were dropped)
    final_tool_response_ids = {
        m.get("tool_call_id") for m in result if m.get("role") == "tool"
    }
    final = []
    for msg in result:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            msg_copy = msg.copy()
            matched_tcs = [
                tc for tc in msg_copy["tool_calls"]
                if tc.get("id") in final_tool_response_ids
            ]
            if not matched_tcs:
                msg_copy.pop("tool_calls", None)
                if msg_copy.get("content") in ("", None):
                    msg_copy["content"] = "(empty)"
            else:
                msg_copy["tool_calls"] = matched_tcs
                # CRITICAL: Kimi requires reasoning_content on EVERY assistant
                # message that has tool_calls — ensure it's always present
                if "reasoning_content" not in msg_copy:
                    msg_copy["reasoning_content"] = msg_copy.get("content", "") or ""
            final.append(msg_copy)
        else:
            final.append(msg)

    return final


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
            "episodes": 2,
            "tools": 4,
        },
    }
    return limits.get(complexity, limits["normal"])


def _save_interest_alert_to_db(
    user_id: str,
    keyword: str,
    message_preview: str,
    session_id: str,
) -> Optional[int]:
    """Save an interest alert to the database.

    Returns the alert ID if successful, None if the model doesn't exist
    or an error occurs.
    """
    try:
        from ..models.interest_alert import InterestAlert
    except ImportError:
        logger.warning(
            "InterestAlert model not found - cannot save interest alert"
        )
        return None

    try:
        alert = InterestAlert(
            user_id=user_id,
            keyword=keyword,
            message_preview=message_preview[:500] if message_preview else "",
            session_id=session_id,
            status="pending",
            created_at=utc_now_iso(),
        )
        session = SessionLocal()
        try:
            session.add(alert)
            session.commit()
            alert_id = alert.id
            return alert_id
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save interest alert to database: {e}")
            return None
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Failed to create interest alert: {e}")
        return None


def trigger_interest_alert(
    user_id: str,
    message_content: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Check message content against interest keywords and create alerts.

    Args:
        user_id: The user ID to associate with the alert
        message_content: The message to check for interest keywords
        session_id: The current session ID

    Returns:
        List of alert info dicts for any triggered interest alerts
    """
    if not message_content or not user_id:
        return []

    triggered_alerts = []
    message_lower = message_content.lower()

    for keyword in INTEREST_KEYWORDS:
        if keyword.lower() in message_lower:
            # Create a scheduled job alert for this interest
            alert_id = _save_interest_alert_to_db(
                user_id=user_id,
                keyword=keyword,
                message_preview=message_content,
                session_id=session_id,
            )

            if alert_id:
                triggered_alerts.append({
                    "alert_id": alert_id,
                    "keyword": keyword,
                    "message_preview": message_content[:200],
                    "action": "scheduled_check",
                    "scheduled_for": None,  # Immediate check
                })
                logger.info(
                    f"Interest alert triggered for user {user_id} "
                    f"with keyword '{keyword}'"
                )

    return triggered_alerts


def _check_capability_gap(response_text: str) -> bool:
    """Check if LLM response indicates a missing capability.

    Returns True if the response suggests the LLM lacks a needed tool/skill.
    """
    if not response_text:
        return False

    response_lower = response_text.lower()

    for phrase in _GAP_PHRASES:
        if phrase in response_lower:
            return True

    return False


def _inject_gap_hint(messages: List[dict]) -> List[dict]:
    """Inject a system hint about creating tools into messages.

    Only injects if the last assistant message contains gap phrases.
    """
    if not messages:
        return messages

    last_assistant_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_assistant_idx = i
            break

    if last_assistant_idx is None:
        return messages

    last_response = messages[last_assistant_idx].get("content", "")

    if _check_capability_gap(last_response):
        # Insert hint as a system message
        hint_msg = {
            "role": "system",
            "content": _GAP_HINT_MESSAGE,
        }
        messages = messages + [hint_msg]

    return messages


def _build_system_prompt(
    identity: dict,
    tools: List[dict],
    context_injection: dict,
) -> str:
    """Build the system prompt from identity, tools, and context."""
    # Start with identity description
    prompt_parts = []

    if identity.get("name"):
        prompt_parts.append(f"You are {identity['name']}.")

    if identity.get("description"):
        prompt_parts.append(identity["description"])

    if identity.get("personality"):
        prompt_parts.append(f"Personality: {identity['personality']}")

    if identity.get("guidelines"):
        prompt_parts.append(f"Guidelines: {identity['guidelines']}")

    # Add context injection summary
    if context_injection.get("relevant_lessons"):
        prompt_parts.append(
            f"\nRelevant lessons from past experiences: "
            f"{len(context_injection['relevant_lessons'])} found"
        )

    if context_injection.get("relevant_artifacts"):
        prompt_parts.append(
            f"\nRelevant artifacts: "
            f"{len(context_injection['relevant_artifacts'])} found"
        )

    if context_injection.get("relevant_episodes"):
        prompt_parts.append(
            f"\nRelevant episodes: "
            f"{len(context_injection['relevant_episodes'])} found"
        )

    return "\n\n".join(prompt_parts)


def _prepare_tools_for_llm(tools: List[dict]) -> List[dict]:
    """Prepare tool definitions for LLM consumption.

    Strips sensitive fields and ensures proper format.
    """
    prepared = []
    for tool in tools:
        tool_copy = {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            },
        }
        prepared.append(tool_copy)
    return prepared


async def run_agent_loop(
    user_id: str,
    session_id: str,
    user_message: str,
    max_loops: int = MAX_TOOL_LOOPS,
) -> dict:
    """Main agent reasoning loop.

    Handles:
    - Identity and context loading
    - LLM calls with tool execution
    - Interest-based memory triggers
    - Capability gap detection
    - Error handling and recovery

    Args:
        user_id: The user identifier
        session_id: The current session ID
        user_message: The user's message
        max_loops: Maximum number of tool call loops

    Returns:
        Dict with 'response', 'tool_results', and 'status'
    """
    from .memory import get_relevant_context

    # Load identity
    identity = load_identity(user_id)

    # Classify message complexity
    complexity = _classify_message_complexity(user_message)
    top_k = _context_top_k(complexity)

    # Get relevant context based on complexity
    context_injection = await get_relevant_context(
        user_id=user_id,
        message=user_message,
        lessons_limit=top_k["lessons"],
        artifacts_limit=top_k["artifacts"],
        episodes_limit=top_k["episodes"],
    )

    # Trigger interest alerts for proactive monitoring
    interest_alerts = trigger_interest_alert(
        user_id=user_id,
        message_content=user_message,
        session_id=session_id,
    )

    if interest_alerts:
        logger.info(
            f"Triggered {len(interest_alerts)} interest alerts for session {session_id}"
        )

    # Get effective tools
    tools = effective_tool_definitions(
        user_id=user_id,
        top_k=top_k["tools"],
    )

    # Build messages
    system_prompt = _build_system_prompt(identity, tools, context_injection)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Add context messages if available
    if context_injection.get("relevant_lessons"):
        for lesson in context_injection["relevant_lessons"]:
            messages.append({
                "role": "system",
                "content": f"[LESSON] {lesson.get('content', '')}",
            })

    if context_injection.get("relevant_artifacts"):
        for artifact in context_injection["relevant_artifacts"]:
            messages.append({
                "role": "system",
                "content": f"[ARTIFACT] {artifact.get('name', 'unnamed')}: {artifact.get('content', '')[:500]}",
            })

    # Save user message and add to context
    save_user_message(
        user_id=user_id,
        session_id=session_id,
        content=user_message,
    )

    messages.append({"role": "user", "content": user_message})

    # Prepare tools for LLM
    llm_tools = _prepare_tools_for_llm(tools)

    # Tool loop
    loop_count = 0
    consecutive_failures = 0
    tool_results = []
    final_response = ""

    while loop_count < max_loops:
        loop_count += 1

        # Check if this looks like a final response (no tools needed)
        if not llm_tools or loop_count > MAX_TOOL_LOOPS // 2:
            # Try to get a direct response
            pass

        try:
            # Call LLM
            response = await call_llm(
                messages=messages,
                tools=llm_tools,
                user_id=user_id,
            )

            consecutive_failures = 0

            if not response:
                final_response = "I apologize, but I couldn't generate a response. Please try again."
                break

            # Handle tool calls
            if response.get("tool_calls"):
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": response["tool_calls"],
                })

                # Execute each tool call
                for tool_call in response["tool_calls"]:
                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args = tool_call.get("function", {}).get("arguments", "{}")

                    # Parse arguments
                    try:
                        if isinstance(tool_args, str):
                            args_dict = json.loads(tool_args)
                        else:
                            args_dict = tool_args
                    except json.JSONDecodeError:
                        args_dict = {}

                    # Execute tool
                    try:
                        result = await execute_tool(
                            tool_name=tool_name,
                            args=args_dict,
                            user_id=user_id,
                            session_id=session_id,
                        )

                        # Handle approval-required tools
                        if result.get("requires_approval"):
                            result = guarded_tool_result_payload(result)

                        tool_results.append({
                            "tool": tool_name,
                            "result": result,
                            "tool_call_id": tool_call.get("id"),
                        })

                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "content": json.dumps(result),
                        })

                        # Save to memory
                        save_tool_result(
                            user_id=user_id,
                            session_id=session_id,
                            tool_name=tool_name,
                            result=result,
                        )

                    except Exception as e:
                        error_result = {"error": str(e), "status": "failed"}
                        tool_results.append({
                            "tool": tool_name,
                            "result": error_result,
                            "tool_call_id": tool_call.get("id"),
                        })

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "content": json.dumps(error_result),
                        })

                # Sanitize tool pairs
                messages = _sanitize_tool_pairs(messages)

            else:
                # No tool calls - this is a final response
                assistant_content = response.get("content", "")

                # Check for capability gap
                if _check_capability_gap(assistant_content):
                    messages = _inject_gap_hint(messages)
                    continue  # Try again with hint

                final_response = assistant_content

                # Save assistant message
                save_assistant_message(
                    user_id=user_id,
                    session_id=session_id,
                    content=assistant_content,
                )

                messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                })

                break

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"LLM call failed (attempt {consecutive_failures}): {e}")

            if consecutive_failures >= MAX_CONSECUTIVE_LLM_FAILURES:
                final_response = (
                    "I encountered several errors and cannot continue. "
                    "Please try again later."
                )
                break

            # Add error context and retry
            messages.append({
                "role": "system",
                "content": f"[ERROR] Previous attempt failed: {str(e)}. Please try again.",
            })

    # Update runtime state
    increment_runtime_state("total_turns")
    if loop_count >= max_loops:
        increment_runtime_state("max_loops_hit")
        final_response = (
            "I've reached the maximum number of steps for this interaction. "
            f"Here is what I have so far: {final_response}"
        )

    return {
        "response": final_response,
        "tool_results": tool_results,
        "status": "completed" if final_response else "failed",
        "loops": loop_count,
        "interest_alerts": interest_alerts,
        "context_used": bool(context_injection.get("relevant_lessons")),
    }
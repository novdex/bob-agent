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

MAX_TOOL_LOOPS = 10

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
    "collections, itertools, functools, string, textwrap, csv, io, statistics."
)


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

    # Prepare messages
    messages = prepare_messages_for_llm(db, owner_id)

    # Inject matching skill playbooks before LLM call
    _inject_matching_skills(db, owner_id, user_message, messages)

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
            error_msg = f"LLM error: {result.get('error', 'Unknown error')}"
            save_assistant_message(db, owner_id, error_msg)
            return error_msg

        # Track usage
        usage = result.get("usage", {})
        total_tokens += usage.get("total_tokens", 0)

        content = result.get("content", "")
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
            return content

        # Save assistant message with tool calls
        save_assistant_message(db, owner_id, content, tool_calls=tool_calls)
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        })

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
        "You are Mind Clone, a sovereign AI agent with the following traits:",
        "- You can use tools to accomplish tasks",
        "- You maintain your own identity and values",
        "- You learn from experience and improve over time",
    ]

    if identity:
        lines.append(f"\nYour UUID: {identity.get('agent_uuid', 'Unknown')}")
        lines.append(f"Origin: {identity.get('origin_statement', 'Unknown')[:100]}")

    lines.append("\nUse tools as needed to help the user. Be concise and effective.")

    return "\n".join(lines)

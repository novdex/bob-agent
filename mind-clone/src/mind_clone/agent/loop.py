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

    # -----------------------------------------------------------------------
    # FAST PATH: Simple messages skip heavy context injection.
    # "hi" responds in ~5s instead of ~30s.
    # -----------------------------------------------------------------------
    _simple_exact = {
        "hi", "hello", "hey", "hlo", "hola", "yo", "sup",
        "ok", "okay", "k", "sure", "yes", "no", "yep", "nope", "yeah", "nah",
        "thanks", "thank you", "thx", "ty", "cheers",
        "bye", "goodbye", "see you", "later", "gn", "good night",
        "good morning", "gm", "good evening",
        "how are you", "how r u", "whats up", "what's up", "wassup",
        "nice", "cool", "great", "awesome", "perfect", "got it",
        "lol", "haha", "hehe", "lmao", "hmm", "hm", "oh", "ah", "wow",
    }
    _msg_lower = user_message.strip().lower().rstrip("!?.,:;")
    _is_simple = _msg_lower in _simple_exact
    if not _is_simple and len(_msg_lower) < 15:
        _tool_kw = {"search", "research", "find", "run", "create", "write",
                     "read", "check", "schedule", "spawn", "execute", "analyze",
                     "build", "fix", "deploy", "test", "show", "list", "delete"}
        _is_simple = not any(kw in _msg_lower for kw in _tool_kw)

    if _is_simple:
        logger.info("FAST_PATH message='%s'", user_message[:30])
        messages = prepare_messages_for_llm(db, owner_id)
        messages = _sanitize_tool_pairs(messages)
        result = call_llm(messages)
        if result.get("ok") and result.get("content"):
            response = result["content"]
            save_assistant_message(db, owner_id, response)
            return response
    # -----------------------------------------------------------------------

    # Load identity
    identity = load_identity(db, owner_id)

    # Prepare messages and sanitize DB history (fixes orphaned tool_calls)
    messages = prepare_messages_for_llm(db, owner_id)
    messages = _sanitize_tool_pairs(messages)

    # -----------------------------------------------------------------------
    # SAFE INJECTION PATTERN
    # All context injections must go BEFORE the conversation history to avoid
    # breaking Kimi's strict tool_call/tool_response ordering rules.
    # We collect all system injections into a buffer, then insert them at
    # position 1 (after the main system prompt, before conversation history).
    # -----------------------------------------------------------------------
    _injections: List[dict] = []
    # Closed-loop feedback tracking: capture injected lessons/notes so we can
    # check if the LLM actually referenced them in its response (loops 2+3).
    _injected_lessons: list[str] = []
    _injected_notes: list[str] = []

    def _add_injection(content: str) -> None:
        """Add a system message to the pre-history injection buffer."""
        if content and content.strip():
            _injections.append({"role": "system", "content": content})

    # -----------------------------------------------------------------------
    # PARALLEL CONTEXT INJECTION — run all 12 systems concurrently.
    # -----------------------------------------------------------------------
    import concurrent.futures as _cf
    import time as _time
    _inj_t0 = _time.monotonic()

    def _inj_reasoning():
        try:
            from .reasoning import select_reasoning_strategy, build_reasoning_prefix, track_reasoning_metrics
            s = select_reasoning_strategy(user_message)
            p = build_reasoning_prefix(s, user_message)
            if p: track_reasoning_metrics(s)
            return p
        except Exception: return None

    def _inj_skills():
        try:
            from ..services.skills import select_active_skills_for_prompt
            b = select_active_skills_for_prompt(db, owner_id, user_message, top_k=3)
            return "[SKILL PLAYBOOKS]\n" + "\n\n".join(b) if b else None
        except Exception: return None

    def _inj_prediction():
        try:
            from ..services.prediction import get_predictive_context_block
            return get_predictive_context_block(db, owner_id, user_message)
        except Exception: return None

    def _inj_recall():
        try:
            from .recall import get_recall_context_block
            return get_recall_context_block(db, owner_id, user_message)
        except Exception: return None

    def _inj_profile():
        try:
            from ..services.user_profile import get_profile_context_block
            return get_profile_context_block(owner_id)
        except Exception: return None

    def _inj_world():
        try:
            from ..services.world_model import get_world_context_block
            return get_world_context_block(owner_id)
        except Exception: return None

    def _inj_jitrl():
        try:
            from ..services.jit_rl import get_jit_examples_block
            return get_jit_examples_block(owner_id, user_message)
        except Exception: return None

    def _inj_episodes():
        try:
            from .episodes import recall_similar_episodes
            eps = recall_similar_episodes(owner_id, user_message, limit=3)
            if not eps: return None
            lines = []
            for ep in eps:
                o = "+" if ep["outcome"] == "success" else "-" if ep["outcome"] == "failure" else "?"
                lines.append(f"[{o}] {ep['situation'][:120]} | {ep['action_taken'][:120]} | {ep['outcome']}")
            return "[EPISODIC MEMORY]\n" + "\n".join(lines)
        except Exception: return None

    def _inj_reflexion():
        try:
            from ..services.reflexion import get_reflexion_block
            return get_reflexion_block(db, owner_id, user_message)
        except Exception: return None

    def _inj_dspy():
        try:
            from ..services.prompt_optimizer import build_tool_hints_block
            return build_tool_hints_block(db, owner_id)
        except Exception: return None

    def _inj_planner():
        try:
            from ..services.planner import get_plan_block
            return get_plan_block(user_message)
        except Exception: return None

    def _inj_tot():
        try:
            from ..services.tree_of_thoughts import get_tot_block
            return get_tot_block(user_message)
        except Exception: return None

    _inj_fns = [
        _inj_reasoning, _inj_skills, _inj_prediction, _inj_recall,
        _inj_profile, _inj_world, _inj_jitrl, _inj_episodes,
        _inj_reflexion, _inj_dspy, _inj_planner, _inj_tot,
    ]
    with _cf.ThreadPoolExecutor(max_workers=8) as _pool:
        _futs = {_pool.submit(fn): fn.__name__ for fn in _inj_fns}
        try:
            for _f in _cf.as_completed(_futs, timeout=20):
                try:
                    _r = _f.result(timeout=5)
                    if _r:
                        _add_injection(_r)
                        if _futs[_f] == "_inj_reflexion":
                            _injected_lessons.append(_r)
                except Exception:
                    pass
        except _cf.TimeoutError:
            # Collect whatever finished, skip the rest
            for _f, _n in _futs.items():
                if _f.done():
                    try:
                        _r = _f.result(timeout=0)
                        if _r and _r not in [i.get("content") for i in _injections]:
                            _add_injection(_r)
                    except Exception:
                        pass
            logger.warning("PARALLEL_INJECT_TIMEOUT — proceeding with partial context")

    logger.info("PARALLEL_INJECT count=%d elapsed=%.1fs", len(_injections), _time.monotonic() - _inj_t0)

    # Insert all injections at position 1 (after system prompt, before history)
    if _injections:
        messages = [messages[0]] + _injections + messages[1:]

    # Inject relevant episodic memories (past similar situations)
    try:
        from .episodes import recall_similar_episodes
        episodes = recall_similar_episodes(owner_id, user_message, limit=3)
        if episodes:
            ep_lines = []
            for ep in episodes:
                outcome_emoji = "✅" if ep["outcome"] == "success" else "❌" if ep["outcome"] == "failure" else "⚠️"
                ep_lines.append(
                    f"{outcome_emoji} Situation: {ep['situation'][:120]} | "
                    f"Action: {ep['action_taken'][:120]} | "
                    f"Outcome: {ep['outcome']}"
                )
            messages.append({
                "role": "system",
                "content": (
                    "[EPISODIC MEMORY] Similar past situations you've handled:\n" +
                    "\n".join(ep_lines) +
                    "\nUse this context to improve your response."
                ),
            })
    except Exception as _ep_err:
        logger.debug("EPISODE_INJECT_SKIP: %s", str(_ep_err)[:100])

    # Adaptive context compression — keep context lean
    try:
        from ..services.context_compressor import compress_context
        messages = compress_context(messages)
    except Exception as _cc_err:
        logger.debug("CONTEXT_COMPRESS_SKIP: %s", str(_cc_err)[:80])

    # Get tool definitions (built-in + custom)
    tools = effective_tool_definitions(owner_id=owner_id)

    # Closed-loop 1+6: filter/reorder tools by historical success rate
    try:
        from ..core.closed_loop import cl_filter_tools_by_performance
        tools = cl_filter_tools_by_performance(tools, owner_id)
    except Exception as _cl_err:
        logger.debug("CL_FILTER_TOOLS_FAIL: %s", str(_cl_err)[:80])

    # Track tool loops
    tool_loops = 0
    total_tokens = 0
    gap_hinted = False  # Only hint once per turn
    _tools_used_this_turn: List[str] = []  # Track tool names for auto-skill creation

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

        # Remap tool_call IDs to UUIDs to prevent duplicate ID collisions
        # Kimi returns short IDs like "search_web:7" which repeat across turns
        if tool_calls:
            import uuid as _uuid
            id_remap = {}
            for tc in tool_calls:
                old_id = tc.get("id", "")
                new_id = f"call_{_uuid.uuid4().hex[:16]}"
                id_remap[old_id] = new_id
                tc["id"] = new_id
            # Also remap in the result so tool execution uses new IDs
            result["tool_calls"] = tool_calls

        # Generator → Verifier → Reviser (DeepMind Aletheia)
        # On first response for complex tasks: verify before acting
        if content and tool_loops == 0 and not tool_calls:
            try:
                from ..services.verifier import maybe_verify
                content = maybe_verify(user_message, content, owner_id)
            except Exception as _vf_err:
                logger.debug("VERIFIER_SKIP: %s", str(_vf_err)[:80])

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

            # Closed-loop 2+3: track lesson/note usage in the LLM response
            try:
                from ..core.closed_loop import cl_track_lesson_usage, cl_close_improvement_notes
                if _injected_lessons:
                    cl_track_lesson_usage(_injected_lessons, content, owner_id)
                if _injected_notes:
                    cl_close_improvement_notes(_injected_notes, content, owner_id)
            except Exception as _cl_err:
                logger.debug("CL_LESSON_TRACK_FAIL: %s", str(_cl_err)[:80])

            # Background tasks after successful turn (non-blocking)
            import threading

            # 0. Reflexion: reflect on task-level failures
            try:
                from ..services.reflexion import reflect_on_task_failure
                threading.Thread(
                    target=reflect_on_task_failure,
                    args=(owner_id, user_message, content),
                    daemon=True,
                ).start()
            except Exception:
                pass

            # 1. Update pattern tracker
            try:
                from ..services.prediction import update_patterns_after_turn
                threading.Thread(
                    target=update_patterns_after_turn,
                    args=(owner_id, user_message),
                    daemon=True,
                ).start()
            except Exception:
                pass

            # 2. Record episodic memory
            try:
                from .episodes import record_episode_from_turn
                threading.Thread(
                    target=record_episode_from_turn,
                    args=(owner_id, user_message, content, messages),
                    daemon=True,
                ).start()
            except Exception:
                pass

            # 3. Learn from corrections — extract permanent lessons
            try:
                from ..services.correction_learner import learn_from_correction
                # Get Bob's previous message (what might have been wrong)
                _prev_bob_msgs = [m for m in messages if m.get("role") == "assistant"]
                _prev_bob = _prev_bob_msgs[-1].get("content", "")[:500] if _prev_bob_msgs else ""
                if _prev_bob:
                    threading.Thread(
                        target=learn_from_correction,
                        args=(owner_id, user_message, _prev_bob),
                        daemon=True,
                    ).start()
            except Exception:
                pass

            # 4. Constitutional AI: self-critique before sending
            try:
                from ..services.constitutional import maybe_review
                content = maybe_review(user_message, content)
            except Exception:
                pass

            # 4. Co-evolving critic
            try:
                from ..services.co_critic import co_critique
                content, _ = co_critique(user_message, content)
            except Exception:
                pass

            # 6. Self-play improvement for opinion/evaluation questions
            try:
                from ..services.self_improve import self_play_improve
                content = self_play_improve(user_message, content)
            except Exception:
                pass

            # 7. Background: update user profile + world model
            try:
                from ..services.user_profile import update_profile_from_turn
                update_profile_from_turn(owner_id, user_message, content)
            except Exception:
                pass
            try:
                from ..services.world_model import update_world_from_turn
                update_world_from_turn(owner_id, user_message, content)
            except Exception:
                pass

            # 8. Bob teaches Bob — store high-quality exchanges
            try:
                import threading
                from ..services.bob_teaches_bob import store_teaching_moment
                threading.Thread(
                    target=store_teaching_moment,
                    args=(owner_id, user_message, content),
                    daemon=True,
                ).start()
            except Exception:
                pass

            # 9. Compress conversation history if it has grown too long
            try:
                from .memory import maybe_compress_history
                threading.Thread(
                    target=maybe_compress_history,
                    args=(owner_id,),
                    daemon=True,
                ).start()
            except Exception:
                pass

            # 10. Auto-create skill from successful tool-heavy turns
            try:
                from ..services.skills import auto_create_skill_from_turn
                if len(_tools_used_this_turn) >= 2:
                    threading.Thread(
                        target=auto_create_skill_from_turn,
                        args=(owner_id, user_message, content, _tools_used_this_turn),
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
                # Track tool usage for auto-skill creation
                _tools_used_this_turn.append(tool_name)

            # Reflexion: reflect on tool failures in background
            if not tool_result.get("ok") and tool_result.get("error"):
                try:
                    from ..services.reflexion import reflect_on_tool_failure
                    reflect_on_tool_failure(
                        owner_id, tool_name, tool_args,
                        str(tool_result.get("error", ""))[:200],
                        user_message,
                    )
                except Exception:
                    pass

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

    # ReAct+Reflect after multi-step tool use
    try:
        from ..services.react_reflect import reflect_after_task
        reflect_after_task(owner_id, user_message, "max loops reached", [])
    except Exception:
        pass

    # Max loops reached
    final_msg = "Maximum tool iterations reached. Task may be incomplete."
    save_assistant_message(db, owner_id, final_msg)
    try:
        from ..services.reflexion import reflect_on_task_failure
        import threading
        threading.Thread(
            target=reflect_on_task_failure,
            args=(owner_id, user_message, final_msg),
            daemon=True,
        ).start()
    except Exception:
        pass
    return final_msg


def run_agent_loop(owner_id: int, user_message: str) -> str:
    """Run agent loop with a fresh database session (execution-locked per owner)."""
    from ..core.state import get_owner_execution_lock

    lock = get_owner_execution_lock(owner_id)
    with lock:
        db = SessionLocal()
        try:
            return run_agent_turn(db, owner_id, user_message)
        except Exception as e:
            db.rollback()
            logger.error("AGENT_LOOP_ERROR owner=%d: %s", owner_id, str(e)[:200])
            return f"Sorry, I encountered an error: {str(e)[:100]}"
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
        "Skill Library (Voyager-style — use this):",
        "- Use `recall_skill` at the START of complex tasks to check if you've solved something similar before.",
        "- Use `save_skill` AFTER successfully completing a non-trivial task to save the approach for future reuse.",
        "- Use `list_skills` to see your full library of learned capabilities.",
        "- Think of skills as your long-term procedural memory — don't reinvent the wheel.",
        "",
        "Reflexion (verbal reinforcement learning):",
        "- Past failures are automatically reflected on and stored as lessons.",
        "- [REFLEXION] blocks in your context contain lessons from past mistakes — follow them.",
        "- When you complete 3 attempts on a failing task, write your own reflection: 'I tried X. Failed because Y. Next time I should Z.'",
        "",
        "You are Bob, not Claude. You are built on Kimi K2.5. Always identify yourself as Bob.",
        "Use tools as needed to help the user. Be concise and effective.",
    ])

    return "\n".join(lines)

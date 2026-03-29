"""
Proactive Intelligence Engine — Bob thinks ahead without being asked.

Three autonomous loops that make Bob genuinely intelligent:

1. auto_respond_to_triggers — scans event triggers and auto-fixes issues
   (run_retro for error spikes, memory cleanup for bloat, improvement notes
   for degraded tools)
2. check_trending_news — searches for breaking AI news, filters through LLM
   for genuine importance, alerts on Telegram
3. generate_smart_suggestions — loads user profile + world model + recent
   activity, asks LLM for 1-2 proactive suggestions

Combined in run_proactive_intelligence() which runs all three as a single
scheduled cycle.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..database.session import SessionLocal
from ..database.models import (
    User,
    SelfImprovementNote,
    EpisodicMemory,
    ConversationMessage,
)

logger = logging.getLogger("mind_clone.services.proactive_intelligence")


# ---------------------------------------------------------------------------
# Helper: send message via Telegram API
# ---------------------------------------------------------------------------


def _send_telegram(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message via Telegram Bot API using httpx.

    Args:
        chat_id: Telegram chat ID to send to.
        text: Message text.
        parse_mode: Telegram parse mode (Markdown or HTML).

    Returns:
        True if sent successfully.
    """
    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        logger.debug("PROACTIVE_INTEL_SKIP no telegram token configured")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("TELEGRAM_SEND_FAIL chat=%s: %s", chat_id, str(exc)[:200])
        return False


def _get_chat_id(owner_id: int) -> Optional[str]:
    """Look up the Telegram chat ID for an owner.

    Args:
        owner_id: Owner to look up.

    Returns:
        Chat ID string, or None if not found.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if user and user.telegram_chat_id:
            return str(user.telegram_chat_id)
        return None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Auto-respond to event triggers
# ---------------------------------------------------------------------------


def auto_respond_to_triggers(owner_id: int) -> Dict[str, Any]:
    """Scan event triggers and auto-fix detected issues.

    Actions per trigger type:
    - error_spike -> run retro analysis to diagnose
    - memory_bloat -> run memory consolidation cleanup
    - tool_degraded -> create a SelfImprovementNote about the degraded tool

    Args:
        owner_id: Owner to scan triggers for.

    Returns:
        Dict with keys: triggers_found, actions_taken, details.
    """
    from .event_triggers import scan_triggers

    actions_taken: List[Dict[str, str]] = []

    try:
        fired = scan_triggers(owner_id)
    except Exception as exc:
        logger.error("TRIGGER_SCAN_FAIL owner=%d: %s", owner_id, exc)
        return {"triggers_found": 0, "actions_taken": 0, "details": [], "error": str(exc)[:300]}

    if not fired:
        logger.debug("TRIGGER_SCAN owner=%d no_triggers_fired", owner_id)
        return {"triggers_found": 0, "actions_taken": 0, "details": []}

    for trigger in fired:
        trigger_type = trigger.get("trigger", "unknown")
        action = trigger.get("action", "")
        message = trigger.get("message", "")

        try:
            if trigger_type == "error_spike" and action == "run_retro":
                # Auto-run retro to diagnose error spike
                from .retro import collect_stats, run_retro_analysis
                db = SessionLocal()
                try:
                    stats = collect_stats(db, owner_id, hours=1)
                finally:
                    db.close()
                run_retro_analysis(stats)
                actions_taken.append({
                    "trigger": trigger_type,
                    "action": "ran_retro_analysis",
                    "detail": message,
                })

            elif trigger_type == "memory_bloat":
                # Auto-run memory consolidation
                from .memory_consolidator import run_full_consolidation
                result = run_full_consolidation(owner_id)
                total_merged = sum(v.get("merged", 0) for v in result.values())
                actions_taken.append({
                    "trigger": trigger_type,
                    "action": "ran_memory_consolidation",
                    "detail": f"Merged {total_merged} duplicate memories",
                })

            elif trigger_type == "tool_degraded":
                # Create a SelfImprovementNote about the degraded tool
                db = SessionLocal()
                try:
                    note = SelfImprovementNote(
                        owner_id=owner_id,
                        title=f"Auto-detected: {trigger_type}",
                        summary=message[:2000],
                        actions_json=json.dumps([
                            "Investigate tool failure patterns",
                            "Check API key validity",
                            "Review recent changes that may have caused degradation",
                        ]),
                        evidence_json=json.dumps(trigger),
                        priority="high",
                        status="open",
                    )
                    db.add(note)
                    db.commit()
                    actions_taken.append({
                        "trigger": trigger_type,
                        "action": "created_improvement_note",
                        "detail": message,
                    })
                except Exception as exc:
                    db.rollback()
                    logger.error("IMPROVEMENT_NOTE_CREATE_FAIL: %s", exc)
                finally:
                    db.close()

            else:
                # Unknown trigger — log but don't act
                logger.info(
                    "TRIGGER_UNHANDLED owner=%d type=%s action=%s",
                    owner_id, trigger_type, action,
                )

        except Exception as exc:
            logger.error(
                "TRIGGER_ACTION_FAIL owner=%d type=%s: %s",
                owner_id, trigger_type, str(exc)[:200],
            )

    logger.info(
        "TRIGGER_RESPONSE owner=%d found=%d acted=%d",
        owner_id, len(fired), len(actions_taken),
    )

    return {
        "triggers_found": len(fired),
        "actions_taken": len(actions_taken),
        "details": actions_taken,
    }


# ---------------------------------------------------------------------------
# 2. Trending AI news check
# ---------------------------------------------------------------------------


def check_trending_news(owner_id: int) -> Dict[str, Any]:
    """Search for breaking AI news and alert if genuinely important.

    Searches the web for recent AI developments, asks the LLM to filter
    for genuinely important items, and sends alerts via Telegram.

    Args:
        owner_id: Owner to send alerts to.

    Returns:
        Dict with keys: searched, important_items, alerted.
    """
    from ..tools.basic import tool_search_web
    from ..agent.llm import call_llm

    search_queries = [
        "breaking AI news today",
        "major AI announcement this week",
        "AGI progress latest developments",
    ]

    all_results: List[str] = []

    for query in search_queries:
        try:
            result = tool_search_web({"query": query, "num_results": 3})
            if result.get("ok") and result.get("results"):
                for item in result["results"]:
                    title = item.get("title", "") if isinstance(item, dict) else str(item)
                    snippet = item.get("snippet", "") if isinstance(item, dict) else ""
                    url = item.get("url", "") if isinstance(item, dict) else ""
                    all_results.append(f"{title}: {snippet} ({url})")
        except Exception as exc:
            logger.debug("NEWS_SEARCH_FAIL query=%s: %s", query, str(exc)[:100])
            continue

    if not all_results:
        return {"searched": len(search_queries), "important_items": 0, "alerted": False}

    # Ask LLM to filter for genuinely important items
    results_text = "\n".join(f"- {r}" for r in all_results[:15])
    filter_prompt = (
        "Here are recent AI news items:\n\n"
        f"{results_text}\n\n"
        "Which of these are GENUINELY important — meaning they represent a real "
        "breakthrough, major release, or paradigm shift in AI/AGI?\n\n"
        "Respond with a JSON array of objects, each with:\n"
        '- "title": headline\n'
        '- "why_important": 1-sentence explanation\n'
        '- "relevance": score 1-10 (10 = world-changing)\n\n'
        "Only include items scoring 7+ on relevance. If nothing is truly important, "
        "return an empty array: []"
    )

    try:
        llm_result = call_llm(
            messages=[
                {"role": "system", "content": "You are a news importance filter. Respond only with valid JSON."},
                {"role": "user", "content": filter_prompt},
            ],
            temperature=0.2,
        )

        if not llm_result.get("ok"):
            return {"searched": len(search_queries), "important_items": 0, "alerted": False}

        content = llm_result.get("content", "")
        # Parse JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        important_items: List[Dict[str, Any]] = json.loads(content.strip())
        if not isinstance(important_items, list):
            important_items = []

    except (json.JSONDecodeError, Exception) as exc:
        logger.debug("NEWS_FILTER_FAIL: %s", str(exc)[:200])
        return {"searched": len(search_queries), "important_items": 0, "alerted": False}

    # Send alert if there are important items
    alerted = False
    if important_items:
        alerted = _send_trending_alert(owner_id, important_items)

    logger.info(
        "TRENDING_NEWS owner=%d searched=%d important=%d alerted=%s",
        owner_id, len(search_queries), len(important_items), alerted,
    )

    return {
        "searched": len(search_queries),
        "important_items": len(important_items),
        "alerted": alerted,
    }


def _send_trending_alert(owner_id: int, items: List[Dict[str, Any]]) -> bool:
    """Send a trending AI news alert via Telegram.

    Args:
        owner_id: Owner to notify.
        items: List of important news items (title, why_important, relevance).

    Returns:
        True if sent successfully.
    """
    chat_id = _get_chat_id(owner_id)
    if not chat_id:
        return False

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"*Bob — AI News Alert* ({now})\n"]
    for item in items[:5]:
        title = item.get("title", "Unknown")
        why = item.get("why_important", "")
        relevance = item.get("relevance", "?")
        lines.append(f"*{title}* (relevance: {relevance}/10)")
        if why:
            lines.append(f"  {why}")
        lines.append("")

    message = "\n".join(lines)
    return _send_telegram(chat_id, message)


# ---------------------------------------------------------------------------
# 3. Smart suggestions
# ---------------------------------------------------------------------------


def generate_smart_suggestions(owner_id: int) -> Dict[str, Any]:
    """Generate 1-2 proactive suggestions based on user profile, world model, and recent activity.

    Loads context from multiple sources and asks the LLM to generate
    actionable suggestions Bob should proactively offer.

    Args:
        owner_id: Owner to generate suggestions for.

    Returns:
        Dict with keys: suggestions (list of strings), sent (bool).
    """
    from ..agent.llm import call_llm
    from .user_profile import _load_profile
    from .world_model import _load_world

    # Load context
    profile = _load_profile(owner_id)
    world = _load_world(owner_id)

    # Load recent activity (last 10 messages)
    db = SessionLocal()
    recent_activity: List[str] = []
    try:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.owner_id == owner_id)
            .order_by(ConversationMessage.id.desc())
            .limit(10)
            .all()
        )
        for msg in reversed(messages):
            role = msg.role if hasattr(msg, "role") else "unknown"
            content = msg.content if hasattr(msg, "content") else ""
            if content:
                recent_activity.append(f"[{role}] {content[:200]}")
    except Exception as exc:
        logger.debug("SUGGESTIONS_LOAD_ACTIVITY_FAIL: %s", str(exc)[:100])
    finally:
        db.close()

    # Build the suggestion prompt
    suggestion_prompt = (
        "You are Bob, an AI agent assistant. Based on the following context, "
        "generate 1-2 proactive suggestions — things you should do or offer "
        "to help the user without being asked.\n\n"
        f"User Profile:\n{json.dumps(profile, indent=1, default=str)[:1000]}\n\n"
        f"World Model:\n{json.dumps(world, indent=1, default=str)[:1000]}\n\n"
        f"Recent Activity:\n" + "\n".join(recent_activity[-5:]) + "\n\n"
        "Rules:\n"
        "- Be specific and actionable (not vague 'you should research more')\n"
        "- Only suggest things that are genuinely useful right now\n"
        "- Keep each suggestion to 1-2 sentences\n"
        "- If nothing useful to suggest, say 'No suggestions at this time.'\n\n"
        "Respond with a JSON array of suggestion strings."
    )

    try:
        llm_result = call_llm(
            messages=[
                {"role": "system", "content": "You are a proactive AI assistant. Respond only with valid JSON."},
                {"role": "user", "content": suggestion_prompt},
            ],
            temperature=0.5,
        )

        if not llm_result.get("ok"):
            return {"suggestions": [], "sent": False}

        content = llm_result.get("content", "")
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        suggestions: List[str] = json.loads(content.strip())
        if not isinstance(suggestions, list):
            suggestions = []
        # Filter out empty or trivially short suggestions
        suggestions = [s for s in suggestions if isinstance(s, str) and len(s.strip()) > 10]

    except (json.JSONDecodeError, Exception) as exc:
        logger.debug("SUGGESTIONS_GENERATE_FAIL: %s", str(exc)[:200])
        return {"suggestions": [], "sent": False}

    # Send suggestions if any
    sent = False
    if suggestions:
        sent = _send_suggestions(owner_id, suggestions)

    logger.info(
        "SMART_SUGGESTIONS owner=%d count=%d sent=%s",
        owner_id, len(suggestions), sent,
    )

    return {"suggestions": suggestions, "sent": sent}


def _send_suggestions(owner_id: int, suggestions: List[str]) -> bool:
    """Send proactive suggestions via Telegram.

    Args:
        owner_id: Owner to notify.
        suggestions: List of suggestion strings.

    Returns:
        True if sent successfully.
    """
    chat_id = _get_chat_id(owner_id)
    if not chat_id:
        return False

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"*Bob — Proactive Suggestions* ({now})\n"]
    for i, suggestion in enumerate(suggestions[:3], 1):
        lines.append(f"{i}. {suggestion}")
    lines.append("\n_(Auto-generated — reply if you want me to act on any of these)_")

    message = "\n".join(lines)
    return _send_telegram(chat_id, message)


# ---------------------------------------------------------------------------
# Full proactive intelligence run
# ---------------------------------------------------------------------------


def run_proactive_intelligence(owner_id: int) -> Dict[str, Any]:
    """Run the full proactive intelligence cycle: triggers -> trending -> suggestions.

    Args:
        owner_id: Owner context.

    Returns:
        Dict with keys: ok, triggers, trending, suggestions.
    """
    logger.info("PROACTIVE_INTEL_START owner=%d", owner_id)

    # Step 1: Auto-respond to triggers
    try:
        triggers_result = auto_respond_to_triggers(owner_id)
    except Exception as exc:
        logger.error("PROACTIVE_TRIGGERS_FAIL: %s", exc)
        triggers_result = {"error": str(exc)[:300]}

    # Step 2: Check trending news
    try:
        trending_result = check_trending_news(owner_id)
    except Exception as exc:
        logger.error("PROACTIVE_TRENDING_FAIL: %s", exc)
        trending_result = {"error": str(exc)[:300]}

    # Step 3: Generate smart suggestions
    try:
        suggestions_result = generate_smart_suggestions(owner_id)
    except Exception as exc:
        logger.error("PROACTIVE_SUGGESTIONS_FAIL: %s", exc)
        suggestions_result = {"error": str(exc)[:300]}

    logger.info("PROACTIVE_INTEL_DONE owner=%d", owner_id)

    return {
        "ok": True,
        "triggers": triggers_result,
        "trending": trending_result,
        "suggestions": suggestions_result,
    }


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


def tool_proactive_intelligence(args: dict) -> dict:
    """Tool wrapper: run proactive intelligence engine.

    Args (dict):
        owner_id (int): Owner ID (default 1).
        mode (str): One of 'all', 'triggers', 'trending', 'suggestions'.
                    Default 'all'.

    Returns:
        Dict with proactive intelligence results.
    """
    owner_id = int(args.get("owner_id", 1))
    mode = str(args.get("mode", "all")).lower()

    try:
        if mode == "triggers":
            result = auto_respond_to_triggers(owner_id)
            return {"ok": True, "mode": "triggers", **result}

        if mode == "trending":
            result = check_trending_news(owner_id)
            return {"ok": True, "mode": "trending", **result}

        if mode == "suggestions":
            result = generate_smart_suggestions(owner_id)
            return {"ok": True, "mode": "suggestions", **result}

        # Default: run all
        return run_proactive_intelligence(owner_id)

    except Exception as exc:
        logger.error("tool_proactive_intelligence error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}

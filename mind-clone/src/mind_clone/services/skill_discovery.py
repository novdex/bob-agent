"""
Skill Auto-Discovery Engine — OpenClaw-inspired capability expansion.

Bob doesn't just use skills — he hunts for new ones. This module
periodically searches the web for interesting techniques, evaluates
whether they're useful and safe, and adds them to Bob's Voyager-style
skill library.

Flow:
1. search_for_skills — web search across DISCOVERY_TOPICS, LLM extracts structured skills
2. evaluate_skill — checks usefulness, novelty, safety
3. save_discovered_skill — saves approved skills via tool_save_skill
4. run_skill_discovery — orchestrates the full cycle + Telegram report

Inspired by OpenClaw's autonomous capability expansion loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..database.session import SessionLocal
from ..database.models import User

logger = logging.getLogger("mind_clone.services.skill_discovery")


# ---------------------------------------------------------------------------
# Discovery search topics — what Bob looks for
# ---------------------------------------------------------------------------

DISCOVERY_TOPICS: List[str] = [
    "new AI agent techniques 2025 2026",
    "autonomous agent tool use patterns",
    "LLM self-improvement methods",
    "agent memory management best practices",
    "AI agent error recovery strategies",
    "multi-agent collaboration patterns",
    "prompt engineering advanced techniques",
    "AI agent planning algorithms",
    "web scraping automation techniques for agents",
    "code generation and self-repair for AI agents",
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def search_for_skills(owner_id: int) -> List[Dict[str, Any]]:
    """Search the web for potential new skills and extract them via LLM.

    Iterates over DISCOVERY_TOPICS, searches the web, then asks the LLM
    to extract structured skill candidates from the search results.

    Args:
        owner_id: Owner context for the search.

    Returns:
        List of skill candidate dicts with keys: name, description, steps,
        trigger_hints, source_url, topic.
    """
    from ..tools.basic import tool_search_web
    from ..agent.llm import call_llm

    candidates: List[Dict[str, Any]] = []

    for topic in DISCOVERY_TOPICS:
        try:
            search_result = tool_search_web({"query": topic, "num_results": 3})
            if not search_result.get("ok"):
                continue

            results_text = json.dumps(
                search_result.get("results", []), indent=1, default=str
            )[:3000]

            # Ask LLM to extract skills from search results
            extraction_prompt = (
                f"You searched for: {topic}\n\n"
                f"Results:\n{results_text}\n\n"
                "Extract 0-2 actionable SKILLS an AI agent could learn from these results.\n"
                "Each skill should be a concrete, reusable technique — not a vague concept.\n\n"
                "Respond with a JSON array of objects, each with:\n"
                '- "name": short skill name\n'
                '- "description": what the skill does (1-2 sentences)\n'
                '- "steps": list of step-by-step instructions\n'
                '- "trigger_hints": list of keywords that should trigger this skill\n'
                '- "source_url": source URL if available\n\n'
                "If nothing useful, return an empty array: []"
            )

            llm_result = call_llm(
                messages=[
                    {"role": "system", "content": "You are a skill extraction assistant. Respond only with valid JSON."},
                    {"role": "user", "content": extraction_prompt},
                ],
                temperature=0.3,
            )

            if not llm_result.get("ok"):
                continue

            content = llm_result.get("content", "")
            # Parse JSON from LLM response
            try:
                # Handle markdown-wrapped JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                skills = json.loads(content.strip())
                if isinstance(skills, list):
                    for skill in skills:
                        skill["topic"] = topic
                        candidates.append(skill)
            except (json.JSONDecodeError, IndexError):
                logger.debug("SKILL_EXTRACT_PARSE_FAIL topic=%s", topic)
                continue

        except Exception as exc:
            logger.warning("SKILL_SEARCH_FAIL topic=%s: %s", topic, str(exc)[:200])
            continue

    logger.info(
        "SKILL_SEARCH_DONE owner=%d topics=%d candidates=%d",
        owner_id, len(DISCOVERY_TOPICS), len(candidates),
    )
    return candidates


def evaluate_skill(skill: Dict[str, Any], owner_id: int) -> Dict[str, Any]:
    """Evaluate whether a discovered skill is useful, novel, and safe.

    Checks:
    1. Usefulness — does it have clear steps and a real description?
    2. Novelty — is it not already in the skill library?
    3. Safety — does it avoid dangerous operations?

    Args:
        skill: Skill candidate dict from search_for_skills.
        owner_id: Owner to check existing skills against.

    Returns:
        Dict with keys: approved (bool), reason (str), skill (original dict).
    """
    from ..tools.skill_library import tool_recall_skill

    name = skill.get("name", "").strip()
    description = skill.get("description", "").strip()
    steps = skill.get("steps", [])

    # Check basic quality
    if not name or len(name) < 3:
        return {"approved": False, "reason": "No valid name", "skill": skill}
    if not description or len(description) < 10:
        return {"approved": False, "reason": "Description too short", "skill": skill}
    if not steps or len(steps) < 1:
        return {"approved": False, "reason": "No actionable steps", "skill": skill}

    # Check for dangerous keywords
    dangerous_keywords = [
        "delete all", "rm -rf", "format disk", "drop database",
        "sudo rm", "shutdown", "destroy", "wipe", "ransomware",
        "exploit", "hack into", "bypass auth", "steal",
    ]
    full_text = f"{name} {description} {' '.join(str(s) for s in steps)}".lower()
    for keyword in dangerous_keywords:
        if keyword in full_text:
            return {
                "approved": False,
                "reason": f"Dangerous keyword detected: '{keyword}'",
                "skill": skill,
            }

    # Check novelty — search existing skills for duplicates
    try:
        existing = tool_recall_skill({"query": name, "owner_id": owner_id})
        if existing.get("ok") and existing.get("skills"):
            for existing_skill in existing["skills"]:
                if existing_skill.get("title", "").lower() == name.lower():
                    return {
                        "approved": False,
                        "reason": f"Duplicate of existing skill: {existing_skill.get('title')}",
                        "skill": skill,
                    }
    except Exception:
        pass  # If recall fails, allow the skill through

    return {"approved": True, "reason": "Passed all checks", "skill": skill}


def save_discovered_skill(skill: Dict[str, Any], owner_id: int) -> Optional[Dict[str, Any]]:
    """Save an approved skill to the Voyager-style skill library.

    Args:
        skill: Evaluated and approved skill dict.
        owner_id: Owner to save the skill for.

    Returns:
        Result dict from tool_save_skill, or None on failure.
    """
    from ..tools.skill_library import tool_save_skill

    name = skill.get("name", "Unknown Skill")
    description = skill.get("description", "")
    steps = skill.get("steps", [])
    trigger_hints = skill.get("trigger_hints", [])
    source_url = skill.get("source_url", "")

    # Build the skill body
    body_parts = [description, ""]
    body_parts.append("Steps:")
    for i, step in enumerate(steps, 1):
        body_parts.append(f"  {i}. {step}")
    if source_url:
        body_parts.append(f"\nSource: {source_url}")

    body = "\n".join(body_parts)

    try:
        result = tool_save_skill({
            "title": name,
            "body": body,
            "trigger_hints": trigger_hints,
            "source": "auto_discovery",
            "owner_id": owner_id,
        })
        if result.get("ok"):
            logger.info("SKILL_SAVED name=%s owner=%d", name, owner_id)
        else:
            logger.warning("SKILL_SAVE_FAIL name=%s: %s", name, result.get("error"))
        return result
    except Exception as exc:
        logger.error("SKILL_SAVE_ERROR name=%s: %s", name, exc)
        return None


def _send_discovery_report(
    owner_id: int,
    candidates: List[Dict[str, Any]],
    saved_names: List[str],
) -> bool:
    """Send a Telegram alert summarizing the skill discovery run.

    Args:
        owner_id: Owner to notify.
        candidates: All candidate skills found.
        saved_names: Names of skills that were actually saved.

    Returns:
        True if sent successfully, False otherwise.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if not user or not user.telegram_chat_id:
            return False
        chat_id = str(user.telegram_chat_id)
    finally:
        db.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    saved_list = "\n".join(f"  - {name}" for name in saved_names) if saved_names else "  (none)"
    message = (
        f"*Bob — Skill Discovery Report* ({now})\n\n"
        f"Searched {len(DISCOVERY_TOPICS)} topics\n"
        f"Found {len(candidates)} candidates\n"
        f"Saved {len(saved_names)} new skills:\n{saved_list}"
    )

    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        logger.debug("SKILL_REPORT_SKIP no telegram token")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("SKILL_REPORT_SEND_FAIL: %s", str(exc)[:200])
        return False


def run_skill_discovery(
    owner_id: int,
    send_to_telegram: bool = True,
) -> Dict[str, Any]:
    """Run the full skill discovery cycle: search -> evaluate -> save -> report.

    Args:
        owner_id: Owner context for discovery.
        send_to_telegram: Whether to send a Telegram report.

    Returns:
        Dict with keys: ok, candidates_found, evaluated, saved, saved_names, sent.
    """
    logger.info("SKILL_DISCOVERY_START owner=%d", owner_id)

    # Step 1: Search
    candidates = search_for_skills(owner_id)
    if not candidates:
        logger.info("SKILL_DISCOVERY_DONE owner=%d no_candidates", owner_id)
        return {
            "ok": True,
            "candidates_found": 0,
            "evaluated": 0,
            "saved": 0,
            "saved_names": [],
            "sent": False,
        }

    # Step 2: Evaluate
    evaluated = 0
    approved: List[Dict[str, Any]] = []
    for candidate in candidates:
        result = evaluate_skill(candidate, owner_id)
        evaluated += 1
        if result.get("approved"):
            approved.append(candidate)

    # Step 3: Save
    saved_names: List[str] = []
    for skill in approved:
        save_result = save_discovered_skill(skill, owner_id)
        if save_result and save_result.get("ok"):
            saved_names.append(skill.get("name", "Unknown"))

    # Step 4: Report
    sent = False
    if send_to_telegram and saved_names:
        sent = _send_discovery_report(owner_id, candidates, saved_names)

    logger.info(
        "SKILL_DISCOVERY_DONE owner=%d candidates=%d evaluated=%d saved=%d",
        owner_id, len(candidates), evaluated, len(saved_names),
    )

    return {
        "ok": True,
        "candidates_found": len(candidates),
        "evaluated": evaluated,
        "saved": len(saved_names),
        "saved_names": saved_names,
        "sent": sent,
    }


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


def tool_discover_skills(args: dict) -> dict:
    """Tool wrapper: run skill auto-discovery.

    Args (dict):
        owner_id (int): Owner ID (default 1).
        send_to_telegram (bool): Whether to send report (default True).

    Returns:
        Dict with discovery results.
    """
    owner_id = int(args.get("owner_id", 1))
    send_to_telegram = bool(args.get("send_to_telegram", True))

    try:
        result = run_skill_discovery(
            owner_id=owner_id,
            send_to_telegram=send_to_telegram,
        )
        return result
    except Exception as exc:
        logger.error("tool_discover_skills error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}

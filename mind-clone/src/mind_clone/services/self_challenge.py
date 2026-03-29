"""
Weekly AGI Pillar Self-Challenge — Bob tests himself across core capabilities.

Every week Bob:
1. Picks random AGI pillars and generates challenges for them
2. Attempts each challenge using his own reasoning
3. Self-evaluates with an honest score (1-10)
4. Saves results as ResearchNotes for longitudinal tracking
5. Reports the scorecard to Arsh via Telegram

This creates a measurable growth loop: Bob can look back at past
challenge scores and see where he's improving (or stalling).
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..database.models import ResearchNote, ScheduledJob, User
from ..database.session import SessionLocal

logger = logging.getLogger("mind_clone.services.self_challenge")

# The eight pillars every AGI candidate should be strong in.
AGI_PILLARS: List[str] = [
    "Reasoning",
    "Memory",
    "Autonomy",
    "Learning",
    "Tool Mastery",
    "Self-Awareness",
    "World Understanding",
    "Communication",
]

# Weekly cadence: 7 days in seconds.
_WEEKLY_INTERVAL_SECONDS: int = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def generate_challenges(owner_id: int) -> List[Dict[str, Any]]:
    """Ask the LLM to create 3 challenges across random AGI pillars.

    Each challenge is a dict with keys: pillar, description, difficulty.
    Three pillars are sampled at random so we get broad coverage over time.

    Args:
        owner_id: The owner requesting the challenges.

    Returns:
        A list of challenge dicts, e.g.
        [{"pillar": "Reasoning", "description": "...", "difficulty": "medium"}, ...]
    """
    from ..agent.llm import call_llm

    selected_pillars = random.sample(AGI_PILLARS, min(3, len(AGI_PILLARS)))
    pillars_str = ", ".join(selected_pillars)

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a rigorous AGI evaluator. Generate exactly 3 challenges "
                "that test an AI agent's capabilities. Each challenge must target "
                "one of the specified AGI pillars. Return ONLY valid JSON — a list "
                "of objects with keys: pillar, description, difficulty (easy/medium/hard)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate 3 self-test challenges for these AGI pillars: {pillars_str}.\n"
                f"Each challenge should be a concrete, answerable task that an AI agent "
                f"can attempt in a single response. Make them genuinely hard enough to "
                f"differentiate strong from weak performance."
            ),
        },
    ]

    try:
        result = call_llm(prompt, temperature=0.7)
        content = _extract_content(result)
        # Strip markdown fences if present.
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        challenges = json.loads(content)
        if isinstance(challenges, list) and len(challenges) > 0:
            return challenges[:3]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.warning("CHALLENGE_GEN_PARSE_FAIL: %s", str(exc)[:200])
    except Exception as exc:
        logger.error("CHALLENGE_GEN_FAIL: %s", str(exc)[:200])

    # Fallback: return hard-coded challenges so the cycle never fully breaks.
    return [
        {"pillar": p, "description": f"Explain a novel approach to {p.lower()} in AGI.", "difficulty": "medium"}
        for p in selected_pillars
    ]


def execute_challenge(challenge: Dict[str, Any], owner_id: int) -> str:
    """Ask the LLM to solve / attempt a single challenge.

    Args:
        challenge: A challenge dict with at least 'pillar' and 'description'.
        owner_id: The owner on whose behalf the challenge runs.

    Returns:
        The LLM's response text.
    """
    from ..agent.llm import call_llm

    pillar = challenge.get("pillar", "General")
    description = challenge.get("description", "No description provided.")

    prompt = [
        {
            "role": "system",
            "content": (
                "You are Bob, an AGI agent being self-tested. Answer the challenge "
                "thoroughly, demonstrating strong capability in the specified pillar. "
                "Be precise and show your reasoning."
            ),
        },
        {
            "role": "user",
            "content": (
                f"AGI Pillar: {pillar}\n"
                f"Challenge: {description}\n\n"
                f"Give your best answer."
            ),
        },
    ]

    try:
        result = call_llm(prompt, temperature=0.3)
        return _extract_content(result)
    except Exception as exc:
        logger.error("CHALLENGE_EXEC_FAIL pillar=%s: %s", pillar, str(exc)[:200])
        return f"[Error executing challenge: {str(exc)[:100]}]"


def evaluate_challenge(challenge: Dict[str, Any], response: str) -> Dict[str, Any]:
    """Ask the LLM to score a challenge response on a 1-10 scale.

    Args:
        challenge: The original challenge dict.
        response: The agent's response to evaluate.

    Returns:
        A dict with keys: score (int 1-10), feedback (str).
    """
    from ..agent.llm import call_llm

    pillar = challenge.get("pillar", "General")
    description = challenge.get("description", "")

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a strict but fair AGI evaluator. Score the response 1-10 "
                "where 10 is flawless expert-level. Be honest — don't inflate scores. "
                "Return ONLY valid JSON: {\"score\": <int>, \"feedback\": \"<1-2 sentences>\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Pillar: {pillar}\n"
                f"Challenge: {description}\n\n"
                f"Response to evaluate:\n{response[:3000]}\n\n"
                f"Score this response 1-10 and give brief feedback."
            ),
        },
    ]

    try:
        result = call_llm(prompt, temperature=0.1)
        content = _extract_content(result).strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        evaluation = json.loads(content)
        score = int(evaluation.get("score", 5))
        score = max(1, min(10, score))
        return {"score": score, "feedback": str(evaluation.get("feedback", ""))}
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("CHALLENGE_EVAL_PARSE_FAIL: %s", str(exc)[:200])
    except Exception as exc:
        logger.error("CHALLENGE_EVAL_FAIL: %s", str(exc)[:200])

    return {"score": 5, "feedback": "Evaluation could not be parsed; default score assigned."}


def save_challenge_results(owner_id: int, results: List[Dict[str, Any]]) -> bool:
    """Persist challenge results as a ResearchNote for longitudinal tracking.

    Args:
        owner_id: Owner who ran the challenges.
        results: List of result dicts (pillar, description, response, score, feedback).

    Returns:
        True if saved successfully.
    """
    db = SessionLocal()
    try:
        summary_lines: List[str] = []
        scores: List[int] = []
        for r in results:
            score = r.get("score", 0)
            scores.append(score)
            summary_lines.append(
                f"[{r.get('pillar', '?')}] score={score}/10 — {r.get('feedback', 'N/A')}"
            )

        avg = round(sum(scores) / max(len(scores), 1), 1)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = (
            f"Self-Challenge Results ({timestamp})\n"
            f"Average Score: {avg}/10\n\n"
            + "\n".join(summary_lines)
        )

        note = ResearchNote(
            owner_id=owner_id,
            topic="self_challenge",
            summary=summary[:4000],
            sources_json=json.dumps(results, default=str)[:8000],
            tags_json=json.dumps(["self_challenge", "agi_pillars", f"avg_{avg}"]),
        )
        db.add(note)
        db.commit()
        logger.info("CHALLENGE_RESULTS_SAVED owner=%d avg=%.1f", owner_id, avg)
        return True
    except Exception as exc:
        logger.error("CHALLENGE_SAVE_FAIL: %s", str(exc)[:200])
        db.rollback()
        return False
    finally:
        db.close()


def run_self_challenge(owner_id: int = 1, send_to_telegram: bool = True) -> Dict[str, Any]:
    """Full self-challenge cycle: generate -> execute -> evaluate -> save -> report.

    Args:
        owner_id: Owner running the challenge.
        send_to_telegram: Whether to send a summary report via Telegram.

    Returns:
        A result dict with ok, results list, and average score.
    """
    logger.info("SELF_CHALLENGE_START owner=%d", owner_id)

    # Step 1: Generate challenges.
    challenges = generate_challenges(owner_id)
    if not challenges:
        return {"ok": False, "error": "Failed to generate challenges"}

    results: List[Dict[str, Any]] = []

    for challenge in challenges:
        pillar = challenge.get("pillar", "Unknown")
        description = challenge.get("description", "")

        # Step 2: Execute the challenge.
        response = execute_challenge(challenge, owner_id)

        # Step 3: Evaluate the response.
        evaluation = evaluate_challenge(challenge, response)

        results.append({
            "pillar": pillar,
            "description": description,
            "difficulty": challenge.get("difficulty", "medium"),
            "response": response[:1000],
            "score": evaluation["score"],
            "feedback": evaluation["feedback"],
        })

    # Step 4: Save results.
    scores = [r["score"] for r in results]
    avg_score = round(sum(scores) / max(len(scores), 1), 1)
    save_challenge_results(owner_id, results)

    # Step 5: Report via Telegram.
    if send_to_telegram:
        _send_challenge_report(owner_id, results, avg_score)

    logger.info("SELF_CHALLENGE_DONE owner=%d avg=%.1f", owner_id, avg_score)
    return {"ok": True, "results": results, "avg_score": avg_score}


# ---------------------------------------------------------------------------
# Telegram reporting
# ---------------------------------------------------------------------------


def _send_challenge_report(
    owner_id: int, results: List[Dict[str, Any]], avg_score: float
) -> bool:
    """Format and send the challenge scorecard via Telegram.

    Args:
        owner_id: Owner to send the report to.
        results: List of scored challenge results.
        avg_score: Pre-computed average score.

    Returns:
        True if sent successfully.
    """
    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        logger.debug("CHALLENGE_REPORT_SKIP no telegram token configured")
        return False

    chat_id = _get_chat_id(owner_id)
    if not chat_id:
        logger.warning("CHALLENGE_REPORT_SKIP no chat_id for owner=%d", owner_id)
        return False

    lines = [f"*Self-Challenge Report* (avg {avg_score}/10)\n"]
    for r in results:
        emoji = "+" if r["score"] >= 7 else ("-" if r["score"] >= 4 else "!")
        lines.append(
            f"[{emoji}] *{r['pillar']}* — {r['score']}/10\n"
            f"    {r.get('feedback', '')}"
        )

    text = "\n".join(lines)[:4000]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        logger.warning("CHALLENGE_REPORT_HTTP_%d", resp.status_code)
        return False
    except Exception as exc:
        logger.warning("CHALLENGE_REPORT_FAIL: %s", str(exc)[:200])
        return False


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


def tool_self_challenge(args: dict) -> dict:
    """Tool: Run the weekly AGI pillar self-challenge.

    Args:
        args: Tool arguments. Accepts optional _owner_id (int) and
              send_to_telegram (bool, default True).

    Returns:
        Result dict with ok, results, and avg_score.
    """
    owner_id = int(args.get("_owner_id", 1))
    send_tg = bool(args.get("send_to_telegram", True))
    try:
        return run_self_challenge(owner_id, send_to_telegram=send_tg)
    except Exception as exc:
        logger.error("TOOL_SELF_CHALLENGE_FAIL: %s", str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Scheduled job bootstrapping
# ---------------------------------------------------------------------------


def ensure_self_challenge_job(db: Any, owner_id: int = 1) -> None:
    """Create the weekly self-challenge ScheduledJob if it doesn't already exist.

    Args:
        db: SQLAlchemy Session.
        owner_id: Owner to attach the job to.
    """
    existing = (
        db.query(ScheduledJob)
        .filter(
            ScheduledJob.name == "self_challenge",
            ScheduledJob.owner_id == owner_id,
        )
        .first()
    )
    if existing:
        logger.debug("SELF_CHALLENGE_JOB_EXISTS id=%d", existing.id)
        return

    now = datetime.now(timezone.utc)
    # First run: next Sunday at 10:00 UTC.
    days_until_sunday = (6 - now.weekday()) % 7 or 7
    next_sunday = (now + timedelta(days=days_until_sunday)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )

    job = ScheduledJob(
        owner_id=owner_id,
        name="self_challenge",
        message=(
            "Run the weekly AGI self-challenge: generate challenges across random "
            "pillars, attempt them, score yourself, and send the report to Telegram."
        ),
        lane="cron",
        interval_seconds=_WEEKLY_INTERVAL_SECONDS,
        next_run_at=next_sunday,
        enabled=True,
        run_count=0,
    )
    db.add(job)
    db.commit()
    logger.info(
        "SELF_CHALLENGE_JOB_CREATED owner=%d next_run=%s",
        owner_id,
        next_sunday.isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_content(result: Any) -> str:
    """Pull the text content out of a call_llm response.

    call_llm may return a dict with 'content' / 'choices' or a plain string.

    Args:
        result: Raw return value from call_llm.

    Returns:
        Extracted text content.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # Try choices first (OpenAI-shaped).
        choices = result.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return result.get("content", "")
    return str(result)


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

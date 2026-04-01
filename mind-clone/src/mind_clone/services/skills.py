"""
Skills system — reusable, versioned capability playbooks.

Skills are persistent playbooks that the agent can invoke when a user's message
matches the skill's trigger hints.  Each skill has immutable versions and an
audit trail of invocations (SkillRun).

This module is the MAIN skill service.  It includes:
  - Core CRUD (DB-backed skills via SkillProfile / SkillVersion)
  - Skill matching & prompt injection
  - Skill auto-creation from capability gaps
  - Markdown-based skills (loaded from ~/.mind-clone/skills/)  [merged from skill_manager]
  - Skill chaining (multi-step workflows)                      [merged from skill_chain]
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import settings
from ..database.models import SkillProfile, SkillRun, SkillVersion
from ..utils import truncate_text, utc_now_iso

logger = logging.getLogger("mind_clone.skills")

# ---------------------------------------------------------------------------
# Configuration constants (mirrors monolith SKILLS_*)
# ---------------------------------------------------------------------------
SKILLS_ACTIVE_TOP_K = 3
SKILLS_MAX_BODY_CHARS = 5000
SKILLS_MAX_PER_OWNER = 120
SKILLS_AUTO_CREATE_COOLDOWN_SECONDS = 600

# Per-owner cooldown tracker (owner_id -> monotonic timestamp)
_auto_create_cooldowns: Dict[int, float] = {}


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------

def save_skill_profile(
    db: Session,
    owner_id: int,
    skill_key: str,
    title: str,
    body_text: str,
    *,
    intent: str = "",
    trigger_hints: Optional[List[str]] = None,
    source_type: str = "manual",
    auto_created: bool = False,
    metadata: Optional[Dict] = None,
) -> Tuple[SkillProfile, SkillVersion]:
    """Create or update a skill, always producing a new immutable version."""
    key = _normalize_key(skill_key)
    body_text = truncate_text(body_text, SKILLS_MAX_BODY_CHARS)
    hints = trigger_hints or []
    intent_hash = hashlib.sha256(intent.encode()).hexdigest()[:16] if intent else ""

    existing = (
        db.query(SkillProfile)
        .filter(SkillProfile.owner_id == owner_id, SkillProfile.skill_key == key)
        .first()
    )

    if existing:
        new_ver = existing.latest_version + 1
        existing.latest_version = new_ver
        existing.active_version = new_ver
        existing.title = title
        existing.intent = intent
        existing.intent_hash = intent_hash
        existing.trigger_hints_json = json.dumps(hints, ensure_ascii=False)
        profile = existing
    else:
        # Check quota
        count = db.query(SkillProfile).filter(SkillProfile.owner_id == owner_id).count()
        if count >= SKILLS_MAX_PER_OWNER:
            raise ValueError(f"Skill quota exceeded ({SKILLS_MAX_PER_OWNER})")
        new_ver = 1
        profile = SkillProfile(
            owner_id=owner_id,
            skill_key=key,
            title=title,
            intent=intent,
            intent_hash=intent_hash,
            trigger_hints_json=json.dumps(hints, ensure_ascii=False),
            status="active",
            active_version=1,
            latest_version=1,
            source_type=source_type,
            auto_created=auto_created,
        )
        db.add(profile)
        db.flush()

    version = SkillVersion(
        owner_id=owner_id,
        skill_id=profile.id,
        version=new_ver,
        body_text=body_text,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )
    db.add(version)
    db.commit()
    db.refresh(profile)
    return profile, version


def list_skill_profiles(
    db: Session, owner_id: int, status: Optional[str] = None, limit: int = 100
) -> List[SkillProfile]:
    q = db.query(SkillProfile).filter(SkillProfile.owner_id == owner_id)
    if status:
        q = q.filter(SkillProfile.status == status)
    return q.order_by(SkillProfile.id.desc()).limit(limit).all()


def skill_profile_detail(
    db: Session, skill_id: int
) -> Tuple[Optional[SkillProfile], List[SkillVersion]]:
    profile = db.query(SkillProfile).filter(SkillProfile.id == skill_id).first()
    if not profile:
        return None, []
    versions = (
        db.query(SkillVersion)
        .filter(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version.desc())
        .all()
    )
    return profile, versions


def set_skill_status(db: Session, skill_id: int, status: str) -> Optional[SkillProfile]:
    profile = db.query(SkillProfile).filter(SkillProfile.id == skill_id).first()
    if profile:
        profile.status = status
        db.commit()
        db.refresh(profile)
    return profile


def rollback_skill_version(
    db: Session, skill_id: int, target_version: int
) -> Optional[SkillProfile]:
    profile = db.query(SkillProfile).filter(SkillProfile.id == skill_id).first()
    if not profile:
        return None
    ver = (
        db.query(SkillVersion)
        .filter(SkillVersion.skill_id == skill_id, SkillVersion.version == target_version)
        .first()
    )
    if not ver:
        return None
    profile.active_version = target_version
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Skill matching & prompt injection
# ---------------------------------------------------------------------------

def _keyword_set(text: str) -> set:
    return {w for w in re.split(r"\W+", (text or "").lower()) if len(w) > 2}


def _score_skill(skill: SkillProfile, message_keywords: set) -> float:
    try:
        hints = json.loads(skill.trigger_hints_json or "[]")
    except Exception:
        hints = []
    hint_kw = set()
    for h in hints:
        hint_kw |= _keyword_set(h)
    if not hint_kw:
        return 0.0
    overlap = len(message_keywords & hint_kw)
    return overlap / max(1, len(hint_kw))


def select_active_skills_for_prompt(
    db: Session, owner_id: int, user_message: str, top_k: int = SKILLS_ACTIVE_TOP_K
) -> List[str]:
    """Select top-K matching active skills, record SkillRun, return prompt blocks."""
    skills = list_skill_profiles(db, owner_id, status="active", limit=200)
    if not skills:
        return []

    msg_kw = _keyword_set(user_message)
    if not msg_kw:
        return []

    scored = [(s, _score_skill(s, msg_kw)) for s in skills]
    scored = [(s, sc) for s, sc in scored if sc > 0]
    scored.sort(key=lambda x: (x[1], x[0].usage_count or 0), reverse=True)
    selected = scored[:top_k]

    blocks: List[str] = []
    for skill, score in selected:
        ver = (
            db.query(SkillVersion)
            .filter(
                SkillVersion.skill_id == skill.id,
                SkillVersion.version == skill.active_version,
            )
            .first()
        )
        if not ver:
            continue

        try:
            hints = json.loads(skill.trigger_hints_json or "[]")
        except Exception:
            hints = []

        block = (
            f"{skill.title} (key={skill.skill_key}, v={skill.active_version}, "
            f"score={score:.2f}): {ver.body_text}"
        )
        if hints:
            block += f"\nTrigger hints: {', '.join(hints[:6])}"
        blocks.append(block)

        # Record run
        run = SkillRun(
            owner_id=owner_id,
            skill_id=skill.id,
            skill_version=skill.active_version,
            source_type="chat",
            status="invoked",
            message_preview=truncate_text(user_message, 200),
        )
        db.add(run)
        skill.usage_count = (skill.usage_count or 0) + 1

    if blocks:
        db.commit()
    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_key(raw: str) -> str:
    key = re.sub(r"[^a-z0-9_]", "_", (raw or "").strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return key[:60] or "unnamed_skill"


# ---------------------------------------------------------------------------
# Skill auto-creation (ported from monolith lines 3382-3482)
# ---------------------------------------------------------------------------

_SKILL_LOCK = threading.Lock()

# Gap phrases that indicate the LLM couldn't fulfil a request
GAP_PHRASES = frozenset({
    "i don't have a tool",
    "no tool available",
    "i cannot",
    "i lack the capability",
    "not currently able to",
})


def _safe_skill_hints(raw_hints: Any) -> List[str]:
    """Normalise trigger hints to a deduped list (max 24, 120 chars each)."""
    if isinstance(raw_hints, list):
        source = raw_hints
    elif isinstance(raw_hints, str) and raw_hints.strip():
        source = [item.strip() for item in raw_hints.split(",") if item.strip()]
    else:
        source = []
    hints: List[str] = []
    for item in source:
        hint = truncate_text(str(item or "").strip(), 120)
        if hint and hint not in hints:
            hints.append(hint)
        if len(hints) >= 24:
            break
    return hints


def _skill_keyword_set(text: str) -> set:
    """Extract lowercase keywords (3+ chars) from text."""
    return {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", str(text or "").lower())
        if token
    }


def synthesize_skill_blueprint(
    request_text: str, preferred_name: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a skill blueprint (key, title, body, hints) from a user request.

    Special handling for crypto, news, regression, and game-theory keywords.
    Falls back to a generic "Autonomous Research Skill" for other requests.
    """
    text = str(request_text or "").strip()
    lowered = text.lower()
    raw_pref = str(preferred_name or "").strip()
    key = _normalize_key(raw_pref) if raw_pref else ""
    hints: List[str] = []

    title = "Autonomous Research Skill"
    body = (
        "When triggered, run a structured research pass:\n"
        "1) Identify key unknowns.\n"
        "2) Use search_web for recent high-trust sources.\n"
        "3) Use read_webpage/deep_research for synthesis.\n"
        "4) Produce concise output with assumptions, risks, and next steps."
    )
    intent = text or "Autonomous multi-step research and synthesis."

    if any(kw in lowered for kw in ("crypto", "bitcoin", "ethereum")):
        title = "Daily Crypto Intelligence Brief"
        if not key:
            key = "daily_crypto_brief"
        hints = ["crypto", "bitcoin", "ethereum", "market update", "signal", "every morning"]
        body = (
            "Run a daily crypto market briefing:\n"
            "1) Gather latest price/action context from trusted market sources.\n"
            "2) Gather top macro/regulatory/news drivers.\n"
            "3) Build a directional bias with confidence and invalidation levels.\n"
            "4) If requested, include simple regression/game-theory framing "
            "and clearly state uncertainty."
        )
    elif "news" in lowered:
        title = "Daily News Digest Skill"
        if not key:
            key = "daily_news_digest"
        hints = ["news", "morning brief", "daily update"]
        body = (
            "Build a daily briefing:\n"
            "1) Collect top global and domain-specific updates from trusted outlets.\n"
            "2) Cluster related stories and remove duplicates.\n"
            "3) Summarize key developments, why they matter, and potential next impacts."
        )

    if "regression" in lowered and "regression" not in body.lower():
        body += "\n5) Apply a lightweight regression sanity-check when numeric time-series data is available."
    if "game theory" in lowered and "game-theory" not in body.lower():
        body += "\n6) Add game-theory framing for strategic actor behavior when relevant."

    if not hints:
        hints = list(sorted(_skill_keyword_set(lowered)))[:8]
    if not key:
        key = _normalize_key(title)

    return {
        "skill_key": key,
        "title": title,
        "intent": intent,
        "trigger_hints": hints,
        "body_text": body,
    }


def maybe_autocreate_skill_from_gap(
    db: Session,
    owner_id: int,
    user_message: str,
    assistant_text: str,
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Detect a capability gap in the LLM response and auto-create a skill.

    Returns a result dict (with ``ok=True`` and ``skill`` key) when a skill is
    created, or ``None`` when no gap is detected or creation is skipped.
    """
    if not (settings.skills_enabled and settings.skills_auto_create_enabled):
        return None

    response_lower = str(assistant_text or "").lower()
    if not any(phrase in response_lower for phrase in GAP_PHRASES):
        return None

    # Per-owner cooldown
    now = time.monotonic()
    cooldown = float(settings.skills_auto_create_cooldown_seconds)
    with _SKILL_LOCK:
        last = float(_auto_create_cooldowns.get(int(owner_id), 0.0))
        if now - last < cooldown:
            return None
        _auto_create_cooldowns[int(owner_id)] = now

    blueprint = synthesize_skill_blueprint(user_message)

    try:
        profile, version = save_skill_profile(
            db,
            owner_id=int(owner_id),
            skill_key=str(blueprint.get("skill_key") or ""),
            title=str(blueprint.get("title") or "Auto Skill"),
            body_text=str(blueprint.get("body_text") or ""),
            intent=str(blueprint.get("intent") or user_message),
            trigger_hints=_safe_skill_hints(blueprint.get("trigger_hints") or []),
            source_type="auto",
            auto_created=True,
            metadata={
                "reason": "capability_gap",
                "session_id": str(session_id or ""),
            },
        )
    except Exception as exc:
        logger.warning(
            "SKILL_AUTOCREATE_FAIL owner=%d error=%s",
            owner_id, truncate_text(str(exc), 220),
        )
        return None

    from ..core.state import increment_runtime_state
    increment_runtime_state("skills_autocreated")

    logger.info(
        "SKILL_AUTOCREATED owner=%d key=%s version=%d",
        owner_id, profile.skill_key, version.version,
    )
    return {
        "ok": True,
        "skill": {
            "id": profile.id,
            "skill_key": profile.skill_key,
            "title": profile.title,
        },
        "version": version.version,
    }


# ===========================================================================
# Markdown-based Skills (merged from skill_manager.py)
# ===========================================================================
# Bob teaches himself new behaviours through .md files.  Instead of
# modifying source code, Bob creates markdown skill files in
# ~/.mind-clone/skills/.  Each skill has YAML frontmatter (name, trigger
# keywords, description) and a body with step-by-step instructions that
# get injected into the LLM context when a user message matches.
# ===========================================================================

# Directory where markdown skill files live
SKILLS_DIR: Path = Path.home() / ".mind-clone" / "skills"


def _ensure_skills_dir() -> Path:
    """Ensure the skills directory exists and return it."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter from a markdown string.

    Returns a tuple of (frontmatter_dict, body_text). If no frontmatter
    delimiters are found, returns empty dict and the full text as body.
    """
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
    match = pattern.match(text)
    if not match:
        return {}, text.strip()

    raw_fm = match.group(1)
    body = match.group(2).strip()

    # Lightweight YAML parsing — avoids requiring pyyaml for simple key: value
    frontmatter: dict[str, Any] = {}
    for line in raw_fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Handle list values like ["a", "b", "c"]
        if value.startswith("[") and value.endswith("]"):
            items = value[1:-1]
            frontmatter[key] = [
                item.strip().strip("\"'")
                for item in items.split(",")
                if item.strip()
            ]
        else:
            frontmatter[key] = value.strip("\"'")

    return frontmatter, body


def load_skills() -> list[dict]:
    """Read all .md files from ~/.mind-clone/skills/ and parse them.

    Each skill file must have YAML frontmatter with at least ``name``.
    Files that fail to parse are logged and skipped.

    Returns:
        A list of skill dicts with keys: name, trigger, description, body, path.
    """
    skills_dir = _ensure_skills_dir()
    skills: list[dict] = []

    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)

            name = fm.get("name", md_file.stem)
            triggers = fm.get("trigger", [])
            if isinstance(triggers, str):
                triggers = [triggers]
            description = fm.get("description", "")

            skills.append({
                "name": name,
                "trigger": triggers,
                "description": description,
                "body": body,
                "path": str(md_file),
            })
        except Exception as exc:
            logger.warning(
                "SKILL_LOAD_FAIL file=%s error=%s",
                md_file.name, str(exc)[:200],
            )

    logger.info("SKILLS_LOADED count=%d dir=%s", len(skills), skills_dir)
    return skills


def match_skill(user_message: str) -> dict | None:
    """Check if a user message matches any skill's trigger keywords.

    Uses keyword overlap scoring — the skill with the highest ratio of
    matched trigger keywords to total trigger keywords wins. A minimum
    overlap of 1 keyword is required.

    Args:
        user_message: The raw user message text.

    Returns:
        The best matching skill dict, or None if no match.
    """
    if not user_message or not user_message.strip():
        return None

    msg_words = set(re.split(r"\W+", user_message.lower()))
    msg_words = {w for w in msg_words if len(w) > 2}

    if not msg_words:
        return None

    skills = load_skills()
    best_skill: dict | None = None
    best_score: float = 0.0

    for skill in skills:
        triggers = skill.get("trigger", [])
        if not triggers:
            continue

        # Collect all keywords from all trigger phrases
        trigger_words: set[str] = set()
        for phrase in triggers:
            words = set(re.split(r"\W+", phrase.lower()))
            trigger_words |= {w for w in words if len(w) > 2}

        if not trigger_words:
            continue

        overlap = len(msg_words & trigger_words)
        if overlap == 0:
            continue

        score = overlap / len(trigger_words)
        if score > best_score:
            best_score = score
            best_skill = skill

    if best_skill:
        logger.info(
            "SKILL_MATCHED name=%s score=%.2f",
            best_skill.get("name", "?"), best_score,
        )

    return best_skill


def create_skill(
    name: str,
    triggers: list[str],
    description: str,
    steps: str,
) -> bool:
    """Create a new markdown skill file.

    Bob can call this to teach himself new procedures. The skill is
    written to ~/.mind-clone/skills/<name>.md with proper frontmatter.

    Args:
        name: Skill identifier (used as filename, spaces become underscores).
        triggers: List of trigger phrases/keywords.
        description: One-line description of what the skill does.
        steps: The step-by-step procedure body (markdown).

    Returns:
        True if the skill was created successfully, False otherwise.
    """
    try:
        skills_dir = _ensure_skills_dir()

        # Sanitise filename
        safe_name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")
        if not safe_name:
            safe_name = "unnamed_skill"

        file_path = skills_dir / f"{safe_name}.md"

        # Build trigger list string
        trigger_str = ", ".join(f'"{t}"' for t in triggers)

        content = f"""---
name: {safe_name}
trigger: [{trigger_str}]
description: {description}
---

{steps.strip()}
"""
        file_path.write_text(content, encoding="utf-8")
        logger.info("SKILL_CREATED name=%s path=%s", safe_name, file_path)
        return True
    except Exception as exc:
        logger.error("SKILL_CREATE_FAIL name=%s error=%s", name, str(exc)[:200])
        return False


def list_skills_md() -> list[dict]:
    """Return all available markdown skills with name and description.

    Returns:
        A list of dicts with keys: name, description, trigger_count.
    """
    skills = load_skills()
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "trigger_count": len(s.get("trigger", [])),
        }
        for s in skills
    ]


def get_skill_injection(user_message: str) -> str | None:
    """If a skill matches the user message, return it as a system injection.

    This string gets added to the LLM context so Bob follows the
    procedure defined in the skill file.

    Args:
        user_message: The raw user message text.

    Returns:
        A formatted system message string, or None if no skill matched.
    """
    skill = match_skill(user_message)
    if not skill:
        return None

    injection = (
        f"[SKILL ACTIVATED: {skill['name']}]\n"
        f"Description: {skill['description']}\n\n"
        f"Follow these steps:\n{skill['body']}\n\n"
        f"[END SKILL]"
    )
    return injection


# ---------------------------------------------------------------------------
# Markdown skill tool wrappers (called from the tool registry)
# ---------------------------------------------------------------------------


def tool_create_skill(args: dict) -> dict:
    """Tool wrapper for create_skill — Bob teaches himself a new procedure.

    Args:
        args: Dict with keys: name, triggers (list), description, steps.

    Returns:
        Dict with ok status and created skill name or error.
    """
    try:
        name = str(args.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "Skill name is required"}

        raw_triggers = args.get("triggers", [])
        if isinstance(raw_triggers, str):
            raw_triggers = [t.strip() for t in raw_triggers.split(",") if t.strip()]
        triggers: list[str] = [str(t) for t in raw_triggers]

        description = str(args.get("description", "")).strip()
        steps = str(args.get("steps", "")).strip()

        if not steps:
            return {"ok": False, "error": "Skill steps are required"}

        success = create_skill(name, triggers, description, steps)
        if success:
            return {"ok": True, "skill_name": name, "message": f"Skill '{name}' created successfully"}
        return {"ok": False, "error": f"Failed to create skill '{name}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def auto_create_skill_from_turn(
    owner_id: int,
    user_message: str,
    response: str,
    tools_used: list,
) -> bool:
    """Auto-create a reusable skill from a successful multi-tool turn.

    After Bob completes a task using 2+ tools, this function asks the LLM
    to extract the procedure and saves it as a new markdown skill file.
    Runs in a background thread so it never blocks the main agent loop.

    Args:
        owner_id: The owner who initiated the turn.
        user_message: The original user request.
        response: Bob's final response text.
        tools_used: List of tool names used during the turn.

    Returns:
        True if a new skill was created, False otherwise.
    """
    if len(tools_used) < 2:
        return False

    try:
        from ..agent.llm import call_llm

        unique_tools = list(dict.fromkeys(tools_used))  # dedupe, preserve order
        tools_str = ", ".join(unique_tools)

        prompt = [
            {
                "role": "user",
                "content": (
                    f"The user asked: {user_message[:500]}\n"
                    f"Bob used these tools: {tools_str}\n"
                    f"Bob's response: {response[:500]}\n\n"
                    "Create a reusable skill from this interaction. "
                    'Return JSON: {"name": "...", "triggers": ["keyword1", "keyword2"], '
                    '"description": "one-line description", '
                    '"steps": "step-by-step markdown procedure"}\n'
                    "Only return the JSON, nothing else."
                ),
            }
        ]

        result = call_llm(prompt, temperature=0.3)
        if not result.get("ok"):
            logger.warning(
                "AUTO_SKILL_LLM_FAIL owner=%d error=%s",
                owner_id, str(result.get("error", ""))[:200],
            )
            return False

        content = result.get("content", "")

        # Extract JSON from the response
        import re as _re
        json_match = _re.search(r"\{.*\}", content, _re.DOTALL)
        if not json_match:
            logger.debug("AUTO_SKILL_NO_JSON owner=%d", owner_id)
            return False

        import json as _json
        data = _json.loads(json_match.group())

        name = str(data.get("name", "")).strip()
        triggers = data.get("triggers", [])
        description = str(data.get("description", "")).strip()
        steps = str(data.get("steps", "")).strip()

        if not name or not steps:
            logger.debug("AUTO_SKILL_INCOMPLETE owner=%d", owner_id)
            return False

        # Check for duplicates — if a similar skill already exists, skip
        existing = match_skill(name)
        if existing:
            logger.debug(
                "AUTO_SKILL_DUPLICATE owner=%d name=%s existing=%s",
                owner_id, name, existing.get("name", "?"),
            )
            return False

        # Create the skill
        success = create_skill(name, triggers, description, steps)
        if success:
            logger.info("AUTO_SKILL_CREATED name=%s owner=%d tools=%s", name, owner_id, tools_str)
        return success

    except Exception as exc:
        logger.warning(
            "AUTO_SKILL_CREATE_ERROR owner=%d error=%s",
            owner_id, str(exc)[:200],
        )
        return False


def tool_list_skills_md(args: dict) -> dict:
    """Tool wrapper for list_skills_md — returns all markdown-based skills.

    Args:
        args: Dict (currently unused, reserved for future filters).

    Returns:
        Dict with ok status and list of skills.
    """
    try:
        skills = list_skills_md()
        return {
            "ok": True,
            "count": len(skills),
            "skills": skills,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


# ===========================================================================
# Skill Chaining (merged from skill_chain.py)
# ===========================================================================
# Connect skills into multi-step workflows.  Each skill's output feeds
# into the next skill as context input.  Chain definitions are stored
# as YAML files in ~/.mind-clone/chains/.
# ===========================================================================

# Directory where chain definition files live
CHAINS_DIR: Path = Path.home() / ".mind-clone" / "chains"


def _ensure_chains_dir() -> Path:
    """Ensure the chains directory exists and return it."""
    CHAINS_DIR.mkdir(parents=True, exist_ok=True)
    return CHAINS_DIR


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse a simple YAML file without requiring pyyaml.

    Supports top-level scalar keys and list values (indicated by ``- item``
    lines under a key).

    Args:
        text: Raw YAML text content.

    Returns:
        Parsed dict with string keys and string or list values.
    """
    result: dict[str, Any] = {}
    current_key: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under current key
        if stripped.startswith("- ") and current_key is not None:
            item = stripped[2:].strip().strip("\"'")
            if not isinstance(result.get(current_key), list):
                result[current_key] = []
            result[current_key].append(item)
            continue

        # Key: value pair
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip("\"'")
            current_key = key
            if value:
                result[key] = value
            else:
                # Next lines might be list items
                result[key] = []
            continue

    return result


def _dump_simple_yaml(data: dict[str, Any]) -> str:
    """Dump a dict to simple YAML format.

    Args:
        data: Dict to serialise.

    Returns:
        YAML-formatted string.
    """
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def create_chain(name: str, skill_names: list[str], description: str = "") -> bool:
    """Create a chain definition and save to ~/.mind-clone/chains/{name}.yaml.

    Args:
        name: Chain identifier (used as filename).
        skill_names: Ordered list of skill names to execute in sequence.
        description: Human-readable description of what the chain does.

    Returns:
        True if the chain was saved successfully, False otherwise.
    """
    try:
        chains_dir = _ensure_chains_dir()

        # Sanitise filename
        safe_name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")
        if not safe_name:
            safe_name = "unnamed_chain"

        if not skill_names or len(skill_names) < 1:
            logger.warning("CREATE_CHAIN_FAIL name=%s reason=no_skills", name)
            return False

        data = {
            "name": safe_name,
            "description": description or f"Chain: {safe_name}",
            "skills": skill_names,
        }

        file_path = chains_dir / f"{safe_name}.yaml"
        file_path.write_text(_dump_simple_yaml(data), encoding="utf-8")
        logger.info("CHAIN_CREATED name=%s skills=%d path=%s", safe_name, len(skill_names), file_path)
        return True
    except Exception as exc:
        logger.error("CHAIN_CREATE_FAIL name=%s error=%s", name, str(exc)[:200])
        return False


def list_chains() -> list[dict]:
    """Return all defined chains with their metadata.

    Returns:
        List of dicts with keys: name, description, skills, path.
    """
    chains_dir = _ensure_chains_dir()
    chains: list[dict] = []

    for yaml_file in sorted(chains_dir.glob("*.yaml")):
        try:
            text = yaml_file.read_text(encoding="utf-8")
            data = _parse_simple_yaml(text)

            chains.append({
                "name": data.get("name", yaml_file.stem),
                "description": data.get("description", ""),
                "skills": data.get("skills", []),
                "path": str(yaml_file),
            })
        except Exception as exc:
            logger.warning("CHAIN_LOAD_FAIL file=%s error=%s", yaml_file.name, str(exc)[:200])

    return chains


def _load_chain(chain_name: str) -> dict | None:
    """Load a single chain definition by name.

    Args:
        chain_name: Name of the chain to load.

    Returns:
        Chain dict or None if not found.
    """
    safe_name = re.sub(r"[^a-z0-9_]", "_", chain_name.lower().strip())
    safe_name = re.sub(r"_+", "_", safe_name).strip("_")

    file_path = _ensure_chains_dir() / f"{safe_name}.yaml"
    if not file_path.exists():
        # Try exact match across all chain files
        for chain in list_chains():
            if chain.get("name", "").lower() == chain_name.lower():
                return chain
        return None

    try:
        text = file_path.read_text(encoding="utf-8")
        data = _parse_simple_yaml(text)
        return {
            "name": data.get("name", file_path.stem),
            "description": data.get("description", ""),
            "skills": data.get("skills", []),
            "path": str(file_path),
        }
    except Exception as exc:
        logger.warning("CHAIN_LOAD_FAIL name=%s error=%s", chain_name, str(exc)[:200])
        return None


def run_chain(chain_name: str, initial_input: str, owner_id: int = 1) -> dict:
    """Run a skill chain -- execute skills in sequence, piping output forward.

    Each skill's output becomes the next skill's input context.

    Args:
        chain_name: Name of the chain to run.
        initial_input: The initial input text to feed to the first skill.
        owner_id: Owner ID for LLM calls.

    Returns:
        Dict with ok status, steps list, and final_output string.
    """
    try:
        from ..agent.llm import call_llm

        chain = _load_chain(chain_name)
        if not chain:
            return {"ok": False, "error": f"Chain '{chain_name}' not found"}

        skill_names = chain.get("skills", [])
        if not skill_names:
            return {"ok": False, "error": f"Chain '{chain_name}' has no skills defined"}

        # Load all available skills for lookup
        all_skills = {s["name"]: s for s in load_skills()}

        steps: list[dict] = []
        current_input = initial_input

        for i, skill_name in enumerate(skill_names):
            skill = all_skills.get(skill_name)
            if not skill:
                step_result = {
                    "skill": skill_name,
                    "status": "skipped",
                    "error": f"Skill '{skill_name}' not found",
                    "output": "",
                }
                steps.append(step_result)
                logger.warning(
                    "CHAIN_SKILL_MISSING chain=%s skill=%s step=%d",
                    chain_name, skill_name, i + 1,
                )
                continue

            # Build prompt with skill instructions and current input
            skill_instruction = (
                f"[SKILL: {skill['name']}]\n"
                f"Description: {skill['description']}\n\n"
                f"Follow these steps:\n{skill['body']}\n\n"
                f"[INPUT]\n{current_input[:2000]}\n[/INPUT]\n\n"
                "Produce a clear output that can be used as input for the next step."
            )

            messages = [
                {"role": "system", "content": "You are Bob, executing a skill chain step. Be concise and structured."},
                {"role": "user", "content": skill_instruction},
            ]

            result = call_llm(messages, temperature=0.5)
            if result.get("ok"):
                output = result.get("content", "")
                current_input = output  # pipe to next skill
                step_result = {
                    "skill": skill_name,
                    "status": "ok",
                    "output": output[:2000],
                }
            else:
                output = ""
                step_result = {
                    "skill": skill_name,
                    "status": "error",
                    "error": result.get("error", "LLM call failed")[:200],
                    "output": "",
                }

            steps.append(step_result)
            logger.info(
                "CHAIN_STEP chain=%s skill=%s step=%d/%d status=%s",
                chain_name, skill_name, i + 1, len(skill_names), step_result["status"],
            )

        final_output = current_input
        ok_count = sum(1 for s in steps if s["status"] == "ok")

        logger.info(
            "CHAIN_COMPLETE chain=%s steps=%d ok=%d",
            chain_name, len(steps), ok_count,
        )

        return {
            "ok": ok_count > 0,
            "chain": chain_name,
            "steps": steps,
            "final_output": final_output[:4000],
        }

    except Exception as exc:
        logger.error("CHAIN_RUN_FAIL chain=%s error=%s", chain_name, str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Chain tool wrappers (called from the tool registry)
# ---------------------------------------------------------------------------


def tool_run_chain(args: dict) -> dict:
    """Tool wrapper for run_chain -- execute a named skill chain.

    Args:
        args: Dict with keys: chain (str), input (str).

    Returns:
        Dict with chain execution results.
    """
    try:
        chain_name = str(args.get("chain", "")).strip()
        initial_input = str(args.get("input", "")).strip()
        owner_id = int(args.get("_owner_id", 1))

        if not chain_name:
            return {"ok": False, "error": "chain name is required"}
        if not initial_input:
            return {"ok": False, "error": "input text is required"}

        return run_chain(chain_name, initial_input, owner_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def tool_create_chain(args: dict) -> dict:
    """Tool wrapper for create_chain -- define a new skill chain pipeline.

    Args:
        args: Dict with keys: name (str), skills (list[str]), description (str).

    Returns:
        Dict with ok status and chain info.
    """
    try:
        name = str(args.get("name", "")).strip()
        skills = args.get("skills", [])
        description = str(args.get("description", "")).strip()

        if not name:
            return {"ok": False, "error": "chain name is required"}
        if not skills or not isinstance(skills, list):
            return {"ok": False, "error": "skills list is required"}

        skill_names = [str(s).strip() for s in skills if str(s).strip()]
        if len(skill_names) < 1:
            return {"ok": False, "error": "at least one skill is required"}

        success = create_chain(name, skill_names, description)
        if success:
            return {"ok": True, "chain_name": name, "skills_count": len(skill_names)}
        return {"ok": False, "error": f"Failed to create chain '{name}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

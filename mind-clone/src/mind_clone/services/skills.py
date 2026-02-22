"""
Skills system — reusable, versioned capability playbooks.

Skills are persistent playbooks that the agent can invoke when a user's message
matches the skill's trigger hints.  Each skill has immutable versions and an
audit trail of invocations (SkillRun).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
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

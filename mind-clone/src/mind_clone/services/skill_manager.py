"""
Markdown-based Skills System — Bob learns new behaviours through .md files.

Instead of modifying source code, Bob teaches himself new procedures by
creating markdown skill files in ~/.mind-clone/skills/. Each skill has
YAML frontmatter (name, trigger keywords, description) and a body with
step-by-step instructions that get injected into the LLM context when
a user message matches the skill's triggers.

This is part of the OpenClaw-style safe self-improvement loop:
  Skills (here) + Config Tuning + Plugins + Safe Nightly Improvement

NO source code is ever modified.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.services.skill_manager")

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


def list_skills() -> list[dict]:
    """Return all available skills with name and description.

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
# Tool wrappers (called from the tool registry)
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
    """Tool wrapper for list_skills — returns all markdown-based skills.

    Args:
        args: Dict (currently unused, reserved for future filters).

    Returns:
        Dict with ok status and list of skills.
    """
    try:
        skills = list_skills()
        return {
            "ok": True,
            "count": len(skills),
            "skills": skills,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

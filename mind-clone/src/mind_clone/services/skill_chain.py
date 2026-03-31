"""Skill Chaining -- connect skills into multi-step workflows.

Allows creating named pipelines of skills that run in sequence.
Each skill's output feeds into the next skill as context input.
Chain definitions are stored as YAML files in ~/.mind-clone/chains/.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.services.skill_chain")

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
        from .skill_manager import load_skills

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
# Tool wrappers (called from the tool registry)
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

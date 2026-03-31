"""
Safe Config Tuning — Bob adjusts his own CONFIG settings, never code.

Bob can tune whitelisted configuration values based on performance data.
For example, if search_web keeps timing out, Bob increases the timeout.
If responses are too long, Bob lowers max_tokens.

All tuning overrides are persisted in ~/.mind-clone/tuning.yaml and
loaded at startup. Only whitelisted keys can be changed, with enforced
min/max bounds. API keys, database paths, and leverage limits are
NEVER tunable.

This is part of the OpenClaw-style safe self-improvement loop:
  Skills + Config Tuning (here) + Plugins + Safe Nightly Improvement
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.services.config_tuner")

# Path to the persistent tuning overrides file
TUNING_FILE: Path = Path.home() / ".mind-clone" / "tuning.yaml"

# ---------------------------------------------------------------------------
# Whitelisted tunable keys with their types and bounds
# ---------------------------------------------------------------------------
TUNABLE_KEYS: dict[str, dict[str, Any]] = {
    "llm_temperature": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
        "default": 1.0,
        "description": "LLM sampling temperature (lower = more deterministic)",
    },
    "llm_max_tokens": {
        "type": int,
        "min": 100,
        "max": 4000,
        "default": 4096,
        "description": "Maximum tokens in LLM response",
    },
    "check_interval_seconds": {
        "type": int,
        "min": 60,
        "max": 3600,
        "default": 300,
        "description": "Interval between scheduled checks in seconds",
    },
    "scanner_sensitivity": {
        "type": float,
        "min": 0.5,
        "max": 2.0,
        "default": 1.0,
        "description": "Multiplier for 'interesting' threshold in content scanning",
    },
}

# Keys that are NEVER tunable, regardless of what Bob tries
_FORBIDDEN_KEYS: frozenset[str] = frozenset({
    "telegram_bot_token",
    "openrouter_api_key",
    "deepseek_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "kimi_api_key",
    "whatsapp_token",
    "smtp_password",
    "ssl_keyfile_password",
    "db_file_path",
    "database_url",
    "leverage_max",
    "leverage_limit",
    "max_position_size",
})


def _read_yaml_simple(path: Path) -> dict[str, Any]:
    """Read a simple key: value YAML file without requiring pyyaml.

    Handles basic types: int, float, bool, string. Does not handle
    nested objects, lists, or multi-line values.

    Args:
        path: Path to the YAML file.

    Returns:
        Dict of parsed key-value pairs.
    """
    if not path.exists():
        return {}

    data: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, raw_val = line.partition(":")
            key = key.strip()
            raw_val = raw_val.strip()

            # Type coercion
            if raw_val.lower() in ("true", "yes"):
                data[key] = True
            elif raw_val.lower() in ("false", "no"):
                data[key] = False
            else:
                try:
                    if "." in raw_val:
                        data[key] = float(raw_val)
                    else:
                        data[key] = int(raw_val)
                except ValueError:
                    data[key] = raw_val
    except Exception as exc:
        logger.warning("TUNING_READ_FAIL path=%s error=%s", path, str(exc)[:200])

    return data


def _write_yaml_simple(path: Path, data: dict[str, Any]) -> None:
    """Write a simple key: value YAML file.

    Args:
        path: Path to the YAML file.
        data: Dict of key-value pairs to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Bob's auto-tuning overrides (managed by config_tuner.py)"]
    lines.append(f"# Last updated by safe self-improvement system")
    lines.append("")
    for key, val in sorted(data.items()):
        lines.append(f"{key}: {val}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def get_tunable_settings() -> dict[str, Any]:
    """Return current tunable settings with their values and metadata.

    Merges defaults with any overrides from tuning.yaml.

    Returns:
        Dict mapping setting name to a dict of value, default, min, max, description.
    """
    overrides = load_tuning_overrides()
    result: dict[str, Any] = {}

    for key, meta in TUNABLE_KEYS.items():
        current = overrides.get(key, meta["default"])
        result[key] = {
            "value": current,
            "default": meta["default"],
            "min": meta["min"],
            "max": meta["max"],
            "type": meta["type"].__name__,
            "description": meta["description"],
            "overridden": key in overrides,
        }

    return result


def tune_setting(key: str, value: Any) -> dict[str, Any]:
    """Safely change a config value. Only whitelisted keys are allowed.

    The new value is clamped to the key's min/max bounds and persisted
    to ~/.mind-clone/tuning.yaml.

    Args:
        key: The setting name (must be in TUNABLE_KEYS).
        value: The new value to set.

    Returns:
        Dict with ok status, the final value, and any notes.
    """
    # Safety: reject forbidden keys
    if key in _FORBIDDEN_KEYS:
        logger.warning("TUNING_BLOCKED_FORBIDDEN key=%s", key)
        return {
            "ok": False,
            "error": f"Key '{key}' is forbidden and cannot be tuned",
        }

    # Check whitelist
    if key not in TUNABLE_KEYS:
        return {
            "ok": False,
            "error": f"Key '{key}' is not tunable. Tunable keys: {list(TUNABLE_KEYS.keys())}",
        }

    meta = TUNABLE_KEYS[key]
    target_type = meta["type"]

    try:
        typed_value = target_type(value)
    except (ValueError, TypeError) as exc:
        return {
            "ok": False,
            "error": f"Cannot convert '{value}' to {target_type.__name__}: {exc}",
        }

    # Clamp to bounds
    clamped = max(meta["min"], min(meta["max"], typed_value))
    notes = ""
    if clamped != typed_value:
        notes = f"Value clamped from {typed_value} to {clamped} (bounds: {meta['min']}-{meta['max']})"

    # Load existing overrides, update, and save
    try:
        overrides = load_tuning_overrides()
        old_value = overrides.get(key, meta["default"])
        overrides[key] = clamped
        _write_yaml_simple(TUNING_FILE, overrides)

        logger.info(
            "TUNING_SET key=%s old=%s new=%s",
            key, old_value, clamped,
        )

        return {
            "ok": True,
            "key": key,
            "old_value": old_value,
            "new_value": clamped,
            "notes": notes,
        }
    except Exception as exc:
        logger.error("TUNING_SAVE_FAIL key=%s error=%s", key, str(exc)[:200])
        return {"ok": False, "error": f"Failed to save tuning: {exc}"}


def load_tuning_overrides() -> dict[str, Any]:
    """Load tuning.yaml and return overrides.

    Only returns keys that are in the whitelist. Any unknown or
    forbidden keys in the file are silently ignored.

    Returns:
        Dict of valid tuning overrides.
    """
    raw = _read_yaml_simple(TUNING_FILE)

    # Filter to only whitelisted, non-forbidden keys
    overrides: dict[str, Any] = {}
    for key, val in raw.items():
        if key in _FORBIDDEN_KEYS:
            logger.warning("TUNING_OVERRIDE_BLOCKED_FORBIDDEN key=%s", key)
            continue
        if key not in TUNABLE_KEYS:
            continue

        meta = TUNABLE_KEYS[key]
        try:
            typed_val = meta["type"](val)
            clamped = max(meta["min"], min(meta["max"], typed_val))
            overrides[key] = clamped
        except (ValueError, TypeError):
            logger.warning("TUNING_OVERRIDE_BAD_TYPE key=%s value=%s", key, val)

    return overrides


def auto_tune_from_performance(owner_id: int) -> dict[str, Any]:
    """Read tool performance stats and auto-tune config if needed.

    Rules:
    - If a tool has <50% success rate over recent calls, adjust related settings.
    - search_web / read_webpage failures -> no direct config knob yet, just report.
    - High token usage -> suggest lowering llm_max_tokens.
    - General poor performance -> lower temperature for more deterministic outputs.

    Args:
        owner_id: The owner/user ID to pull stats for.

    Returns:
        Dict describing what was changed (if anything).
    """
    changes: list[dict[str, Any]] = []

    try:
        from ..database.session import SessionLocal
        from ..database.models import ToolPerformanceLog
        from datetime import datetime, timedelta, timezone

        db = SessionLocal()
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            rows = (
                db.query(ToolPerformanceLog)
                .filter(
                    ToolPerformanceLog.owner_id == owner_id,
                    ToolPerformanceLog.created_at >= since,
                )
                .all()
            )

            if not rows:
                return {
                    "ok": True,
                    "changes": [],
                    "message": "No performance data in last 24h — nothing to tune",
                }

            # Aggregate per tool
            tool_stats: dict[str, dict[str, int]] = {}
            for row in rows:
                name = row.tool_name
                if name not in tool_stats:
                    tool_stats[name] = {"total": 0, "success": 0, "fail": 0}
                tool_stats[name]["total"] += 1
                if row.success:
                    tool_stats[name]["success"] += 1
                else:
                    tool_stats[name]["fail"] += 1

            # Identify struggling tools
            struggling: list[str] = []
            for tool_name, stats in tool_stats.items():
                if stats["total"] >= 3:
                    success_rate = stats["success"] / stats["total"]
                    if success_rate < 0.5:
                        struggling.append(tool_name)

            overrides = load_tuning_overrides()

            # Rule: if many tools are failing, lower temperature for stability
            if len(struggling) >= 2:
                current_temp = overrides.get(
                    "llm_temperature",
                    TUNABLE_KEYS["llm_temperature"]["default"],
                )
                if current_temp > 0.4:
                    new_temp = max(0.3, current_temp - 0.2)
                    result = tune_setting("llm_temperature", new_temp)
                    if result.get("ok"):
                        changes.append({
                            "key": "llm_temperature",
                            "reason": f"Multiple tools struggling ({', '.join(struggling[:3])})",
                            "old": current_temp,
                            "new": new_temp,
                        })

            # Rule: if LLM-related tools fail, reduce max_tokens to avoid truncation issues
            llm_tools = {"execute_python", "llm_structured_task", "deep_research"}
            llm_struggling = [t for t in struggling if t in llm_tools]
            if llm_struggling:
                current_tokens = overrides.get(
                    "llm_max_tokens",
                    TUNABLE_KEYS["llm_max_tokens"]["default"],
                )
                if current_tokens > 2000:
                    new_tokens = max(1500, current_tokens - 500)
                    result = tune_setting("llm_max_tokens", new_tokens)
                    if result.get("ok"):
                        changes.append({
                            "key": "llm_max_tokens",
                            "reason": f"LLM tools struggling ({', '.join(llm_struggling)})",
                            "old": current_tokens,
                            "new": new_tokens,
                        })

        finally:
            db.close()

    except Exception as exc:
        logger.error("AUTO_TUNE_FAIL owner=%d error=%s", owner_id, str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300], "changes": changes}

    logger.info(
        "AUTO_TUNE_COMPLETE owner=%d changes=%d",
        owner_id, len(changes),
    )
    return {
        "ok": True,
        "changes": changes,
        "message": f"Auto-tuned {len(changes)} setting(s)" if changes else "No tuning needed",
    }

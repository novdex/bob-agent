"""Config migration -- handles upgrades between Bob versions.

When Bob updates, config is automatically migrated to the new format.
Migrations are stored as simple functions keyed by version number.
Each migration takes a config dict and returns the upgraded dict.

Usage:
    from mind_clone.core.config_migration import ensure_config_up_to_date

    # Call once on startup
    ensure_config_up_to_date()
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Dict, Any

logger = logging.getLogger("mind_clone.core.config_migration")

# Current config version -- bump this when adding new migrations
CONFIG_VERSION = 2

# Path to the version marker file
_VERSION_FILE_NAME = "config_version.txt"


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------

def _get_config_dir() -> Path:
    """Return the config directory (``~/.mind-clone/``), creating it if needed."""
    config_dir = Path.home() / ".mind-clone"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create config dir %s: %s", config_dir, exc)
    return config_dir


def get_config_version() -> int:
    """Read the current config version from disk.

    Returns:
        The version number (int), or 1 if the file doesn't exist
        (assumes a fresh / v1 install).
    """
    version_file = _get_config_dir() / _VERSION_FILE_NAME
    try:
        if version_file.exists():
            content = version_file.read_text(encoding="utf-8").strip()
            return int(content)
    except (ValueError, OSError) as exc:
        logger.warning("Could not read config version: %s", exc)
    return 1  # Default to v1


def set_config_version(version: int) -> None:
    """Write the config version to disk.

    Args:
        version: The version number to persist.
    """
    version_file = _get_config_dir() / _VERSION_FILE_NAME
    try:
        version_file.write_text(str(version), encoding="utf-8")
        logger.info("Config version set to %d", version)
    except OSError as exc:
        logger.error("Could not write config version: %s", exc)


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

def _migrate_v1_to_v2(config: dict) -> dict:
    """Migrate config from v1 to v2.

    Adds default values for new settings introduced in v2:
    - ``session_max_age_hours``: How long sessions live (default 24).
    - ``gateway_enabled``: Whether the gateway layer is active (default True).
    - ``adapter_channels``: List of enabled channel adapters.
    - ``auto_fix_on_startup``: Run doctor auto-fix on boot (default True).
    - ``config_version``: Embedded version for self-reference.

    Args:
        config: The v1 config dict.

    Returns:
        The upgraded v2 config dict (original is not mutated).
    """
    upgraded = dict(config)

    # New defaults for v2
    v2_defaults: Dict[str, Any] = {
        "session_max_age_hours": 24,
        "gateway_enabled": True,
        "adapter_channels": ["telegram", "cron"],
        "auto_fix_on_startup": True,
        "config_version": 2,
    }

    for key, default in v2_defaults.items():
        if key not in upgraded:
            upgraded[key] = default
            logger.info("Migration v1->v2: added %s = %r", key, default)

    return upgraded


# Migration registry -- key is the SOURCE version, value is the migration fn
MIGRATIONS: Dict[int, Callable[[dict], dict]] = {
    1: _migrate_v1_to_v2,
}


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def run_migrations(config: dict | None = None) -> dict:
    """Check current version and run all needed migrations in order.

    Args:
        config: Optional config dict to migrate.  If None, an empty
            dict is used (useful when config is managed by env vars).

    Returns:
        A summary dict with ``ok``, ``from_version``, ``to_version``,
        ``migrations_run``, and the final ``config``.
    """
    if config is None:
        config = {}

    current_version = get_config_version()
    from_version = current_version
    migrations_run: list[str] = []

    logger.info(
        "Config migration check: current_version=%d target=%d",
        current_version, CONFIG_VERSION,
    )

    while current_version < CONFIG_VERSION:
        migration_fn = MIGRATIONS.get(current_version)
        if migration_fn is None:
            logger.error(
                "No migration found for version %d -> %d",
                current_version, current_version + 1,
            )
            break

        try:
            label = f"v{current_version}->v{current_version + 1}"
            logger.info("Running migration %s ...", label)
            config = migration_fn(config)
            current_version += 1
            migrations_run.append(label)
        except Exception as exc:
            logger.error("Migration %s failed: %s", label, exc)
            break

    # Persist the new version
    if current_version != from_version:
        set_config_version(current_version)

    summary = {
        "ok": current_version == CONFIG_VERSION,
        "from_version": from_version,
        "to_version": current_version,
        "target_version": CONFIG_VERSION,
        "migrations_run": migrations_run,
        "config": config,
    }

    if migrations_run:
        logger.info(
            "Config migrated: %s (v%d -> v%d)",
            ", ".join(migrations_run), from_version, current_version,
        )
    else:
        logger.debug("Config is up to date (v%d)", current_version)

    return summary


def ensure_config_up_to_date(config: dict | None = None) -> dict:
    """Run migrations if needed.  Safe to call on every startup.

    This is the recommended entry point -- call it once during
    application boot.

    Args:
        config: Optional config dict.

    Returns:
        The migrated config dict (or original if no migration needed).
    """
    try:
        result = run_migrations(config)
        return result.get("config", config or {})
    except Exception as exc:
        logger.error("Config migration failed: %s", exc)
        return config or {}


# ---------------------------------------------------------------------------
# Utility: save / load config from JSON
# ---------------------------------------------------------------------------

def save_config_snapshot(config: dict) -> bool:
    """Save a config snapshot to ``~/.mind-clone/config_snapshot.json``.

    Args:
        config: The config dict to persist.

    Returns:
        True on success.
    """
    snapshot_path = _get_config_dir() / "config_snapshot.json"
    try:
        snapshot_path.write_text(
            json.dumps(config, indent=2, default=str),
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        logger.error("Could not save config snapshot: %s", exc)
        return False


def load_config_snapshot() -> dict:
    """Load the last config snapshot from disk.

    Returns:
        The config dict, or an empty dict if not found.
    """
    snapshot_path = _get_config_dir() / "config_snapshot.json"
    try:
        if snapshot_path.exists():
            return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load config snapshot: %s", exc)
    return {}


__all__ = [
    "CONFIG_VERSION",
    "get_config_version",
    "set_config_version",
    "run_migrations",
    "ensure_config_up_to_date",
    "save_config_snapshot",
    "load_config_snapshot",
]

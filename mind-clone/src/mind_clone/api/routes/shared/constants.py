"""
Constants, configuration values, and environment variables for API routes.
"""

from __future__ import annotations

import os
from pathlib import Path

from ....config import settings


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# Config imports - settings is a singleton instance of Settings class
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TOKEN_PLACEHOLDER = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
KIMI_MODEL = settings.kimi_model
KIMI_FALLBACK_MODEL = settings.kimi_fallback_model
OPS_AUTH_ENABLED = False  # Default, may be overridden
OPS_AUTH_TOKEN = os.getenv("OPS_AUTH_TOKEN", "")
OPS_AUTH_REQUIRE_SIGNATURE = _env_flag("OPS_AUTH_REQUIRE_SIGNATURE", False)
OPS_AUTH_ROLE_SECRETS = {}  # Default empty
OPS_AUTH_ALLOWED_ROLES = set()
OPS_AUTH_SIGNATURE_SKEW_SECONDS = 300
BLACKBOX_ENABLED = settings.blackbox_enabled
NODE_CONTROL_PLANE_ENABLED = settings.node_control_plane_enabled
HEARTBEAT_AUTONOMY_ENABLED = _env_flag("HEARTBEAT_AUTONOMY_ENABLED", False)
CRON_ENABLED = settings.cron_enabled
TEAM_MODE_ENABLED = settings.team_mode_enabled
TEAM_AGENT_DEFAULT_KEY = settings.team_agent_default_key
TEAM_BROADCAST_ENABLED = settings.team_broadcast_enabled
IDENTITY_SCOPE_MODE = settings.identity_scope_mode
WORKFLOW_V2_ENABLED = settings.workflow_v2_enabled
WORKFLOW_LOOP_MAX_ITERATIONS = settings.workflow_loop_max_iterations
WORKFLOW_MAX_STEPS = 100
EVAL_MAX_CASES = int(os.getenv("EVAL_MAX_CASES", "50"))
EVENT_STREAM_POLL_SECONDS = float(os.getenv("EVENT_STREAM_POLL_SECONDS", "0.5"))
EVENT_STREAM_BATCH_SIZE = int(os.getenv("EVENT_STREAM_BATCH_SIZE", "100"))
MEMORY_VAULT_ROOT = Path(
    os.getenv("MEMORY_VAULT_ROOT", str(settings.app_dir / "persist" / "memory_vault"))
)
UI_DIST_DIR = settings.ui_dist_dir
NODE_AUTO_CAPABILITY_DEFAULT = os.getenv("NODE_AUTO_CAPABILITY_DEFAULT", "general")
NODE_SCHEDULER_LEASE_PENALTY = float(os.getenv("NODE_SCHEDULER_LEASE_PENALTY", "10.0"))
NODE_SCHEDULER_FAILURE_PENALTY = float(os.getenv("NODE_SCHEDULER_FAILURE_PENALTY", "50.0"))
NODE_SCHEDULER_LATENCY_PENALTY = float(os.getenv("NODE_SCHEDULER_LATENCY_PENALTY", "5.0"))
NODE_SCHEDULER_RECOVERY_BONUS = float(os.getenv("NODE_SCHEDULER_RECOVERY_BONUS", "20.0"))
NODE_SCHEDULER_FAILURE_WINDOW_SECONDS = int(
    os.getenv("NODE_SCHEDULER_FAILURE_WINDOW_SECONDS", "300")
)
TASK_CHECKPOINT_REPLAY_STRICT = _env_flag("TASK_CHECKPOINT_REPLAY_STRICT", True)
TASK_STATUS_QUEUED = "queued"

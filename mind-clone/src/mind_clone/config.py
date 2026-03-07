"""
Configuration module for Mind Clone Agent.

All settings are loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Set, List, Dict, Optional, Any, Annotated
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_list(raw_value: str) -> List[str]:
    """Parse comma-separated values."""
    raw = (raw_value or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_path_list(raw_value: str) -> List[Path]:
    """Parse semicolon-separated paths."""
    raw = (raw_value or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    paths = []
    for item in parts:
        try:
            paths.append(Path(os.path.expandvars(item)).expanduser().resolve(strict=False))
        except Exception:
            continue
    return paths


def _default_runtime_dir() -> Path:
    """Get default runtime directory."""
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "mind-clone"
    return Path.home() / ".mind-clone"


class Settings(BaseSettings):
    """Mind Clone Agent settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # API Keys
    # =========================================================================
    kimi_api_key: str = Field(default="YOUR_KIMI_API_KEY_HERE", alias="KIMI_API_KEY")
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    kimi_model: str = "kimi-k2.5"
    kimi_fallback_model: str = Field(default="", alias="KIMI_FALLBACK_MODEL")

    telegram_bot_token: str = Field(
        default="YOUR_TELEGRAM_BOT_TOKEN_HERE", alias="TELEGRAM_BOT_TOKEN"
    )
    webhook_base_url: str = Field(default="https://your-domain.com", alias="WEBHOOK_BASE_URL")

    # SSL/TLS
    ssl_certfile: str = Field(default="", alias="SSL_CERTFILE")
    ssl_keyfile: str = Field(default="", alias="SSL_KEYFILE")
    ssl_keyfile_password: str = Field(default="", alias="SSL_KEYFILE_PASSWORD")

    # =========================================================================
    # LLM Settings
    # =========================================================================
    llm_temperature: float = 1.0
    llm_max_tokens: int = 4096
    llm_request_timeout_seconds: int = 120
    llm_failover_enabled: bool = Field(default=True, alias="LLM_FAILOVER_ENABLED")
    llm_structured_task_enabled: bool = Field(default=True, alias="LLM_STRUCTURED_TASK_ENABLED")
    llm_structured_task_max_attempts: int = 2

    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: int = 60

    # =========================================================================
    # Email (SMTP)
    # =========================================================================
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_name: str = Field(default="Bob Agent", alias="SMTP_FROM_NAME")

    # =========================================================================
    # Policy & Autonomy
    # =========================================================================
    policy_pack: str = Field(default="dev", alias="POLICY_PACK")
    autonomy_mode: str = Field(default="openclaw_max", alias="AUTONOMY_MODE")

    # =========================================================================
    # Budget Governor
    # =========================================================================
    budget_governor_enabled: bool = Field(default=True, alias="BUDGET_GOVERNOR_ENABLED")
    budget_governor_mode: str = Field(default="degrade", alias="BUDGET_GOVERNOR_MODE")
    budget_max_seconds: int = 180
    budget_max_tool_calls: int = 40
    budget_max_llm_calls: int = 24
    budget_max_est_tokens: int = 90000
    budget_degrade_at_percent: int = 80

    # =========================================================================
    # Workspace & Security
    # =========================================================================
    workspace_diff_gate_enabled: bool = Field(default=True, alias="WORKSPACE_DIFF_GATE_ENABLED")
    workspace_diff_gate_mode: str = Field(default="approval", alias="WORKSPACE_DIFF_GATE_MODE")
    workspace_diff_max_changed_lines: int = 260
    workspace_diff_max_file_bytes: int = 350_000

    secret_guardrail_enabled: bool = Field(default=True, alias="SECRET_GUARDRAIL_ENABLED")
    secret_redaction_token: str = Field(default="[REDACTED]", alias="SECRET_REDACTION_TOKEN")
    secret_redaction_max_hits: int = 50

    # =========================================================================
    # Command Queue
    # =========================================================================
    command_queue_mode: str = Field(default="auto", alias="COMMAND_QUEUE_MODE")
    command_queue_max_size: int = 200
    command_queue_auto_backpressure: int = 1
    command_queue_worker_count: int = 2
    command_queue_collect_window_seconds: int = 4

    # =========================================================================
    # Tool Policy
    # =========================================================================
    tool_policy_profile: str = Field(default="balanced", alias="TOOL_POLICY_PROFILE")
    tool_policy_allow_extra_write_roots: Annotated[List[Path], NoDecode] = Field(
        default_factory=list, alias="TOOL_POLICY_WRITE_ROOTS"
    )

    # =========================================================================
    # Execution Sandbox
    # =========================================================================
    execution_sandbox_profile: str = Field(default="default", alias="EXECUTION_SANDBOX_PROFILE")
    execution_sandbox_remote_allowlist: Annotated[Set[str], NoDecode] = Field(
        default_factory=set, alias="EXECUTION_SANDBOX_REMOTE_ALLOWLIST"
    )

    os_sandbox_mode: str = Field(default="docker", alias="OS_SANDBOX_MODE")
    os_sandbox_required: bool = Field(default=True, alias="OS_SANDBOX_REQUIRED")
    os_sandbox_docker_image: str = "python:3.11-slim"
    os_sandbox_docker_network: str = "none"
    os_sandbox_docker_cpus: float = 1.0
    os_sandbox_docker_memory_mb: int = 512

    # =========================================================================
    # Desktop Control
    # =========================================================================
    desktop_control_enabled: bool = Field(default=True, alias="DESKTOP_CONTROL_ENABLED")
    desktop_failsafe_enabled: bool = Field(default=True, alias="DESKTOP_FAILSAFE_ENABLED")
    desktop_action_pause_seconds: float = 0.05
    desktop_default_move_duration: float = 0.08
    desktop_default_type_interval: float = 0.01
    desktop_require_active_session: bool = Field(
        default=True, alias="DESKTOP_REQUIRE_ACTIVE_SESSION"
    )
    desktop_replay_max_steps: int = 800
    desktop_image_match_threshold: float = 0.86

    # =========================================================================
    # Browser
    # =========================================================================
    browser_tool_enabled: bool = Field(default=True, alias="BROWSER_TOOL_ENABLED")
    browser_headless_default: bool = Field(default=False, alias="BROWSER_HEADLESS_DEFAULT")
    browser_session_timeout_seconds: int = 300
    tool_chaining_hints_enabled: bool = Field(default=True, alias="TOOL_CHAINING_HINTS_ENABLED")

    # =========================================================================
    # Team Mode
    # =========================================================================
    team_mode_enabled: bool = Field(default=True, alias="TEAM_MODE_ENABLED")
    team_agent_max_per_owner: int = 12
    team_agent_default_key: str = "main"
    team_broadcast_enabled: bool = Field(default=True, alias="TEAM_BROADCAST_ENABLED")
    identity_scope_mode: str = Field(default="strict_chat", alias="IDENTITY_SCOPE_MODE")
    workflow_v2_enabled: bool = Field(default=True, alias="WORKFLOW_V2_ENABLED")
    workflow_loop_max_iterations: int = 8

    # =========================================================================
    # Approval Gate
    # =========================================================================
    approval_gate_mode: str = Field(default="balanced", alias="APPROVAL_GATE_MODE")
    approval_token_ttl_minutes: int = 240
    approval_required_tools: Annotated[Set[str], NoDecode] = Field(
        default_factory=lambda: {"run_command", "execute_python", "write_file", "run_command_node"},
        alias="APPROVAL_REQUIRED_TOOLS",
    )

    # =========================================================================
    # Cron
    # =========================================================================
    cron_enabled: bool = Field(default=True, alias="CRON_ENABLED")
    cron_tick_seconds: int = 10
    cron_min_interval_seconds: int = 60
    cron_max_due_per_tick: int = 10

    # =========================================================================
    # Memory & Session
    # =========================================================================
    history_compact_trigger_messages: int = 120
    history_recent_keep_messages: int = 45
    session_soft_trim_enabled: bool = Field(default=True, alias="SESSION_SOFT_TRIM_ENABLED")
    session_soft_trim_char_budget: int = 42000
    task_artifact_retrieve_top_k: int = 3
    task_artifact_max_per_user: int = 600
    lesson_max_per_user: int = 400

    # =========================================================================
    # Blackbox Logging
    # =========================================================================
    blackbox_enabled: bool = Field(default=True, alias="BLACKBOX_ENABLED")
    blackbox_payload_max_chars: int = 6000

    # =========================================================================
    # Node Control Plane
    # =========================================================================
    node_control_plane_enabled: bool = Field(default=True, alias="NODE_CONTROL_PLANE_ENABLED")
    node_heartbeat_stale_seconds: int = 90
    node_lease_ttl_seconds: int = 180

    # =========================================================================
    # SSRF Protection
    # =========================================================================
    ssrf_guard_enabled: bool = Field(default=True, alias="SSRF_GUARD_ENABLED")
    ssrf_allow_private_net: bool = Field(default=False, alias="SSRF_ALLOW_PRIVATE_NET")
    ssrf_block_localhost: bool = Field(default=True, alias="SSRF_BLOCK_LOCALHOST")
    ssrf_allow_hosts: str = Field(default="", alias="SSRF_ALLOW_HOSTS")
    ssrf_deny_hosts: str = Field(default="", alias="SSRF_DENY_HOSTS")
    ssrf_resolve_timeout_seconds: int = Field(default=2, alias="SSRF_RESOLVE_TIMEOUT_SECONDS")

    # =========================================================================
    # Skills System
    # =========================================================================
    skills_enabled: bool = Field(default=True, alias="SKILLS_ENABLED")
    skills_auto_create_enabled: bool = Field(default=True, alias="SKILLS_AUTO_CREATE_ENABLED")
    skills_auto_activate_enabled: bool = Field(default=True, alias="SKILLS_AUTO_ACTIVATE_ENABLED")
    skills_auto_create_cooldown_seconds: int = Field(default=600, alias="SKILLS_AUTO_CREATE_COOLDOWN_SECONDS")
    skills_max_per_owner: int = Field(default=120, alias="SKILLS_MAX_PER_OWNER")
    skills_active_top_k: int = Field(default=3, alias="SKILLS_ACTIVE_TOP_K")

    # =========================================================================
    # Custom Tool Creation
    # =========================================================================
    custom_tool_enabled: bool = Field(default=True, alias="CUSTOM_TOOL_ENABLED")
    custom_tool_max_per_user: int = Field(default=30, alias="CUSTOM_TOOL_MAX_PER_USER")
    custom_tool_max_code_size: int = Field(default=5000, alias="CUSTOM_TOOL_MAX_CODE_SIZE")
    custom_tool_sandbox_timeout: int = Field(default=15, alias="CUSTOM_TOOL_SANDBOX_TIMEOUT")
    custom_tool_trust_mode: str = Field(default="safe", alias="CUSTOM_TOOL_TRUST_MODE")

    # =========================================================================
    # Discord Integration
    # =========================================================================
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    discord_enabled: bool = Field(default=False, alias="DISCORD_ENABLED")

    # =========================================================================
    # Voice STT (Speech-to-Text)
    # =========================================================================
    stt_api_key: str = Field(default="", alias="STT_API_KEY")
    stt_api_base: str = Field(default="https://api.openai.com/v1", alias="STT_API_BASE")

    # =========================================================================
    # Host Exec Interlock
    # =========================================================================
    host_exec_interlock_enabled: bool = Field(default=True, alias="HOST_EXEC_INTERLOCK_ENABLED")
    host_exec_allowlist_prefixes: Annotated[List[str], NoDecode] = Field(
        default_factory=list, alias="HOST_EXEC_ALLOWLIST_PREFIXES"
    )

    @field_validator("tool_policy_allow_extra_write_roots", mode="before")
    @classmethod
    def _validate_tool_policy_write_roots(cls, value: Any) -> List[Path]:
        if value is None:
            return []
        if isinstance(value, str):
            return _parse_path_list(value)
        if isinstance(value, Path):
            return [value]
        if isinstance(value, (list, tuple, set)):
            out: List[Path] = []
            for item in value:
                if item is None:
                    continue
                try:
                    out.append(Path(str(item)).expanduser().resolve(strict=False))
                except Exception:
                    continue
            return out
        return []

    @field_validator("execution_sandbox_remote_allowlist", mode="before")
    @classmethod
    def _validate_remote_allowlist(cls, value: Any) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return set(_parse_csv_list(value))
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        return set()

    @field_validator("approval_required_tools", mode="before")
    @classmethod
    def _validate_approval_required_tools(cls, value: Any) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return set(_parse_csv_list(value))
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        return set()

    @field_validator("host_exec_allowlist_prefixes", mode="before")
    @classmethod
    def _validate_host_exec_allowlist_prefixes(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _parse_csv_list(value)
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    # =========================================================================
    # Tool Performance & Plugin Trust
    # =========================================================================
    TOOL_PERF_TRACKING_ENABLED: bool = Field(default=True, alias="TOOL_PERF_TRACKING_ENABLED")
    PLUGIN_ENFORCE_TRUST: bool = Field(default=False, alias="PLUGIN_ENFORCE_TRUST")

    # =========================================================================
    # Paths
    # =========================================================================
    @property
    def app_dir(self) -> Path:
        """Get application directory."""
        return Path(__file__).resolve().parent.parent

    @property
    def repo_root_dir(self) -> Path:
        """Get repository root directory."""
        return self.app_dir.parent

    @property
    def ui_dist_dir(self) -> Path:
        """Get UI distribution directory."""
        return self.repo_root_dir / "mind-clone-ui" / "dist"

    @property
    def db_file_path(self) -> Path:
        """Get database file path."""
        configured = os.getenv("MIND_CLONE_DB_PATH")
        if configured:
            return Path(os.path.expandvars(configured)).expanduser().resolve(strict=False)
        return _default_runtime_dir() / "mind_clone.db"

    @property
    def desktop_screenshot_dir(self) -> Path:
        """Get desktop screenshot directory."""
        return self.app_dir / "persist" / "desktop" / "screenshots"

    @property
    def desktop_session_dir(self) -> Path:
        """Get desktop session directory."""
        return self.app_dir / "persist" / "desktop" / "sessions"

    # =========================================================================
    # Derived Properties
    # =========================================================================
    @property
    def autonomy_openclaw_max(self) -> bool:
        """Check if autonomy mode is openclaw_max."""
        return self.autonomy_mode == "openclaw_max"

    @property
    def policy_pack_preset(self) -> Dict:
        """Get policy pack preset configuration."""
        presets = {
            "dev": {
                "command_queue_mode": "auto",
                "tool_policy_profile": "power",
                "execution_sandbox_profile": "power",
                "approval_gate_mode": "balanced",
                "budget_mode": "warn",
            },
            "staging": {
                "command_queue_mode": "auto",
                "tool_policy_profile": "balanced",
                "execution_sandbox_profile": "default",
                "approval_gate_mode": "balanced",
                "budget_mode": "degrade",
            },
            "prod": {
                "command_queue_mode": "on",
                "tool_policy_profile": "safe",
                "execution_sandbox_profile": "strict",
                "approval_gate_mode": "strict",
                "budget_mode": "stop",
            },
        }
        return presets.get(self.policy_pack, presets["dev"])


# Global settings instance
settings = Settings()

# Convenience exports for commonly used settings
# Telegram settings
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TELEGRAM_WEBHOOK_BASE_URL = settings.webhook_base_url

# SSL/TLS
SSL_CERTFILE = settings.ssl_certfile
SSL_KEYFILE = settings.ssl_keyfile
SSL_KEYFILE_PASSWORD = settings.ssl_keyfile_password
WEBHOOK_BASE_URL = settings.webhook_base_url

# SSL/TLS
SSL_CERTFILE = settings.ssl_certfile
SSL_KEYFILE = settings.ssl_keyfile
SSL_KEYFILE_PASSWORD = settings.ssl_keyfile_password
TOKEN_PLACEHOLDER = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

# Model settings
KIMI_MODEL = settings.kimi_model
KIMI_FALLBACK_MODEL = settings.kimi_fallback_model
KIMI_API_KEY = settings.kimi_api_key
KIMI_BASE_URL = settings.kimi_base_url
LLM_FAILOVER_ENABLED = settings.llm_failover_enabled
LLM_REQUEST_TIMEOUT_SECONDS = settings.llm_request_timeout_seconds

# Autonomy & Policy
AUTONOMY_MODE = settings.autonomy_mode
AUTONOMY_OPENCLAW_MAX = settings.autonomy_openclaw_max
POLICY_PACK = settings.policy_pack
POLICY_PACK_PRESETS = settings.policy_pack_preset

# Budget Governor
BUDGET_GOVERNOR_ENABLED = settings.budget_governor_enabled
BUDGET_GOVERNOR_MODE = settings.budget_governor_mode
BUDGET_MAX_SECONDS = settings.budget_max_seconds
BUDGET_MAX_TOOL_CALLS = settings.budget_max_tool_calls
BUDGET_MAX_LLM_CALLS = settings.budget_max_llm_calls
BUDGET_DEGRADE_AT_PERCENT = settings.budget_degrade_at_percent

# Approval & Security
APPROVAL_GATE_MODE = settings.approval_gate_mode
APPROVAL_TOKEN_TTL_MINUTES = settings.approval_token_ttl_minutes
APPROVAL_REQUIRED_TOOLS = settings.approval_required_tools
SECRET_GUARDRAIL_ENABLED = True  # Default value
SECRET_GUARDRAIL_MASKED_COUNT = 3  # Default value
SECRET_GUARDRAIL_DENY_LIST = []  # Default value

# Workspace Diff Gate
WORKSPACE_DIFF_GATE_ENABLED = settings.workspace_diff_gate_enabled
WORKSPACE_DIFF_GATE_MODE = settings.workspace_diff_gate_mode
WORKSPACE_DIFF_MAX_CHANGED_LINES = settings.workspace_diff_max_changed_lines
WORKSPACE_DIFF_MAX_FILE_BYTES = settings.workspace_diff_max_file_bytes
WORKSPACE_ISOLATION_ENABLED = True  # Default value
WORKSPACE_ISOLATION_DEFAULT_ROOT = None  # Default value
WORKSPACE_SESSION_ISOLATION_ENABLED = True  # Default value
WORKSPACE_SOFT_DELETE_ENABLED = True  # Default value
WORKSPACE_SESSION_ROOT = None  # Default value
WORKSPACE_PERSIST_ROOT = None  # Default value
WORKSPACE_DIFF_SNAPSHOT_RETENTION_HOURS = 24  # Default value

# Features
CRON_ENABLED = settings.cron_enabled
CRON_TICK_SECONDS = settings.cron_tick_seconds
DESKTOP_CONTROL_ENABLED = settings.desktop_control_enabled
DESKTOP_FAILSAFE_ENABLED = settings.desktop_failsafe_enabled
BROWSER_TOOL_ENABLED = settings.browser_tool_enabled
BLACKBOX_ENABLED = settings.blackbox_enabled
TEAM_MODE_ENABLED = settings.team_mode_enabled
WORKFLOW_V2_ENABLED = settings.workflow_v2_enabled
WORKFLOW_LOOP_MAX_ITERATIONS = settings.workflow_loop_max_iterations
WORKFLOW_MAX_STEPS = 50  # Default value

# Queue
COMMAND_QUEUE_MODE = settings.command_queue_mode
COMMAND_QUEUE_MAX_SIZE = settings.command_queue_max_size
COMMAND_QUEUE_WORKER_COUNT = settings.command_queue_worker_count
COMMAND_QUEUE_AUTO_BACKPRESSURE = settings.command_queue_auto_backpressure
COMMAND_QUEUE_LANE_LIMITS = {"interactive": 50, "background": 100, "batch": 200}

# Node control
NODE_CONTROL_PLANE_ENABLED = settings.node_control_plane_enabled

# Eval
EVAL_MAX_CASES = 12  # Default value

# Paths
APP_DIR = settings.app_dir
DB_FILE_PATH = settings.db_file_path

# Email
SMTP_HOST = settings.smtp_host
SMTP_PORT = settings.smtp_port
SMTP_USERNAME = settings.smtp_username
SMTP_PASSWORD = settings.smtp_password
NOTIFICATION_EMAIL = settings.smtp_username  # Use username as notification email
SMTP_FROM_NAME = settings.smtp_from_name

# Additional config exports for telegram.py and task_engine.py
SECRET_REDACTION_TOKEN = "***REDACTED***"  # Default value
OS_SANDBOX_MODE = "disabled"  # Default value
OS_SANDBOX_REQUIRED = False  # Default value
HOST_EXEC_INTERLOCK_ENABLED = True  # Default value
DESKTOP_REQUIRE_ACTIVE_SESSION = True  # Default value
CRON_MIN_INTERVAL_SECONDS = 60  # Default value
CRON_MAX_DUE_PER_TICK = 10  # Default value
CRON_BOOTSTRAP_JOBS_JSON = None  # Default value
HEARTBEAT_AUTONOMY_ENABLED = True  # Default value
HEARTBEAT_INTERVAL_SECONDS = 60  # Default value
EVAL_HARNESS_ENABLED = True  # Default value

# Desktop Control - missing exports
DESKTOP_ACTION_PAUSE_SECONDS = 0.05
DESKTOP_DEFAULT_MOVE_DURATION = 0.08
DESKTOP_DEFAULT_TYPE_INTERVAL = 0.01
DESKTOP_SCREENSHOT_DIR = APP_DIR / "persist" / "desktop" / "screenshots"
DESKTOP_SESSION_DIR = APP_DIR / "persist" / "desktop" / "sessions"
DESKTOP_REPLAY_MAX_STEPS = 800
DESKTOP_IMAGE_MATCH_THRESHOLD = 0.86
DESKTOP_UITREE_DEFAULT_LIMIT = 80
EVAL_AUTORUN_EVERY_TICKS = 10  # Default value
RELEASE_GATE_MIN_PASS_RATE = 0.8  # Default value
RELEASE_GATE_REQUIRE_ZERO_FAILS = False  # Default value
OPS_AUTH_ENABLED = False  # Default value
OPS_AUTH_TOKEN = None  # Default value
OPS_AUTH_REQUIRE_SIGNATURE = False  # Default value
OPS_AUTH_ROLE_SECRETS = {}  # Default value
TASK_PROGRESS_REPORTING_ENABLED = True  # Default value
TASK_PROGRESS_MIN_INTERVAL_SECONDS = 5  # Default value
TASK_ROLE_LOOP_ENABLED = True  # Default value
TASK_ROLE_LOOP_MODE = "auto"  # Default value
GOAL_SYSTEM_ENABLED = True  # Default value
GOAL_SUPERVISOR_EVERY_TICKS = 5  # Default value
TOOL_PERF_TRACKING_ENABLED = True  # Default value
CUSTOM_TOOL_ENABLED = True  # Default value
BLACKBOX_PRUNE_ENABLED = True  # Default value
BLACKBOX_PRUNE_INTERVAL_SECONDS = 3600  # Default value
BLACKBOX_READ_MAX_LIMIT = 1000  # Default value
IDENTITY_SCOPE_MODE = "strict_chat"  # Default value
REMOTE_NODES_JSON = None  # Default value
PLUGIN_ENFORCE_TRUST = False  # Default value
PLUGIN_TRUSTED_HASHES = []  # Default value
WEBHOOK_RETRY_BASE_SECONDS = 5  # Default value
WEBHOOK_RETRY_MAX_SECONDS = 300  # Default value
WEBHOOK_RETRY_FACTOR = 2  # Default value
WEBHOOK_RETRY_JITTER_RATIO = 0.1  # Default value
CANARY_ROUTER_ENABLED = False  # Default value
MEMORY_VAULT_ROOT = None  # Default value
UI_DIST_DIR = "mind_clone_ui/dist"  # Default value

# Additional exports for runner.py
from mind_clone.core.policies import active_tool_policy_profile
from mind_clone.core.sandbox import _normalize_os_sandbox_mode
from mind_clone.core.model_router import llm_failover_active

active_tool_policy = active_tool_policy_profile
active_execution_sandbox_profile = active_tool_policy_profile
EXECUTION_SANDBOX_REMOTE_ALLOWLIST = []
OS_SANDBOX_DOCKER_IMAGE = "python:3.11-slim"

# More exports for runner.py
REMOTE_NODE_REGISTRY = None
PLUGIN_ENABLE_DYNAMIC_TOOLS = True
PLUGIN_TOOL_REGISTRY = None
PLUGIN_ENFORCE_TRUST = False
CUSTOM_TOOL_REGISTRY = None
CUSTOM_TOOL_MAX_PER_USER = 10
TASK_GRAPH_BRANCHING_ENABLED = True
TASK_GRAPH_MAX_NODES = 100
TASK_ARTIFACT_RETRIEVE_TOP_K = 5
TASK_ARTIFACT_MAX_PER_USER = 100
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60
TASK_GUARD_ORPHAN_LEASE_SECONDS = 300
NODE_HEARTBEAT_STALE_SECONDS = 60
NODE_LEASE_TTL_SECONDS = 300
TASK_CHECKPOINT_SNAPSHOT_ENABLED = True
TASK_CHECKPOINT_MAX_PER_TASK = 10
USAGE_LEDGER_ENABLED = True
CANARY_PROFILE_NAME = "default"
CANARY_TRAFFIC_PERCENT = 10

# =========================================================================
# Closed Loop Feedback Engine (Section 5B)
# =========================================================================
CLOSED_LOOP_ENABLED = _env_flag("CLOSED_LOOP_ENABLED", True)
CLOSED_LOOP_TOOL_WARN_THRESHOLD = max(5, min(80, int(os.getenv("CLOSED_LOOP_TOOL_WARN_THRESHOLD", "40"))))
CLOSED_LOOP_TOOL_BLOCK_THRESHOLD = max(1, min(50, int(os.getenv("CLOSED_LOOP_TOOL_BLOCK_THRESHOLD", "15"))))
CLOSED_LOOP_TOOL_MIN_CALLS = max(2, min(50, int(os.getenv("CLOSED_LOOP_TOOL_MIN_CALLS", "5"))))
CLOSED_LOOP_NOTE_MAX_RETRIEVALS = max(2, min(20, int(os.getenv("CLOSED_LOOP_NOTE_MAX_RETRIEVALS", "5"))))
CLOSED_LOOP_DEAD_LETTER_BLOCK_COUNT = max(2, min(10, int(os.getenv("CLOSED_LOOP_DEAD_LETTER_BLOCK_COUNT", "3"))))
CLOSED_LOOP_FORECAST_LOW_CONFIDENCE = max(5, min(60, int(os.getenv("CLOSED_LOOP_FORECAST_LOW_CONFIDENCE", "30"))))
CLOSED_LOOP_LESSON_MATCH_THRESHOLD = max(0.05, min(0.80, float(os.getenv("CLOSED_LOOP_LESSON_MATCH_THRESHOLD", "0.25"))))

# =========================================================================
# Self-Tuning Performance Engine (Section 5C)
# =========================================================================
SELF_TUNE_ENABLED = _env_flag("SELF_TUNE_ENABLED", True)
SELF_TUNE_INTERVAL_TICKS = max(1, int(os.getenv("SELF_TUNE_INTERVAL_TICKS", "2")))
SELF_TUNE_QUEUE_BACKLOG_THRESHOLD = max(1, int(os.getenv("SELF_TUNE_QUEUE_BACKLOG_THRESHOLD", "3")))
SELF_TUNE_HARD_CLEAR_RATE_THRESHOLD = max(1, int(os.getenv("SELF_TUNE_HARD_CLEAR_RATE_THRESHOLD", "5")))
SELF_TUNE_SESSION_BUDGET_STEP = max(2000, int(os.getenv("SELF_TUNE_SESSION_BUDGET_STEP", "8000")))
SELF_TUNE_SESSION_BUDGET_MAX = max(40000, int(os.getenv("SELF_TUNE_SESSION_BUDGET_MAX", "80000")))
SELF_TUNE_SESSION_BUDGET_MIN = max(6000, int(os.getenv("SELF_TUNE_SESSION_BUDGET_MIN", "20000")))
SELF_TUNE_WORKER_MAX = max(2, min(16, int(os.getenv("SELF_TUNE_WORKER_MAX", "6"))))

# Session budget vars mutated by self-tune engine at runtime
SESSION_SOFT_TRIM_CHAR_BUDGET = settings.session_soft_trim_char_budget
SESSION_HARD_CLEAR_CHAR_BUDGET = SESSION_SOFT_TRIM_CHAR_BUDGET + 8000

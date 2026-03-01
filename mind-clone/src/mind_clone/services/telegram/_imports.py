# SECTION 10: TELEGRAM ADAPTER
# ============================================================================
"""
Telegram Bot Adapter for Mind Clone Agent.

This module handles all Telegram bot interactions including:
- Webhook management and retry logic
- Command handlers (/start, /help, /task, /status, etc.)
- Message dispatch and queue management
- Runtime metrics and health monitoring
- Cron job execution
- Approval token handling
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Import database models and session
from ...database.models import (
    User,
    Task,
    ScheduledJob,
)
from ...database.session import SessionLocal, engine, ensure_db_ready
from sqlalchemy import text as sql_text

# Import config
from mind_clone.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_BASE_URL,
    TOKEN_PLACEHOLDER,
    KIMI_MODEL,
    KIMI_FALLBACK_MODEL,
    LLM_FAILOVER_ENABLED,
    LLM_REQUEST_TIMEOUT_SECONDS,
    AUTONOMY_MODE,
    AUTONOMY_OPENCLAW_MAX,
    POLICY_PACK,
    POLICY_PACK_PRESETS,
    BUDGET_GOVERNOR_ENABLED,
    BUDGET_GOVERNOR_MODE,
    COMMAND_QUEUE_MODE,
    COMMAND_QUEUE_WORKER_COUNT,
    COMMAND_QUEUE_MAX_SIZE,
    COMMAND_QUEUE_LANE_LIMITS,
    COMMAND_QUEUE_AUTO_BACKPRESSURE,
    WORKSPACE_DIFF_GATE_ENABLED,
    WORKSPACE_DIFF_GATE_MODE,
    WORKSPACE_DIFF_MAX_CHANGED_LINES,
    WORKSPACE_ISOLATION_ENABLED,
    WORKSPACE_ISOLATION_DEFAULT_ROOT,
    WORKSPACE_SESSION_ISOLATION_ENABLED,
    WORKSPACE_SESSION_ROOT,
    SECRET_GUARDRAIL_ENABLED,
    SECRET_REDACTION_TOKEN,
    OS_SANDBOX_MODE,
    OS_SANDBOX_REQUIRED,
    HOST_EXEC_INTERLOCK_ENABLED,
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_REQUIRE_ACTIVE_SESSION,
    BROWSER_TOOL_ENABLED,
    CRON_ENABLED,
    CRON_TICK_SECONDS,
    CRON_MIN_INTERVAL_SECONDS,
    CRON_MAX_DUE_PER_TICK,
    CRON_BOOTSTRAP_JOBS_JSON,
    HEARTBEAT_AUTONOMY_ENABLED,
    HEARTBEAT_INTERVAL_SECONDS,
    EVAL_HARNESS_ENABLED,
    EVAL_MAX_CASES,
    EVAL_AUTORUN_EVERY_TICKS,
    RELEASE_GATE_MIN_PASS_RATE,
    RELEASE_GATE_REQUIRE_ZERO_FAILS,
    OPS_AUTH_ENABLED,
    OPS_AUTH_TOKEN,
    OPS_AUTH_REQUIRE_SIGNATURE,
    OPS_AUTH_ROLE_SECRETS,
    TASK_PROGRESS_REPORTING_ENABLED,
    TASK_PROGRESS_MIN_INTERVAL_SECONDS,
    TASK_ROLE_LOOP_ENABLED,
    TASK_ROLE_LOOP_MODE,
    GOAL_SYSTEM_ENABLED,
    GOAL_SUPERVISOR_EVERY_TICKS,
    TOOL_PERF_TRACKING_ENABLED,
    CUSTOM_TOOL_ENABLED,
    BLACKBOX_PRUNE_ENABLED,
    BLACKBOX_PRUNE_INTERVAL_SECONDS,
    BLACKBOX_READ_MAX_LIMIT,
    TEAM_MODE_ENABLED,
    IDENTITY_SCOPE_MODE,
    NODE_CONTROL_PLANE_ENABLED,
    REMOTE_NODES_JSON,
    PLUGIN_ENFORCE_TRUST,
    PLUGIN_TRUSTED_HASHES,
    APPROVAL_GATE_MODE,
    WEBHOOK_RETRY_BASE_SECONDS,
    WEBHOOK_RETRY_MAX_SECONDS,
    WEBHOOK_RETRY_FACTOR,
    WEBHOOK_RETRY_JITTER_RATIO,
    CANARY_ROUTER_ENABLED,
)

# Import runtime state and locks
from mind_clone.core.state import (
    RUNTIME_STATE,
    OWNER_STATE_LOCK,
    OWNER_QUEUE_COUNTS,
    OWNER_ACTIVE_RUNS,
    CONTEXT_XRAY_LOCK,
    CONTEXT_XRAY_SNAPSHOTS,
    CONTEXT_XRAY_SEQ,
    MODEL_ROUTER_LOCK,
    MODEL_PROFILE_STICKY,
    MODEL_PROFILE_COOLDOWNS,
    MODEL_PROFILE_HEALTH,
    SANDBOX_REGISTRY_LOCK,
    SANDBOX_REGISTRY,
    TASK_GUARD_LOCK,
    ACTIVE_TASK_EXECUTIONS,
    TASK_GUARD_ORPHAN_RECOVERIES,
    NODE_CONTROL_LOCK,
    NODE_SCHEDULER_STATS,
    CIRCUIT_LOCK,
    PROVIDER_CIRCUITS,
    CIRCUIT_STATE_DEFAULT,
    COMMAND_QUEUE,
    COMMAND_QUEUE_WORKER_TASKS,
    COMMAND_QUEUE_LANE_SEMAPHORES,
    TASK_QUEUE,
    TASK_QUEUE_IDS,
    HEARTBEAT_WAKE_EVENT,
    WEBHOOK_RETRY_TASK,
    CANARY_STATE,
    _task_progress_last_send,
    _collect_buffers,
    _self_improve_last_time,
)

# Import core agent functions
from mind_clone.core.agent import (
    run_agent_loop_with_new_session,
)

# Import task management
from mind_clone.core.tasks import (
    enqueue_task,
    normalize_task_plan,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    recover_orphan_running_tasks,
    task_worker_loop,
    mark_owner_active,
    get_owner_execution_lock,
)

# Import approval system
from mind_clone.core.approvals import (
    decide_approval_token,
)

# Import budget system
from mind_clone.core.budget import (
    create_run_budget,
    budget_should_stop,
    budget_should_degrade,
)

# Import command queue utilities
from mind_clone.core.queue import (
    command_queue_enabled,
    effective_command_queue_mode,
    classify_message_lane,
    normalize_queue_lane,
    is_owner_busy_or_backlogged,
    increment_owner_queue,
    decrement_owner_queue,
    owner_active_count,
    owner_backlog_count,
    active_command_queue_worker_count,
    ensure_command_queue_workers_running,
    _collect_buffer_append,
    _collect_buffer_pop,
    pop_expired_collect_buffers,
    get_lane_semaphore,
)

# Import circuit breaker
from mind_clone.core.circuit import (
    circuit_snapshot,
    _default_circuit_state,
)

# Import node scheduler
from mind_clone.core.nodes import (
    REMOTE_NODE_REGISTRY,
)

# Import plugin registry
from mind_clone.core.plugins import (
    PLUGIN_TOOL_REGISTRY,
)

# Import sandbox utilities
from mind_clone.core.sandbox import (
    os_sandbox_enabled,
    _docker_executable,
    _normalize_os_sandbox_mode,
    cleanup_sandbox_registry,
)

# Import protocol schemas
from mind_clone.core.protocols import (
    PROTOCOL_SCHEMA_REGISTRY,
)

# Import workspace diff gate
from mind_clone.core.workspace_diff import (
    evaluate_workspace_diff_gate,
)

# Import secret redaction
from mind_clone.core.secrets import (
    redact_secret_data,
)

# Import goal supervisor
from mind_clone.core.goals import (
    run_goal_supervisor,
)

# Import tool performance
from mind_clone.core.tools import (
    prune_tool_performance_logs,
)

# Import custom tools
from mind_clone.core.custom_tools import (
    prune_custom_tools,
)

# Import blackbox
from mind_clone.core.blackbox import (
    fetch_blackbox_events_after,
    prune_blackbox_events,
)

# Import tool policies
from mind_clone.core.policies import (
    TOOL_POLICY_PROFILE_RAW,
    TOOL_POLICY_PROFILES,
    active_tool_policy_profile,
    EXECUTION_SANDBOX_PROFILE_RAW,
    EXECUTION_SANDBOX_PROFILES,
    active_execution_sandbox_profile,
)

# Import model router
from mind_clone.core.model_router import (
    configured_llm_profiles,
    llm_failover_active,
    MODEL_ROUTER_BILLING_HARD_DISABLE,
)

# Import browser cleanup
from mind_clone.tools.browser import (
    _cleanup_browser_sessions,
)

# Import utilities
from mind_clone.utils.text import truncate_text
from mind_clone.utils.json import _safe_json_dict

# Setup logging
log = logging.getLogger("mind_clone.telegram")

# Telegram API base URL
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"



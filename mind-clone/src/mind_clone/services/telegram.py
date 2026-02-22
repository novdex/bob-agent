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
from ..database.models import (
    User,
    Task,
    ScheduledJob,
)
from ..database.session import SessionLocal, engine, ensure_db_ready
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


# ============================================================================
# Utility Functions
# ============================================================================


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def iso_after_seconds(seconds: float) -> str:
    """Return ISO timestamp after specified seconds."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))
    return dt.isoformat()


def _normalize_schedule_lane(lane: str) -> str:
    """Normalize schedule lane to a valid value."""
    valid_lanes = {"default", "interactive", "background", "cron", "agent", "research"}
    lane = (lane or "cron").strip().lower()
    return lane if lane in valid_lanes else "cron"


def _compute_next_run_at_time(run_at_time: str | None) -> datetime | None:
    """Compute next run time from a time string (HH:MM)."""
    if not run_at_time:
        return None
    try:
        now = datetime.now(timezone.utc)
        parts = str(run_at_time).split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target
    except Exception:
        return None


def clamp_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    """Clamp integer value to range."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except Exception:
        return default


def parse_approval_token(text: str, command_name: str) -> str | None:
    """Parse approval token from command text."""
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    if parts[0].strip().lower() != command_name.strip().lower():
        return None
    token = parts[1].strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", token):
        return None
    return token


def parse_command_id(text: str, command_name: str) -> int | None:
    """Parse command ID from text (e.g., /cancel 123)."""
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0] != command_name:
        return None
    try:
        return int(parts[1].strip())
    except Exception:
        return None


# ============================================================================
# Task and Approval Management
# ============================================================================


def unpause_task_after_approval(
    owner_id: int, task_id: int, step_id: str | None
) -> tuple[bool, str]:
    """Unpause a task after approval token is approved."""
    db = SessionLocal()
    try:
        task = (
            db.query(Task).filter(Task.id == int(task_id), Task.owner_id == int(owner_id)).first()
        )
        if not task:
            return False, f"Task #{task_id} not found for this user."
        plan = normalize_task_plan(task.plan)
        if step_id:
            for step in plan:
                if step.get("step_id") == step_id and step.get("status") == TASK_STATUS_BLOCKED:
                    step["status"] = "pending"
                    step["last_error"] = None
                    step["checkpoint_at"] = utc_now_iso()
                    break
        task.plan = plan
        task.status = TASK_STATUS_QUEUED
        db.commit()
        enqueue_task(task.id)
        return True, f"Task #{task.id} resumed from approval token."
    except Exception as e:
        db.rollback()
        return False, f"Failed to resume task: {truncate_text(str(e), 200)}"
    finally:
        db.close()


async def handle_approval_command(chat_id: str, username: str, token: str, approve: bool):
    """Handle /approve or /reject command."""
    from mind_clone.agent.identity import resolve_owner_id

    owner_id = resolve_owner_id(chat_id, username)
    decision = decide_approval_token(owner_id=owner_id, token=token, approve=approve)
    if not decision.get("ok"):
        await send_telegram_message(
            chat_id, f"⚠️ {decision.get('error', 'Approval command failed.')}"
        )
        return

    status = str(decision.get("status", "pending"))
    token_owner_id = int(decision.get("owner_id") or owner_id)
    if status != "approved":
        await send_telegram_message(chat_id, f"Approval token {token} set to {status}.")
        return

    payload = _safe_json_dict(decision.get("resume_payload"), {})
    kind = str(payload.get("kind") or "")
    if kind == "task_step":
        task_id = int(payload.get("task_id") or 0)
        step_id = str(payload.get("step_id") or "") or None
        ok, message = unpause_task_after_approval(
            owner_id=token_owner_id, task_id=task_id, step_id=step_id
        )
        await send_telegram_message(chat_id, message if ok else f"⚠️ {message}")
        return

    if kind == "chat_message":
        user_message = str(payload.get("user_message") or "").strip()
        if not user_message:
            await send_telegram_message(
                chat_id, "Approval saved, but no resumable message was found."
            )
            return
        await send_telegram_message(chat_id, f"Approved {token}. Resuming message execution.")
        await dispatch_incoming_message(
            owner_id=token_owner_id,
            chat_id=chat_id,
            username=username,
            text=user_message,
            source="telegram",
            expect_response=False,
        )
        return

    await send_telegram_message(chat_id, f"Approval token {token} approved.")


# ============================================================================
# Message Sending Functions
# ============================================================================


def send_task_progress_sync(chat_id: str | None, task_id: int, message: str) -> None:
    """Send a task progress message to Telegram (sync, rate-limited)."""
    if not TASK_PROGRESS_REPORTING_ENABLED or not chat_id:
        return
    now = time.monotonic()
    last = _task_progress_last_send.get(task_id, 0.0)
    if (now - last) < TASK_PROGRESS_MIN_INTERVAL_SECONDS:
        return
    _task_progress_last_send[task_id] = now
    text = f"[Task #{task_id}] {message}"
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        with httpx.Client(timeout=15, trust_env=False) as client:
            resp = client.post(url, json={"chat_id": chat_id, "text": text})
            if resp.status_code != 200:
                log.debug(
                    "TASK_PROGRESS_SEND_FAIL task=%d status=%d",
                    task_id,
                    resp.status_code,
                )
    except Exception:
        log.debug("TASK_PROGRESS_SEND_ERROR task=%d", task_id, exc_info=True)


async def send_telegram_message(chat_id: str, text: str):
    """Send a message back to Telegram. Splits long messages."""
    text = str(text or "")
    if not text.strip():
        log.warning("TELEGRAM_SEND_SKIP_EMPTY chat_id=%s", chat_id)
        return

    url = f"{TELEGRAM_API}/sendMessage"

    # Telegram max message length is 4096
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for chunk in chunks:
            markdown_payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
            }
            try:
                resp = await client.post(url, json=markdown_payload)
                markdown_ok = False
                markdown_err = ""
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                        markdown_ok = bool(body.get("ok", False))
                        if not markdown_ok:
                            markdown_err = truncate_text(str(body), 220)
                    except Exception:
                        markdown_err = truncate_text(
                            resp.text or "Invalid JSON response from Telegram.", 220
                        )
                else:
                    markdown_err = f"status={resp.status_code} body={truncate_text(resp.text, 220)}"

                if markdown_ok:
                    continue

                # Retry in plain text mode for reliability.
                plain_payload = {"chat_id": chat_id, "text": chunk}
                plain_resp = await client.post(url, json=plain_payload)
                plain_ok = False
                plain_err = ""
                if plain_resp.status_code == 200:
                    try:
                        plain_body = plain_resp.json()
                        plain_ok = bool(plain_body.get("ok", False))
                        if not plain_ok:
                            plain_err = truncate_text(str(plain_body), 220)
                    except Exception:
                        plain_err = truncate_text(
                            plain_resp.text or "Invalid JSON response from Telegram.", 220
                        )
                else:
                    plain_err = f"status={plain_resp.status_code} body={truncate_text(plain_resp.text, 220)}"

                if not plain_ok:
                    log.error(
                        "TELEGRAM_SEND_FAIL chat_id=%s markdown_error=%s plain_error=%s text_preview=%s",
                        chat_id,
                        markdown_err,
                        plain_err,
                        truncate_text(chunk, 180),
                    )
            except Exception as e:
                log.error(f"Failed to send telegram message: {e}")


async def send_typing_indicator(chat_id: str):
    """Send typing indicator to chat."""
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            await client.post(
                f"{TELEGRAM_API}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
    except Exception as e:
        log.warning(
            "Typing indicator failed for chat_id=%s error=%s",
            chat_id,
            truncate_text(str(e), 180),
        )


# ============================================================================
# Runtime State Initialization
# ============================================================================


def initialize_runtime_state_baseline():
    """Initialize runtime state with baseline values."""
    profiles = configured_llm_profiles()
    primary_model = str(profiles[0].get("model")) if profiles else KIMI_MODEL
    fallback_model = (
        str(profiles[1].get("model")) if len(profiles) > 1 else (KIMI_FALLBACK_MODEL or None)
    )
    RUNTIME_STATE["app_start_monotonic"] = time.monotonic()
    RUNTIME_STATE["shutting_down"] = False
    RUNTIME_STATE["worker_alive"] = False
    RUNTIME_STATE["llm_primary_model"] = primary_model
    RUNTIME_STATE["llm_fallback_model"] = fallback_model
    RUNTIME_STATE["llm_failover_enabled"] = llm_failover_active()
    RUNTIME_STATE["llm_last_model_used"] = None
    RUNTIME_STATE["llm_last_attempt_at"] = None
    RUNTIME_STATE["llm_last_success_at"] = None
    RUNTIME_STATE["llm_last_error"] = None
    RUNTIME_STATE["llm_failover_count"] = 0
    RUNTIME_STATE["llm_primary_failures"] = 0
    RUNTIME_STATE["llm_fallback_failures"] = 0
    RUNTIME_STATE["autonomy_mode"] = AUTONOMY_MODE
    RUNTIME_STATE["autonomy_openclaw_max"] = bool(AUTONOMY_OPENCLAW_MAX)
    RUNTIME_STATE["policy_pack"] = POLICY_PACK
    RUNTIME_STATE["budget_governor_enabled"] = bool(BUDGET_GOVERNOR_ENABLED)
    RUNTIME_STATE["budget_governor_mode"] = BUDGET_GOVERNOR_MODE
    RUNTIME_STATE["budget_runs_started"] = 0
    RUNTIME_STATE["budget_runs_stopped"] = 0
    RUNTIME_STATE["budget_runs_degraded"] = 0
    RUNTIME_STATE["budget_last_scope"] = None
    RUNTIME_STATE["budget_last_reason"] = None
    RUNTIME_STATE["budget_last_usage"] = {}
    RUNTIME_STATE["command_queue_mode"] = COMMAND_QUEUE_MODE
    RUNTIME_STATE["command_queue_mode_override_count"] = 0
    RUNTIME_STATE["command_queue_collect_merges"] = 0
    RUNTIME_STATE["command_queue_collect_flushes"] = 0
    RUNTIME_STATE["command_queue_state_invalid_transitions"] = 0
    RUNTIME_STATE["command_queue_worker_target"] = COMMAND_QUEUE_WORKER_COUNT
    RUNTIME_STATE["command_queue_worker_alive"] = False
    RUNTIME_STATE["command_queue_worker_alive_count"] = 0
    RUNTIME_STATE["command_queue_worker_restarts"] = 0
    RUNTIME_STATE["command_queue_enqueued"] = 0
    RUNTIME_STATE["command_queue_processed"] = 0
    RUNTIME_STATE["command_queue_dropped"] = 0
    RUNTIME_STATE["command_queue_direct_routed"] = 0
    RUNTIME_STATE["command_queue_auto_routed"] = 0
    RUNTIME_STATE["session_soft_trim_count"] = 0
    RUNTIME_STATE["session_hard_clear_count"] = 0
    RUNTIME_STATE["session_last_prune_chars"] = 0
    RUNTIME_STATE["session_memory_flush_count"] = 0
    RUNTIME_STATE["session_memory_flush_failures"] = 0
    RUNTIME_STATE["tool_policy_profile"] = active_tool_policy_profile()
    RUNTIME_STATE["tool_policy_blocks"] = 0
    RUNTIME_STATE["workspace_diff_gate_enabled"] = bool(WORKSPACE_DIFF_GATE_ENABLED)
    RUNTIME_STATE["workspace_diff_gate_mode"] = WORKSPACE_DIFF_GATE_MODE
    RUNTIME_STATE["workspace_diff_gate_blocks"] = 0
    RUNTIME_STATE["workspace_diff_gate_approvals"] = 0
    RUNTIME_STATE["workspace_diff_gate_warns"] = 0
    RUNTIME_STATE["workspace_diff_gate_last_path"] = None
    RUNTIME_STATE["workspace_diff_gate_last_reason"] = None
    RUNTIME_STATE["workspace_diff_gate_last_changed_lines"] = 0
    RUNTIME_STATE["secret_guardrail_enabled"] = bool(SECRET_GUARDRAIL_ENABLED)
    RUNTIME_STATE["secret_redactions_total"] = 0
    RUNTIME_STATE["execution_sandbox_profile"] = active_execution_sandbox_profile()
    RUNTIME_STATE["execution_sandbox_blocks"] = 0
    RUNTIME_STATE["approval_gate_mode"] = APPROVAL_GATE_MODE
    RUNTIME_STATE["approval_required_count"] = 0
    RUNTIME_STATE["approval_pending_count"] = 0
    RUNTIME_STATE["approval_approved_count"] = 0
    RUNTIME_STATE["approval_rejected_count"] = 0
    RUNTIME_STATE["approval_last_token"] = None
    RUNTIME_STATE["task_graph_branches_created"] = 0
    RUNTIME_STATE["task_graph_resume_events"] = 0
    RUNTIME_STATE["task_guard_orphan_requeues"] = 0
    RUNTIME_STATE["task_guard_dead_letters"] = 0
    RUNTIME_STATE["task_dedupe_hits"] = 0
    RUNTIME_STATE["circuit_blocked_calls"] = 0
    RUNTIME_STATE["circuit_open_events"] = 0
    RUNTIME_STATE["task_artifacts_stored"] = 0
    RUNTIME_STATE["task_artifacts_pruned"] = 0
    RUNTIME_STATE["task_artifact_injections"] = 0
    RUNTIME_STATE["structured_task_calls"] = 0
    RUNTIME_STATE["structured_task_failures"] = 0
    RUNTIME_STATE["spine_supervisor_alive"] = False
    RUNTIME_STATE["startup_preflight_ok"] = False
    RUNTIME_STATE["startup_preflight_errors"] = []
    RUNTIME_STATE["db_healthy"] = False
    RUNTIME_STATE["db_last_check"] = None
    RUNTIME_STATE["db_last_error"] = None
    RUNTIME_STATE["task_worker_restarts"] = 0
    RUNTIME_STATE["webhook_supervisor_restarts"] = 0
    RUNTIME_STATE["webhook_registered"] = False
    RUNTIME_STATE["webhook_last_attempt"] = None
    RUNTIME_STATE["webhook_last_success"] = None
    RUNTIME_STATE["webhook_last_error"] = None
    RUNTIME_STATE["webhook_next_retry_at"] = None
    RUNTIME_STATE["webhook_retry_attempt"] = 0
    RUNTIME_STATE["webhook_retry_delay_seconds"] = WEBHOOK_RETRY_BASE_SECONDS
    RUNTIME_STATE["cron_supervisor_alive"] = False
    RUNTIME_STATE["cron_due_runs"] = 0
    RUNTIME_STATE["cron_failures"] = 0
    RUNTIME_STATE["cron_last_tick"] = None
    RUNTIME_STATE["heartbeat_supervisor_alive"] = False
    RUNTIME_STATE["heartbeat_ticks_total"] = 0
    RUNTIME_STATE["heartbeat_manual_wakes"] = 0
    RUNTIME_STATE["heartbeat_last_tick"] = None
    RUNTIME_STATE["heartbeat_last_reason"] = None
    RUNTIME_STATE["heartbeat_last_alert_count"] = 0
    RUNTIME_STATE["heartbeat_next_tick_at"] = None
    RUNTIME_STATE["heartbeat_restarts"] = 0
    RUNTIME_STATE["eval_runs_total"] = 0
    RUNTIME_STATE["eval_autoruns_total"] = 0
    RUNTIME_STATE["eval_last_run_at"] = None
    RUNTIME_STATE["eval_last_pass_rate"] = None
    RUNTIME_STATE["eval_last_fail_count"] = 0
    RUNTIME_STATE["eval_last_report"] = {}
    RUNTIME_STATE["task_role_loop_enabled"] = bool(TASK_ROLE_LOOP_ENABLED)
    RUNTIME_STATE["task_role_loop_mode"] = TASK_ROLE_LOOP_MODE
    RUNTIME_STATE["task_role_loop_runs"] = 0
    RUNTIME_STATE["task_role_loop_last_role"] = None
    RUNTIME_STATE["team_mode_enabled"] = bool(TEAM_MODE_ENABLED)
    RUNTIME_STATE["identity_scope_mode"] = IDENTITY_SCOPE_MODE
    RUNTIME_STATE["team_agents_total"] = 0
    RUNTIME_STATE["team_last_agent"] = None
    RUNTIME_STATE["team_broadcasts_total"] = 0
    RUNTIME_STATE["context_xray_snapshots_total"] = 0
    RUNTIME_STATE["context_xray_last_snapshot_at"] = None
    RUNTIME_STATE["host_exec_interlock_enabled"] = bool(HOST_EXEC_INTERLOCK_ENABLED)
    RUNTIME_STATE["host_exec_grants_issued"] = 0
    RUNTIME_STATE["host_exec_grants_consumed"] = 0
    RUNTIME_STATE["host_exec_interlock_blocks"] = 0
    RUNTIME_STATE["workspace_isolation_enabled"] = bool(WORKSPACE_ISOLATION_ENABLED)
    RUNTIME_STATE["workspace_session_isolation_enabled"] = bool(WORKSPACE_SESSION_ISOLATION_ENABLED)
    RUNTIME_STATE["workspace_isolation_blocks"] = 0
    RUNTIME_STATE["memory_last_retrieved_total"] = 0
    RUNTIME_STATE["memory_last_lessons_retrieved"] = 0
    RUNTIME_STATE["memory_last_summaries_retrieved"] = 0
    RUNTIME_STATE["memory_last_task_artifacts_retrieved"] = 0
    RUNTIME_STATE["memory_last_lesson_quality"] = None
    RUNTIME_STATE["memory_last_summary_quality"] = None
    RUNTIME_STATE["memory_last_task_artifact_quality"] = None
    RUNTIME_STATE["memory_last_hit_quality"] = None
    RUNTIME_STATE["memory_last_continuity_score"] = None
    RUNTIME_STATE["memory_last_retrieval_at"] = None
    RUNTIME_STATE["memory_lessons_pruned"] = 0
    RUNTIME_STATE["memory_summaries_pruned"] = 0
    RUNTIME_STATE["world_model_forecasts_total"] = 0
    RUNTIME_STATE["world_model_mismatches"] = 0
    RUNTIME_STATE["world_model_recent_accuracy"] = None
    RUNTIME_STATE["world_model_last_forecast_at"] = None
    RUNTIME_STATE["world_model_last_reconciliation_at"] = None
    RUNTIME_STATE["self_improve_notes_total"] = 0
    RUNTIME_STATE["self_improve_last_run_at"] = None
    RUNTIME_STATE["self_improve_last_note"] = None
    RUNTIME_STATE["dormant_capabilities_active"] = []
    RUNTIME_STATE["dormant_activations_total"] = 0
    RUNTIME_STATE["dormant_last_activation_at"] = None
    RUNTIME_STATE["blackbox_events_total"] = 0
    RUNTIME_STATE["blackbox_last_event_at"] = None
    RUNTIME_STATE["blackbox_reports_built"] = 0
    RUNTIME_STATE["blackbox_recovery_plans_built"] = 0
    RUNTIME_STATE["blackbox_last_recovery_plan_at"] = None
    RUNTIME_STATE["blackbox_events_pruned"] = 0
    RUNTIME_STATE["blackbox_last_prune_at"] = None
    RUNTIME_STATE["blackbox_last_prune_reason"] = None
    RUNTIME_STATE["blackbox_last_prune_count"] = 0
    RUNTIME_STATE["blackbox_exports_built"] = 0
    RUNTIME_STATE["blackbox_last_export_at"] = None
    RUNTIME_STATE["plugin_tools_loaded"] = len(PLUGIN_TOOL_REGISTRY)
    RUNTIME_STATE["plugin_tools_blocked"] = 0
    RUNTIME_STATE["remote_nodes_loaded"] = len(REMOTE_NODE_REGISTRY)
    RUNTIME_STATE["node_control_plane_enabled"] = bool(NODE_CONTROL_PLANE_ENABLED)
    RUNTIME_STATE["node_control_plane_nodes"] = len(REMOTE_NODE_REGISTRY)
    RUNTIME_STATE["node_control_plane_leases_active"] = 0
    RUNTIME_STATE["node_scheduler_dispatches"] = 0
    RUNTIME_STATE["node_scheduler_failures"] = 0
    RUNTIME_STATE["node_scheduler_last_node"] = None
    RUNTIME_STATE["node_scheduler_last_score"] = None
    RUNTIME_STATE["ops_auth_enabled"] = bool(OPS_AUTH_ENABLED)
    RUNTIME_STATE["ops_auth_failures"] = 0
    RUNTIME_STATE["ops_auth_last_error"] = None
    RUNTIME_STATE["ops_signature_failures"] = 0
    RUNTIME_STATE["ops_audit_events_total"] = int(
        RUNTIME_STATE.get("ops_audit_events_total", 0) or 0
    )
    RUNTIME_STATE["ops_audit_last_hash"] = RUNTIME_STATE.get("ops_audit_last_hash")
    RUNTIME_STATE["os_sandbox_mode"] = _normalize_os_sandbox_mode(OS_SANDBOX_MODE)
    RUNTIME_STATE["os_sandbox_required"] = bool(OS_SANDBOX_REQUIRED)
    RUNTIME_STATE["os_sandbox_runs"] = 0
    RUNTIME_STATE["os_sandbox_failures"] = 0
    RUNTIME_STATE["desktop_control_enabled"] = bool(DESKTOP_CONTROL_ENABLED)
    RUNTIME_STATE["desktop_actions_total"] = 0
    RUNTIME_STATE["desktop_last_action"] = None
    RUNTIME_STATE["desktop_last_error"] = None
    RUNTIME_STATE["desktop_session_required"] = bool(
        RUNTIME_STATE.get("desktop_session_required", DESKTOP_REQUIRE_ACTIVE_SESSION)
    )
    RUNTIME_STATE["desktop_session_active"] = False
    RUNTIME_STATE["desktop_session_id"] = None
    RUNTIME_STATE["desktop_sessions_started"] = 0
    RUNTIME_STATE["desktop_sessions_completed"] = 0
    RUNTIME_STATE["desktop_sessions_replayed"] = 0
    RUNTIME_STATE["desktop_last_session_path"] = None
    RUNTIME_STATE["model_router_enabled"] = True
    RUNTIME_STATE["model_router_profiles_loaded"] = len(configured_llm_profiles())
    RUNTIME_STATE["model_router_last_profile"] = None
    RUNTIME_STATE["model_router_failovers"] = 0
    RUNTIME_STATE["model_router_cooldowns"] = 0
    RUNTIME_STATE["model_router_profile_disables"] = 0
    RUNTIME_STATE["model_router_compat_skips"] = 0
    RUNTIME_STATE["sandbox_registry_count"] = 0
    RUNTIME_STATE["sandbox_registry_reused"] = 0
    RUNTIME_STATE["sandbox_registry_created"] = 0
    RUNTIME_STATE["sandbox_registry_cleanups"] = 0
    RUNTIME_STATE["sandbox_registry_last_context"] = None
    RUNTIME_STATE["sandbox_registry_last_error"] = None
    RUNTIME_STATE["protocol_schema_count"] = len(PROTOCOL_SCHEMA_REGISTRY)
    RUNTIME_STATE["protocol_schema_validations"] = 0
    RUNTIME_STATE["protocol_schema_failures"] = 0
    RUNTIME_STATE["ssrf_blocked_requests"] = 0
    RUNTIME_STATE["node_policy_blocks"] = 0
    RUNTIME_STATE["usage_ledger_last_owner_summary"] = {}
    RUNTIME_STATE["usage_ledger_last_task_summary"] = {}
    RUNTIME_STATE["usage_ledger_last_session_summary"] = {}
    RUNTIME_STATE["workflow_programs_total"] = 0
    RUNTIME_STATE["workflow_runs_total"] = 0
    RUNTIME_STATE["workflow_v2_runs"] = 0
    RUNTIME_STATE["memory_vault_bootstraps"] = 0
    RUNTIME_STATE["memory_vault_backups"] = 0
    RUNTIME_STATE["memory_vault_restores"] = 0
    RUNTIME_STATE["task_checkpoint_snapshots"] = int(
        RUNTIME_STATE.get("task_checkpoint_snapshots", 0) or 0
    )
    RUNTIME_STATE["task_checkpoint_replay_restores"] = int(
        RUNTIME_STATE.get("task_checkpoint_replay_restores", 0) or 0
    )
    RUNTIME_STATE["task_checkpoint_restore_failures"] = int(
        RUNTIME_STATE.get("task_checkpoint_restore_failures", 0) or 0
    )
    RUNTIME_STATE["task_checkpoint_restore_drift"] = int(
        RUNTIME_STATE.get("task_checkpoint_restore_drift", 0) or 0
    )
    RUNTIME_STATE["task_checkpoint_last_replay_mode"] = RUNTIME_STATE.get(
        "task_checkpoint_last_replay_mode"
    )
    RUNTIME_STATE["usage_ledger_events"] = int(RUNTIME_STATE.get("usage_ledger_events", 0) or 0)
    RUNTIME_STATE["usage_ledger_cost_usd"] = float(
        RUNTIME_STATE.get("usage_ledger_cost_usd", 0.0) or 0.0
    )
    RUNTIME_STATE["canary_enabled"] = bool(CANARY_ROUTER_ENABLED)
    RUNTIME_STATE["canary_samples"] = int(CANARY_STATE.get("samples", 0) or 0)
    RUNTIME_STATE["canary_failures"] = int(CANARY_STATE.get("failures", 0) or 0)
    RUNTIME_STATE["canary_rolled_back"] = not bool(
        CANARY_STATE.get("enabled", CANARY_ROUTER_ENABLED)
    )
    RUNTIME_STATE["canary_last_reason"] = CANARY_STATE.get("last_reason")
    RUNTIME_STATE["canary_last_rollback_at"] = CANARY_STATE.get("last_rollback_at")
    RUNTIME_STATE["schema_version"] = int(RUNTIME_STATE.get("schema_version", 0) or 0)
    RUNTIME_STATE["release_gate_last_status"] = RUNTIME_STATE.get("release_gate_last_status")
    with OWNER_STATE_LOCK:
        OWNER_QUEUE_COUNTS.clear()
        OWNER_ACTIVE_RUNS.clear()
    with CONTEXT_XRAY_LOCK:
        CONTEXT_XRAY_SNAPSHOTS.clear()
        CONTEXT_XRAY_SEQ.clear()
    with MODEL_ROUTER_LOCK:
        MODEL_PROFILE_STICKY.clear()
        MODEL_PROFILE_COOLDOWNS.clear()
        MODEL_PROFILE_HEALTH.clear()
    with SANDBOX_REGISTRY_LOCK:
        SANDBOX_REGISTRY.clear()
    _self_improve_last_time.clear()
    COMMAND_QUEUE_WORKER_TASKS.clear()
    COMMAND_QUEUE_LANE_SEMAPHORES.clear()
    global COMMAND_QUEUE
    if COMMAND_QUEUE is None:
        COMMAND_QUEUE = asyncio.Queue()
    else:
        try:
            while not COMMAND_QUEUE.empty():
                COMMAND_QUEUE.get_nowait()
        except Exception:
            pass
    with TASK_GUARD_LOCK:
        ACTIVE_TASK_EXECUTIONS.clear()
        TASK_GUARD_ORPHAN_RECOVERIES.clear()
    with NODE_CONTROL_LOCK:
        NODE_SCHEDULER_STATS.clear()
    with CIRCUIT_LOCK:
        for provider in list(PROVIDER_CIRCUITS.keys()):
            PROVIDER_CIRCUITS[provider] = _default_circuit_state()


# ============================================================================
# Database and Health Checks
# ============================================================================


def check_db_liveness() -> tuple[bool, str | None]:
    """Check if database is alive."""
    check_time = utc_now_iso()
    err: str | None = None
    ok = False
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1")).scalar_one()
        ok = True
    except Exception as e:
        err = truncate_text(str(e), 300)

    RUNTIME_STATE["db_healthy"] = ok
    RUNTIME_STATE["db_last_check"] = check_time
    RUNTIME_STATE["db_last_error"] = None if ok else err
    return ok, err


# ============================================================================
# Startup Preflight
# ============================================================================


def run_startup_preflight() -> tuple[bool, list[str]]:
    """Run startup preflight checks."""
    import os

    errors: list[str] = []

    try:
        ensure_db_ready()
    except Exception as e:
        errors.append(f"DB preflight failed: {truncate_text(str(e), 240)}")

    if WORKSPACE_ISOLATION_ENABLED:
        try:
            WORKSPACE_ISOLATION_DEFAULT_ROOT.mkdir(parents=True, exist_ok=True)
            if WORKSPACE_SESSION_ISOLATION_ENABLED:
                WORKSPACE_SESSION_ROOT.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Workspace isolation root check failed: {truncate_text(str(e), 240)}")

    if OS_SANDBOX_REQUIRED and not os_sandbox_enabled():
        errors.append("OS_SANDBOX_REQUIRED=true requires OS_SANDBOX_MODE=docker.")
    if os_sandbox_enabled() and OS_SANDBOX_REQUIRED and not _docker_executable():
        errors.append("OS sandbox is required but Docker executable is not available.")

    parsed_webhook = urlparse((TELEGRAM_WEBHOOK_BASE_URL or "").strip())
    if parsed_webhook.scheme not in {"http", "https"} or not parsed_webhook.netloc:
        errors.append("TELEGRAM_WEBHOOK_BASE_URL must be a valid http/https URL.")

    from mind_clone.config import KIMI_API_KEY

    if KIMI_API_KEY == "YOUR_KIMI_API_KEY_HERE":
        log.warning("SPINE_PRECHECK_WARN KIMI_API_KEY placeholder detected.")
    if TELEGRAM_BOT_TOKEN == TOKEN_PLACEHOLDER:
        log.warning("SPINE_PRECHECK_WARN TELEGRAM_BOT_TOKEN placeholder detected.")
    if OPS_AUTH_ENABLED and not OPS_AUTH_TOKEN:
        errors.append("OPS_AUTH_ENABLED requires OPS_AUTH_TOKEN.")
    if OPS_AUTH_REQUIRE_SIGNATURE:
        if not OPS_AUTH_ENABLED:
            errors.append("OPS_AUTH_REQUIRE_SIGNATURE requires OPS_AUTH_ENABLED=true.")
        if not OPS_AUTH_ROLE_SECRETS and not OPS_AUTH_TOKEN:
            errors.append("Ops auth signatures need OPS_AUTH_ROLE_SECRETS or OPS_AUTH_TOKEN.")
    if LLM_FAILOVER_ENABLED:
        if not KIMI_FALLBACK_MODEL:
            log.warning(
                "SPINE_PRECHECK_WARN LLM failover enabled but KIMI_FALLBACK_MODEL is not set."
            )
        elif KIMI_FALLBACK_MODEL == KIMI_MODEL:
            log.warning(
                "SPINE_PRECHECK_WARN KIMI_FALLBACK_MODEL matches primary model; failover inactive."
            )
    profiles = configured_llm_profiles()
    if not profiles:
        errors.append("No enabled model profiles available for router.")
    if MODEL_ROUTER_BILLING_HARD_DISABLE:
        disabled_profiles = [p for p in profiles if not bool(p.get("billing_enabled", True))]
        if disabled_profiles:
            log.warning(
                "SPINE_PRECHECK_WARN billing hard-disable active; some profiles may be inactive."
            )
    if not TEAM_MODE_ENABLED:
        log.warning(
            "SPINE_PRECHECK_WARN TEAM_MODE_ENABLED=false; subagent control endpoints will be limited."
        )
    if AUTONOMY_OPENCLAW_MAX:
        log.warning(
            "SPINE_PRECHECK_WARN AUTONOMY_MODE=openclaw_max active: approvals/interlocks/control friction are reduced."
        )

    raw_pack = (os.getenv("POLICY_PACK", "dev") or "").strip().lower()
    if raw_pack and raw_pack not in POLICY_PACK_PRESETS:
        log.warning(
            "SPINE_PRECHECK_WARN POLICY_PACK invalid '%s'; using '%s'.", raw_pack, POLICY_PACK
        )
    raw_profile = (TOOL_POLICY_PROFILE_RAW or "").strip().lower()
    if raw_profile and raw_profile not in TOOL_POLICY_PROFILES:
        log.warning(
            "SPINE_PRECHECK_WARN TOOL_POLICY_PROFILE invalid '%s'; using '%s'.",
            TOOL_POLICY_PROFILE_RAW,
            active_tool_policy_profile(),
        )
    raw_sandbox_profile = (EXECUTION_SANDBOX_PROFILE_RAW or "").strip().lower()
    if raw_sandbox_profile and raw_sandbox_profile not in EXECUTION_SANDBOX_PROFILES:
        log.warning(
            "SPINE_PRECHECK_WARN EXECUTION_SANDBOX_PROFILE invalid '%s'; using '%s'.",
            EXECUTION_SANDBOX_PROFILE_RAW,
            active_execution_sandbox_profile(),
        )

    raw_approval_mode = (os.getenv("APPROVAL_GATE_MODE", "balanced") or "").strip().lower()
    if raw_approval_mode and raw_approval_mode not in {"off", "balanced", "strict"}:
        log.warning(
            "SPINE_PRECHECK_WARN APPROVAL_GATE_MODE invalid '%s'; using '%s'.",
            raw_approval_mode,
            APPROVAL_GATE_MODE,
        )
    raw_budget_mode = (
        (os.getenv("BUDGET_GOVERNOR_MODE", BUDGET_GOVERNOR_MODE) or "").strip().lower()
    )
    if raw_budget_mode and raw_budget_mode not in {"warn", "degrade", "stop"}:
        log.warning(
            "SPINE_PRECHECK_WARN BUDGET_GOVERNOR_MODE invalid '%s'; using '%s'.",
            raw_budget_mode,
            BUDGET_GOVERNOR_MODE,
        )
    raw_diff_mode = (
        (os.getenv("WORKSPACE_DIFF_GATE_MODE", WORKSPACE_DIFF_GATE_MODE) or "").strip().lower()
    )
    if raw_diff_mode and raw_diff_mode not in {"warn", "approval", "block"}:
        log.warning(
            "SPINE_PRECHECK_WARN WORKSPACE_DIFF_GATE_MODE invalid '%s'; using '%s'.",
            raw_diff_mode,
            WORKSPACE_DIFF_GATE_MODE,
        )
    if PLUGIN_ENFORCE_TRUST and not PLUGIN_TRUSTED_HASHES:
        log.warning(
            "SPINE_PRECHECK_WARN PLUGIN_ENFORCE_TRUST=true but PLUGIN_TRUSTED_HASHES is empty."
        )
    try:
        parsed_nodes = json.loads(REMOTE_NODES_JSON or "[]")
        if parsed_nodes and not isinstance(parsed_nodes, list):
            errors.append("REMOTE_NODES_JSON must be a JSON array.")
    except Exception:
        errors.append("REMOTE_NODES_JSON is not valid JSON.")

    ok = len(errors) == 0
    RUNTIME_STATE["startup_preflight_ok"] = ok
    RUNTIME_STATE["startup_preflight_errors"] = list(errors)

    if ok:
        log.info("SPINE_PRECHECK_OK")
    else:
        log.warning("SPINE_PRECHECK_FAIL errors=%s", errors)
    return ok, errors


from urllib.parse import urlparse


# ============================================================================
# Runtime Metrics and Alerts
# ============================================================================


def compute_runtime_alerts(payload: dict) -> list[dict]:
    """Compute runtime alerts based on current state."""
    alerts: list[dict] = []

    def add_alert(level: str, code: str, message: str):
        alerts.append(
            {
                "level": level,
                "code": code,
                "message": truncate_text(message, 240),
            }
        )

    if not bool(payload.get("db_healthy", True)):
        add_alert("critical", "db_unhealthy", "Database health check is failing.")

    if not bool(payload.get("worker_alive", True)):
        add_alert("critical", "task_worker_down", "Task worker is not alive.")

    queue_size = int(payload.get("command_queue_size", 0))
    queue_max = max(1, int(payload.get("command_queue_max_size", COMMAND_QUEUE_MAX_SIZE)))
    queue_fill = queue_size / queue_max
    if queue_fill >= 0.95:
        add_alert(
            "critical", "command_queue_near_capacity", f"Command queue is {queue_fill:.0%} full."
        )
    elif queue_fill >= 0.80:
        add_alert("warning", "command_queue_high", f"Command queue is {queue_fill:.0%} full.")

    target_workers = max(
        1, int(payload.get("command_queue_worker_target", COMMAND_QUEUE_WORKER_COUNT))
    )
    alive_workers = int(payload.get("command_queue_worker_alive_count", 0))
    if command_queue_enabled() and alive_workers < target_workers:
        add_alert(
            "warning",
            "command_queue_workers_below_target",
            f"Queue workers alive={alive_workers}, target={target_workers}.",
        )

    pending_approvals = int(payload.get("approval_pending_count", 0))
    if pending_approvals >= 20:
        add_alert(
            "warning", "approval_backlog_high", f"Pending approvals backlog is {pending_approvals}."
        )

    budget_stops = int(payload.get("budget_runs_stopped", 0))
    if budget_stops > 0:
        add_alert(
            "warning",
            "budget_stop_events",
            f"Budget stop triggered {budget_stops} time(s). Last reason: {payload.get('budget_last_reason')}.",
        )

    circuit_data = payload.get("circuit_breakers", {})
    if isinstance(circuit_data, dict):
        open_providers = [
            name
            for name, state in circuit_data.items()
            if isinstance(state, dict) and str(state.get("state", "")).lower() == "open"
        ]
        if open_providers:
            add_alert(
                "warning",
                "circuit_open",
                f"Provider circuits open: {', '.join(open_providers[:5])}.",
            )

    if (
        CRON_ENABLED
        and not bool(payload.get("cron_supervisor_alive", False))
        and not bool(RUNTIME_STATE.get("shutting_down"))
    ):
        add_alert(
            "critical", "cron_supervisor_down", "Cron supervisor is expected but not running."
        )

    if (
        HEARTBEAT_AUTONOMY_ENABLED
        and not bool(payload.get("heartbeat_supervisor_alive", False))
        and not bool(RUNTIME_STATE.get("shutting_down"))
    ):
        add_alert(
            "critical",
            "heartbeat_supervisor_down",
            "Heartbeat supervisor is expected but not running.",
        )

    if TELEGRAM_BOT_TOKEN != TOKEN_PLACEHOLDER and not bool(
        payload.get("webhook_registered", True)
    ):
        add_alert(
            "warning", "webhook_unregistered", "Telegram webhook is not currently registered."
        )

    if (
        bool(payload.get("os_sandbox_required", False))
        and str(payload.get("os_sandbox_mode", "off")).lower() != "docker"
    ):
        add_alert(
            "critical",
            "os_sandbox_required_disabled",
            "OS sandbox is required but not running in docker mode.",
        )

    blocked_plugins = int(payload.get("plugin_tools_blocked", 0))
    if blocked_plugins > 0:
        add_alert(
            "info",
            "plugins_blocked",
            f"{blocked_plugins} plugin manifest(s) were blocked by policy.",
        )

    node_failures = int(payload.get("node_scheduler_failures", 0))
    if node_failures >= 5:
        add_alert(
            "warning",
            "node_scheduler_failures",
            f"Node scheduler recorded {node_failures} dispatch failures.",
        )

    if bool(payload.get("ops_auth_enabled", False)) and not OPS_AUTH_TOKEN:
        add_alert(
            "critical", "ops_auth_misconfigured", "Ops auth is enabled but OPS_AUTH_TOKEN is empty."
        )

    world_total = int(payload.get("world_model_forecasts_total", 0))
    world_accuracy = payload.get("world_model_recent_accuracy")
    if (
        world_total >= 12
        and isinstance(world_accuracy, (int, float))
        and float(world_accuracy) < 0.50
    ):
        add_alert(
            "warning",
            "world_model_accuracy_low",
            f"World-model forecast accuracy is low ({float(world_accuracy):.2f}) over recent runs.",
        )

    eval_fail_count = int(payload.get("eval_last_fail_count", 0))
    if eval_fail_count > 0:
        add_alert(
            "warning", "eval_failures", f"Latest eval run has {eval_fail_count} failing case(s)."
        )

    gate_state = payload.get("release_gate_last_status")
    if isinstance(gate_state, dict):
        state = str(gate_state.get("state") or "").strip().lower()
        if state == "fail":
            add_alert("warning", "release_gate_failed", "Release gate currently failing.")

    return alerts


def runtime_metrics() -> dict:
    """Return current runtime metrics."""
    payload = {
        "worker_alive": bool(RUNTIME_STATE["worker_alive"]),
        "llm_primary_model": RUNTIME_STATE["llm_primary_model"],
        "llm_fallback_model": RUNTIME_STATE["llm_fallback_model"],
        "llm_failover_enabled": bool(RUNTIME_STATE["llm_failover_enabled"]),
        "llm_last_model_used": RUNTIME_STATE["llm_last_model_used"],
        "llm_last_attempt_at": RUNTIME_STATE["llm_last_attempt_at"],
        "llm_last_success_at": RUNTIME_STATE["llm_last_success_at"],
        "llm_last_error": RUNTIME_STATE["llm_last_error"],
        "llm_failover_count": int(RUNTIME_STATE["llm_failover_count"]),
        "llm_primary_failures": int(RUNTIME_STATE["llm_primary_failures"]),
        "llm_fallback_failures": int(RUNTIME_STATE["llm_fallback_failures"]),
        "autonomy_mode": RUNTIME_STATE.get("autonomy_mode", AUTONOMY_MODE),
        "autonomy_openclaw_max": bool(
            RUNTIME_STATE.get("autonomy_openclaw_max", AUTONOMY_OPENCLAW_MAX)
        ),
        "policy_pack": RUNTIME_STATE.get("policy_pack", POLICY_PACK),
        "budget_governor_enabled": bool(
            RUNTIME_STATE.get("budget_governor_enabled", BUDGET_GOVERNOR_ENABLED)
        ),
        "budget_governor_mode": RUNTIME_STATE.get("budget_governor_mode", BUDGET_GOVERNOR_MODE),
        "budget_runs_started": int(RUNTIME_STATE.get("budget_runs_started", 0)),
        "budget_runs_stopped": int(RUNTIME_STATE.get("budget_runs_stopped", 0)),
        "budget_runs_degraded": int(RUNTIME_STATE.get("budget_runs_degraded", 0)),
        "budget_last_scope": RUNTIME_STATE.get("budget_last_scope"),
        "budget_last_reason": RUNTIME_STATE.get("budget_last_reason"),
        "budget_last_usage": dict(RUNTIME_STATE.get("budget_last_usage") or {}),
        "command_queue_mode": RUNTIME_STATE["command_queue_mode"],
        "command_queue_worker_target": int(
            RUNTIME_STATE.get("command_queue_worker_target", COMMAND_QUEUE_WORKER_COUNT)
        ),
        "command_queue_worker_alive": bool(RUNTIME_STATE["command_queue_worker_alive"]),
        "command_queue_worker_alive_count": int(
            RUNTIME_STATE.get("command_queue_worker_alive_count", 0)
        ),
        "command_queue_worker_restarts": int(RUNTIME_STATE["command_queue_worker_restarts"]),
        "command_queue_size": COMMAND_QUEUE.qsize(),
        "command_queue_max_size": COMMAND_QUEUE_MAX_SIZE,
        "command_queue_lane_limits": dict(COMMAND_QUEUE_LANE_LIMITS),
        "command_queue_enqueued": int(RUNTIME_STATE["command_queue_enqueued"]),
        "command_queue_processed": int(RUNTIME_STATE["command_queue_processed"]),
        "command_queue_dropped": int(RUNTIME_STATE["command_queue_dropped"]),
        "command_queue_direct_routed": int(RUNTIME_STATE["command_queue_direct_routed"]),
        "command_queue_auto_routed": int(RUNTIME_STATE["command_queue_auto_routed"]),
        "command_queue_mode_override_count": int(
            RUNTIME_STATE.get("command_queue_mode_override_count", 0)
        ),
        "command_queue_collect_merges": int(RUNTIME_STATE.get("command_queue_collect_merges", 0)),
        "command_queue_collect_flushes": int(RUNTIME_STATE.get("command_queue_collect_flushes", 0)),
        "command_queue_state_invalid_transitions": int(
            RUNTIME_STATE.get("command_queue_state_invalid_transitions", 0)
        ),
        "session_soft_trim_count": int(RUNTIME_STATE.get("session_soft_trim_count", 0)),
        "session_hard_clear_count": int(RUNTIME_STATE.get("session_hard_clear_count", 0)),
        "session_last_prune_chars": int(RUNTIME_STATE.get("session_last_prune_chars", 0)),
        "session_memory_flush_count": int(RUNTIME_STATE.get("session_memory_flush_count", 0)),
        "session_memory_flush_failures": int(RUNTIME_STATE.get("session_memory_flush_failures", 0)),
        "tool_policy_profile": RUNTIME_STATE["tool_policy_profile"],
        "tool_policy_blocks": int(RUNTIME_STATE["tool_policy_blocks"]),
        "workspace_diff_gate_enabled": bool(
            RUNTIME_STATE.get("workspace_diff_gate_enabled", WORKSPACE_DIFF_GATE_ENABLED)
        ),
        "workspace_diff_gate_mode": RUNTIME_STATE.get(
            "workspace_diff_gate_mode", WORKSPACE_DIFF_GATE_MODE
        ),
        "workspace_diff_gate_blocks": int(RUNTIME_STATE.get("workspace_diff_gate_blocks", 0)),
        "workspace_diff_gate_approvals": int(RUNTIME_STATE.get("workspace_diff_gate_approvals", 0)),
        "workspace_diff_gate_warns": int(RUNTIME_STATE.get("workspace_diff_gate_warns", 0)),
        "workspace_diff_gate_last_path": RUNTIME_STATE.get("workspace_diff_gate_last_path"),
        "workspace_diff_gate_last_reason": RUNTIME_STATE.get("workspace_diff_gate_last_reason"),
        "workspace_diff_gate_last_changed_lines": int(
            RUNTIME_STATE.get("workspace_diff_gate_last_changed_lines", 0)
        ),
        "secret_guardrail_enabled": bool(
            RUNTIME_STATE.get("secret_guardrail_enabled", SECRET_GUARDRAIL_ENABLED)
        ),
        "secret_redactions_total": int(RUNTIME_STATE.get("secret_redactions_total", 0)),
        "execution_sandbox_profile": active_execution_sandbox_profile(),
        "execution_sandbox_blocks": int(RUNTIME_STATE.get("execution_sandbox_blocks", 0)),
        "approval_gate_mode": RUNTIME_STATE.get("approval_gate_mode", APPROVAL_GATE_MODE),
        "approval_required_count": int(RUNTIME_STATE.get("approval_required_count", 0)),
        "approval_pending_count": int(RUNTIME_STATE.get("approval_pending_count", 0)),
        "approval_approved_count": int(RUNTIME_STATE.get("approval_approved_count", 0)),
        "approval_rejected_count": int(RUNTIME_STATE.get("approval_rejected_count", 0)),
        "approval_last_token": RUNTIME_STATE.get("approval_last_token"),
        "task_graph_branches_created": int(RUNTIME_STATE["task_graph_branches_created"]),
        "task_graph_resume_events": int(RUNTIME_STATE["task_graph_resume_events"]),
        "task_guard_orphan_requeues": int(RUNTIME_STATE["task_guard_orphan_requeues"]),
        "task_guard_dead_letters": int(RUNTIME_STATE["task_guard_dead_letters"]),
        "task_dedupe_hits": int(RUNTIME_STATE["task_dedupe_hits"]),
        "circuit_blocked_calls": int(RUNTIME_STATE["circuit_blocked_calls"]),
        "circuit_open_events": int(RUNTIME_STATE["circuit_open_events"]),
        "task_artifacts_stored": int(RUNTIME_STATE["task_artifacts_stored"]),
        "task_artifacts_pruned": int(RUNTIME_STATE["task_artifacts_pruned"]),
        "task_artifact_injections": int(RUNTIME_STATE["task_artifact_injections"]),
        "structured_task_calls": int(RUNTIME_STATE.get("structured_task_calls", 0)),
        "structured_task_failures": int(RUNTIME_STATE.get("structured_task_failures", 0)),
        "circuit_breakers": circuit_snapshot(),
        "plugin_tools_loaded": int(RUNTIME_STATE.get("plugin_tools_loaded", 0)),
        "plugin_tools_blocked": int(RUNTIME_STATE.get("plugin_tools_blocked", 0)),
        "remote_nodes_loaded": int(RUNTIME_STATE.get("remote_nodes_loaded", 0)),
        "node_control_plane_enabled": bool(
            RUNTIME_STATE.get("node_control_plane_enabled", NODE_CONTROL_PLANE_ENABLED)
        ),
        "node_control_plane_nodes": int(RUNTIME_STATE.get("node_control_plane_nodes", 0)),
        "node_control_plane_leases_active": int(
            RUNTIME_STATE.get("node_control_plane_leases_active", 0)
        ),
        "node_scheduler_dispatches": int(RUNTIME_STATE.get("node_scheduler_dispatches", 0)),
        "node_scheduler_failures": int(RUNTIME_STATE.get("node_scheduler_failures", 0)),
        "node_scheduler_last_node": RUNTIME_STATE.get("node_scheduler_last_node"),
        "node_scheduler_last_score": RUNTIME_STATE.get("node_scheduler_last_score"),
        "ops_auth_enabled": bool(RUNTIME_STATE.get("ops_auth_enabled", False)),
        "ops_auth_failures": int(RUNTIME_STATE.get("ops_auth_failures", 0)),
        "ops_auth_last_error": RUNTIME_STATE.get("ops_auth_last_error"),
        "ops_signature_failures": int(RUNTIME_STATE.get("ops_signature_failures", 0)),
        "ops_audit_events_total": int(RUNTIME_STATE.get("ops_audit_events_total", 0)),
        "ops_audit_last_hash": RUNTIME_STATE.get("ops_audit_last_hash"),
        "os_sandbox_mode": RUNTIME_STATE.get(
            "os_sandbox_mode", _normalize_os_sandbox_mode(OS_SANDBOX_MODE)
        ),
        "os_sandbox_required": bool(RUNTIME_STATE.get("os_sandbox_required", OS_SANDBOX_REQUIRED)),
        "os_sandbox_runs": int(RUNTIME_STATE.get("os_sandbox_runs", 0)),
        "os_sandbox_failures": int(RUNTIME_STATE.get("os_sandbox_failures", 0)),
        "desktop_control_enabled": bool(
            RUNTIME_STATE.get("desktop_control_enabled", DESKTOP_CONTROL_ENABLED)
        ),
        "desktop_actions_total": int(RUNTIME_STATE.get("desktop_actions_total", 0)),
        "desktop_last_action": RUNTIME_STATE.get("desktop_last_action"),
        "desktop_last_error": RUNTIME_STATE.get("desktop_last_error"),
        "desktop_session_required": bool(
            RUNTIME_STATE.get("desktop_session_required", DESKTOP_REQUIRE_ACTIVE_SESSION)
        ),
        "desktop_session_active": bool(RUNTIME_STATE.get("desktop_session_active", False)),
        "desktop_session_id": RUNTIME_STATE.get("desktop_session_id"),
        "desktop_sessions_started": int(RUNTIME_STATE.get("desktop_sessions_started", 0)),
        "desktop_sessions_completed": int(RUNTIME_STATE.get("desktop_sessions_completed", 0)),
        "desktop_sessions_replayed": int(RUNTIME_STATE.get("desktop_sessions_replayed", 0)),
        "desktop_last_session_path": RUNTIME_STATE.get("desktop_last_session_path"),
        "memory_last_retrieved_total": int(RUNTIME_STATE.get("memory_last_retrieved_total", 0)),
        "memory_last_lessons_retrieved": int(RUNTIME_STATE.get("memory_last_lessons_retrieved", 0)),
        "memory_last_summaries_retrieved": int(
            RUNTIME_STATE.get("memory_last_summaries_retrieved", 0)
        ),
        "memory_last_task_artifacts_retrieved": int(
            RUNTIME_STATE.get("memory_last_task_artifacts_retrieved", 0)
        ),
        "memory_last_lesson_quality": RUNTIME_STATE.get("memory_last_lesson_quality"),
        "memory_last_summary_quality": RUNTIME_STATE.get("memory_last_summary_quality"),
        "memory_last_task_artifact_quality": RUNTIME_STATE.get("memory_last_task_artifact_quality"),
        "memory_last_hit_quality": RUNTIME_STATE.get("memory_last_hit_quality"),
        "memory_last_continuity_score": RUNTIME_STATE.get("memory_last_continuity_score"),
        "memory_last_retrieval_at": RUNTIME_STATE.get("memory_last_retrieval_at"),
        "memory_lessons_pruned": int(RUNTIME_STATE.get("memory_lessons_pruned", 0)),
        "memory_summaries_pruned": int(RUNTIME_STATE.get("memory_summaries_pruned", 0)),
        "world_model_forecasts_total": int(RUNTIME_STATE.get("world_model_forecasts_total", 0)),
        "world_model_mismatches": int(RUNTIME_STATE.get("world_model_mismatches", 0)),
        "world_model_recent_accuracy": RUNTIME_STATE.get("world_model_recent_accuracy"),
        "world_model_last_forecast_at": RUNTIME_STATE.get("world_model_last_forecast_at"),
        "world_model_last_reconciliation_at": RUNTIME_STATE.get(
            "world_model_last_reconciliation_at"
        ),
        "self_improve_notes_total": int(RUNTIME_STATE.get("self_improve_notes_total", 0)),
        "self_improve_last_run_at": RUNTIME_STATE.get("self_improve_last_run_at"),
        "self_improve_last_note": RUNTIME_STATE.get("self_improve_last_note"),
        "dormant_capabilities_active": list(RUNTIME_STATE.get("dormant_capabilities_active", [])),
        "dormant_activations_total": int(RUNTIME_STATE.get("dormant_activations_total", 0)),
        "dormant_last_activation_at": RUNTIME_STATE.get("dormant_last_activation_at"),
        "blackbox_events_total": int(RUNTIME_STATE.get("blackbox_events_total", 0)),
        "blackbox_last_event_at": RUNTIME_STATE.get("blackbox_last_event_at"),
        "blackbox_reports_built": int(RUNTIME_STATE.get("blackbox_reports_built", 0)),
        "blackbox_recovery_plans_built": int(RUNTIME_STATE.get("blackbox_recovery_plans_built", 0)),
        "blackbox_last_recovery_plan_at": RUNTIME_STATE.get("blackbox_last_recovery_plan_at"),
        "blackbox_events_pruned": int(RUNTIME_STATE.get("blackbox_events_pruned", 0)),
        "blackbox_last_prune_at": RUNTIME_STATE.get("blackbox_last_prune_at"),
        "blackbox_last_prune_reason": RUNTIME_STATE.get("blackbox_last_prune_reason"),
        "blackbox_last_prune_count": int(RUNTIME_STATE.get("blackbox_last_prune_count", 0)),
        "blackbox_exports_built": int(RUNTIME_STATE.get("blackbox_exports_built", 0)),
        "blackbox_last_export_at": RUNTIME_STATE.get("blackbox_last_export_at"),
        "command_queue_owner_active": owner_active_count(),
        "command_queue_owner_backlog": owner_backlog_count(),
        "spine_supervisor_alive": bool(RUNTIME_STATE["spine_supervisor_alive"]),
        "startup_preflight_ok": bool(RUNTIME_STATE["startup_preflight_ok"]),
        "startup_preflight_errors": list(RUNTIME_STATE.get("startup_preflight_errors", [])),
        "db_healthy": bool(RUNTIME_STATE["db_healthy"]),
        "db_last_check": RUNTIME_STATE["db_last_check"],
        "db_last_error": RUNTIME_STATE["db_last_error"],
        "task_worker_restarts": int(RUNTIME_STATE["task_worker_restarts"]),
        "webhook_supervisor_restarts": int(RUNTIME_STATE["webhook_supervisor_restarts"]),
        "webhook_registered": bool(RUNTIME_STATE["webhook_registered"]),
        "webhook_last_attempt": RUNTIME_STATE["webhook_last_attempt"],
        "webhook_last_success": RUNTIME_STATE["webhook_last_success"],
        "webhook_last_error": RUNTIME_STATE["webhook_last_error"],
        "webhook_next_retry_at": RUNTIME_STATE["webhook_next_retry_at"],
        "cron_supervisor_alive": bool(RUNTIME_STATE.get("cron_supervisor_alive", False)),
        "cron_due_runs": int(RUNTIME_STATE.get("cron_due_runs", 0)),
        "cron_failures": int(RUNTIME_STATE.get("cron_failures", 0)),
        "cron_last_tick": RUNTIME_STATE.get("cron_last_tick"),
        "heartbeat_supervisor_alive": bool(RUNTIME_STATE.get("heartbeat_supervisor_alive", False)),
        "heartbeat_ticks_total": int(RUNTIME_STATE.get("heartbeat_ticks_total", 0)),
        "heartbeat_manual_wakes": int(RUNTIME_STATE.get("heartbeat_manual_wakes", 0)),
        "heartbeat_last_tick": RUNTIME_STATE.get("heartbeat_last_tick"),
        "heartbeat_last_reason": RUNTIME_STATE.get("heartbeat_last_reason"),
        "heartbeat_last_alert_count": int(RUNTIME_STATE.get("heartbeat_last_alert_count", 0)),
        "heartbeat_next_tick_at": RUNTIME_STATE.get("heartbeat_next_tick_at"),
        "heartbeat_restarts": int(RUNTIME_STATE.get("heartbeat_restarts", 0)),
        "eval_runs_total": int(RUNTIME_STATE.get("eval_runs_total", 0)),
        "eval_autoruns_total": int(RUNTIME_STATE.get("eval_autoruns_total", 0)),
        "eval_last_run_at": RUNTIME_STATE.get("eval_last_run_at"),
        "eval_last_pass_rate": RUNTIME_STATE.get("eval_last_pass_rate"),
        "eval_last_fail_count": int(RUNTIME_STATE.get("eval_last_fail_count", 0)),
        "task_role_loop_enabled": bool(
            RUNTIME_STATE.get("task_role_loop_enabled", TASK_ROLE_LOOP_ENABLED)
        ),
        "task_role_loop_mode": RUNTIME_STATE.get("task_role_loop_mode", TASK_ROLE_LOOP_MODE),
        "task_role_loop_runs": int(RUNTIME_STATE.get("task_role_loop_runs", 0)),
        "task_role_loop_last_role": RUNTIME_STATE.get("task_role_loop_last_role"),
        "team_mode_enabled": bool(RUNTIME_STATE.get("team_mode_enabled", TEAM_MODE_ENABLED)),
        "identity_scope_mode": RUNTIME_STATE.get("identity_scope_mode", IDENTITY_SCOPE_MODE),
        "team_agents_total": int(RUNTIME_STATE.get("team_agents_total", 0)),
        "team_last_agent": RUNTIME_STATE.get("team_last_agent"),
        "team_broadcasts_total": int(RUNTIME_STATE.get("team_broadcasts_total", 0)),
        "context_xray_snapshots_total": int(RUNTIME_STATE.get("context_xray_snapshots_total", 0)),
        "context_xray_last_snapshot_at": RUNTIME_STATE.get("context_xray_last_snapshot_at"),
        "host_exec_interlock_enabled": bool(
            RUNTIME_STATE.get("host_exec_interlock_enabled", HOST_EXEC_INTERLOCK_ENABLED)
        ),
        "host_exec_grants_issued": int(RUNTIME_STATE.get("host_exec_grants_issued", 0)),
        "host_exec_grants_consumed": int(RUNTIME_STATE.get("host_exec_grants_consumed", 0)),
        "host_exec_interlock_blocks": int(RUNTIME_STATE.get("host_exec_interlock_blocks", 0)),
        "workspace_isolation_enabled": bool(
            RUNTIME_STATE.get("workspace_isolation_enabled", WORKSPACE_ISOLATION_ENABLED)
        ),
        "workspace_session_isolation_enabled": bool(
            RUNTIME_STATE.get(
                "workspace_session_isolation_enabled", WORKSPACE_SESSION_ISOLATION_ENABLED
            )
        ),
        "workspace_isolation_blocks": int(RUNTIME_STATE.get("workspace_isolation_blocks", 0)),
        "workspace_isolation_last_root": RUNTIME_STATE.get("workspace_isolation_last_root"),
        "sandbox_registry_count": int(RUNTIME_STATE.get("sandbox_registry_count", 0)),
        "sandbox_registry_reused": int(RUNTIME_STATE.get("sandbox_registry_reused", 0)),
        "sandbox_registry_created": int(RUNTIME_STATE.get("sandbox_registry_created", 0)),
        "sandbox_registry_cleanups": int(RUNTIME_STATE.get("sandbox_registry_cleanups", 0)),
        "sandbox_registry_last_context": RUNTIME_STATE.get("sandbox_registry_last_context"),
        "sandbox_registry_last_error": RUNTIME_STATE.get("sandbox_registry_last_error"),
        "model_router_enabled": bool(RUNTIME_STATE.get("model_router_enabled", True)),
        "model_router_profiles_loaded": int(RUNTIME_STATE.get("model_router_profiles_loaded", 0)),
        "model_router_last_profile": RUNTIME_STATE.get("model_router_last_profile"),
        "model_router_failovers": int(RUNTIME_STATE.get("model_router_failovers", 0)),
        "model_router_cooldowns": int(RUNTIME_STATE.get("model_router_cooldowns", 0)),
        "model_router_profile_disables": int(RUNTIME_STATE.get("model_router_profile_disables", 0)),
        "model_router_compat_skips": int(RUNTIME_STATE.get("model_router_compat_skips", 0)),
        "workflow_programs_total": int(RUNTIME_STATE.get("workflow_programs_total", 0)),
        "workflow_runs_total": int(RUNTIME_STATE.get("workflow_runs_total", 0)),
        "workflow_v2_runs": int(RUNTIME_STATE.get("workflow_v2_runs", 0)),
        "memory_vault_bootstraps": int(RUNTIME_STATE.get("memory_vault_bootstraps", 0)),
        "memory_vault_backups": int(RUNTIME_STATE.get("memory_vault_backups", 0)),
        "memory_vault_restores": int(RUNTIME_STATE.get("memory_vault_restores", 0)),
        "task_checkpoint_snapshots": int(RUNTIME_STATE.get("task_checkpoint_snapshots", 0) or 0),
        "task_checkpoint_replay_restores": int(
            RUNTIME_STATE.get("task_checkpoint_replay_restores", 0) or 0
        ),
        "task_checkpoint_restore_failures": int(
            RUNTIME_STATE.get("task_checkpoint_restore_failures", 0) or 0
        ),
        "task_checkpoint_restore_drift": int(
            RUNTIME_STATE.get("task_checkpoint_restore_drift", 0) or 0
        ),
        "task_checkpoint_last_replay_mode": RUNTIME_STATE.get("task_checkpoint_last_replay_mode"),
        "usage_ledger_events": int(RUNTIME_STATE.get("usage_ledger_events", 0) or 0),
        "usage_ledger_cost_usd": float(RUNTIME_STATE.get("usage_ledger_cost_usd", 0.0) or 0.0),
        "canary_enabled": bool(RUNTIME_STATE.get("canary_enabled", CANARY_ROUTER_ENABLED)),
        "canary_samples": int(RUNTIME_STATE.get("canary_samples", 0) or 0),
        "canary_failures": int(RUNTIME_STATE.get("canary_failures", 0) or 0),
        "canary_rolled_back": bool(RUNTIME_STATE.get("canary_rolled_back", False)),
        "canary_last_reason": RUNTIME_STATE.get("canary_last_reason"),
        "canary_last_rollback_at": RUNTIME_STATE.get("canary_last_rollback_at"),
        "schema_version": int(RUNTIME_STATE.get("schema_version", 0) or 0),
        "protocol_schema_count": int(RUNTIME_STATE.get("protocol_schema_count", 0) or 0),
        "protocol_schema_validations": int(
            RUNTIME_STATE.get("protocol_schema_validations", 0) or 0
        ),
        "protocol_schema_failures": int(RUNTIME_STATE.get("protocol_schema_failures", 0) or 0),
        "ssrf_blocked_requests": int(RUNTIME_STATE.get("ssrf_blocked_requests", 0) or 0),
        "node_policy_blocks": int(RUNTIME_STATE.get("node_policy_blocks", 0) or 0),
        "release_gate_last_status": RUNTIME_STATE.get("release_gate_last_status"),
        "task_queue_size": TASK_QUEUE.qsize(),
        "tasks_tracked": len(TASK_QUEUE_IDS),
    }
    alerts = compute_runtime_alerts(payload)
    payload["runtime_alerts"] = alerts
    payload["runtime_alert_count"] = len(alerts)
    return payload


def runtime_uptime_seconds() -> float | None:
    """Return runtime uptime in seconds."""
    started = RUNTIME_STATE.get("app_start_monotonic")
    if started is None:
        return None
    return round(max(0.0, time.monotonic() - float(started)), 3)


# ============================================================================
# SSE and Blackbox Event Streaming
# ============================================================================


def sse_frame(event: str, data: dict, event_id: int | None = None) -> str:
    """Create an SSE frame."""
    payload = data
    try:
        payload, _ = redact_secret_data(data)
    except Exception:
        payload = data
    lines = []
    if event_id is not None:
        lines.append(f"id: {int(event_id)}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


async def blackbox_event_stream_generator(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    after_event_id: int = 0,
    poll_seconds: float = 1.0,
    batch_size: int = 120,
):
    """Generate SSE stream for blackbox events."""
    cursor = max(0, int(after_event_id))
    wait_seconds = max(0.2, min(10.0, float(poll_seconds)))
    batch_limit = max(10, min(BLACKBOX_READ_MAX_LIMIT, int(batch_size)))
    keepalive_tick = 0
    while True:
        events = fetch_blackbox_events_after(
            owner_id=int(owner_id),
            after_event_id=cursor,
            session_id=session_id,
            source_type=source_type,
            limit=batch_limit,
        )
        if events:
            for event in events:
                try:
                    event_id = int(event.get("id") or 0)
                except Exception:
                    event_id = cursor
                if event_id > cursor:
                    cursor = event_id
                event_name = str(event.get("event_type") or "blackbox_event")
                yield sse_frame(event=event_name, data=event, event_id=event_id)
            keepalive_tick = 0
            continue

        keepalive_tick += 1
        if keepalive_tick >= int(max(5, round(15.0 / wait_seconds))):
            yield ": keepalive\n\n"
            keepalive_tick = 0
        await asyncio.sleep(wait_seconds)


# ============================================================================
# Continuous Evaluation
# ============================================================================


def run_continuous_eval_suite(max_cases: int = 12) -> dict:
    """Run continuous evaluation suite."""
    if not EVAL_HARNESS_ENABLED:
        return {"ok": False, "error": "Eval harness disabled."}

    case_limit = max(1, min(EVAL_MAX_CASES, int(max_cases or EVAL_MAX_CASES)))
    cases: list[dict] = []

    metrics = runtime_metrics()
    must_have_runtime = {
        "worker_alive",
        "spine_supervisor_alive",
        "db_healthy",
        "webhook_registered",
        "command_queue_mode",
        "tool_policy_profile",
        "execution_sandbox_profile",
        "approval_gate_mode",
        "budget_governor_mode",
    }
    missing_runtime = sorted(k for k in must_have_runtime if k not in metrics)
    cases.append(
        {
            "name": "runtime_contract",
            "ok": len(missing_runtime) == 0,
            "detail": "runtime keys present"
            if not missing_runtime
            else f"missing keys: {', '.join(missing_runtime)}",
        }
    )

    cases.append(
        {
            "name": "policy_pack_valid",
            "ok": POLICY_PACK in POLICY_PACK_PRESETS,
            "detail": f"policy_pack={POLICY_PACK}",
        }
    )

    redacted, hits = redact_secret_data("Authorization: Bearer sk-live-super-secret-token-123456")
    redaction_ok = (
        SECRET_GUARDRAIL_ENABLED and (hits > 0) and (SECRET_REDACTION_TOKEN in str(redacted))
    )
    cases.append(
        {
            "name": "secret_redaction",
            "ok": redaction_ok,
            "detail": f"hits={hits}",
        }
    )

    diff_probe = evaluate_workspace_diff_gate(
        "write_file",
        {
            "file_path": "mind-clone/.diff_gate_probe.txt",
            "content": "\n".join(
                f"line {i}" for i in range(int(WORKSPACE_DIFF_MAX_CHANGED_LINES) + 30)
            ),
        },
    )
    diff_ok = True
    if WORKSPACE_DIFF_GATE_ENABLED:
        if WORKSPACE_DIFF_GATE_MODE == "block":
            diff_ok = bool(diff_probe.get("blocked"))
        elif WORKSPACE_DIFF_GATE_MODE == "approval":
            diff_ok = bool(diff_probe.get("require_approval"))
        else:
            diff_ok = bool(diff_probe.get("warned"))
    cases.append(
        {
            "name": "workspace_diff_gate",
            "ok": diff_ok,
            "detail": f"mode={WORKSPACE_DIFF_GATE_MODE} changed_lines={diff_probe.get('changed_lines')}",
        }
    )

    budget_probe = create_run_budget("eval_probe", owner_id=0, source_ref="eval")
    if budget_probe is not None:
        from mind_clone.config import BUDGET_MAX_LLM_CALLS

        budget_probe["llm_calls"] = int(BUDGET_MAX_LLM_CALLS) + 1
        stop_hit, _ = budget_should_stop(budget_probe)
        if BUDGET_GOVERNOR_MODE == "stop":
            budget_ok = bool(stop_hit)
        elif BUDGET_GOVERNOR_MODE == "degrade":
            budget_ok = bool(budget_should_degrade(budget_probe))
        else:
            budget_ok = True
    else:
        budget_ok = True
    cases.append(
        {
            "name": "budget_governor_mode",
            "ok": budget_ok,
            "detail": f"mode={BUDGET_GOVERNOR_MODE}",
        }
    )

    case_results = cases[:case_limit]
    passed = sum(1 for row in case_results if bool(row.get("ok")))
    failed = max(0, len(case_results) - passed)
    pass_rate = round((passed / max(1, len(case_results))), 4)
    report = {
        "ok": failed == 0,
        "total_cases": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "pass_rate": pass_rate,
        "cases": case_results,
        "timestamp": utc_now_iso(),
    }
    RUNTIME_STATE["eval_runs_total"] = int(RUNTIME_STATE.get("eval_runs_total", 0)) + 1
    RUNTIME_STATE["eval_last_run_at"] = report["timestamp"]
    RUNTIME_STATE["eval_last_pass_rate"] = pass_rate
    RUNTIME_STATE["eval_last_fail_count"] = int(failed)
    RUNTIME_STATE["eval_last_report"] = report
    return report


def evaluate_release_gate(run_eval: bool = False, max_cases: int | None = None) -> dict:
    """Evaluate release gate status."""
    report = dict(RUNTIME_STATE.get("eval_last_report") or {})
    if run_eval or not report:
        report = run_continuous_eval_suite(max_cases=max_cases or EVAL_MAX_CASES)
        if not bool(report.get("ok", False)) and "cases" not in report:
            status = {
                "state": "fail",
                "reason": str(report.get("error") or "eval_failed"),
                "pass_rate": 0.0,
                "failed_cases": int(report.get("failed_cases", 1) or 1),
                "min_pass_rate": float(RELEASE_GATE_MIN_PASS_RATE),
                "require_zero_fails": bool(RELEASE_GATE_REQUIRE_ZERO_FAILS),
                "checked_at": utc_now_iso(),
            }
            RUNTIME_STATE["release_gate_last_status"] = status
            return {"ok": False, "state": "fail", "status": status, "eval_report": report}

    pass_rate = float(report.get("pass_rate", 0.0) or 0.0)
    failed_cases = int(report.get("failed_cases", 0) or 0)
    has_min_rate = pass_rate >= float(RELEASE_GATE_MIN_PASS_RATE)
    has_zero_fails = (failed_cases == 0) if RELEASE_GATE_REQUIRE_ZERO_FAILS else True
    gate_ok = bool(has_min_rate and has_zero_fails)
    reason_parts = []
    if not has_min_rate:
        reason_parts.append(f"pass_rate<{RELEASE_GATE_MIN_PASS_RATE:.2f}")
    if not has_zero_fails:
        reason_parts.append("failing_cases_present")
    status = {
        "state": "pass" if gate_ok else "fail",
        "reason": ", ".join(reason_parts) if reason_parts else "ok",
        "pass_rate": round(pass_rate, 4),
        "failed_cases": int(failed_cases),
        "min_pass_rate": float(RELEASE_GATE_MIN_PASS_RATE),
        "require_zero_fails": bool(RELEASE_GATE_REQUIRE_ZERO_FAILS),
        "checked_at": utc_now_iso(),
    }
    RUNTIME_STATE["release_gate_last_status"] = status
    return {"ok": gate_ok, "state": status["state"], "status": status, "eval_report": report}


# ============================================================================
# Heartbeat Self-Check
# ============================================================================


def run_heartbeat_self_check(reason: str = "interval") -> dict:
    """Run heartbeat self-check."""
    reason_key = str(reason or "interval").strip().lower()
    if reason_key not in {"interval", "manual_wake", "startup"}:
        reason_key = "interval"
    check_db_liveness()
    payload = runtime_metrics()
    alert_count = int(payload.get("runtime_alert_count", 0))
    RUNTIME_STATE["heartbeat_ticks_total"] = int(RUNTIME_STATE.get("heartbeat_ticks_total", 0)) + 1
    RUNTIME_STATE["heartbeat_last_tick"] = utc_now_iso()
    RUNTIME_STATE["heartbeat_last_reason"] = reason_key
    RUNTIME_STATE["heartbeat_last_alert_count"] = alert_count
    RUNTIME_STATE["heartbeat_next_tick_at"] = iso_after_seconds(HEARTBEAT_INTERVAL_SECONDS)
    if reason_key == "manual_wake":
        RUNTIME_STATE["heartbeat_manual_wakes"] = (
            int(RUNTIME_STATE.get("heartbeat_manual_wakes", 0)) + 1
        )

    if EVAL_HARNESS_ENABLED and EVAL_AUTORUN_EVERY_TICKS > 0:
        tick_no = int(RUNTIME_STATE.get("heartbeat_ticks_total", 0))
        if tick_no > 0 and tick_no % int(EVAL_AUTORUN_EVERY_TICKS) == 0:
            report = run_continuous_eval_suite(max_cases=min(8, EVAL_MAX_CASES))
            if report.get("ok"):
                RUNTIME_STATE["eval_autoruns_total"] = (
                    int(RUNTIME_STATE.get("eval_autoruns_total", 0)) + 1
                )
            log.info(
                "EVAL_AUTORUN tick=%d ok=%s pass_rate=%s",
                tick_no,
                bool(report.get("ok", False)),
                report.get("pass_rate"),
            )
    try:
        evaluate_release_gate(run_eval=False)
    except Exception:
        pass

    # Cleanup idle browser sessions
    if BROWSER_TOOL_ENABLED:
        try:
            _cleanup_browser_sessions()
        except Exception:
            pass

    # Goal supervisor — check active goals periodically
    tick_no = int(RUNTIME_STATE.get("heartbeat_ticks_total", 0))
    if GOAL_SYSTEM_ENABLED and tick_no > 0 and tick_no % GOAL_SUPERVISOR_EVERY_TICKS == 0:
        try:
            db = SessionLocal()
            try:
                goal_tasks = run_goal_supervisor(db)
                if goal_tasks > 0:
                    log.info("GOAL_SUPERVISOR new_tasks=%d", goal_tasks)
            finally:
                db.close()
        except Exception:
            pass

    # Prune old tool performance logs every 10 ticks
    if TOOL_PERF_TRACKING_ENABLED and tick_no > 0 and tick_no % 10 == 0:
        try:
            pruned = prune_tool_performance_logs()
            if pruned > 0:
                log.info("TOOL_PERF_PRUNE deleted=%d", pruned)
        except Exception:
            pass

    if CUSTOM_TOOL_ENABLED and tick_no > 0 and tick_no % 20 == 0:
        try:
            prune_custom_tools()
        except Exception:
            pass

    if alert_count > 0:
        log.info("HEARTBEAT_TICK reason=%s alerts=%d", reason_key, alert_count)
    else:
        log.info("HEARTBEAT_TICK reason=%s alerts=0", reason_key)
    return {
        "ok": True,
        "reason": reason_key,
        "alert_count": alert_count,
        "timestamp": RUNTIME_STATE.get("heartbeat_last_tick"),
    }


async def heartbeat_supervisor_loop():
    """Heartbeat supervisor loop."""
    global HEARTBEAT_WAKE_EVENT
    if HEARTBEAT_WAKE_EVENT is None:
        HEARTBEAT_WAKE_EVENT = asyncio.Event()
    RUNTIME_STATE["heartbeat_supervisor_alive"] = True
    RUNTIME_STATE["heartbeat_next_tick_at"] = iso_after_seconds(HEARTBEAT_INTERVAL_SECONDS)
    log.info("HEARTBEAT_SUPERVISOR_START interval=%ss", HEARTBEAT_INTERVAL_SECONDS)
    try:
        while True:
            if RUNTIME_STATE.get("shutting_down"):
                await asyncio.sleep(1)
                continue

            wake_reason = "interval"
            try:
                await asyncio.wait_for(
                    HEARTBEAT_WAKE_EVENT.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
                wake_reason = "manual_wake"
            except asyncio.TimeoutError:
                wake_reason = "interval"
            finally:
                HEARTBEAT_WAKE_EVENT.clear()

            if RUNTIME_STATE.get("shutting_down"):
                continue
            await asyncio.to_thread(run_heartbeat_self_check, wake_reason)
    except asyncio.CancelledError:
        log.info("HEARTBEAT_SUPERVISOR_STOP")
        raise
    finally:
        RUNTIME_STATE["heartbeat_supervisor_alive"] = False
        RUNTIME_STATE["heartbeat_next_tick_at"] = None


# ============================================================================
# Cron Jobs
# ============================================================================


def bootstrap_cron_jobs_from_env():
    """Bootstrap cron jobs from environment variable."""
    raw = (CRON_BOOTSTRAP_JOBS_JSON or "").strip()
    if not raw or raw in {"[]", "{}"}:
        return
    db = SessionLocal()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return
        now_dt = datetime.now(timezone.utc)
        created = 0
        for item in parsed[:50]:
            if not isinstance(item, dict):
                continue
            owner_id = int(item.get("owner_id") or 0)
            name = truncate_text(str(item.get("name") or "").strip(), 120)
            message = truncate_text(str(item.get("message") or "").strip(), 4000)
            interval = clamp_int(
                item.get("interval_seconds"), CRON_MIN_INTERVAL_SECONDS, 604800, 300
            )
            lane = _normalize_schedule_lane(str(item.get("lane") or "cron"))
            if owner_id <= 0 or not name or not message:
                continue
            exists = (
                db.query(ScheduledJob)
                .filter(
                    ScheduledJob.owner_id == owner_id,
                    ScheduledJob.name == name,
                    ScheduledJob.message == message,
                    ScheduledJob.interval_seconds == interval,
                )
                .first()
            )
            if exists:
                continue
            row = ScheduledJob(
                owner_id=owner_id,
                name=name,
                message=message,
                lane=lane,
                interval_seconds=interval,
                enabled=1,
                run_count=0,
                next_run_at=now_dt + timedelta(seconds=interval),
            )
            db.add(row)
            created += 1
        if created:
            db.commit()
            log.info("CRON_BOOTSTRAP_CREATED count=%d", created)
    except Exception as e:
        db.rollback()
        log.warning("CRON_BOOTSTRAP_FAIL error=%s", str(e)[:220])
    finally:
        db.close()


async def run_due_cron_jobs_once() -> int:
    """Run all due cron jobs."""
    if not CRON_ENABLED:
        return 0

    dispatch_payloads: list[dict] = []
    db = SessionLocal()
    try:
        now_dt = datetime.now(timezone.utc)
        due_rows = (
            db.query(ScheduledJob)
            .filter(
                ScheduledJob.enabled == 1,
                ScheduledJob.next_run_at <= now_dt,
            )
            .order_by(ScheduledJob.next_run_at.asc(), ScheduledJob.id.asc())
            .limit(CRON_MAX_DUE_PER_TICK)
            .all()
        )
        for row in due_rows:
            owner = db.query(User).filter(User.id == row.owner_id).first()
            row.last_run_at = now_dt
            if row.run_at_time:
                row.next_run_at = _compute_next_run_at_time(row.run_at_time)
            else:
                row.next_run_at = now_dt + timedelta(
                    seconds=clamp_int(row.interval_seconds, CRON_MIN_INTERVAL_SECONDS, 604800, 300)
                )
            row.run_count = int(row.run_count or 0) + 1
            row.last_error = None
            if owner is None or not owner.telegram_chat_id:
                row.last_error = "Owner or telegram chat not found."
                continue
            dispatch_payloads.append(
                {
                    "job_id": row.id,
                    "owner_id": int(row.owner_id),
                    "chat_id": str(owner.telegram_chat_id),
                    "username": str(owner.username or "cron"),
                    "text": str(row.message),
                    "lane": normalize_queue_lane(str(row.lane or "cron")),
                }
            )
        if due_rows:
            db.commit()
    except Exception as e:
        db.rollback()
        RUNTIME_STATE["cron_failures"] = int(RUNTIME_STATE.get("cron_failures", 0)) + 1
        log.warning("CRON_DUE_QUERY_FAIL error=%s", str(e)[:220])
        return 0
    finally:
        db.close()

    executed = 0
    for payload in dispatch_payloads:
        try:
            result = await dispatch_incoming_message(
                owner_id=int(payload["owner_id"]),
                chat_id=str(payload["chat_id"]),
                username=str(payload.get("username", "cron")),
                text=str(payload["text"]),
                source="cron",
                expect_response=False,
            )
            if result.get("ok"):
                executed += 1
            else:
                db2 = SessionLocal()
                try:
                    row = (
                        db2.query(ScheduledJob)
                        .filter(ScheduledJob.id == int(payload["job_id"]))
                        .first()
                    )
                    if row:
                        row.last_error = truncate_text(
                            str(result.get("error", "Unknown cron dispatch error.")), 300
                        )
                        db2.commit()
                except Exception:
                    db2.rollback()
                finally:
                    db2.close()
        except Exception as e:
            RUNTIME_STATE["cron_failures"] = int(RUNTIME_STATE.get("cron_failures", 0)) + 1
            log.warning(
                "CRON_DISPATCH_FAIL job_id=%s error=%s", payload.get("job_id"), str(e)[:220]
            )
    return executed


async def cron_supervisor_loop():
    """Cron supervisor loop."""
    bootstrap_cron_jobs_from_env()
    RUNTIME_STATE["cron_supervisor_alive"] = True
    log.info("CRON_SUPERVISOR_START tick=%ss", CRON_TICK_SECONDS)
    try:
        while True:
            await asyncio.sleep(CRON_TICK_SECONDS)
            if RUNTIME_STATE.get("shutting_down"):
                continue
            RUNTIME_STATE["cron_last_tick"] = utc_now_iso()
            executed = await run_due_cron_jobs_once()
            if executed > 0:
                RUNTIME_STATE["cron_due_runs"] = (
                    int(RUNTIME_STATE.get("cron_due_runs", 0)) + executed
                )
                log.info("CRON_DUE_RUNS executed=%d", executed)
    except asyncio.CancelledError:
        log.info("CRON_SUPERVISOR_STOP")
        raise
    finally:
        RUNTIME_STATE["cron_supervisor_alive"] = False


# ============================================================================
# Webhook Management
# ============================================================================


async def try_set_telegram_webhook_once() -> tuple[bool, str | None]:
    """Try to set Telegram webhook once."""
    if TELEGRAM_BOT_TOKEN == TOKEN_PLACEHOLDER:
        msg = "Telegram bot token not configured."
        RUNTIME_STATE["webhook_registered"] = False
        RUNTIME_STATE["webhook_last_error"] = msg
        RUNTIME_STATE["webhook_next_retry_at"] = None
        return False, msg

    url = f"{TELEGRAM_API}/setWebhook"
    webhook_url = f"{TELEGRAM_WEBHOOK_BASE_URL}/telegram/webhook"

    attempt = int(RUNTIME_STATE["webhook_retry_attempt"]) + 1
    RUNTIME_STATE["webhook_retry_attempt"] = attempt
    RUNTIME_STATE["webhook_last_attempt"] = utc_now_iso()

    log.info(f"WEBHOOK_ATTEMPT attempt={attempt} webhook_url={webhook_url}")

    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(url, json={"url": webhook_url})
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok", False):
            err = truncate_text(str(payload.get("description", "Unknown Telegram response")), 400)
            RUNTIME_STATE["webhook_registered"] = False
            RUNTIME_STATE["webhook_last_error"] = err
            log.warning(f"WEBHOOK_FAIL attempt={attempt} error={err}")
            return False, err

        RUNTIME_STATE["webhook_registered"] = True
        RUNTIME_STATE["webhook_last_success"] = utc_now_iso()
        RUNTIME_STATE["webhook_last_error"] = None
        RUNTIME_STATE["webhook_next_retry_at"] = None
        RUNTIME_STATE["webhook_retry_attempt"] = 0
        RUNTIME_STATE["webhook_retry_delay_seconds"] = WEBHOOK_RETRY_BASE_SECONDS
        log.info(f"WEBHOOK_OK attempt={attempt}")
        return True, None

    except Exception as e:
        err = truncate_text(str(e), 400)
        RUNTIME_STATE["webhook_registered"] = False
        RUNTIME_STATE["webhook_last_error"] = err
        log.warning(f"WEBHOOK_FAIL attempt={attempt} error={err}")
        return False, err


async def webhook_retry_loop():
    """Webhook retry loop with exponential backoff."""
    while True:
        delay = float(RUNTIME_STATE.get("webhook_retry_delay_seconds", WEBHOOK_RETRY_BASE_SECONDS))
        jitter = random.uniform(0.0, delay * WEBHOOK_RETRY_JITTER_RATIO)
        wait_seconds = delay + jitter
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        RUNTIME_STATE["webhook_next_retry_at"] = next_retry_at.isoformat()

        log.info(f"WEBHOOK_ATTEMPT scheduled_in={wait_seconds:.1f}s")

        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            RUNTIME_STATE["webhook_next_retry_at"] = None
            raise

        ok, err = await try_set_telegram_webhook_once()
        if ok:
            RUNTIME_STATE["webhook_next_retry_at"] = None
            return

        next_delay = min(
            WEBHOOK_RETRY_MAX_SECONDS,
            max(WEBHOOK_RETRY_BASE_SECONDS, delay * WEBHOOK_RETRY_FACTOR),
        )
        RUNTIME_STATE["webhook_retry_delay_seconds"] = next_delay
        log.warning(
            f"WEBHOOK_FAIL retry_in={next_delay:.1f}s error={truncate_text(err or '', 220)}"
        )


async def webhook_retry_supervisor_loop():
    """Webhook retry supervisor loop."""
    global WEBHOOK_RETRY_TASK

    log.info("WEBHOOK_SUPERVISOR started")
    while True:
        WEBHOOK_RETRY_TASK = asyncio.create_task(webhook_retry_loop())
        try:
            await WEBHOOK_RETRY_TASK
        except asyncio.CancelledError:
            if WEBHOOK_RETRY_TASK and not WEBHOOK_RETRY_TASK.done():
                WEBHOOK_RETRY_TASK.cancel()
                try:
                    await WEBHOOK_RETRY_TASK
                except asyncio.CancelledError:
                    pass
            WEBHOOK_RETRY_TASK = None
            log.info("WEBHOOK_SUPERVISOR stopped")
            raise
        except Exception as e:
            WEBHOOK_RETRY_TASK = None
            log.error(f"WEBHOOK_SUPERVISOR crash={e}; restarting")
            await asyncio.sleep(1)
            continue

        WEBHOOK_RETRY_TASK = None
        if RUNTIME_STATE["webhook_registered"]:
            log.info("WEBHOOK_SUPERVISOR completed")
            return

        log.error("WEBHOOK_SUPERVISOR unexpected retry loop exit; restarting")
        await asyncio.sleep(1)


# ============================================================================
# Spine Supervisor
# ============================================================================


def _task_completion_reason(task: asyncio.Task | None) -> str:
    """Get the completion reason for a task."""
    if task is None:
        return "missing"
    if not task.done():
        return "alive"
    if task.cancelled():
        return "cancelled"
    try:
        exc = task.exception()
    except Exception as e:
        return truncate_text(str(e), 160)
    if exc is None:
        return "completed"
    return truncate_text(str(exc), 160)


async def spine_supervisor_loop():
    """Spine supervisor loop - monitors and restarts background tasks."""
    from mind_clone.core.state import (
        TASK_WORKER_TASK,
        WEBHOOK_SUPERVISOR_TASK,
        COMMAND_QUEUE_WORKER_TASK,
        CRON_SUPERVISOR_TASK,
        HEARTBEAT_SUPERVISOR_TASK,
    )

    tick = 0
    last_blackbox_prune_monotonic = time.monotonic()
    RUNTIME_STATE["spine_supervisor_alive"] = True
    log.info("SPINE_WATCHDOG_START")
    try:
        while True:
            await asyncio.sleep(15)
            tick += 1

            if RUNTIME_STATE.get("shutting_down"):
                continue

            if TASK_WORKER_TASK is None or TASK_WORKER_TASK.done():
                reason = _task_completion_reason(TASK_WORKER_TASK)
                TASK_WORKER_TASK = asyncio.create_task(task_worker_loop())
                RUNTIME_STATE["task_worker_restarts"] = (
                    int(RUNTIME_STATE["task_worker_restarts"]) + 1
                )
                log.warning(
                    "SPINE_TASK_WORKER_RESTART count=%d reason=%s",
                    RUNTIME_STATE["task_worker_restarts"],
                    reason,
                )

            if command_queue_enabled():
                active_workers = active_command_queue_worker_count()
                if active_workers < COMMAND_QUEUE_WORKER_COUNT:
                    await ensure_command_queue_workers_running()
                    started = max(0, active_command_queue_worker_count() - active_workers)
                    if started > 0:
                        RUNTIME_STATE["command_queue_worker_restarts"] = (
                            int(RUNTIME_STATE["command_queue_worker_restarts"]) + started
                        )
                        log.warning(
                            "SPINE_COMMAND_QUEUE_RESTART started=%d alive=%d target=%d",
                            started,
                            active_command_queue_worker_count(),
                            COMMAND_QUEUE_WORKER_COUNT,
                        )

                expired_collect_jobs = pop_expired_collect_buffers()
                for collect_job in expired_collect_jobs:
                    job = {
                        "owner_id": int(collect_job.get("owner_id") or 0),
                        "chat_id": str(collect_job.get("chat_id") or ""),
                        "username": str(collect_job.get("username") or ""),
                        "text": str(collect_job.get("text") or ""),
                        "source": str(collect_job.get("source") or "telegram"),
                        "future": None,
                        "enqueued_at": utc_now_iso(),
                        "lane": normalize_queue_lane(str(collect_job.get("lane") or "default")),
                    }
                    if not job["text"]:
                        continue
                    if enqueue_command_job(job):
                        RUNTIME_STATE["command_queue_collect_flushes"] = (
                            int(RUNTIME_STATE.get("command_queue_collect_flushes", 0)) + 1
                        )

            if CRON_ENABLED and (CRON_SUPERVISOR_TASK is None or CRON_SUPERVISOR_TASK.done()):
                reason = _task_completion_reason(CRON_SUPERVISOR_TASK)
                CRON_SUPERVISOR_TASK = asyncio.create_task(cron_supervisor_loop())
                RUNTIME_STATE["cron_failures"] = int(RUNTIME_STATE.get("cron_failures", 0)) + 1
                log.warning("SPINE_CRON_RESTART reason=%s", reason)

            if HEARTBEAT_AUTONOMY_ENABLED and (
                HEARTBEAT_SUPERVISOR_TASK is None or HEARTBEAT_SUPERVISOR_TASK.done()
            ):
                reason = _task_completion_reason(HEARTBEAT_SUPERVISOR_TASK)
                HEARTBEAT_SUPERVISOR_TASK = asyncio.create_task(heartbeat_supervisor_loop())
                RUNTIME_STATE["heartbeat_restarts"] = (
                    int(RUNTIME_STATE.get("heartbeat_restarts", 0)) + 1
                )
                log.warning(
                    "SPINE_HEARTBEAT_RESTART reason=%s count=%d",
                    reason,
                    int(RUNTIME_STATE["heartbeat_restarts"]),
                )

            if not RUNTIME_STATE["webhook_registered"]:
                if WEBHOOK_SUPERVISOR_TASK is None or WEBHOOK_SUPERVISOR_TASK.done():
                    WEBHOOK_SUPERVISOR_TASK = asyncio.create_task(webhook_retry_supervisor_loop())
                    RUNTIME_STATE["webhook_supervisor_restarts"] = (
                        int(RUNTIME_STATE["webhook_supervisor_restarts"]) + 1
                    )
                    log.warning(
                        "SPINE_WEBHOOK_SUPERVISOR_RESTART count=%d",
                        RUNTIME_STATE["webhook_supervisor_restarts"],
                    )

            if tick % 2 == 1:
                recovered = recover_orphan_running_tasks()
                if recovered:
                    log.warning("SPINE_TASK_ORPHAN_RECOVER recovered=%d", recovered)

            if tick % 2 == 0:
                db_ok, db_err = check_db_liveness()
                if not db_ok:
                    log.warning("SPINE_DB_CHECK_FAIL error=%s", truncate_text(db_err or "", 220))

            if BLACKBOX_PRUNE_ENABLED:
                now_mono = time.monotonic()
                if (now_mono - last_blackbox_prune_monotonic) >= float(
                    BLACKBOX_PRUNE_INTERVAL_SECONDS
                ):
                    result = await asyncio.to_thread(
                        prune_blackbox_events,
                        None,
                        "spine_interval",
                    )
                    last_blackbox_prune_monotonic = now_mono
                    if (
                        isinstance(result, dict)
                        and result.get("ok")
                        and int(result.get("deleted_total", 0)) > 0
                    ):
                        log.info(
                            "SPINE_BLACKBOX_PRUNE deleted=%d",
                            int(result.get("deleted_total", 0)),
                        )
            if tick % 4 == 0:
                cleaned = cleanup_sandbox_registry()
                if cleaned > 0:
                    log.info("SPINE_SANDBOX_REGISTRY_CLEANUP removed=%d", int(cleaned))
    except asyncio.CancelledError:
        log.info("SPINE_WATCHDOG_STOP")
        raise
    finally:
        RUNTIME_STATE["spine_supervisor_alive"] = False


async def cancel_background_task(task: asyncio.Task | None, name: str):
    """Cancel a background task gracefully."""
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Failed shutting down {name}: {e}")


# ============================================================================
# Message Processing and Dispatch
# ============================================================================


def run_agent_loop_serialized(owner_id: int, user_message: str) -> str:
    """Run agent loop with serialization per owner."""
    lock = get_owner_execution_lock(owner_id)
    with lock:
        mark_owner_active(owner_id, True)
        try:
            return run_agent_loop_with_new_session(owner_id, user_message)
        finally:
            mark_owner_active(owner_id, False)


async def run_owner_message_job(job: dict):
    """Run a message job for an owner."""
    owner_id = int(job["owner_id"])
    chat_id = str(job.get("chat_id", ""))
    text = str(job.get("text", ""))
    source = str(job.get("source", "telegram"))
    future = job.get("future")

    try:
        if source == "telegram" and chat_id:
            await send_typing_indicator(chat_id)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, run_agent_loop_serialized, owner_id, text)

        if source in {"telegram", "cron"} and chat_id:
            await send_telegram_message(chat_id, response)

        if future is not None and not future.done():
            future.set_result(response)
        return response
    except Exception as e:
        err = truncate_text(str(e), 260)
        log.error("Message processing failed owner=%s source=%s error=%s", owner_id, source, err)
        if source in {"telegram", "cron"} and chat_id:
            await send_telegram_message(chat_id, f"⚠️ Error: {err}")
        if future is not None and not future.done():
            future.set_exception(RuntimeError(err))
        return None


def enqueue_command_job(job: dict) -> bool:
    """Enqueue a command job."""
    global COMMAND_QUEUE
    if COMMAND_QUEUE is None:
        COMMAND_QUEUE = asyncio.Queue()
    owner_id = int(job["owner_id"])
    if COMMAND_QUEUE.qsize() >= COMMAND_QUEUE_MAX_SIZE:
        RUNTIME_STATE["command_queue_dropped"] = int(RUNTIME_STATE["command_queue_dropped"]) + 1
        return False

    increment_owner_queue(owner_id)
    try:
        COMMAND_QUEUE.put_nowait(job)
    except Exception:
        decrement_owner_queue(owner_id)
        RUNTIME_STATE["command_queue_dropped"] = int(RUNTIME_STATE["command_queue_dropped"]) + 1
        return False

    RUNTIME_STATE["command_queue_enqueued"] = int(RUNTIME_STATE["command_queue_enqueued"]) + 1
    return True


def should_enqueue_message(owner_id: int, source: str = "telegram", text: str = "") -> bool:
    """Determine if a message should be enqueued."""
    mode = effective_command_queue_mode(owner_id)
    if mode == "on":
        return True
    if mode == "off":
        return False
    if mode == "steer":
        lane = classify_message_lane(source, text)
        return lane in {"research", "cron"}
    if mode == "followup":
        return is_owner_busy_or_backlogged(owner_id)
    if mode == "collect":
        return True
    if is_owner_busy_or_backlogged(owner_id):
        return True
    if (
        COMMAND_QUEUE_AUTO_BACKPRESSURE > 0
        and COMMAND_QUEUE.qsize() >= COMMAND_QUEUE_AUTO_BACKPRESSURE
    ):
        return True
    return False


async def command_queue_worker_loop(worker_id: int):
    """Command queue worker loop."""
    alive_count = active_command_queue_worker_count()
    RUNTIME_STATE["command_queue_worker_alive_count"] = max(alive_count, 1)
    RUNTIME_STATE["command_queue_worker_alive"] = True
    log.info(
        "COMMAND_QUEUE_WORKER_START worker=%d mode=%s max_size=%d",
        worker_id,
        COMMAND_QUEUE_MODE,
        COMMAND_QUEUE_MAX_SIZE,
    )
    try:
        while True:
            job = await COMMAND_QUEUE.get()
            owner_id = int(job.get("owner_id", 0) or 0)
            lane = normalize_queue_lane(str(job.get("lane", "default")))
            try:
                if owner_id > 0:
                    decrement_owner_queue(owner_id)
                lane_sem = get_lane_semaphore(lane)
                async with lane_sem:
                    await run_owner_message_job(job)
            except Exception as e:
                log.error(
                    "COMMAND_QUEUE_WORKER_JOB_FAIL worker=%d owner=%s lane=%s error=%s",
                    worker_id,
                    owner_id,
                    lane,
                    truncate_text(str(e), 220),
                )
            finally:
                RUNTIME_STATE["command_queue_processed"] = (
                    int(RUNTIME_STATE["command_queue_processed"]) + 1
                )
                COMMAND_QUEUE.task_done()
    except asyncio.CancelledError:
        log.info("COMMAND_QUEUE_WORKER_STOP worker=%d", worker_id)
        raise
    finally:
        COMMAND_QUEUE_WORKER_TASKS.pop(worker_id, None)
        alive = active_command_queue_worker_count()
        RUNTIME_STATE["command_queue_worker_alive_count"] = alive
        RUNTIME_STATE["command_queue_worker_alive"] = alive > 0


# ============================================================================
# Main Dispatch Function
# ============================================================================


async def dispatch_incoming_message(
    owner_id: int,
    chat_id: str,
    username: str,
    text: str,
    source: str,
    expect_response: bool,
) -> dict:
    """Dispatch an incoming message to the appropriate handler."""
    from mind_clone.core.state import COMMAND_QUEUE_WORKER_TASK

    if (
        command_queue_enabled() or source == "cron"
    ) and active_command_queue_worker_count() < COMMAND_QUEUE_WORKER_COUNT:
        before = active_command_queue_worker_count()
        await ensure_command_queue_workers_running()
        started = max(0, active_command_queue_worker_count() - before)
        if started > 0:
            RUNTIME_STATE["command_queue_worker_restarts"] = (
                int(RUNTIME_STATE["command_queue_worker_restarts"]) + started
            )
            log.warning(
                "COMMAND_QUEUE_WORKER_LATE_START started=%d alive=%d",
                started,
                active_command_queue_worker_count(),
            )

    mode = effective_command_queue_mode(owner_id)
    RUNTIME_STATE["command_queue_mode"] = mode
    lane = classify_message_lane(source, text)
    if mode == "collect":
        merged_text, should_flush = _collect_buffer_append(
            owner_id=owner_id,
            text=text,
            lane=lane,
            source=source,
            chat_id=chat_id,
            username=username,
        )
        RUNTIME_STATE["command_queue_collect_merges"] = (
            int(RUNTIME_STATE.get("command_queue_collect_merges", 0)) + 1
        )
        if not should_flush:
            if expect_response:
                return {
                    "ok": True,
                    "queued": True,
                    "collecting": True,
                    "message": "Collect mode buffering active. Send follow-up or wait for auto flush.",
                }
            return {"ok": True, "queued": True, "collecting": True}
        popped = _collect_buffer_pop(owner_id) or {}
        text = str(merged_text or text).strip()
        lane = normalize_queue_lane(str(popped.get("lane") or lane))
        source = str(popped.get("source") or source)
        RUNTIME_STATE["command_queue_collect_flushes"] = (
            int(RUNTIME_STATE.get("command_queue_collect_flushes", 0)) + 1
        )

    enqueue_now = should_enqueue_message(owner_id, source=source, text=text) or source == "cron"
    if enqueue_now:
        loop = asyncio.get_running_loop()
        future = loop.create_future() if expect_response else None
        job = {
            "owner_id": owner_id,
            "chat_id": chat_id,
            "username": username,
            "text": text,
            "source": source,
            "future": future,
            "enqueued_at": utc_now_iso(),
            "lane": lane,
        }
        if not enqueue_command_job(job):
            msg = "Command queue is full. Please retry in a moment."
            log.warning("COMMAND_QUEUE_DROP owner=%d source=%s reason=full", owner_id, source)
            if source == "telegram":
                await send_telegram_message(chat_id, f"⚠️ {msg}")
            return {"ok": False, "queued": False, "error": msg}

        RUNTIME_STATE["command_queue_auto_routed"] = (
            int(RUNTIME_STATE.get("command_queue_auto_routed", 0)) + 1
        )

        if not expect_response:
            return {"ok": True, "queued": True}

        try:
            timeout_seconds = max(120, LLM_REQUEST_TIMEOUT_SECONDS * 3)
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            return {"ok": True, "queued": True, "response": response}
        except Exception as e:
            return {"ok": False, "queued": True, "error": truncate_text(str(e), 260)}

    RUNTIME_STATE["command_queue_direct_routed"] = (
        int(RUNTIME_STATE.get("command_queue_direct_routed", 0)) + 1
    )
    if expect_response:
        response = await run_owner_message_job(
            {
                "owner_id": owner_id,
                "chat_id": chat_id,
                "username": username,
                "text": text,
                "source": source,
                "future": None,
                "lane": lane,
            }
        )
        if response is None:
            return {"ok": False, "queued": False, "error": "Message processing failed."}
        return {"ok": True, "queued": False, "response": response}

    asyncio.create_task(
        run_owner_message_job(
            {
                "owner_id": owner_id,
                "chat_id": chat_id,
                "username": username,
                "text": text,
                "source": source,
                "future": None,
                "lane": lane,
            }
        )
    )
    return {"ok": True, "queued": False}


# ============================================================================
# Telegram Command Handlers
# ============================================================================


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    welcome = (
        f"Welcome! I'm your Mind Clone Agent.\n\n"
        f"Your owner ID: {owner_id}\n\n"
        f"Available commands:\n"
        f"/help - Show all commands\n"
        f"/status - Check system status\n"
        f"/task - Create a new task\n"
        f"/tasks - List your tasks\n"
        f"/cancel - Cancel a task\n"
        f"/approve - Approve a pending action\n"
        f"/reject - Reject a pending action\n"
        f"/cron - List scheduled jobs\n\n"
        f"Or just send me a message and I'll help you!"
    )
    await update.message.reply_text(welcome)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🤖 *Mind Clone Agent Commands*\n\n"
        "*Basic:*\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/status - System status and metrics\n\n"
        "*Tasks:*\n"
        "/task <description> - Create a task\n"
        "/cancel <task_id> - Cancel a task\n"
        "/tasks - List your tasks\n\n"
        "*Approvals:*\n"
        "/approve <token> - Approve pending action\n"
        "/reject <token> - Reject pending action\n"
        "/approvals - List pending approvals\n\n"
        "*Goals:*\n"
        "/goal <description> - Create a goal\n"
        "/goals - List your goals\n\n"
        "*Cron:*\n"
        "/cron - List scheduled jobs\n\n"
        "*Memory:*\n"
        "/remember <text> - Save to memory\n"
        "/recall <query> - Search memory\n\n"
        "Just send a message to chat with me!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    metrics = runtime_metrics()
    alerts = metrics.get("runtime_alerts", [])

    status_lines = [
        "📊 *System Status*",
        "",
        f"*Runtime:*",
        f"• Worker: {'✅' if metrics.get('worker_alive') else '❌'}",
        f"• Spine: {'✅' if metrics.get('spine_supervisor_alive') else '❌'}",
        f"• DB: {'✅' if metrics.get('db_healthy') else '❌'}",
        f"• Webhook: {'✅' if metrics.get('webhook_registered') else '❌'}",
        "",
        f"*Queue:*",
        f"• Mode: {metrics.get('command_queue_mode', 'unknown')}",
        f"• Size: {metrics.get('command_queue_size', 0)}/{metrics.get('command_queue_max_size', 0)}",
        f"• Workers: {metrics.get('command_queue_worker_alive_count', 0)}/{metrics.get('command_queue_worker_target', 0)}",
        "",
        f"*Tasks:*",
        f"• Queue: {metrics.get('task_queue_size', 0)}",
        f"• Tracked: {metrics.get('tasks_tracked', 0)}",
        "",
        f"*Model:*",
        f"• Primary: {metrics.get('llm_primary_model', 'unknown')}",
        f"• Fallback: {metrics.get('llm_fallback_model', 'none')}",
        f"• Failover: {'enabled' if metrics.get('llm_failover_enabled') else 'disabled'}",
    ]

    if alerts:
        status_lines.extend(
            [
                "",
                f"⚠️ *Alerts ({len(alerts)}):*",
            ]
        )
        for alert in alerts[:5]:
            status_lines.append(f"• {alert.get('code')}: {alert.get('message', '')[:50]}")

    await update.message.reply_text("\n".join(status_lines), parse_mode="Markdown")


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /task command."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    if not context.args:
        await update.message.reply_text(
            "Usage: /task <description>\nExample: /task Research Python async patterns"
        )
        return

    description = " ".join(context.args)

    # Create task
    db = SessionLocal()
    try:
        task = Task(
            owner_id=owner_id,
            description=description,
            status="pending",
            plan={},
        )
        db.add(task)
        db.commit()
        task_id = task.id
        db.refresh(task)

        # Enqueue task
        enqueue_task(task_id)

        await update.message.reply_text(
            f"✅ Task #{task_id} created!\n"
            f"Description: {description[:100]}{'...' if len(description) > 100 else ''}\n\n"
            f"Use /cancel {task_id} to cancel."
        )
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ Failed to create task: {truncate_text(str(e), 200)}")
    finally:
        db.close()


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    if not context.args:
        await update.message.reply_text("Usage: /cancel <task_id>\nExample: /cancel 123")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Task ID must be a number.")
        return

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.owner_id == owner_id).first()
        if not task:
            await update.message.reply_text(f"❌ Task #{task_id} not found.")
            return

        if task.status in ("completed", "failed", "cancelled"):
            await update.message.reply_text(f"ℹ️ Task #{task_id} is already {task.status}.")
            return

        task.status = "cancelled"
        db.commit()
        await update.message.reply_text(f"✅ Task #{task_id} cancelled.")
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ Failed to cancel task: {truncate_text(str(e), 200)}")
    finally:
        db.close()


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tasks command."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    db = SessionLocal()
    try:
        tasks = (
            db.query(Task)
            .filter(Task.owner_id == owner_id)
            .order_by(Task.created_at.desc())
            .limit(10)
            .all()
        )

        if not tasks:
            await update.message.reply_text(
                "You have no tasks. Create one with /task <description>"
            )
            return

        lines = ["📋 *Your Recent Tasks*\n"]
        for task in tasks:
            status_emoji = {
                "pending": "⏳",
                "queued": "📝",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "cancelled": "🚫",
                "blocked": "⏸️",
            }.get(task.status, "❓")
            desc = truncate_text(task.description or "No description", 40)
            lines.append(f"{status_emoji} #{task.id}: {desc}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        db.close()


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command."""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None

    if not context.args:
        await update.message.reply_text("Usage: /approve <token>\nExample: /approve abc123")
        return

    token = context.args[0]
    await handle_approval_command(chat_id, username, token, approve=True)


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reject command."""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None

    if not context.args:
        await update.message.reply_text("Usage: /reject <token>\nExample: /reject abc123")
        return

    token = context.args[0]
    await handle_approval_command(chat_id, username, token, approve=False)


async def cmd_approvals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approvals command."""
    from mind_clone.agent.identity import resolve_owner_id
    from mind_clone.core.approvals import list_pending_approvals

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    pending = list_pending_approvals(owner_id)
    if not pending:
        await update.message.reply_text("No pending approvals.")
        return

    lines = ["⏸️ *Pending Approvals*\n"]
    for approval in pending[:10]:
        token = approval.get("token", "unknown")
        tool = approval.get("tool_name", "unknown")
        desc = truncate_text(approval.get("description", "No description"), 40)
        lines.append(f"• `{token}`: {tool}\n  {desc}")

    lines.append("\nUse /approve <token> or /reject <token>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cron command."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    db = SessionLocal()
    try:
        jobs = (
            db.query(ScheduledJob)
            .filter(ScheduledJob.owner_id == owner_id)
            .order_by(ScheduledJob.id.desc())
            .limit(10)
            .all()
        )

        if not jobs:
            await update.message.reply_text("No scheduled jobs. Jobs can be created via the API.")
            return

        lines = ["⏰ *Your Scheduled Jobs*\n"]
        for job in jobs:
            status = "✅" if job.enabled else "🚫"
            name = truncate_text(job.name, 30)
            interval = f"{job.interval_seconds}s"
            runs = job.run_count or 0
            lines.append(f"{status} {name}\n  Interval: {interval} | Runs: {runs}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        db.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    text = update.message.text

    owner_id = resolve_owner_id(chat_id, username)
    await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=chat_id,
        username=username or "unknown",
        text=text,
        source="telegram",
        expect_response=False,
    )


# ============================================================================
# Webhook Handler
# ============================================================================


async def telegram_webhook_handler(request_data: dict) -> dict:
    """Handle incoming Telegram webhook update.

    This is the main entry point for webhook-based Telegram updates.
    It processes the update and routes it to the appropriate handler.

    Args:
        request_data: The webhook request data from Telegram

    Returns:
        Response dict with status
    """
    try:
        update = Update.de_json(request_data, None)
        if not update:
            return {"ok": False, "error": "Invalid update"}

        chat_id = str(update.effective_chat.id) if update.effective_chat else None
        username = update.effective_user.username if update.effective_user else None

        if not chat_id:
            return {"ok": False, "error": "No chat ID"}

        # Handle commands
        if update.message and update.message.text:
            text = update.message.text

            # Command routing
            if text.startswith("/start"):
                await cmd_start(update, None)
            elif text.startswith("/help"):
                await cmd_help(update, None)
            elif text.startswith("/status"):
                await cmd_status(update, None)
            elif text.startswith("/tasks"):
                await cmd_tasks(update, None)
            elif text.startswith("/task "):
                await cmd_task(update, type("Context", (), {"args": text.split()[1:]}))
            elif text.startswith("/cancel "):
                await cmd_cancel(update, type("Context", (), {"args": text.split()[1:]}))
            elif text.startswith("/approve "):
                await cmd_approve(update, type("Context", (), {"args": text.split()[1:]}))
            elif text.startswith("/reject "):
                await cmd_reject(update, type("Context", (), {"args": text.split()[1:]}))
            elif text.startswith("/approvals"):
                await cmd_approvals(update, None)
            elif text.startswith("/cron"):
                await cmd_cron(update, None)
            else:
                # Regular message
                from mind_clone.agent.identity import resolve_owner_id

                owner_id = resolve_owner_id(chat_id, username)
                await dispatch_incoming_message(
                    owner_id=owner_id,
                    chat_id=chat_id,
                    username=username or "unknown",
                    text=text,
                    source="telegram",
                    expect_response=False,
                )

        return {"ok": True}
    except Exception as e:
        log.exception("Webhook handler error: %s", e)
        return {"ok": False, "error": str(e)}


# ============================================================================
# Bot Application Setup
# ============================================================================

# Global Application instance
_bot_application: Application | None = None


def get_bot_application() -> Application | None:
    """Get the bot application instance."""
    global _bot_application
    if _bot_application is None and TELEGRAM_BOT_TOKEN != TOKEN_PLACEHOLDER:
        _bot_application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _setup_handlers(_bot_application)
    return _bot_application


def _setup_handlers(app: Application):
    """Set up command handlers for the bot."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("task", cmd_task))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("approvals", cmd_approvals))
    app.add_handler(CommandHandler("cron", cmd_cron))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


async def setup_bot() -> Application | None:
    """Set up and initialize the bot application.

    Returns:
        The initialized Application or None if token not configured
    """
    app = get_bot_application()
    if app:
        await app.initialize()
        log.info("Telegram bot initialized")
    return app


async def shutdown_bot():
    """Shutdown the bot application gracefully."""
    global _bot_application
    if _bot_application:
        await _bot_application.shutdown()
        _bot_application = None
        log.info("Telegram bot shutdown")


# ============================================================================
# Polling Mode (for development)
# ============================================================================


async def run_polling():
    """Run the bot in polling mode (for development)."""
    app = get_bot_application()
    if not app:
        log.error("Cannot start polling: Bot token not configured")
        return

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        poll_interval=0.5,
        timeout=30,
        drop_pending_updates=False,
        allowed_updates=["message", "edited_message", "callback_query"],
    )
    log.info("Telegram bot started in polling mode")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


# ============================================================================
# Initialization and Shutdown
# ============================================================================


async def initialize_telegram():
    """Initialize all Telegram-related services."""
    # Initialize runtime state
    initialize_runtime_state_baseline()

    # Run preflight checks
    ok, errors = run_startup_preflight()
    if not ok:
        log.warning("Preflight checks failed: %s", errors)

    # Setup bot application (for potential polling mode)
    await setup_bot()

    log.info("Telegram services initialized")


async def shutdown_telegram():
    """Shutdown all Telegram-related services gracefully."""
    await shutdown_bot()
    log.info("Telegram services shutdown")


# ============================================================================
# Entry Point for Direct Execution
# ============================================================================

if __name__ == "__main__":
    # Allow running the bot in polling mode for development
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) > 1 and sys.argv[1] == "polling":
        try:
            asyncio.run(run_polling())
        except KeyboardInterrupt:
            print("\nBot stopped by user")
    else:
        print("Usage: python telegram.py polling")
        print("Or import and use initialize_telegram() / shutdown_telegram()")

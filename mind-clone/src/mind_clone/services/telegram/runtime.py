"""Runtime state initialization, health checks, preflight, and metrics."""
from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse

from ._imports import (
    asyncio,
    log,
    SessionLocal,
    engine,
    ensure_db_ready,
    sql_text,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_BASE_URL,
    TOKEN_PLACEHOLDER,
    KIMI_MODEL,
    KIMI_FALLBACK_MODEL,
    LLM_FAILOVER_ENABLED,
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
    HEARTBEAT_AUTONOMY_ENABLED,
    HEARTBEAT_INTERVAL_SECONDS,
    EVAL_HARNESS_ENABLED,
    EVAL_MAX_CASES,
    EVAL_AUTORUN_EVERY_TICKS,
    OPS_AUTH_ENABLED,
    OPS_AUTH_TOKEN,
    OPS_AUTH_REQUIRE_SIGNATURE,
    OPS_AUTH_ROLE_SECRETS,
    TASK_ROLE_LOOP_ENABLED,
    TASK_ROLE_LOOP_MODE,
    TEAM_MODE_ENABLED,
    IDENTITY_SCOPE_MODE,
    NODE_CONTROL_PLANE_ENABLED,
    REMOTE_NODES_JSON,
    PLUGIN_ENFORCE_TRUST,
    PLUGIN_TRUSTED_HASHES,
    APPROVAL_GATE_MODE,
    WEBHOOK_RETRY_BASE_SECONDS,
    CANARY_ROUTER_ENABLED,
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
    COMMAND_QUEUE,
    COMMAND_QUEUE_WORKER_TASKS,
    COMMAND_QUEUE_LANE_SEMAPHORES,
    TASK_QUEUE,
    TASK_QUEUE_IDS,
    CANARY_STATE,
    _self_improve_last_time,
    truncate_text,
    configured_llm_profiles,
    llm_failover_active,
    MODEL_ROUTER_BILLING_HARD_DISABLE,
    active_tool_policy_profile,
    active_execution_sandbox_profile,
    TOOL_POLICY_PROFILE_RAW,
    TOOL_POLICY_PROFILES,
    EXECUTION_SANDBOX_PROFILE_RAW,
    EXECUTION_SANDBOX_PROFILES,
    os_sandbox_enabled,
    _docker_executable,
    _normalize_os_sandbox_mode,
    PLUGIN_TOOL_REGISTRY,
    REMOTE_NODE_REGISTRY,
    PROTOCOL_SCHEMA_REGISTRY,
    _default_circuit_state,
    circuit_snapshot,
    owner_active_count,
    owner_backlog_count,
    command_queue_enabled,
)
from .utils import utc_now_iso


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
        "autonomy_openclaw_max": bool(RUNTIME_STATE.get("autonomy_openclaw_max", AUTONOMY_OPENCLAW_MAX)),
        "policy_pack": RUNTIME_STATE.get("policy_pack", POLICY_PACK),
        "budget_governor_enabled": bool(RUNTIME_STATE.get("budget_governor_enabled", BUDGET_GOVERNOR_ENABLED)),
        "budget_governor_mode": RUNTIME_STATE.get("budget_governor_mode", BUDGET_GOVERNOR_MODE),
        "budget_runs_started": int(RUNTIME_STATE.get("budget_runs_started", 0)),
        "budget_runs_stopped": int(RUNTIME_STATE.get("budget_runs_stopped", 0)),
        "budget_runs_degraded": int(RUNTIME_STATE.get("budget_runs_degraded", 0)),
        "budget_last_scope": RUNTIME_STATE.get("budget_last_scope"),
        "budget_last_reason": RUNTIME_STATE.get("budget_last_reason"),
        "budget_last_usage": dict(RUNTIME_STATE.get("budget_last_usage") or {}),
        "command_queue_mode": RUNTIME_STATE["command_queue_mode"],
        "command_queue_worker_target": int(RUNTIME_STATE.get("command_queue_worker_target", COMMAND_QUEUE_WORKER_COUNT)),
        "command_queue_worker_alive": bool(RUNTIME_STATE["command_queue_worker_alive"]),
        "command_queue_worker_alive_count": int(RUNTIME_STATE.get("command_queue_worker_alive_count", 0)),
        "command_queue_worker_restarts": int(RUNTIME_STATE["command_queue_worker_restarts"]),
        "command_queue_size": COMMAND_QUEUE.qsize(),
        "command_queue_max_size": COMMAND_QUEUE_MAX_SIZE,
        "command_queue_lane_limits": dict(COMMAND_QUEUE_LANE_LIMITS),
        "command_queue_enqueued": int(RUNTIME_STATE["command_queue_enqueued"]),
        "command_queue_processed": int(RUNTIME_STATE["command_queue_processed"]),
        "command_queue_dropped": int(RUNTIME_STATE["command_queue_dropped"]),
        "command_queue_direct_routed": int(RUNTIME_STATE["command_queue_direct_routed"]),
        "command_queue_auto_routed": int(RUNTIME_STATE["command_queue_auto_routed"]),
        "command_queue_mode_override_count": int(RUNTIME_STATE.get("command_queue_mode_override_count", 0)),
        "command_queue_collect_merges": int(RUNTIME_STATE.get("command_queue_collect_merges", 0)),
        "command_queue_collect_flushes": int(RUNTIME_STATE.get("command_queue_collect_flushes", 0)),
        "command_queue_state_invalid_transitions": int(RUNTIME_STATE.get("command_queue_state_invalid_transitions", 0)),
        "session_soft_trim_count": int(RUNTIME_STATE.get("session_soft_trim_count", 0)),
        "session_hard_clear_count": int(RUNTIME_STATE.get("session_hard_clear_count", 0)),
        "session_last_prune_chars": int(RUNTIME_STATE.get("session_last_prune_chars", 0)),
        "session_memory_flush_count": int(RUNTIME_STATE.get("session_memory_flush_count", 0)),
        "session_memory_flush_failures": int(RUNTIME_STATE.get("session_memory_flush_failures", 0)),
        "tool_policy_profile": RUNTIME_STATE["tool_policy_profile"],
        "tool_policy_blocks": int(RUNTIME_STATE["tool_policy_blocks"]),
        "workspace_diff_gate_enabled": bool(RUNTIME_STATE.get("workspace_diff_gate_enabled", WORKSPACE_DIFF_GATE_ENABLED)),
        "workspace_diff_gate_mode": RUNTIME_STATE.get("workspace_diff_gate_mode", WORKSPACE_DIFF_GATE_MODE),
        "workspace_diff_gate_blocks": int(RUNTIME_STATE.get("workspace_diff_gate_blocks", 0)),
        "workspace_diff_gate_approvals": int(RUNTIME_STATE.get("workspace_diff_gate_approvals", 0)),
        "workspace_diff_gate_warns": int(RUNTIME_STATE.get("workspace_diff_gate_warns", 0)),
        "workspace_diff_gate_last_path": RUNTIME_STATE.get("workspace_diff_gate_last_path"),
        "workspace_diff_gate_last_reason": RUNTIME_STATE.get("workspace_diff_gate_last_reason"),
        "workspace_diff_gate_last_changed_lines": int(RUNTIME_STATE.get("workspace_diff_gate_last_changed_lines", 0)),
        "secret_guardrail_enabled": bool(RUNTIME_STATE.get("secret_guardrail_enabled", SECRET_GUARDRAIL_ENABLED)),
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
        "node_control_plane_enabled": bool(RUNTIME_STATE.get("node_control_plane_enabled", NODE_CONTROL_PLANE_ENABLED)),
        "node_control_plane_nodes": int(RUNTIME_STATE.get("node_control_plane_nodes", 0)),
        "node_control_plane_leases_active": int(RUNTIME_STATE.get("node_control_plane_leases_active", 0)),
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
        "os_sandbox_mode": RUNTIME_STATE.get("os_sandbox_mode", _normalize_os_sandbox_mode(OS_SANDBOX_MODE)),
        "os_sandbox_required": bool(RUNTIME_STATE.get("os_sandbox_required", OS_SANDBOX_REQUIRED)),
        "os_sandbox_runs": int(RUNTIME_STATE.get("os_sandbox_runs", 0)),
        "os_sandbox_failures": int(RUNTIME_STATE.get("os_sandbox_failures", 0)),
        "desktop_control_enabled": bool(RUNTIME_STATE.get("desktop_control_enabled", DESKTOP_CONTROL_ENABLED)),
        "desktop_actions_total": int(RUNTIME_STATE.get("desktop_actions_total", 0)),
        "desktop_last_action": RUNTIME_STATE.get("desktop_last_action"),
        "desktop_last_error": RUNTIME_STATE.get("desktop_last_error"),
        "desktop_session_required": bool(RUNTIME_STATE.get("desktop_session_required", DESKTOP_REQUIRE_ACTIVE_SESSION)),
        "desktop_session_active": bool(RUNTIME_STATE.get("desktop_session_active", False)),
        "desktop_session_id": RUNTIME_STATE.get("desktop_session_id"),
        "desktop_sessions_started": int(RUNTIME_STATE.get("desktop_sessions_started", 0)),
        "desktop_sessions_completed": int(RUNTIME_STATE.get("desktop_sessions_completed", 0)),
        "desktop_sessions_replayed": int(RUNTIME_STATE.get("desktop_sessions_replayed", 0)),
        "desktop_last_session_path": RUNTIME_STATE.get("desktop_last_session_path"),
        "memory_last_retrieved_total": int(RUNTIME_STATE.get("memory_last_retrieved_total", 0)),
        "memory_last_lessons_retrieved": int(RUNTIME_STATE.get("memory_last_lessons_retrieved", 0)),
        "memory_last_summaries_retrieved": int(RUNTIME_STATE.get("memory_last_summaries_retrieved", 0)),
        "memory_last_task_artifacts_retrieved": int(RUNTIME_STATE.get("memory_last_task_artifacts_retrieved", 0)),
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
        "world_model_last_reconciliation_at": RUNTIME_STATE.get("world_model_last_reconciliation_at"),
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
        "task_role_loop_enabled": bool(RUNTIME_STATE.get("task_role_loop_enabled", TASK_ROLE_LOOP_ENABLED)),
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
        "host_exec_interlock_enabled": bool(RUNTIME_STATE.get("host_exec_interlock_enabled", HOST_EXEC_INTERLOCK_ENABLED)),
        "host_exec_grants_issued": int(RUNTIME_STATE.get("host_exec_grants_issued", 0)),
        "host_exec_grants_consumed": int(RUNTIME_STATE.get("host_exec_grants_consumed", 0)),
        "host_exec_interlock_blocks": int(RUNTIME_STATE.get("host_exec_interlock_blocks", 0)),
        "workspace_isolation_enabled": bool(RUNTIME_STATE.get("workspace_isolation_enabled", WORKSPACE_ISOLATION_ENABLED)),
        "workspace_session_isolation_enabled": bool(RUNTIME_STATE.get("workspace_session_isolation_enabled", WORKSPACE_SESSION_ISOLATION_ENABLED)),
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
        "task_checkpoint_replay_restores": int(RUNTIME_STATE.get("task_checkpoint_replay_restores", 0) or 0),
        "task_checkpoint_restore_failures": int(RUNTIME_STATE.get("task_checkpoint_restore_failures", 0) or 0),
        "task_checkpoint_restore_drift": int(RUNTIME_STATE.get("task_checkpoint_restore_drift", 0) or 0),
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
        "protocol_schema_validations": int(RUNTIME_STATE.get("protocol_schema_validations", 0) or 0),
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

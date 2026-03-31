"""
Service modules for Mind Clone Agent.

Each service loads independently — one failure doesn't crash others.
If a service has a broken dependency, it logs a warning and the rest
of Bob keeps running.
"""

import logging

_log = logging.getLogger("mind_clone.services")

# ── Task Engine ──────────────────────────────────────────────────────────────
try:
    from .task_engine import (
        create_task,
        get_task,
        list_tasks,
        cancel_task,
        run_task,
        task_to_dict,
        format_task_details,
        update_task_status,
        execute_task_step,
        TASK_STATUS_OPEN,
        TASK_STATUS_QUEUED,
        TASK_STATUS_RUNNING,
        TASK_STATUS_BLOCKED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED,
        TASK_STATUS_CANCELLED,
    )
except ImportError as e:
    _log.warning("task_engine unavailable: %s", e)

# ── Scheduler ────────────────────────────────────────────────────────────────
try:
    from .scheduler import (
        create_job,
        list_jobs,
        disable_job,
        start_scheduler,
        stop_scheduler,
        get_scheduler_status,
    )
except ImportError as e:
    _log.warning("scheduler unavailable: %s", e)

# ── Telegram ─────────────────────────────────────────────────────────────────
try:
    from .telegram import (
        # Message functions
        send_telegram_message,
        send_typing_indicator,
        send_task_progress_sync,
        # Command handlers
        cmd_start,
        cmd_help,
        cmd_status,
        cmd_task,
        cmd_cancel,
        cmd_tasks,
        cmd_approve,
        cmd_reject,
        cmd_approvals,
        cmd_cron,
        handle_message,
        # Webhook
        telegram_webhook_handler,
        try_set_telegram_webhook_once,
        webhook_retry_loop,
        webhook_retry_supervisor_loop,
        # Bot management
        get_bot_application,
        setup_bot,
        shutdown_bot,
        run_polling,
        initialize_telegram,
        shutdown_telegram,
        # Runtime
        initialize_runtime_state_baseline,
        runtime_metrics,
        runtime_uptime_seconds,
        check_db_liveness,
        run_startup_preflight,
        compute_runtime_alerts,
        # Evaluation
        run_continuous_eval_suite,
        evaluate_release_gate,
        # Heartbeat & Cron
        run_heartbeat_self_check,
        heartbeat_supervisor_loop,
        bootstrap_cron_jobs_from_env,
        run_due_cron_jobs_once,
        cron_supervisor_loop,
        # Queue & Dispatch
        dispatch_incoming_message,
        run_owner_message_job,
        enqueue_command_job,
        should_enqueue_message,
        command_queue_worker_loop,
        # Spine
        spine_supervisor_loop,
        cancel_background_task,
        # Utilities
        utc_now_iso,
        iso_after_seconds,
        parse_approval_token,
        parse_command_id,
        clamp_int,
    )
except ImportError as e:
    _log.warning("telegram unavailable: %s", e)

# ── Doctor ───────────────────────────────────────────────────────────────────
try:
    from .doctor import run_doctor
except ImportError as e:
    _log.warning("doctor unavailable: %s", e)

__all__ = [
    # Task Engine
    "create_task",
    "get_task",
    "list_tasks",
    "cancel_task",
    "run_task",
    "task_to_dict",
    "format_task_details",
    "update_task_status",
    "execute_task_step",
    "TASK_STATUS_OPEN",
    "TASK_STATUS_QUEUED",
    "TASK_STATUS_RUNNING",
    "TASK_STATUS_BLOCKED",
    "TASK_STATUS_DONE",
    "TASK_STATUS_FAILED",
    "TASK_STATUS_CANCELLED",
    # Scheduler
    "create_job",
    "list_jobs",
    "disable_job",
    "start_scheduler",
    "stop_scheduler",
    "get_scheduler_status",
    # Telegram - Message
    "send_telegram_message",
    "send_typing_indicator",
    "send_task_progress_sync",
    # Telegram - Commands
    "cmd_start",
    "cmd_help",
    "cmd_status",
    "cmd_task",
    "cmd_cancel",
    "cmd_tasks",
    "cmd_approve",
    "cmd_reject",
    "cmd_approvals",
    "cmd_cron",
    "handle_message",
    # Telegram - Webhook
    "telegram_webhook_handler",
    "try_set_telegram_webhook_once",
    "webhook_retry_loop",
    "webhook_retry_supervisor_loop",
    # Telegram - Bot
    "get_bot_application",
    "setup_bot",
    "shutdown_bot",
    "run_polling",
    "initialize_telegram",
    "shutdown_telegram",
    # Telegram - Runtime
    "initialize_runtime_state_baseline",
    "runtime_metrics",
    "runtime_uptime_seconds",
    "check_db_liveness",
    "run_startup_preflight",
    "compute_runtime_alerts",
    # Telegram - Eval
    "run_continuous_eval_suite",
    "evaluate_release_gate",
    # Telegram - Heartbeat/Cron
    "run_heartbeat_self_check",
    "heartbeat_supervisor_loop",
    "bootstrap_cron_jobs_from_env",
    "run_due_cron_jobs_once",
    "cron_supervisor_loop",
    # Telegram - Queue
    "dispatch_incoming_message",
    "run_owner_message_job",
    "enqueue_command_job",
    "should_enqueue_message",
    "command_queue_worker_loop",
    # Telegram - Spine
    "spine_supervisor_loop",
    "cancel_background_task",
    # Telegram - Utils
    "utc_now_iso",
    "iso_after_seconds",
    "parse_approval_token",
    "parse_command_id",
    "clamp_int",
    # Doctor
    "run_doctor",
]

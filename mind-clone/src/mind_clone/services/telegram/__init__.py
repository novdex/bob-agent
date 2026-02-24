"""Telegram adapter package — re-exports public API for external consumers."""

# runner.py imports:
from .bot import initialize_telegram, run_polling  # noqa: F401

# api/routes/_shared.py imports:
from .runtime import (  # noqa: F401
    initialize_runtime_state_baseline,
    run_startup_preflight,
    check_db_liveness,
)
from .messaging import (  # noqa: F401
    send_telegram_message,
    unpause_task_after_approval,
    handle_approval_command,
)
from .utils import (  # noqa: F401
    parse_approval_token,
    parse_command_id,
)
from .supervisors import (  # noqa: F401
    try_set_telegram_webhook_once,
    webhook_retry_supervisor_loop,
)
from .dispatch import dispatch_incoming_message  # noqa: F401

# Additional public exports used by other modules
from .runtime import (  # noqa: F401
    runtime_metrics,
    runtime_uptime_seconds,
    compute_runtime_alerts,
)
from .events import (  # noqa: F401
    sse_frame,
    blackbox_event_stream_generator,
    run_continuous_eval_suite,
    evaluate_release_gate,
)
from .supervisors import (  # noqa: F401
    heartbeat_supervisor_loop,
    cron_supervisor_loop,
    spine_supervisor_loop,
    cancel_background_task,
)
from .messaging import (  # noqa: F401
    send_task_progress_sync,
    send_typing_indicator,
)
from .dispatch import (  # noqa: F401
    run_agent_loop_serialized,
    enqueue_command_job,
    command_queue_worker_loop,
)
from .commands import telegram_webhook_handler  # noqa: F401
from .bot import (  # noqa: F401
    setup_bot,
    shutdown_bot,
    shutdown_telegram,
)

# --- Missing re-exports needed by services/__init__.py ---

# Command handlers
from .commands import (  # noqa: F401
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
)

# Bot helpers
from .bot import get_bot_application  # noqa: F401

# Supervisor / cron helpers
from .supervisors import (  # noqa: F401
    webhook_retry_loop,
    run_heartbeat_self_check,
    bootstrap_cron_jobs_from_env,
    run_due_cron_jobs_once,
)

# Dispatch helpers
from .dispatch import (  # noqa: F401
    run_owner_message_job,
    should_enqueue_message,
)

# Utility helpers
from .utils import (  # noqa: F401
    utc_now_iso,
    iso_after_seconds,
    clamp_int,
)

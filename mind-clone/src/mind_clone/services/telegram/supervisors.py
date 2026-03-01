"""Supervisor loops: heartbeat, cron, webhook, spine watchdog."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from ._imports import (
    asyncio,
    random,
    httpx,
    log,
    SessionLocal,
    User,
    ScheduledJob,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_BASE_URL,
    TELEGRAM_API,
    TOKEN_PLACEHOLDER,
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
    BROWSER_TOOL_ENABLED,
    GOAL_SYSTEM_ENABLED,
    GOAL_SUPERVISOR_EVERY_TICKS,
    TOOL_PERF_TRACKING_ENABLED,
    CUSTOM_TOOL_ENABLED,
    BLACKBOX_PRUNE_ENABLED,
    BLACKBOX_PRUNE_INTERVAL_SECONDS,
    COMMAND_QUEUE_WORKER_COUNT,
    WEBHOOK_RETRY_BASE_SECONDS,
    WEBHOOK_RETRY_MAX_SECONDS,
    WEBHOOK_RETRY_FACTOR,
    WEBHOOK_RETRY_JITTER_RATIO,
    RUNTIME_STATE,
    HEARTBEAT_WAKE_EVENT,
    WEBHOOK_RETRY_TASK,
    truncate_text,
    task_worker_loop,
    recover_orphan_running_tasks,
    run_goal_supervisor,
    prune_tool_performance_logs,
    prune_custom_tools,
    prune_blackbox_events,
    _cleanup_browser_sessions,
    cleanup_sandbox_registry,
    command_queue_enabled,
    active_command_queue_worker_count,
    ensure_command_queue_workers_running,
    pop_expired_collect_buffers,
    normalize_queue_lane,
)
from .utils import (
    utc_now_iso,
    iso_after_seconds,
    clamp_int,
    _normalize_schedule_lane,
    _compute_next_run_at_time,
)
from .runtime import (
    check_db_liveness,
    runtime_metrics,
)
from .events import (
    run_continuous_eval_suite,
    evaluate_release_gate,
)


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

    from .dispatch import dispatch_incoming_message

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
    from .dispatch import enqueue_command_job

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

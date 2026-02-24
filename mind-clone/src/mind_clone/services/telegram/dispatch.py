"""Message processing, queue workers, and dispatch."""
from __future__ import annotations

from ._imports import (
    asyncio,
    log,
    COMMAND_QUEUE_MODE,
    COMMAND_QUEUE_WORKER_COUNT,
    COMMAND_QUEUE_MAX_SIZE,
    COMMAND_QUEUE_AUTO_BACKPRESSURE,
    LLM_REQUEST_TIMEOUT_SECONDS,
    RUNTIME_STATE,
    COMMAND_QUEUE,
    COMMAND_QUEUE_WORKER_TASKS,
    truncate_text,
    run_agent_loop_with_new_session,
    mark_owner_active,
    get_owner_execution_lock,
    command_queue_enabled,
    effective_command_queue_mode,
    classify_message_lane,
    normalize_queue_lane,
    is_owner_busy_or_backlogged,
    increment_owner_queue,
    decrement_owner_queue,
    active_command_queue_worker_count,
    ensure_command_queue_workers_running,
    _collect_buffer_append,
    _collect_buffer_pop,
    get_lane_semaphore,
)
from .utils import utc_now_iso
from .messaging import send_telegram_message, send_typing_indicator


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
            await send_telegram_message(chat_id, f"\u26a0\ufe0f Error: {err}")
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
                await send_telegram_message(chat_id, f"\u26a0\ufe0f {msg}")
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

"""
FastAPI application factory.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..database.session import init_db
from .routes import router

logger = logging.getLogger("mind_clone.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    logger.info("Starting up Mind Clone Agent API")
    init_db()

    # Load custom tools from DB into TOOL_DISPATCH
    try:
        from ..tools.registry import load_custom_tools_from_db
        loaded = load_custom_tools_from_db()
        logger.info("Loaded %d custom tools from database", loaded)
    except Exception as exc:
        logger.warning("Failed to load custom tools: %s", exc)

    # Restore persistent channel state from disk (if any)
    _restored_chat_id = None
    try:
        from ..services.channel_state import load_channel_state
        _channel_state = load_channel_state()
        if _channel_state and "telegram" in _channel_state:
            _tg = _channel_state["telegram"]
            _restored_chat_id = _tg.get("chat_id")
            logger.info(
                "Restored channel state: chat_id=%s owner_id=%s connected_at=%s",
                _tg.get("chat_id"),
                _tg.get("owner_id"),
                _tg.get("connected_at"),
            )
        else:
            logger.info("No saved channel state found — fresh start")
    except Exception as exc:
        logger.warning("Failed to load channel state on startup: %s", exc)

    # Start Telegram polling as a background task
    polling_task = None
    try:
        from ..services.telegram.bot import get_bot_application
        bot_app = get_bot_application()
        if bot_app:
            async def _run_telegram_polling():
                try:
                    await bot_app.initialize()
                    await bot_app.start()
                    await bot_app.updater.start_polling(
                        poll_interval=0.5,
                        timeout=30,
                        drop_pending_updates=False,
                        allowed_updates=["message", "edited_message", "callback_query"],
                    )
                    logger.info("Telegram polling started as background task")
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error("Telegram polling error: %s", exc)
                finally:
                    try:
                        await bot_app.updater.stop()
                        await bot_app.stop()
                        await bot_app.shutdown()
                    except Exception:
                        pass

            polling_task = asyncio.create_task(_run_telegram_polling())
            logger.info("Telegram polling task created")

            # Send "Bob is back online" notification to the saved channel
            if _restored_chat_id:
                try:
                    from ..services.telegram.messaging import send_telegram_message
                    # Small delay to let polling initialise before sending
                    async def _send_online_notice():
                        await asyncio.sleep(3)
                        try:
                            await send_telegram_message(
                                _restored_chat_id,
                                "Bob is back online. All systems restored.",
                            )
                            logger.info("Sent 'back online' notification to chat %s", _restored_chat_id)
                        except Exception as exc:
                            logger.warning("Failed to send back-online notification: %s", exc)
                    asyncio.create_task(_send_online_notice())
                except Exception as exc:
                    logger.warning("Failed to schedule back-online notification: %s", exc)
        else:
            logger.warning("Telegram bot token not configured, polling disabled")
    except Exception as exc:
        logger.warning("Failed to start Telegram polling: %s", exc)

    # Start command queue workers
    queue_worker_tasks = []
    try:
        from ..services.telegram.dispatch import command_queue_worker_loop
        from ..core.queue import command_queue_enabled, COMMAND_QUEUE_WORKER_COUNT
        from ..core.state import COMMAND_QUEUE_WORKER_TASKS
        if command_queue_enabled():
            for worker_id in range(COMMAND_QUEUE_WORKER_COUNT):
                task = asyncio.create_task(command_queue_worker_loop(worker_id))
                queue_worker_tasks.append(task)
                # Also register in the global dict so active_command_queue_worker_count works
                COMMAND_QUEUE_WORKER_TASKS[worker_id] = task
            logger.info("Started %d command queue workers", COMMAND_QUEUE_WORKER_COUNT)
    except Exception as exc:
        logger.warning("Failed to start command queue workers: %s", exc)

    # Seed proactive check-in scheduled job
    try:
        from ..services.proactive import ensure_checkin_job_seeded
        seeded = ensure_checkin_job_seeded()
        if seeded:
            logger.info("Proactive check-in job seeded (first run in 1 hour)")
        else:
            logger.debug("Proactive check-in job already exists")
    except Exception as exc:
        logger.warning("Failed to seed proactive check-in job: %s", exc)

    # Seed daily retro scheduled job
    try:
        from ..services.retro import ensure_retro_job_seeded
        seeded = ensure_retro_job_seeded()
        if seeded:
            logger.info("Daily retro job seeded (first run at midnight UTC)")
        else:
            logger.debug("Daily retro job already exists")
    except Exception as exc:
        logger.warning("Failed to seed retro job: %s", exc)

    # Seed continuous learning job (every 6h)
    try:
        from ..services.continuous_learner import ensure_learning_job
        from ..database.session import SessionLocal as _SL4
        _db4 = _SL4()
        try:
            ensure_learning_job(_db4, owner_id=1)
            logger.info("Continuous learning job ensured")
        finally:
            _db4.close()
    except Exception as exc:
        logger.warning("Failed to seed learning job: %s", exc)

    # Seed morning briefing job (7am UTC daily)
    try:
        from ..services.autonomous_research import ensure_morning_briefing_job
        from ..database.session import SessionLocal as _SL3
        _db3 = _SL3()
        try:
            ensure_morning_briefing_job(_db3, owner_id=1)
            logger.info("Morning briefing job ensured")
        finally:
            _db3.close()
    except Exception as exc:
        logger.warning("Failed to seed morning briefing: %s", exc)

    # Seed daily Ebbinghaus memory maintenance job
    try:
        from ..services.scheduler import create_job
        from ..database.session import SessionLocal as _SL2
        from ..database.models import ScheduledJob as _SJ
        _db2 = _SL2()
        try:
            _exists = _db2.query(_SJ).filter(_SJ.name == "ebbinghaus_decay", _SJ.owner_id == 1).first()
            if not _exists:
                create_job(
                    _db2, owner_id=1,
                    name="ebbinghaus_decay",
                    message="Run Ebbinghaus memory decay and pruning. Call: from mind_clone.services.ebbinghaus import run_daily_memory_maintenance; run_daily_memory_maintenance(1)",
                    interval_seconds=86400,
                    schedule="03:00",
                )
                logger.info("Ebbinghaus daily decay job seeded")
        except Exception:
            pass
        finally:
            _db2.close()
    except Exception as exc:
        logger.warning("Failed to seed Ebbinghaus job: %s", exc)

    # Seed nightly experiment job (Karpathy-style self-improvement loop)
    try:
        from ..services.auto_research import ensure_nightly_experiment_job
        from ..database.session import SessionLocal as _SessionLocal
        _db = _SessionLocal()
        try:
            ensure_nightly_experiment_job(_db, owner_id=1)
            logger.info("Nightly experiment job ensured")
        finally:
            _db.close()
    except Exception as exc:
        logger.warning("Failed to seed nightly experiment job: %s", exc)

    # Start cron supervisor (runs scheduled jobs including proactive check-ins)
    cron_task = None
    try:
        from ..services.telegram.supervisors import cron_supervisor_loop
        cron_task = asyncio.create_task(cron_supervisor_loop())
        logger.info("Cron supervisor started")
    except Exception as exc:
        logger.warning("Failed to start cron supervisor: %s", exc)

    # Start task worker in a thread (it's a sync blocking loop)
    import threading as _threading
    _task_worker_thread = None
    try:
        from ..core.tasks import task_worker_loop
        from ..core.state import RUNTIME_STATE
        _task_worker_thread = _threading.Thread(
            target=task_worker_loop, daemon=True, name="task-worker"
        )
        _task_worker_thread.start()
        RUNTIME_STATE["worker_alive"] = True
        logger.info("Task worker thread started")
    except Exception as exc:
        logger.warning("Failed to start task worker: %s", exc)

    # Run db health check in thread (sync SQLAlchemy - don't block event loop)
    try:
        from ..services.telegram.runtime import check_db_liveness
        import asyncio as _asyncio
        ok, err = await _asyncio.get_event_loop().run_in_executor(None, check_db_liveness)
        logger.info("DB health: %s%s", "OK" if ok else "FAIL", f" ({err})" if err else "")
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)

    yield

    # Mark worker stopped (thread is daemon so it dies with process)
    try:
        from ..core.state import RUNTIME_STATE
        RUNTIME_STATE["worker_alive"] = False
    except Exception:
        pass

    # Shutdown cron supervisor
    if cron_task and not cron_task.done():
        cron_task.cancel()
        try:
            await cron_task
        except asyncio.CancelledError:
            pass

    # Shutdown queue workers
    try:
        from ..core.queue import cancel_command_queue_workers
        await cancel_command_queue_workers()
    except Exception:
        for task in queue_worker_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # Shutdown telegram
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutting down Mind Clone Agent API")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Mind Clone Agent",
        description="Sovereign AI Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(router)

    return app

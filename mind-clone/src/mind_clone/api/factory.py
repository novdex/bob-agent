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

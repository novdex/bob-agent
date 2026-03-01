"""Bot application setup, polling, and lifecycle."""
from __future__ import annotations

from ._imports import (
    asyncio,
    logging,
    log,
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    TELEGRAM_BOT_TOKEN,
    TOKEN_PLACEHOLDER,
)
from .commands import (
    cmd_start,
    cmd_help,
    cmd_status,
    cmd_task,
    cmd_tasks,
    cmd_cancel,
    cmd_approve,
    cmd_reject,
    cmd_approvals,
    cmd_cron,
    handle_message,
)
from .runtime import (
    initialize_runtime_state_baseline,
    run_startup_preflight,
)


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
    """Set up and initialize the bot application."""
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

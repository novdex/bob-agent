"""Telegram bot command handlers."""
from __future__ import annotations

from ._imports import (
    log,
    SessionLocal,
    Task,
    ScheduledJob,
    Update,
    ContextTypes,
    truncate_text,
    enqueue_task,
)
from .messaging import (
    send_telegram_message,
    handle_approval_command,
)
from .runtime import runtime_metrics
from .dispatch import dispatch_incoming_message


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
        "\U0001f916 *Mind Clone Agent Commands*\n\n"
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

    _ok = "\u2705"  # checkmark
    _no = "\u274c"  # cross

    status_lines = [
        "\U0001f4ca *System Status*",
        "",
        f"*Runtime:*",
        f"\u2022 Worker: {_ok if metrics.get('worker_alive') else _no}",
        f"\u2022 Spine: {_ok if metrics.get('spine_supervisor_alive') else _no}",
        f"\u2022 DB: {_ok if metrics.get('db_healthy') else _no}",
        f"\u2022 Webhook: {_ok if metrics.get('webhook_registered') else _no}",
        "",
        f"*Queue:*",
        f"\u2022 Mode: {metrics.get('command_queue_mode', 'unknown')}",
        f"\u2022 Size: {metrics.get('command_queue_size', 0)}/{metrics.get('command_queue_max_size', 0)}",
        f"\u2022 Workers: {metrics.get('command_queue_worker_alive_count', 0)}/{metrics.get('command_queue_worker_target', 0)}",
        "",
        f"*Tasks:*",
        f"\u2022 Queue: {metrics.get('task_queue_size', 0)}",
        f"\u2022 Tracked: {metrics.get('tasks_tracked', 0)}",
        "",
        f"*Model:*",
        f"\u2022 Primary: {metrics.get('llm_primary_model', 'unknown')}",
        f"\u2022 Fallback: {metrics.get('llm_fallback_model', 'none')}",
        f"\u2022 Failover: {'enabled' if metrics.get('llm_failover_enabled') else 'disabled'}",
    ]

    if alerts:
        status_lines.extend(
            [
                "",
                f"\u26a0\ufe0f *Alerts ({len(alerts)}):*",
            ]
        )
        for alert in alerts[:5]:
            status_lines.append(f"\u2022 {alert.get('code')}: {alert.get('message', '')[:50]}")

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
            f"\u2705 Task #{task_id} created!\n"
            f"Description: {description[:100]}{'...' if len(description) > 100 else ''}\n\n"
            f"Use /cancel {task_id} to cancel."
        )
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"\u274c Failed to create task: {truncate_text(str(e), 200)}")
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
        await update.message.reply_text("\u274c Task ID must be a number.")
        return

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.owner_id == owner_id).first()
        if not task:
            await update.message.reply_text(f"\u274c Task #{task_id} not found.")
            return

        if task.status in ("completed", "failed", "cancelled"):
            await update.message.reply_text(f"\u2139\ufe0f Task #{task_id} is already {task.status}.")
            return

        task.status = "cancelled"
        db.commit()
        await update.message.reply_text(f"\u2705 Task #{task_id} cancelled.")
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"\u274c Failed to cancel task: {truncate_text(str(e), 200)}")
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

        lines = ["\U0001f4cb *Your Recent Tasks*\n"]
        for task in tasks:
            status_emoji = {
                "pending": "\u23f3",
                "queued": "\U0001f4dd",
                "running": "\U0001f504",
                "completed": "\u2705",
                "failed": "\u274c",
                "cancelled": "\U0001f6ab",
                "blocked": "\u23f8\ufe0f",
            }.get(task.status, "\u2753")
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

    lines = ["\u23f8\ufe0f *Pending Approvals*\n"]
    for approval in pending[:10]:
        token = approval.get("token", "unknown")
        tool = approval.get("tool_name", "unknown")
        desc = truncate_text(approval.get("description", "No description"), 40)
        lines.append(f"\u2022 `{token}`: {tool}\n  {desc}")

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

        lines = ["\u23f0 *Your Scheduled Jobs*\n"]
        for job in jobs:
            status = "\u2705" if job.enabled else "\U0001f6ab"
            name = truncate_text(job.name, 30)
            interval = f"{job.interval_seconds}s"
            runs = job.run_count or 0
            lines.append(f"{status} {name}\n  Interval: {interval} | Runs: {runs}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        db.close()


async def handle_btw_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /btw side conversations -- separate context from main chat.

    Creates a temporary side session so the quick question does not
    pollute the main conversation history.  Responds with a concise
    answer prefixed with ``[btw]``.

    Supports both ``/btw <text>`` (slash command) and ``btw: <text>``
    or ``btw <text>`` (plain message prefix, detected in handle_message).
    """
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    text = update.message.text or ""

    owner_id = resolve_owner_id(chat_id, username)

    # Strip the /btw or btw: prefix to get the actual question
    btw_text = text
    for prefix in ("/btw ", "btw:", "btw "):
        if btw_text.lower().startswith(prefix):
            btw_text = btw_text[len(prefix):]
            break
    btw_text = btw_text.strip()

    if not btw_text:
        await send_telegram_message(chat_id, "[btw] What's your side question?")
        return

    try:
        # Create a temporary side session (isolated from main conversation)
        from mind_clone.core.sessions import create_session
        side_session = create_session(owner_id, "btw", chat_id)
        log.info("BTW_SESSION chat_id=%s session=%s", chat_id, side_session[:12])
    except Exception as exc:
        log.warning("BTW_SESSION_FAIL chat_id=%s error=%s", chat_id, str(exc)[:150])

    try:
        # Process with minimal context -- no main conversation history
        from mind_clone.agent.llm import call_llm
        result = call_llm([
            {"role": "system", "content": "You are Bob. Answer this quick side question concisely."},
            {"role": "user", "content": btw_text},
        ])

        if result.get("ok"):
            answer = result.get("content", "I could not generate a response.")
            await send_telegram_message(chat_id, f"[btw] {answer}")
        else:
            error = result.get("error", "Unknown error")
            await send_telegram_message(chat_id, f"[btw] Sorry, I hit an error: {error[:200]}")
    except Exception as exc:
        log.error("BTW_HANDLER_FAIL chat_id=%s error=%s", chat_id, str(exc)[:200])
        await send_telegram_message(chat_id, "[btw] Sorry, something went wrong.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages."""
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    text = update.message.text

    # Intercept "btw:" and "btw " prefixed messages as side conversations
    if text and (text.lower().startswith("btw:") or text.lower().startswith("btw ")):
        return await handle_btw_message(update, context)

    owner_id = resolve_owner_id(chat_id, username)

    # Persist channel state on every message for restart resilience
    try:
        from mind_clone.services.channel_state import save_channel_state
        save_channel_state(chat_id, username or "", owner_id)
    except Exception as exc:
        log.warning("Failed to save channel state: %s", exc)

    await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=chat_id,
        username=username or "unknown",
        text=text,
        source="telegram",
        expect_response=False,
    )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages — analyse images using vision model.

    Downloads the largest available resolution of the photo, sends it
    to MiMo-V2-Pro via OpenRouter for analysis, and relays the result
    back to the user.  Also dispatches the analysis text into the
    agent loop so Bob can use tools based on what he sees.
    """
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None

    owner_id = resolve_owner_id(chat_id, username)

    # Persist channel state
    try:
        from mind_clone.services.channel_state import save_channel_state
        save_channel_state(chat_id, username or "", owner_id)
    except Exception:
        pass

    try:
        # Get the largest photo (Telegram provides multiple sizes)
        if not update.message.photo:
            await send_telegram_message(chat_id, "No photo found in the message.")
            return

        photo = update.message.photo[-1]  # Largest resolution
        caption = update.message.caption or ""

        # Download the image via Telegram bot API
        file_obj = await context.bot.get_file(photo.file_id)
        image_data = await file_obj.download_as_bytearray()
        image_bytes = bytes(image_data)

        # Analyse the image
        from mind_clone.services.vision import analyse_image
        analysis = analyse_image(image_bytes, caption=caption, owner_id=owner_id)

        # Send analysis back to user
        await send_telegram_message(chat_id, analysis)

        # Also dispatch to agent loop so Bob can use tools based on what he sees
        agent_text = f"[Image analysis] {caption + ': ' if caption else ''}{analysis}"
        await dispatch_incoming_message(
            owner_id=owner_id,
            chat_id=chat_id,
            username=username or "unknown",
            text=agent_text,
            source="telegram",
            expect_response=False,
        )

    except Exception as exc:
        log.exception("Photo message handling failed: %s", exc)
        await send_telegram_message(
            chat_id,
            f"Failed to analyse image: {str(exc)[:200]}",
        )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages: transcribe -> process -> reply.

    Downloads voice file, transcribes via Groq Whisper STT, shows
    transcription, then dispatches text to the agent loop.
    """
    from mind_clone.agent.identity import resolve_owner_id

    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username if update.effective_user else None
    owner_id = resolve_owner_id(chat_id, username)

    voice = update.message.voice
    if not voice:
        return

    log.info("VOICE_MESSAGE_RECEIVED chat_id=%s duration=%ss", chat_id, voice.duration)

    try:
        voice_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await voice_file.download_as_bytearray()
        audio_bytes = bytes(audio_bytes)
    except Exception as e:
        log.error("VOICE_DOWNLOAD_FAIL: %s", str(e)[:150])
        await send_telegram_message(chat_id, "Could not download voice message.")
        return

    try:
        from mind_clone.services.voice_stt import transcribe_voice, stt_enabled
        if not stt_enabled():
            await send_telegram_message(chat_id, "Voice transcription is not configured.")
            return

        ok, text = await transcribe_voice(audio_bytes, mime_type="audio/ogg")
        if not ok:
            await send_telegram_message(chat_id, f"Could not transcribe voice: {text}")
            return

        log.info("VOICE_TRANSCRIBED text='%s'", text[:80])
    except Exception as e:
        log.error("VOICE_STT_FAIL: %s", str(e)[:150])
        await send_telegram_message(chat_id, "Voice transcription failed.")
        return

    await send_telegram_message(chat_id, f"[Voice] {text}")

    # Get Bob's response via dispatch
    result = await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=chat_id,
        username=username or "unknown",
        text=text,
        source="telegram",
        expect_response=True,
    )

    # Send reply as voice note back
    response_text = ""
    if isinstance(result, dict):
        response_text = str(result.get("response", ""))
    elif isinstance(result, str):
        response_text = result

    if response_text:
        try:
            from mind_clone.services.voice_tts import synthesize_speech, tts_enabled
            if tts_enabled():
                import asyncio
                import concurrent.futures
                def _do_tts():
                    import asyncio as _aio
                    return _aio.run(synthesize_speech(response_text[:500]))
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    loop = asyncio.get_event_loop()
                    tts_ok, tts_result = await loop.run_in_executor(pool, _do_tts)
                if tts_ok and isinstance(tts_result, bytes) and len(tts_result) > 100:
                    from mind_clone.services.telegram.messaging import send_telegram_voice
                    await send_telegram_voice(chat_id, tts_result)
                    log.info("VOICE_REPLY_SENT chat_id=%s bytes=%d", chat_id, len(tts_result))
                else:
                    log.warning("TTS failed or too short, text reply already sent")
        except Exception as e:
            log.warning("VOICE_REPLY_FAIL: %s", str(e)[:150])


# ============================================================================
# Webhook Handler
# ============================================================================


async def telegram_webhook_handler(request_data: dict) -> dict:
    """Handle incoming Telegram webhook update."""
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
            elif text.startswith("/btw"):
                await handle_btw_message(update, type("Context", (), {"args": text.split()[1:]}))
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

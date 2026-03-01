from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request

from ._shared import (
    SessionLocal,
    _resolve_identity_owner,
    load_identity,
    send_telegram_message,
    parse_approval_token,
    parse_command_id,
    parse_cron_add_payload,
    parse_task_command_payload,
    handle_approval_command,
    tool_schedule_job,
    tool_list_scheduled_jobs,
    tool_disable_scheduled_job,
    set_owner_queue_mode,
    list_recent_tasks,
    task_progress,
    get_user_task_by_id,
    format_task_details,
    cancel_task,
    create_goal,
    list_goals,
    update_goal_progress,
    decompose_goal_into_tasks,
    create_queued_task,
    enqueue_task,
    resolve_owner_id,
    dispatch_incoming_message,
    normalize_agent_key,
    truncate_text,
    log,
    ConversationMessage,
    Goal,
)

router = APIRouter()


# --- Telegram Webhook ---
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive messages from Telegram."""
    data = await request.json()

    # Extract message
    message = data.get("message")
    if not message:
        return {"ok": True}

    chat_id = str(message["chat"]["id"])
    text = message.get("text", "")
    username = message.get("from", {}).get("username", "")

    if not text:
        return {"ok": True}

    log.info(f"Telegram message from {username} ({chat_id}): {text}")

    # Handle /start command
    if text.strip() == "/start":
        await send_telegram_message(
            chat_id,
            "ðŸ§ *Mind Clone activated.*\n\n"
            "I am your sovereign AI agent. I can:\n"
            "â€¢ Search the web\n"
            "â€¢ Read and write files\n"
            "â€¢ Run shell commands\n"
            "â€¢ Read webpages\n\n"
            "Send me any task.",
        )
        return {"ok": True}

    # Handle /identity command â€" show current identity
    if text.strip() == "/identity":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            identity = load_identity(db, user.id)
            if identity:
                msg = (
                    f"ðŸ† *Identity Kernel*\n\n"
                    f"*UUID:* `{identity['agent_uuid']}`\n"
                    f"*Origin:* {identity['origin_statement']}\n\n"
                    f"*Values:* {', '.join(identity['core_values'])}\n\n"
                    f"*Directives:* {json.dumps(identity['authority_bounds'], indent=2)}"
                )
            else:
                msg = "No identity kernel found."
            await send_telegram_message(chat_id, msg)
        finally:
            db.close()
        return {"ok": True}

    # Handle /clear command â€" clear conversation history
    if text.strip() == "/clear":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            db.query(ConversationMessage).filter(ConversationMessage.owner_id == user.id).delete()
            db.commit()
            await send_telegram_message(chat_id, "ðŸ§¹ Conversation history cleared.")
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/approve"):
        token = parse_approval_token(text, "/approve")
        if not token:
            await send_telegram_message(chat_id, "Usage: /approve <token>")
            return {"ok": True}
        await handle_approval_command(chat_id=chat_id, username=username, token=token, approve=True)
        return {"ok": True}

    if text.strip().startswith("/reject"):
        token = parse_approval_token(text, "/reject")
        if not token:
            await send_telegram_message(chat_id, "Usage: /reject <token>")
            return {"ok": True}
        await handle_approval_command(
            chat_id=chat_id, username=username, token=token, approve=False
        )
        return {"ok": True}

    if text.strip().startswith("/cron_add"):
        parsed_cron = parse_cron_add_payload(text.strip())
        if not parsed_cron:
            await send_telegram_message(chat_id, "Usage: /cron_add <interval_seconds> :: <message>")
            return {"ok": True}
        interval_seconds, cron_message = parsed_cron
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_schedule_job(
                owner_id=int(user.id),
                name=f"telegram_cron_{int(time.time())}",
                message=cron_message,
                interval_seconds=interval_seconds,
                lane="cron",
            )
            if result.get("ok"):
                await send_telegram_message(
                    chat_id,
                    (
                        f"Cron job created: #{result.get('job_id')}\n"
                        f"Interval: {result.get('interval_seconds')}s\n"
                        f"Next run: {result.get('next_run_at')}"
                    ),
                )
            else:
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to create cron job.')}"
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip() == "/cron_list":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_list_scheduled_jobs(
                owner_id=int(user.id), include_disabled=True, limit=30
            )
            if not result.get("ok"):
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to list cron jobs.')}"
                )
            else:
                jobs = result.get("jobs", [])
                if not jobs:
                    await send_telegram_message(chat_id, "No cron jobs found.")
                else:
                    lines = ["Cron jobs:"]
                    for row in jobs:
                        status = "on" if row.get("enabled") else "off"
                        lines.append(
                            f"#{row.get('job_id')} [{status}] every {row.get('interval_seconds')}s "
                            f"runs={row.get('run_count')} next={row.get('next_run_at')}"
                        )
                    await send_telegram_message(chat_id, "\n".join(lines))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/cron_disable"):
        job_id = parse_command_id(text, "/cron_disable")
        if job_id is None:
            await send_telegram_message(chat_id, "Usage: /cron_disable <job_id>")
            return {"ok": True}
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_disable_scheduled_job(owner_id=int(user.id), job_id=job_id)
            if result.get("ok"):
                await send_telegram_message(chat_id, f"Cron job #{job_id} disabled.")
            else:
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to disable cron job.')}"
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/queue_mode"):
        parts = text.strip().split(maxsplit=1)
        if len(parts) != 2:
            await send_telegram_message(
                chat_id, "Usage: /queue_mode <off|on|auto|steer|followup|collect>"
            )
            return {"ok": True}
        mode_raw = parts[1].strip().lower()
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            mode_set = set_owner_queue_mode(int(user.id), mode_raw)
            await send_telegram_message(
                chat_id, f"Queue mode set to `{mode_set}` for this session."
            )
        finally:
            db.close()
        return {"ok": True}

    if text.strip() == "/tasks":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            tasks = list_recent_tasks(db, user.id, limit=10)
            if not tasks:
                await send_telegram_message(chat_id, "No tasks found.")
            else:
                lines = ["Recent tasks:"]
                for task in tasks:
                    done, total = task_progress(task.plan)
                    lines.append(
                        f"#{task.id} | {task.status} | {done}/{total} | {truncate_text(task.title, 70)}"
                    )
                await send_telegram_message(chat_id, "\n".join(lines))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task_status"):
        task_id = parse_command_id(text, "/task_status")
        if task_id is None:
            await send_telegram_message(chat_id, "Usage: /task_status <id>")
            return {"ok": True}

        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task = get_user_task_by_id(db, user.id, task_id)
            if not task:
                await send_telegram_message(chat_id, f"Task #{task_id} not found.")
            else:
                await send_telegram_message(chat_id, format_task_details(task))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task_cancel"):
        task_id = parse_command_id(text, "/task_cancel")
        if task_id is None:
            await send_telegram_message(chat_id, "Usage: /task_cancel <id>")
            return {"ok": True}

        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task = get_user_task_by_id(db, user.id, task_id)
            if not task:
                await send_telegram_message(chat_id, f"Task #{task_id} not found.")
            else:
                _, msg = cancel_task(db, task)
                await send_telegram_message(chat_id, msg)
        finally:
            db.close()
        return {"ok": True}

    # Pillar 3: /goal commands
    if text.strip().startswith("/goal"):
        parts = text.strip().split(None, 2)
        subcmd = parts[1].lower() if len(parts) > 1 else "help"
        goal_arg = parts[2] if len(parts) > 2 else ""
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            if subcmd == "set" and goal_arg:
                result = create_goal(db, int(user.id), goal_arg)
                if result.get("ok"):
                    goal_obj = db.query(Goal).filter(Goal.id == result["goal_id"]).first()
                    if goal_obj:
                        identity = load_identity(db, int(user.id))
                        new_task_ids = decompose_goal_into_tasks(db, goal_obj, identity)
                        await send_telegram_message(
                            chat_id,
                            f"Goal #{result['goal_id']} created: {result['title']}\n"
                            f"Generated {len(new_task_ids)} tasks.",
                        )
                        for tid in new_task_ids:
                            enqueue_task(tid)
                else:
                    await send_telegram_message(chat_id, f"Goal error: {result.get('error')}")
            elif subcmd == "list":
                goals = list_goals(db, int(user.id))
                if goals:
                    lines = ["Active Goals:"]
                    for g in goals:
                        lines.append(
                            f"#{g['id']} [{g['status']}] {g['title']} ({g['progress_pct']}%)"
                        )
                    await send_telegram_message(chat_id, "\n".join(lines))
                else:
                    await send_telegram_message(chat_id, "No goals found.")
            elif subcmd == "status" and goal_arg:
                try:
                    gid = int(goal_arg)
                    goal_obj = (
                        db.query(Goal).filter(Goal.id == gid, Goal.owner_id == int(user.id)).first()
                    )
                    if goal_obj:
                        update_goal_progress(db, goal_obj)
                        task_ids = json.loads(goal_obj.task_ids_json or "[]")
                        await send_telegram_message(
                            chat_id,
                            f"Goal #{goal_obj.id}: {goal_obj.title}\n"
                            f"Status: {goal_obj.status}\n"
                            f"Progress: {goal_obj.progress_pct}%\n"
                            f"Tasks: {len(task_ids)}\n"
                            f"Priority: {goal_obj.priority}",
                        )
                    else:
                        await send_telegram_message(chat_id, f"Goal #{gid} not found.")
                except ValueError:
                    await send_telegram_message(chat_id, "Usage: /goal status <id>")
            elif subcmd in ("pause", "resume", "abandon") and goal_arg:
                try:
                    gid = int(goal_arg)
                    goal_obj = (
                        db.query(Goal).filter(Goal.id == gid, Goal.owner_id == int(user.id)).first()
                    )
                    if goal_obj:
                        new_status = {
                            "pause": "paused",
                            "resume": "active",
                            "abandon": "abandoned",
                        }[subcmd]
                        goal_obj.status = new_status
                        db.commit()
                        await send_telegram_message(chat_id, f"Goal #{gid} -> {new_status}")
                    else:
                        await send_telegram_message(chat_id, f"Goal #{gid} not found.")
                except ValueError:
                    await send_telegram_message(chat_id, f"Usage: /goal {subcmd} <id>")
            else:
                await send_telegram_message(
                    chat_id,
                    "Goal Commands:\n"
                    "/goal set <title> - Create a new goal\n"
                    "/goal list - List all goals\n"
                    "/goal status <id> - Goal details\n"
                    "/goal pause <id> - Pause a goal\n"
                    "/goal resume <id> - Resume a goal\n"
                    "/goal abandon <id> - Abandon a goal",
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task"):
        parsed = parse_task_command_payload(text.strip())
        if not parsed:
            await send_telegram_message(chat_id, "Usage: /task <title> :: <goal>")
            return {"ok": True}

        title, goal = parsed
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task, created_new = create_queued_task(db, user.id, title, goal)
            if created_new:
                enqueue_task(task.id)
                await send_telegram_message(
                    chat_id,
                    f"Task created: #{task.id}\nTitle: {task.title}\nStatus: {task.status}",
                )
            else:
                await send_telegram_message(
                    chat_id,
                    f"Duplicate task detected. Reusing existing task #{task.id} ({task.status}).",
                )
        finally:
            db.close()
        return {"ok": True}

    # --- Main agent flow ---
    owner_id = resolve_owner_id(chat_id, username)
    await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=chat_id,
        username=username,
        text=text,
        source="telegram",
        expect_response=False,
    )

    return {"ok": True}

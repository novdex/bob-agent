"""Telegram message sending and approval handling."""
from __future__ import annotations

from ._imports import (
    asyncio,
    time,
    httpx,
    log,
    SessionLocal,
    Task,
    TELEGRAM_API,
    TASK_PROGRESS_REPORTING_ENABLED,
    TASK_PROGRESS_MIN_INTERVAL_SECONDS,
    _task_progress_last_send,
    _safe_json_dict,
    truncate_text,
    normalize_task_plan,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_QUEUED,
    enqueue_task,
    decide_approval_token,
)
from .utils import utc_now_iso

# ============================================================================
# Task and Approval Management
# ============================================================================


def unpause_task_after_approval(
    owner_id: int, task_id: int, step_id: str | None
) -> tuple[bool, str]:
    """Unpause a task after approval token is approved."""
    db = SessionLocal()
    try:
        task = (
            db.query(Task).filter(Task.id == int(task_id), Task.owner_id == int(owner_id)).first()
        )
        if not task:
            return False, f"Task #{task_id} not found for this user."
        plan = normalize_task_plan(task.plan)
        if step_id:
            for step in plan:
                if step.get("step_id") == step_id and step.get("status") == TASK_STATUS_BLOCKED:
                    step["status"] = "pending"
                    step["last_error"] = None
                    step["checkpoint_at"] = utc_now_iso()
                    break
        task.plan = plan
        task.status = TASK_STATUS_QUEUED
        db.commit()
        enqueue_task(task.id)
        return True, f"Task #{task.id} resumed from approval token."
    except Exception as e:
        db.rollback()
        return False, f"Failed to resume task: {truncate_text(str(e), 200)}"
    finally:
        db.close()

async def handle_approval_command(chat_id: str, username: str, token: str, approve: bool):
    """Handle /approve or /reject command."""
    from mind_clone.agent.identity import resolve_owner_id

    owner_id = resolve_owner_id(chat_id, username)
    decision = decide_approval_token(owner_id=owner_id, token=token, approve=approve)
    if not decision.get("ok"):
        await send_telegram_message(
            chat_id, f"Warning: {decision.get('error', 'Approval command failed.')}"
        )
        return

    status = str(decision.get("status", "pending"))
    token_owner_id = int(decision.get("owner_id") or owner_id)
    if status != "approved":
        await send_telegram_message(chat_id, f"Approval token {token} set to {status}.")
        return

    payload = _safe_json_dict(decision.get("resume_payload"), {})
    kind = str(payload.get("kind") or "")
    if kind == "task_step":
        task_id = int(payload.get("task_id") or 0)
        step_id = str(payload.get("step_id") or "") or None
        ok, message = unpause_task_after_approval(
            owner_id=token_owner_id, task_id=task_id, step_id=step_id
        )
        await send_telegram_message(chat_id, message if ok else f"Warning: {message}")
        return

    if kind == "chat_message":
        user_message = str(payload.get("user_message") or "").strip()
        if not user_message:
            await send_telegram_message(
                chat_id, "Approval saved, but no resumable message was found."
            )
            return
        await send_telegram_message(chat_id, f"Approved {token}. Resuming message execution.")
        from .dispatch import dispatch_incoming_message

        await dispatch_incoming_message(
            owner_id=token_owner_id,
            chat_id=chat_id,
            username=username,
            text=user_message,
            source="telegram",
            expect_response=False,
        )
        return

    await send_telegram_message(chat_id, f"Approval token {token} approved.")

# ============================================================================
# Message Sending Functions
# ============================================================================


def send_task_progress_sync(chat_id: str | None, task_id: int, message: str) -> None:
    """Send a task progress message to Telegram (sync, rate-limited)."""
    if not TASK_PROGRESS_REPORTING_ENABLED or not chat_id:
        return
    now = time.monotonic()
    last = _task_progress_last_send.get(task_id, 0.0)
    if (now - last) < TASK_PROGRESS_MIN_INTERVAL_SECONDS:
        return
    _task_progress_last_send[task_id] = now
    text = f"[Task #{task_id}] {message}"
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        with httpx.Client(timeout=15, trust_env=False) as client:
            resp = client.post(url, json={"chat_id": chat_id, "text": text})
            if resp.status_code != 200:
                log.debug(
                    "TASK_PROGRESS_SEND_FAIL task=0 status=0",
                    task_id,
                    resp.status_code,
                )
    except Exception:
        log.debug("TASK_PROGRESS_SEND_ERROR task=0", task_id, exc_info=True)

async def send_telegram_message(chat_id: str, text: str):
    """Send a message back to Telegram. Splits long messages."""
    text = str(text or "")
    if not text.strip():
        log.warning("TELEGRAM_SEND_SKIP_EMPTY chat_id=", chat_id)
        return

    url = f"{TELEGRAM_API}/sendMessage"

    # Telegram max message length is 4096
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for chunk in chunks:
            markdown_payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
            }
            try:
                resp = await client.post(url, json=markdown_payload)
                markdown_ok = False
                markdown_err = ""
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                        markdown_ok = bool(body.get("ok", False))
                        if not markdown_ok:
                            markdown_err = truncate_text(str(body), 220)
                    except Exception:
                        markdown_err = truncate_text(
                            resp.text or "Invalid JSON response from Telegram.", 220
                        )
                else:
                    markdown_err = f"status={resp.status_code} body={truncate_text(resp.text, 220)}"

                if markdown_ok:
                    continue

                # Retry in plain text mode for reliability.
                plain_payload = {"chat_id": chat_id, "text": chunk}
                plain_resp = await client.post(url, json=plain_payload)
                plain_ok = False
                plain_err = ""
                if plain_resp.status_code == 200:
                    try:
                        plain_body = plain_resp.json()
                        plain_ok = bool(plain_body.get("ok", False))
                        if not plain_ok:
                            plain_err = truncate_text(str(plain_body), 220)
                    except Exception:
                        plain_err = truncate_text(
                            plain_resp.text or "Invalid JSON response from Telegram.", 220
                        )
                else:
                    plain_err = f"status={plain_resp.status_code} body={truncate_text(plain_resp.text, 220)}"

                if not plain_ok:
                    log.error(
                        "TELEGRAM_SEND_FAIL chat_id= markdown_error= plain_error= text_preview=",
                        chat_id,
                        markdown_err,
                        plain_err,
                        truncate_text(chunk, 180),
                    )
            except Exception as e:
                log.error(f"Failed to send telegram message: {e}")

async def send_typing_indicator(chat_id: str):
    """Send typing indicator to chat."""
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            await client.post(
                f"{TELEGRAM_API}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
    except Exception as e:
        log.warning(
            "Typing indicator failed for chat_id= error=",
            chat_id,
            truncate_text(str(e), 180),
        )
"""
Utility functions, formatters, parsers, and serializers for API routes.

Contains helper functions used across multiple route modules including
ops auth, serialization, workflow parsing, memory vault, and UI helpers.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....database.session import SessionLocal
from ....database.models import (
    User,
    TeamAgent,
    ApprovalRequest,
    ConversationSummary,
    Goal,
    MemoryVector,
    OpsAuditEvent,
    ResearchNote,
    Task,
    TaskCheckpointSnapshot,
    UsageLedger,
    WorkflowProgram,
)
from ....utils import truncate_text, clamp_int, utc_now_iso, _safe_json_dict, _safe_json_list

from .constants import (
    TELEGRAM_BOT_TOKEN,
    TOKEN_PLACEHOLDER,
    HEARTBEAT_AUTONOMY_ENABLED,
    CRON_ENABLED,
    TEAM_MODE_ENABLED,
    TEAM_AGENT_DEFAULT_KEY,
    WORKFLOW_LOOP_MAX_ITERATIONS,
    WORKFLOW_MAX_STEPS,
    MEMORY_VAULT_ROOT,
    UI_DIST_DIR,
    OPS_AUTH_ENABLED,
    OPS_AUTH_TOKEN,
    OPS_AUTH_REQUIRE_SIGNATURE,
    OPS_AUTH_ROLE_SECRETS,
    OPS_AUTH_ALLOWED_ROLES,
    OPS_AUTH_SIGNATURE_SKEW_SECONDS,
)
from .state import (
    RUNTIME_STATE,
    TASK_WORKER_TASK,
    WEBHOOK_RETRY_TASK,
    WEBHOOK_SUPERVISOR_TASK,
    SPINE_SUPERVISOR_TASK,
    COMMAND_QUEUE_WORKER_TASK,
    CRON_SUPERVISOR_TASK,
    HEARTBEAT_SUPERVISOR_TASK,
    HEARTBEAT_WAKE_EVENT,
)
from .imports import (
    initialize_runtime_state_baseline,
    run_startup_preflight,
    check_db_liveness,
    try_set_telegram_webhook_once,
    webhook_retry_supervisor_loop,
    task_worker_loop,
    enqueue_task,
    recover_pending_tasks,
    task_progress,
    current_task_step,
    store_lesson,
    load_remote_node_registry,
    load_plugin_tools_registry,
    load_custom_tools_from_db,
    _refresh_approval_pending_runtime_count,
    evaluate_release_gate,
    run_startup_transcript_repair,
    command_queue_enabled,
    ensure_command_queue_workers_running,
    active_command_queue_worker_count,
    cancel_command_queue_workers,
    cron_supervisor_loop,
    COMMAND_QUEUE_MODE,
    COMMAND_QUEUE_WORKER_COUNT,
    init_db,
    _resolve_identity_owner,
    _ensure_team_agent_owner,
    _get_team_agent_row,
    normalize_agent_key,
)

logger = logging.getLogger("mind_clone.api")
log = logger  # alias used by monolith-ported lifespan code


# Stub fallbacks for functions that come from telegram.py but are used in lifespan
try:
    spine_supervisor_loop  # type: ignore[name-defined]
except NameError:
    async def spine_supervisor_loop() -> None:
        """No-op spine supervisor when telegram module unavailable."""
        import asyncio as _aio
        while True:
            await _aio.sleep(60)

try:
    heartbeat_supervisor_loop  # type: ignore[name-defined]
except NameError:
    async def heartbeat_supervisor_loop() -> None:
        """No-op heartbeat supervisor when telegram module unavailable."""
        import asyncio as _aio
        while True:
            await _aio.sleep(60)

try:
    cancel_background_task  # type: ignore[name-defined]
except NameError:
    async def cancel_background_task(task, name: str = "") -> None:
        """Cancel an asyncio background task safely."""
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    """Application lifespan context manager for startup/shutdown."""
    # Import state module to modify globals
    from . import state as _state

    _state.TASK_WORKER_TASK = None
    _state.WEBHOOK_RETRY_TASK = None
    _state.WEBHOOK_SUPERVISOR_TASK = None
    _state.SPINE_SUPERVISOR_TASK = None
    _state.COMMAND_QUEUE_WORKER_TASK = None
    _state.CRON_SUPERVISOR_TASK = None
    _state.HEARTBEAT_SUPERVISOR_TASK = None

    initialize_runtime_state_baseline()
    _preflight_ok, preflight_errors = run_startup_preflight()
    critical_preflight_errors = [
        err
        for err in preflight_errors
        if "OS_SANDBOX_REQUIRED" in str(err) or "OS sandbox is required" in str(err)
    ]
    if critical_preflight_errors:
        raise RuntimeError(
            "Critical startup preflight failure: " + "; ".join(critical_preflight_errors)
        )
    if _state.HEARTBEAT_WAKE_EVENT is None:
        _state.HEARTBEAT_WAKE_EVENT = asyncio.Event()

    init_db()
    repair_boot = await asyncio.to_thread(run_startup_transcript_repair, 250)
    if isinstance(repair_boot, dict):
        if repair_boot.get("ok"):
            if int(repair_boot.get("owners_changed", 0)) > 0:
                log.info(
                    "SESSION_TRANSCRIPT_STARTUP_REPAIR owners_processed=%d owners_changed=%d",
                    int(repair_boot.get("owners_processed", 0)),
                    int(repair_boot.get("owners_changed", 0)),
                )
        else:
            log.warning("SESSION_TRANSCRIPT_STARTUP_REPAIR_FAIL error=%s", repair_boot.get("error"))
    load_remote_node_registry()
    load_plugin_tools_registry()
    load_custom_tools_from_db()
    _refresh_approval_pending_runtime_count()
    try:
        db_boot = SessionLocal()
        try:
            RUNTIME_STATE["team_agents_total"] = int(db_boot.query(TeamAgent).count())
            RUNTIME_STATE["workflow_programs_total"] = int(db_boot.query(WorkflowProgram).count())
            RUNTIME_STATE["ops_audit_events_total"] = int(db_boot.query(OpsAuditEvent).count())
            last_audit = db_boot.query(OpsAuditEvent).order_by(OpsAuditEvent.id.desc()).first()
            if last_audit is not None:
                RUNTIME_STATE["ops_audit_last_hash"] = str(last_audit.event_hash or "")
            usage_rows = db_boot.query(UsageLedger).all()
            RUNTIME_STATE["usage_ledger_events"] = int(len(usage_rows))
            usage_cost = 0.0
            for row in usage_rows:
                try:
                    usage_cost += float(row.estimated_cost_usd or "0")
                except Exception:
                    continue
            RUNTIME_STATE["usage_ledger_cost_usd"] = round(float(usage_cost), 8)
        finally:
            db_boot.close()
    except Exception:
        pass
    check_db_liveness()
    try:
        evaluate_release_gate(run_eval=False)
    except Exception as e:
        log.warning("RELEASE_GATE_BOOTSTRAP_FAIL error=%s", truncate_text(str(e), 220))
    log.info("Database initialized")

    if _state.TASK_WORKER_TASK is None or _state.TASK_WORKER_TASK.done():
        _state.TASK_WORKER_TASK = asyncio.create_task(task_worker_loop())
        log.info("Task worker started")

    if command_queue_enabled():
        await ensure_command_queue_workers_running()
        log.info(
            "Command queue workers started (mode=%s target=%d alive=%d)",
            COMMAND_QUEUE_MODE,
            COMMAND_QUEUE_WORKER_COUNT,
            active_command_queue_worker_count(),
        )

    recovered = recover_pending_tasks()
    for task_id in recovered:
        enqueue_task(task_id)
    if recovered:
        log.info(f"Recovered {len(recovered)} queued task(s)")

    if TELEGRAM_BOT_TOKEN != TOKEN_PLACEHOLDER:
        ok, _ = await try_set_telegram_webhook_once()
        if not ok and (_state.WEBHOOK_SUPERVISOR_TASK is None or _state.WEBHOOK_SUPERVISOR_TASK.done()):
            _state.WEBHOOK_SUPERVISOR_TASK = asyncio.create_task(webhook_retry_supervisor_loop())
        elif ok:
            log.info("Telegram webhook set")
    else:
        RUNTIME_STATE["webhook_last_error"] = "Telegram bot token not configured."
        log.warning("Telegram bot token not configured")

    if _state.SPINE_SUPERVISOR_TASK is None or _state.SPINE_SUPERVISOR_TASK.done():
        _state.SPINE_SUPERVISOR_TASK = asyncio.create_task(spine_supervisor_loop())

    if HEARTBEAT_AUTONOMY_ENABLED and (
        _state.HEARTBEAT_SUPERVISOR_TASK is None or _state.HEARTBEAT_SUPERVISOR_TASK.done()
    ):
        _state.HEARTBEAT_SUPERVISOR_TASK = asyncio.create_task(heartbeat_supervisor_loop())

    if CRON_ENABLED and (_state.CRON_SUPERVISOR_TASK is None or _state.CRON_SUPERVISOR_TASK.done()):
        _state.CRON_SUPERVISOR_TASK = asyncio.create_task(cron_supervisor_loop())

    # Seed proactive check-in scheduled job
    try:
        from ....services.proactive import ensure_checkin_job_seeded
        seeded = ensure_checkin_job_seeded()
        if seeded:
            log.info("Proactive check-in job seeded")
    except Exception as _proactive_err:
        log.warning("PROACTIVE_SEED_FAIL error=%s", str(_proactive_err)[:200])

    try:
        yield
    finally:
        RUNTIME_STATE["shutting_down"] = True

        await cancel_background_task(_state.SPINE_SUPERVISOR_TASK, "spine supervisor")
        _state.SPINE_SUPERVISOR_TASK = None

        await cancel_background_task(_state.HEARTBEAT_SUPERVISOR_TASK, "heartbeat supervisor")
        _state.HEARTBEAT_SUPERVISOR_TASK = None

        await cancel_command_queue_workers()

        await cancel_background_task(_state.CRON_SUPERVISOR_TASK, "cron supervisor")
        _state.CRON_SUPERVISOR_TASK = None

        await cancel_background_task(_state.WEBHOOK_SUPERVISOR_TASK, "webhook supervisor")
        _state.WEBHOOK_SUPERVISOR_TASK = None

        await cancel_background_task(_state.WEBHOOK_RETRY_TASK, "webhook retry")
        _state.WEBHOOK_RETRY_TASK = None

        await cancel_background_task(_state.TASK_WORKER_TASK, "task worker")
        _state.TASK_WORKER_TASK = None

        RUNTIME_STATE["worker_alive"] = False
        RUNTIME_STATE["spine_supervisor_alive"] = False
        RUNTIME_STATE["heartbeat_supervisor_alive"] = False
        RUNTIME_STATE["heartbeat_next_tick_at"] = None
        RUNTIME_STATE["webhook_next_retry_at"] = None


def get_db():
    """Yield a database session, closing it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ops_auth_fail(status_code: int, message: str):
    """Record auth failure in runtime state and raise HTTP exception."""
    RUNTIME_STATE["ops_auth_failures"] = int(RUNTIME_STATE.get("ops_auth_failures", 0)) + 1
    RUNTIME_STATE["ops_auth_last_error"] = truncate_text(message, 220)
    raise HTTPException(status_code=status_code, detail=message)


def _extract_ops_token(request: Request) -> str:
    """Extract ops auth token from request headers or query params."""
    auth = str(request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = str(request.headers.get("x-ops-token") or "").strip()
    if token:
        return token
    return str(request.query_params.get("ops_token") or "").strip()


def _ops_signature_secret(role: str | None) -> str:
    """Get the HMAC secret for ops signature verification."""
    role_key = str(role or "").strip().lower()
    if role_key:
        specific = str(OPS_AUTH_ROLE_SECRETS.get(role_key) or "").strip()
        if specific:
            return specific
    fallback = str(OPS_AUTH_ROLE_SECRETS.get("default") or "").strip()
    if fallback:
        return fallback
    return OPS_AUTH_TOKEN


def _ops_signature_payload(request: Request, timestamp: int) -> str:
    """Build the signature payload string."""
    method = str(request.method or "GET").upper()
    path = str(request.url.path or "")
    query = str(request.url.query or "")
    return f"{method}\n{path}\n{query}\n{int(timestamp)}"


def _verify_ops_signature(request: Request, role: str | None) -> tuple[bool, str]:
    """Verify HMAC signature on ops requests."""
    timestamp_raw = str(request.headers.get("x-ops-timestamp") or "").strip()
    signature = str(request.headers.get("x-ops-signature") or "").strip().lower()
    if not timestamp_raw:
        return False, "Missing x-ops-timestamp header."
    if not signature:
        return False, "Missing x-ops-signature header."
    try:
        timestamp = int(timestamp_raw)
    except Exception:
        return False, "Invalid x-ops-timestamp header."
    now_epoch = int(time.time())
    skew = abs(now_epoch - int(timestamp))
    if skew > int(OPS_AUTH_SIGNATURE_SKEW_SECONDS):
        return False, f"Signature timestamp skew too high ({skew}s)."
    secret = _ops_signature_secret(role)
    payload = _ops_signature_payload(request, timestamp)
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False, "Invalid ops request signature."
    return True, ""


def record_ops_audit_event(
    *,
    actor_role: str | None,
    actor_ref: str | None,
    action: str,
    target: str | None = None,
    status: str = "ok",
    detail: dict | None = None,
):
    """Record an ops audit event to the database."""
    try:
        db = SessionLocal()
    except Exception:
        return
    try:
        prev_row = db.query(OpsAuditEvent).order_by(OpsAuditEvent.id.desc()).first()
        prev_hash = str(prev_row.event_hash or "") if prev_row else ""
        detail_obj = _safe_json_dict(detail, {})
        detail_json = json.dumps(detail_obj, ensure_ascii=False, sort_keys=True)
        hash_raw = (
            f"{prev_hash}|{str(actor_role or '')}|{str(actor_ref or '')}|{str(action or '')}|"
            f"{str(target or '')}|{str(status or '')}|{detail_json}|{utc_now_iso()}"
        )
        event_hash = hashlib.sha256(hash_raw.encode("utf-8")).hexdigest()
        row = OpsAuditEvent(
            actor_role=truncate_text(str(actor_role or ""), 40) or None,
            actor_ref=truncate_text(str(actor_ref or ""), 140) or None,
            action=truncate_text(str(action or ""), 120) or "unknown",
            target=truncate_text(str(target or ""), 220) or None,
            status=truncate_text(str(status or "ok"), 20) or "ok",
            detail_json=detail_json,
            prev_hash=prev_hash or None,
            event_hash=event_hash,
        )
        db.add(row)
        db.commit()
        RUNTIME_STATE["ops_audit_events_total"] = (
            int(RUNTIME_STATE.get("ops_audit_events_total", 0)) + 1
        )
        RUNTIME_STATE["ops_audit_last_hash"] = event_hash
    except Exception:
        db.rollback()
    finally:
        db.close()


def require_ops_auth(request: Request):
    """Validate ops authentication on a request."""
    if not OPS_AUTH_ENABLED:
        return {"enabled": False, "role": None}
    if not OPS_AUTH_TOKEN:
        _ops_auth_fail(503, "Ops auth enabled but OPS_AUTH_TOKEN is not configured.")

    token = _extract_ops_token(request)
    if not token:
        _ops_auth_fail(401, "Missing ops auth token.")
    if token != OPS_AUTH_TOKEN:
        _ops_auth_fail(403, "Invalid ops auth token.")

    role = str(request.headers.get("x-ops-role") or "").strip().lower()
    if OPS_AUTH_ALLOWED_ROLES and role and role not in OPS_AUTH_ALLOWED_ROLES:
        _ops_auth_fail(403, f"Role '{role}' is not allowed for ops routes.")

    actor_ref = str(request.headers.get("x-ops-actor") or "").strip()
    if not actor_ref:
        actor_ref = str(request.client.host) if request.client else "unknown"

    if OPS_AUTH_REQUIRE_SIGNATURE:
        sig_ok, sig_error = _verify_ops_signature(request, role=role)
        if not sig_ok:
            RUNTIME_STATE["ops_signature_failures"] = (
                int(RUNTIME_STATE.get("ops_signature_failures", 0)) + 1
            )
            record_ops_audit_event(
                actor_role=role or None,
                actor_ref=actor_ref,
                action=f"{str(request.method).upper()} {request.url.path}",
                target=request.url.path,
                status="denied",
                detail={"reason": sig_error, "signature_required": True},
            )
            _ops_auth_fail(403, sig_error)

    record_ops_audit_event(
        actor_role=role or None,
        actor_ref=actor_ref,
        action=f"{str(request.method).upper()} {request.url.path}",
        target=request.url.path,
        status="ok",
        detail={"query": truncate_text(str(request.url.query or ""), 240)},
    )

    return {
        "enabled": True,
        "role": role or None,
        "actor_ref": actor_ref,
    }


def iso_datetime_or_none(value: datetime | None) -> str | None:
    """Convert datetime to ISO string, or return None."""
    if value is None:
        return None
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return value.isoformat()
        except Exception:
            return None


def resolve_ui_user_context(
    db: Session,
    chat_id: str,
    username: str | None,
    agent_key: str | None = None,
) -> tuple[User, int, str]:
    """Resolve user context for UI requests."""
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("chat_id is required.")
    normalized_username = str(username or "").strip()
    if not normalized_username or normalized_username == "api_user":
        normalized_username = f"tg_{normalized_chat_id}"
    root_user = _resolve_identity_owner(db, normalized_chat_id, normalized_username)
    key = normalize_agent_key(agent_key)
    if TEAM_MODE_ENABLED and key != TEAM_AGENT_DEFAULT_KEY:
        user = _ensure_team_agent_owner(db, root_user, key)
    else:
        user = root_user
    return user, int(user.id), normalized_chat_id


def serialize_task_summary(task: Task) -> dict:
    """Serialize a Task object to a summary dict."""
    done, total = task_progress(task.plan)
    return {
        "id": int(task.id),
        "title": task.title,
        "status": task.status,
        "created_at": iso_datetime_or_none(task.created_at),
        "progress_done": int(done),
        "progress_total": int(total),
        "current_step": current_task_step(task.plan),
    }


def serialize_pending_approval(row: ApprovalRequest) -> dict:
    """Serialize an ApprovalRequest to a dict."""
    return {
        "token": row.token,
        "tool_name": row.tool_name,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "step_id": row.step_id,
        "created_at": iso_datetime_or_none(row.created_at),
        "expires_at": iso_datetime_or_none(row.expires_at),
    }


def list_pending_approvals_for_owner(db: Session, owner_id: int, limit: int = 20) -> list[dict]:
    """List pending approval requests for a given owner."""
    now_dt = datetime.utcnow()
    rows = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.owner_id == int(owner_id),
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at > now_dt,
        )
        .order_by(ApprovalRequest.id.desc())
        .limit(clamp_int(limit, 1, 100, 20))
        .all()
    )
    return [serialize_pending_approval(row) for row in rows]


def resolve_root_ui_user_context(
    db: Session, chat_id: str, username: str | None
) -> tuple[User, int, str]:
    """Resolve root user context (no team agent resolution)."""
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("chat_id is required.")
    normalized_username = str(username or "").strip()
    if not normalized_username or normalized_username == "api_user":
        normalized_username = f"tg_{normalized_chat_id}"
    root_owner = _resolve_identity_owner(db, normalized_chat_id, normalized_username)
    return root_owner, int(root_owner.id), normalized_chat_id


def get_team_agent_with_user(
    db: Session, root_owner_id: int, agent_key: str
) -> tuple[TeamAgent | None, User | None]:
    """Get a team agent row and its associated user."""
    row = _get_team_agent_row(db, root_owner_id, agent_key)
    if not row:
        return None, None
    user = db.query(User).filter(User.id == int(row.agent_owner_id)).first()
    return row, user


def serialize_team_agent(row: TeamAgent, user: User | None = None) -> dict:
    """Serialize a TeamAgent to a dict."""
    return {
        "agent_key": str(row.agent_key),
        "display_name": str(row.display_name or row.agent_key),
        "status": str(row.status or "active"),
        "owner_id": int(row.owner_id),
        "agent_owner_id": int(row.agent_owner_id),
        "workspace_root": str(row.workspace_root or ""),
        "username": str(user.username) if user else None,
        "chat_id": str(user.telegram_chat_id) if user and user.telegram_chat_id else None,
        "created_at": iso_datetime_or_none(row.created_at),
        "updated_at": iso_datetime_or_none(row.updated_at),
        "last_seen_at": iso_datetime_or_none(row.last_seen_at),
    }


def list_team_agents_for_owner(
    db: Session, root_owner_id: int, include_stopped: bool = True
) -> list[dict]:
    """List all team agents for a given root owner."""
    q = db.query(TeamAgent).filter(TeamAgent.owner_id == int(root_owner_id))
    if not include_stopped:
        q = q.filter(TeamAgent.status == "active")
    rows = q.order_by(TeamAgent.id.asc()).all()
    payload: list[dict] = []
    for row in rows:
        user = db.query(User).filter(User.id == int(row.agent_owner_id)).first()
        payload.append(serialize_team_agent(row, user))
    return payload


def resolve_team_agent_owner_for_request(
    db: Session,
    chat_id: str,
    username: str | None,
    agent_key: str | None,
    create_if_missing: bool = False,
    require_active: bool = True,
) -> tuple[User, User, int, str]:
    """Resolve team agent owner for an API request."""
    root_owner, root_owner_id, normalized_chat_id = resolve_root_ui_user_context(
        db, chat_id, username
    )
    key = normalize_agent_key(agent_key)
    if key == TEAM_AGENT_DEFAULT_KEY or not TEAM_MODE_ENABLED:
        return root_owner, root_owner, root_owner_id, normalized_chat_id

    row, user = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        if not create_if_missing:
            raise ValueError(f"Agent '{key}' does not exist. Spawn it first.")
        user = _ensure_team_agent_owner(db, root_owner, key)
        row, _ = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        raise ValueError(f"Failed to resolve agent '{key}'.")
    if require_active and str(row.status or "active") != "active":
        raise ValueError(f"Agent '{key}' is stopped.")
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return root_owner, user, root_owner_id, normalized_chat_id


def _compile_workflow_step(line: str, line_no: int) -> dict | None:
    """Compile a single workflow program line into a step dict."""
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None
    upper = text.upper()
    if upper == "ENDIF":
        return {"kind": "endif"}
    if upper == "ENDLOOP":
        return {"kind": "endloop"}
    if upper.startswith("SET "):
        payload = text[len("SET ") :].strip()
        if "=" not in payload:
            raise ValueError(f"Line {line_no}: SET requires 'name = value'.")
        key, value = payload.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", key):
            raise ValueError(f"Line {line_no}: invalid SET variable name '{key}'.")
        return {"kind": "set", "name": key, "value": truncate_text(value.strip(), 2000)}
    if upper.startswith("IF "):
        condition = truncate_text(text[len("IF ") :].strip(), 320)
        if not condition:
            raise ValueError(f"Line {line_no}: IF requires a condition.")
        return {"kind": "if", "condition": condition}
    if upper.startswith("LOOP "):
        count_raw = text[len("LOOP ") :].strip()
        try:
            count = int(count_raw)
        except Exception:
            raise ValueError(f"Line {line_no}: LOOP requires an integer count.")
        count = clamp_int(count, 1, WORKFLOW_LOOP_MAX_ITERATIONS, 1)
        return {"kind": "loop", "count": int(count)}
    if upper.startswith("SEND "):
        _, payload = text.split(" ", 1)
        if "::" not in payload:
            raise ValueError(f"Line {line_no}: SEND requires 'agent_key :: message'.")
        agent_key, message = payload.split("::", 1)
        return {
            "kind": "send",
            "agent_key": normalize_agent_key(agent_key),
            "message": truncate_text(message.strip(), 4000),
        }
    if upper.startswith("BROADCAST "):
        payload = text[len("BROADCAST ") :]
        if "::" in payload:
            _, message = payload.split("::", 1)
            payload = message
        return {"kind": "broadcast", "message": truncate_text(payload.strip(), 4000)}
    if upper.startswith("SLEEP "):
        seconds_raw = text[len("SLEEP ") :].strip()
        try:
            seconds = float(seconds_raw)
        except Exception:
            raise ValueError(f"Line {line_no}: invalid SLEEP seconds.")
        return {"kind": "sleep", "seconds": max(0.0, min(120.0, seconds))}
    if upper.startswith("TASK "):
        _, payload = text.split(" ", 1)
        parts = payload.split("::")
        if len(parts) < 3:
            raise ValueError(f"Line {line_no}: TASK requires 'agent_key :: title :: goal'.")
        agent_key = normalize_agent_key(parts[0].strip())
        title = truncate_text(parts[1].strip(), 140)
        goal = truncate_text("::".join(parts[2:]).strip(), 6000)
        if not title or not goal:
            raise ValueError(f"Line {line_no}: TASK title/goal cannot be empty.")
        return {"kind": "task", "agent_key": agent_key, "title": title, "goal": goal}
    raise ValueError(f"Line {line_no}: unknown workflow command.")


def _count_workflow_actions(steps: list[dict]) -> int:
    """Count total workflow actions including loop expansions."""
    total = 0
    for step in steps:
        kind = str(step.get("kind") or "").strip().lower()
        if kind in {"if", "loop"}:
            nested = _count_workflow_actions(_safe_json_list(step.get("steps"), []))
            if kind == "loop":
                total += int(step.get("count", 1)) * nested
            else:
                total += nested
            continue
        total += 1
    return int(total)


def parse_workflow_program_text(body_text: str) -> list[dict]:
    """Parse workflow program text into a list of step dicts."""
    lines = str(body_text or "").splitlines()
    root_steps: list[dict] = []
    stack: list[dict] = [{"kind": "root", "line_no": 0, "steps": root_steps}]
    for idx, line in enumerate(lines, 1):
        step = _compile_workflow_step(line, idx)
        if step is not None:
            kind = str(step.get("kind") or "").strip().lower()
            if kind in {"if", "loop"}:
                node = dict(step)
                node["steps"] = []
                stack[-1]["steps"].append(node)
                stack.append({"kind": kind, "line_no": idx, "steps": node["steps"]})
                continue
            if kind == "endif":
                if len(stack) <= 1 or stack[-1]["kind"] != "if":
                    raise ValueError(f"Line {idx}: ENDIF without matching IF.")
                stack.pop()
                continue
            if kind == "endloop":
                if len(stack) <= 1 or stack[-1]["kind"] != "loop":
                    raise ValueError(f"Line {idx}: ENDLOOP without matching LOOP.")
                stack.pop()
                continue
            stack[-1]["steps"].append(step)
    if len(stack) != 1:
        dangling = stack[-1]
        raise ValueError(
            f"Unclosed {dangling['kind'].upper()} block starting at line {dangling['line_no']}."
        )
    if not root_steps:
        raise ValueError("Workflow has no executable steps.")
    total_actions = _count_workflow_actions(root_steps)
    if total_actions > WORKFLOW_MAX_STEPS:
        raise ValueError(f"Workflow exceeds max steps ({WORKFLOW_MAX_STEPS}).")
    return root_steps


def _workflow_render_template(text: str, variables: dict[str, str]) -> str:
    """Render template variables in workflow text."""
    raw = str(text or "")
    if "{{" not in raw:
        return raw

    def _replace(match: re.Match) -> str:
        key = str(match.group(1) or "").strip()
        if not key:
            return ""
        return str(variables.get(key, ""))

    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", _replace, raw)


def _workflow_eval_condition(condition: str, variables: dict[str, str]) -> bool:
    """Evaluate a workflow condition expression."""
    expr = str(condition or "").strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=)\s*(.+)$", expr)
    if not match:
        raise ValueError("Condition must be in format: <var> == <value> or <var> != <value>.")
    var_name = match.group(1)
    op = match.group(2)
    right = str(match.group(3) or "").strip()
    if (right.startswith("'") and right.endswith("'")) or (
        right.startswith('"') and right.endswith('"')
    ):
        right = right[1:-1]
    left_val = str(variables.get(var_name, ""))
    right_val = _workflow_render_template(right, variables)
    if op == "==":
        return left_val == right_val
    return left_val != right_val


def _vault_owner_dir(owner_id: int) -> Path:
    """Get the vault directory path for an owner."""
    path = (MEMORY_VAULT_ROOT / f"owner_{int(owner_id)}").resolve(strict=False)
    return path


def _vault_git_run(vault_dir: Path, args: list[str]) -> tuple[bool, str]:
    """Run a git command in the vault directory."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            return False, truncate_text(result.stderr or result.stdout or "git failed", 500)
        return True, truncate_text(result.stdout or "ok", 500)
    except Exception as e:
        return False, truncate_text(str(e), 500)


def memory_vault_bootstrap(owner_id: int) -> dict:
    """Initialize the memory vault for an owner."""
    vault_dir = _vault_owner_dir(owner_id)
    vault_dir.mkdir(parents=True, exist_ok=True)
    readme = vault_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Bob Memory Vault\n\nPrivate backup repository for agent memory snapshots.\n",
            encoding="utf-8",
        )
    if not (vault_dir / ".git").exists():
        ok, out = _vault_git_run(vault_dir, ["init"])
        if not ok:
            return {"ok": False, "error": f"git init failed: {out}", "path": str(vault_dir)}
    _vault_git_run(vault_dir, ["config", "user.name", "bob-vault"])
    _vault_git_run(vault_dir, ["config", "user.email", "bob-vault@local"])
    RUNTIME_STATE["memory_vault_bootstraps"] = (
        int(RUNTIME_STATE.get("memory_vault_bootstraps", 0)) + 1
    )
    return {"ok": True, "path": str(vault_dir)}


def _build_memory_export_payload(db: Session, owner_id: int) -> dict:
    """Build the memory export payload for vault backup."""
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.owner_id == int(owner_id))
        .order_by(ResearchNote.id.asc())
        .all()
    )
    summaries = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.owner_id == int(owner_id))
        .order_by(ConversationSummary.id.asc())
        .all()
    )
    lessons = (
        db.query(MemoryVector)
        .filter(
            MemoryVector.owner_id == int(owner_id),
            MemoryVector.memory_type == "lesson",
        )
        .order_by(MemoryVector.id.asc())
        .all()
    )
    return {
        "exported_at": utc_now_iso(),
        "owner_id": int(owner_id),
        "research_notes": [
            {
                "topic": row.topic,
                "summary": row.summary,
                "sources": _safe_json_list(row.sources_json, []),
                "tags": _safe_json_list(row.tags_json, []),
            }
            for row in notes
        ],
        "conversation_summaries": [
            {
                "start_message_id": int(row.start_message_id),
                "end_message_id": int(row.end_message_id),
                "summary": row.summary,
                "key_points": _safe_json_list(row.key_points_json, []),
                "open_loops": _safe_json_list(row.open_loops_json, []),
            }
            for row in summaries
        ],
        "lessons": [{"lesson": str(row.text_preview or ""), "context": ""} for row in lessons],
    }


def memory_vault_backup(owner_id: int, message: str = "vault backup") -> dict:
    """Create a memory vault backup for an owner."""
    init = memory_vault_bootstrap(owner_id)
    if not init.get("ok"):
        return init
    vault_dir = Path(init["path"]).resolve(strict=False)
    db = SessionLocal()
    try:
        payload = _build_memory_export_payload(db, owner_id)
    finally:
        db.close()
    export_path = vault_dir / "memory_export.json"
    export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _vault_git_run(vault_dir, ["add", "memory_export.json"])
    commit_msg = truncate_text(str(message or "vault backup"), 120)
    ok, out = _vault_git_run(vault_dir, ["commit", "-m", commit_msg, "--allow-empty"])
    if not ok:
        return {"ok": False, "error": out}
    RUNTIME_STATE["memory_vault_backups"] = int(RUNTIME_STATE.get("memory_vault_backups", 0)) + 1
    return {"ok": True, "path": str(export_path), "commit": out}


def memory_vault_restore(owner_id: int, ref: str = "HEAD") -> dict:
    """Restore memory from vault for an owner."""
    vault_dir = _vault_owner_dir(owner_id)
    if not (vault_dir / ".git").exists():
        return {"ok": False, "error": "Vault is not initialized."}
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:memory_export.json"],
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            return {"ok": False, "error": truncate_text(result.stderr or "git show failed", 500)}
        payload = json.loads(result.stdout or "{}")
    except Exception as e:
        return {"ok": False, "error": truncate_text(str(e), 500)}

    db = SessionLocal()
    restored = {"research_notes": 0, "conversation_summaries": 0, "lessons": 0}
    try:
        for item in payload.get("research_notes", []):
            if not isinstance(item, dict):
                continue
            topic = truncate_text(str(item.get("topic") or "").strip(), 200)
            summary = truncate_text(str(item.get("summary") or "").strip(), 6000)
            if not topic or not summary:
                continue
            row = ResearchNote(
                owner_id=int(owner_id),
                topic=topic,
                summary=summary,
                sources_json=json.dumps(
                    _safe_json_list(item.get("sources"), []), ensure_ascii=False
                ),
                tags_json=json.dumps(_safe_json_list(item.get("tags"), []), ensure_ascii=False),
            )
            db.add(row)
            restored["research_notes"] += 1
        for item in payload.get("conversation_summaries", []):
            if not isinstance(item, dict):
                continue
            summary = truncate_text(str(item.get("summary") or "").strip(), 8000)
            if not summary:
                continue
            row = ConversationSummary(
                owner_id=int(owner_id),
                start_message_id=int(item.get("start_message_id") or 0),
                end_message_id=int(item.get("end_message_id") or 0),
                summary=summary,
                key_points_json=json.dumps(
                    _safe_json_list(item.get("key_points"), []), ensure_ascii=False
                ),
                open_loops_json=json.dumps(
                    _safe_json_list(item.get("open_loops"), []), ensure_ascii=False
                ),
            )
            db.add(row)
            restored["conversation_summaries"] += 1
        for item in payload.get("lessons", []):
            if not isinstance(item, dict):
                continue
            lesson = truncate_text(str(item.get("lesson") or "").strip(), 800)
            if not lesson:
                continue
            context_text = truncate_text(str(item.get("context") or ""), 1200)
            if store_lesson(db, int(owner_id), lesson, context_text):
                restored["lessons"] += 1
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 500)}
    finally:
        db.close()

    RUNTIME_STATE["memory_vault_restores"] = int(RUNTIME_STATE.get("memory_vault_restores", 0)) + 1
    return {"ok": True, "restored": restored, "ref": ref}


def ui_dist_ready() -> tuple[Path, Path, bool]:
    """Check if UI distribution files are ready."""
    dist_dir = UI_DIST_DIR.resolve(strict=False)
    index_file = (dist_dir / "index.html").resolve(strict=False)
    ready = dist_dir.exists() and dist_dir.is_dir() and index_file.exists() and index_file.is_file()
    return dist_dir, index_file, ready


def ui_not_built_response() -> JSONResponse:
    """Return a 503 response when UI is not built."""
    dist_dir, _, _ = ui_dist_ready()
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": "UI bundle not found. Build UI first in mind-clone-ui using npm install && npm run build.",
            "ui_dist_dir": str(dist_dir),
        },
    )


def resolve_ui_asset_path(path: str) -> Path | None:
    """Resolve a UI asset path, falling back to index.html for SPA routing."""
    dist_dir, index_file, ready = ui_dist_ready()
    if not ready:
        return None

    raw_path = str(path or "").strip().lstrip("/")
    if not raw_path:
        return index_file

    candidate = (dist_dir / raw_path).resolve(strict=False)
    try:
        candidate.relative_to(dist_dir)
    except Exception:
        return index_file

    if candidate.exists() and candidate.is_file():
        return candidate

    if "." in raw_path:
        return None
    return index_file


def parse_task_command_payload(text: str) -> tuple[str, str] | None:
    """Parse '/task <title> :: <goal>' command text."""
    prefix = "/task"
    if not text.startswith(prefix):
        return None
    payload = text[len(prefix) :].strip()
    if "::" not in payload:
        return None
    title, goal = payload.split("::", 1)
    title = title.strip()
    goal = goal.strip()
    if not title or not goal:
        return None
    return (title, goal)


def parse_cron_add_payload(text: str) -> tuple[int, str] | None:
    """Parse '/cron_add <interval_seconds> :: <message>' command text."""
    try:
        parts = text.strip().split("::", 1)
        if len(parts) != 2:
            return None
        interval_part = parts[0].strip()
        message = parts[1].strip()
        interval_str = interval_part.split()[-1]
        interval = int(interval_str)
        return (interval, message)
    except Exception:
        return None

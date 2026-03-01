from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ._shared import (
    SessionLocal,
    get_db,
    require_ops_auth,
    resolve_owner_id,
    iso_datetime_or_none,
    RUNTIME_STATE,
    PROTOCOL_SCHEMA_LOCK,
    PROTOCOL_SCHEMA_REGISTRY,
    EVAL_MAX_CASES,
    TASK_CHECKPOINT_REPLAY_STRICT,
    TASK_STATUS_QUEUED,
    OpsAuditEvent,
    UsageLedger,
    SchemaMigration,
    Goal,
    TaskCheckpointSnapshot,
    Task,
    clamp_int,
    truncate_text,
    utc_now_iso,
    _safe_json_dict,
    _safe_json_list,
    record_ops_audit_event,
    load_identity,
    create_goal,
    list_goals,
    update_goal_progress,
    decompose_goal_into_tasks,
    enqueue_task,
    protocol_contracts_public_view,
    protocol_validate_payload,
    reindex_owner_memory_vectors,
    tool_list_plugin_tools,
    load_plugin_tools_registry,
    run_continuous_eval_suite,
    evaluate_release_gate,
    get_user_task_by_id,
    latest_task_checkpoint_snapshot,
    restore_task_from_checkpoint_snapshot,
    store_task_checkpoint_snapshot,
    _validate_checkpoint_replay_state,
    normalize_task_plan,
    create_queued_task,
    tool_schedule_job,
    tool_list_scheduled_jobs,
    tool_disable_scheduled_job,
    set_owner_queue_mode,
    effective_command_queue_mode,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskResumeSnapshotRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    snapshot_id: int
    branch: bool = False
    strict: bool | None = None


class CronCreateRequest(BaseModel):
    chat_id: str
    name: str
    message: str
    interval_seconds: int = 300
    lane: str = "cron"
    username: str = "api_user"
    agent_key: str | None = None


class QueueModeRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    mode: str


# ---------------------------------------------------------------------------
# Ops routes: audit events, usage summary, usage session, schema version
# ---------------------------------------------------------------------------

@router.get("/ops/audit/events")
def ops_audit_events_endpoint(limit: int = 60, _ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        rows = (
            db.query(OpsAuditEvent)
            .order_by(OpsAuditEvent.id.desc())
            .limit(clamp_int(limit, 1, 500, 60))
            .all()
        )
        return {
            "ok": True,
            "count": len(rows),
            "items": [
                {
                    "id": int(row.id),
                    "actor_role": row.actor_role,
                    "actor_ref": row.actor_ref,
                    "action": row.action,
                    "target": row.target,
                    "status": row.status,
                    "created_at": iso_datetime_or_none(row.created_at),
                    "event_hash": row.event_hash,
                    "prev_hash": row.prev_hash,
                    "detail": _safe_json_dict(row.detail_json, {}),
                }
                for row in rows
            ],
        }
    finally:
        db.close()


@router.get("/ops/usage/summary")
def usage_summary_endpoint(
    owner_id: int | None = None,
    source_type: str | None = None,
    max_rows: int = 5000,
    _ops=Depends(require_ops_auth),
):
    db = SessionLocal()
    try:
        q = db.query(UsageLedger)
        if owner_id is not None:
            q = q.filter(UsageLedger.owner_id == int(owner_id))
        if source_type:
            q = q.filter(UsageLedger.source_type == truncate_text(str(source_type), 40))
        rows = q.order_by(UsageLedger.id.desc()).limit(clamp_int(max_rows, 20, 20000, 5000)).all()
        total_cost = 0.0
        total_prompt = 0
        total_completion = 0
        by_model: dict[str, dict] = {}
        for row in rows:
            try:
                total_cost += float(row.estimated_cost_usd or "0")
            except Exception:
                pass
            total_prompt += int(row.prompt_tokens or 0)
            total_completion += int(row.completion_tokens or 0)
            model_name = str(row.model_name or "unknown")
            bucket = by_model.setdefault(
                model_name,
                {"events": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            bucket["events"] += 1
            bucket["prompt_tokens"] += int(row.prompt_tokens or 0)
            bucket["completion_tokens"] += int(row.completion_tokens or 0)
            try:
                bucket["cost_usd"] += float(row.estimated_cost_usd or "0")
            except Exception:
                pass
        return {
            "ok": True,
            "rows": len(rows),
            "total_prompt_tokens": int(total_prompt),
            "total_completion_tokens": int(total_completion),
            "total_cost_usd": round(float(total_cost), 8),
            "owner_rollup_snapshot": dict(
                RUNTIME_STATE.get("usage_ledger_last_owner_summary") or {}
            ),
            "task_rollup_snapshot": dict(RUNTIME_STATE.get("usage_ledger_last_task_summary") or {}),
            "session_rollup_snapshot": dict(
                RUNTIME_STATE.get("usage_ledger_last_session_summary") or {}
            ),
            "by_model": {
                key: {
                    "events": int(val["events"]),
                    "prompt_tokens": int(val["prompt_tokens"]),
                    "completion_tokens": int(val["completion_tokens"]),
                    "cost_usd": round(float(val["cost_usd"]), 8),
                }
                for key, val in sorted(by_model.items(), key=lambda item: item[0])
            },
        }
    finally:
        db.close()


@router.get("/ops/usage/session")
def usage_session_endpoint(session_id: str, max_rows: int = 500, _ops=Depends(require_ops_auth)):
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "session_id is required."}
    db = SessionLocal()
    try:
        rows = (
            db.query(UsageLedger)
            .filter(UsageLedger.session_id == sid)
            .order_by(UsageLedger.id.desc())
            .limit(clamp_int(max_rows, 1, 5000, 500))
            .all()
        )
        total_cost = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        for row in rows:
            prompt_tokens += int(row.prompt_tokens or 0)
            completion_tokens += int(row.completion_tokens or 0)
            try:
                total_cost += float(row.estimated_cost_usd or "0")
            except Exception:
                continue
        return {
            "ok": True,
            "session_id": sid,
            "rows": len(rows),
            "total_prompt_tokens": int(prompt_tokens),
            "total_completion_tokens": int(completion_tokens),
            "total_cost_usd": round(float(total_cost), 8),
        }
    finally:
        db.close()


@router.get("/ops/schema/version")
def schema_version_endpoint(_ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        rows = db.query(SchemaMigration).order_by(SchemaMigration.version.asc()).all()
        latest = int(rows[-1].version) if rows else 0
        return {
            "ok": True,
            "schema_version": latest,
            "migrations": [
                {
                    "version": int(row.version),
                    "name": row.name,
                    "checksum": row.checksum,
                    "applied_at": iso_datetime_or_none(row.applied_at),
                }
                for row in rows
            ],
        }
    finally:
        db.close()


# Pillar 3: Goal API endpoints
@router.post("/goal")
async def create_goal_endpoint(request: Request, _ops=Depends(require_ops_auth)):
    body = await request.json() if hasattr(request, "json") else {}
    db = SessionLocal()
    try:
        owner_id = int(body.get("owner_id", 1))
        title = str(body.get("title", "")).strip()
        if not title:
            return {"ok": False, "error": "title required"}
        result = create_goal(
            db,
            owner_id,
            title,
            description=str(body.get("description", "")),
            success_criteria=str(body.get("success_criteria", "")),
            priority=str(body.get("priority", "medium")),
        )
        if result.get("ok"):
            goal_obj = db.query(Goal).filter(Goal.id == result["goal_id"]).first()
            if goal_obj:
                identity = load_identity(db, owner_id)
                task_ids = decompose_goal_into_tasks(db, goal_obj, identity)
                for tid in task_ids:
                    enqueue_task(tid)
                result["task_ids"] = task_ids
        return result
    finally:
        db.close()


@router.get("/goals")
def list_goals_endpoint(_ops=Depends(require_ops_auth), owner_id: int = 1):
    db = SessionLocal()
    try:
        return {"ok": True, "goals": list_goals(db, owner_id)}
    finally:
        db.close()


@router.get("/goal/{goal_id}")
def get_goal_endpoint(goal_id: int, _ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        update_goal_progress(db, goal)
        return {
            "ok": True,
            "goal": {
                "id": goal.id,
                "title": goal.title,
                "description": goal.description,
                "status": goal.status,
                "progress_pct": goal.progress_pct,
                "priority": goal.priority,
                "task_ids": json.loads(goal.task_ids_json or "[]"),
                "milestones": json.loads(goal.milestones_json or "[]"),
                "created_at": str(goal.created_at),
            },
        }
    finally:
        db.close()


@router.patch("/goal/{goal_id}")
async def update_goal_endpoint(goal_id: int, request: Request, _ops=Depends(require_ops_auth)):
    body = await request.json() if hasattr(request, "json") else {}
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        if "status" in body:
            goal.status = str(body["status"])[:20]
        if "priority" in body:
            goal.priority = str(body["priority"])[:10]
        db.commit()
        return {"ok": True, "goal_id": goal.id, "status": goal.status}
    finally:
        db.close()


@router.get("/ops/protocol/contracts")
def protocol_contracts_endpoint(_ops=Depends(require_ops_auth)):
    with PROTOCOL_SCHEMA_LOCK:
        contracts = protocol_contracts_public_view(dict(PROTOCOL_SCHEMA_REGISTRY))
    return {
        "ok": True,
        "count": len(contracts),
        "contracts": contracts,
        "timestamp": utc_now_iso(),
    }


@router.post("/ops/memory/reindex")
def ops_memory_reindex_endpoint(
    owner_id: int, rebuild_lessons: bool = False, _ops=Depends(require_ops_auth)
):
    if int(owner_id) <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    result = reindex_owner_memory_vectors(
        owner_id=int(owner_id), rebuild_lessons=bool(rebuild_lessons)
    )
    result["timestamp"] = utc_now_iso()
    return result


@router.get("/plugins/tools")
def list_plugins_endpoint(_ops=Depends(require_ops_auth)):
    return tool_list_plugin_tools()


@router.post("/plugins/reload")
def reload_plugins_endpoint(_ops=Depends(require_ops_auth)):
    load_plugin_tools_registry()
    return tool_list_plugin_tools()


@router.post("/eval/run")
def eval_run_endpoint(max_cases: int = EVAL_MAX_CASES, _ops=Depends(require_ops_auth)):
    report = run_continuous_eval_suite(max_cases=max_cases)
    if not report.get("ok", False):
        return {**report, "timestamp": utc_now_iso()}
    return {**report, "timestamp": utc_now_iso()}


@router.get("/eval/last")
def eval_last_endpoint(_ops=Depends(require_ops_auth)):
    report = dict(RUNTIME_STATE.get("eval_last_report") or {})
    if not report:
        return {"ok": False, "error": "No eval run recorded yet.", "timestamp": utc_now_iso()}
    report["timestamp"] = utc_now_iso()
    return report


@router.get("/release/gate")
def release_gate_endpoint(
    run_eval: bool = False, max_cases: int | None = None, _ops=Depends(require_ops_auth)
):
    result = evaluate_release_gate(run_eval=bool(run_eval), max_cases=max_cases)
    result["timestamp"] = utc_now_iso()
    return result


# ---------------------------------------------------------------------------
# Task checkpoint routes
# ---------------------------------------------------------------------------

@router.get("/ops/tasks/{task_id}/checkpoints")
def task_checkpoint_list_endpoint(
    task_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    rows = (
        db.query(TaskCheckpointSnapshot)
        .filter(
            TaskCheckpointSnapshot.task_id == int(task.id),
            TaskCheckpointSnapshot.owner_id == int(owner_id),
        )
        .order_by(TaskCheckpointSnapshot.id.desc())
        .limit(clamp_int(limit, 1, 200, 25))
        .all()
    )
    return {
        "ok": True,
        "task_id": int(task.id),
        "status": task.status,
        "count": len(rows),
        "checkpoints": [
            {
                "id": int(row.id),
                "source": row.source,
                "task_status": row.task_status,
                "created_at": iso_datetime_or_none(row.created_at),
                "extra": _safe_json_dict(row.extra_json, {}),
                "replay_state": _safe_json_dict(
                    _safe_json_dict(row.extra_json, {}).get("replay_state"), {}
                ),
            }
            for row in rows
        ],
    }


@router.post("/ops/tasks/{task_id}/resume_latest")
def task_resume_latest_checkpoint_endpoint(
    task_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    strict: bool | None = None,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    snap = latest_task_checkpoint_snapshot(db, int(task.id))
    if not snap:
        return {"ok": False, "error": f"Task #{task_id} has no checkpoint snapshots."}
    strict_mode = TASK_CHECKPOINT_REPLAY_STRICT if strict is None else bool(strict)
    restored = restore_task_from_checkpoint_snapshot(db, task, snap, strict=strict_mode)
    if not restored:
        return {"ok": False, "error": "Latest checkpoint failed deterministic validation."}
    task.status = TASK_STATUS_QUEUED
    store_task_checkpoint_snapshot(
        db,
        task,
        "manual_resume_latest",
        extra={
            "from_snapshot_id": int(snap.id),
            "replay_mode": "strict" if strict_mode else "legacy",
        },
    )
    db.commit()
    enqueue_task(int(task.id))
    return {
        "ok": True,
        "task_id": int(task.id),
        "from_snapshot_id": int(snap.id),
        "status": task.status,
        "replay_mode": "strict" if strict_mode else "legacy",
        "message": f"Task #{task.id} resumed from latest checkpoint.",
    }


@router.post("/ops/tasks/{task_id}/resume_from_snapshot")
def task_resume_from_snapshot_endpoint(
    task_id: int,
    req: TaskResumeSnapshotRequest,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    snap = (
        db.query(TaskCheckpointSnapshot)
        .filter(
            TaskCheckpointSnapshot.id == int(req.snapshot_id),
            TaskCheckpointSnapshot.task_id == int(task.id),
            TaskCheckpointSnapshot.owner_id == int(owner_id),
        )
        .first()
    )
    if not snap:
        return {"ok": False, "error": f"Snapshot #{req.snapshot_id} not found for task #{task.id}."}
    strict_mode = TASK_CHECKPOINT_REPLAY_STRICT if req.strict is None else bool(req.strict)
    plan = normalize_task_plan(_safe_json_list(snap.plan_json, []))
    if not plan:
        return {"ok": False, "error": "Checkpoint plan is empty or invalid."}
    snap_extra = _safe_json_dict(snap.extra_json, {})
    replay_ok, replay_reason, _ = _validate_checkpoint_replay_state(
        task, plan, snap_extra, strict=strict_mode
    )
    if not replay_ok:
        RUNTIME_STATE["task_checkpoint_restore_failures"] = (
            int(RUNTIME_STATE.get("task_checkpoint_restore_failures", 0)) + 1
        )
        RUNTIME_STATE["task_checkpoint_restore_drift"] = (
            int(RUNTIME_STATE.get("task_checkpoint_restore_drift", 0)) + 1
        )
        return {
            "ok": False,
            "error": f"Checkpoint validation failed: {replay_reason or 'unknown'}",
        }

    if bool(req.branch):
        branched = Task(
            owner_id=int(task.owner_id),
            agent_uuid=str(task.agent_uuid),
            title=truncate_text(str(snap_extra.get("task_title") or task.title), 200),
            description=truncate_text(
                str(snap_extra.get("task_description") or task.description), 8000
            ),
            status=TASK_STATUS_QUEUED,
            plan=plan,
        )
        db.add(branched)
        db.flush()
        store_task_checkpoint_snapshot(
            db,
            branched,
            "manual_branch_resume",
            extra={
                "from_task_id": int(task.id),
                "from_snapshot_id": int(snap.id),
                "replay_mode": "strict" if strict_mode else "legacy",
            },
        )
        db.commit()
        enqueue_task(int(branched.id))
        return {
            "ok": True,
            "task_id": int(branched.id),
            "branched_from_task_id": int(task.id),
            "from_snapshot_id": int(snap.id),
            "status": branched.status,
            "replay_mode": "strict" if strict_mode else "legacy",
            "message": f"Created task #{branched.id} from checkpoint #{snap.id}.",
        }

    restored = restore_task_from_checkpoint_snapshot(db, task, snap, strict=strict_mode)
    if not restored:
        return {"ok": False, "error": "Checkpoint failed deterministic restore validation."}
    task.status = TASK_STATUS_QUEUED
    store_task_checkpoint_snapshot(
        db,
        task,
        "manual_resume_snapshot",
        extra={
            "from_snapshot_id": int(snap.id),
            "replay_mode": "strict" if strict_mode else "legacy",
        },
    )
    db.commit()
    enqueue_task(int(task.id))
    return {
        "ok": True,
        "task_id": int(task.id),
        "from_snapshot_id": int(snap.id),
        "status": task.status,
        "replay_mode": "strict" if strict_mode else "legacy",
        "message": f"Task #{task.id} resumed from checkpoint #{snap.id}.",
    }


# ---------------------------------------------------------------------------
# Queue mode and cron job routes
# ---------------------------------------------------------------------------

@router.post("/ops/queue/mode")
def queue_mode_set_endpoint(req: QueueModeRequest, _ops=Depends(require_ops_auth)):
    ok_req, err_req = protocol_validate_payload(
        "queue.mode.request", req.model_dump(), direction="request"
    )
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    normalized = set_owner_queue_mode(owner_id=int(owner_id), mode=req.mode)
    payload = {"ok": True, "owner_id": int(owner_id), "mode": normalized}
    protocol_validate_payload("queue.mode.response", payload, direction="response")
    return payload


@router.get("/ops/queue/mode")
def queue_mode_get_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    payload = {
        "ok": True,
        "owner_id": int(owner_id),
        "mode": effective_command_queue_mode(owner_id),
    }
    protocol_validate_payload("queue.mode.response", payload, direction="response")
    return payload


@router.post("/cron/jobs")
def cron_create_endpoint(req: CronCreateRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = tool_schedule_job(
        owner_id=owner_id,
        name=req.name,
        message=req.message,
        interval_seconds=req.interval_seconds,
        lane=req.lane,
    )
    return result


@router.get("/cron/jobs")
def cron_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    include_disabled: bool = False,
    limit: int = 20,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    return tool_list_scheduled_jobs(
        owner_id=owner_id, include_disabled=include_disabled, limit=limit
    )


@router.post("/cron/jobs/{job_id}/disable")
def cron_disable_endpoint(
    job_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    return tool_disable_scheduled_job(owner_id=owner_id, job_id=job_id)

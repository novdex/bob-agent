"""UI routes — dashboard endpoints, chat, approval decision, and static asset serving."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ._shared import (
    get_db,
    resolve_ui_user_context,
    resolve_owner_id,
    load_identity,
    serialize_task_summary,
    list_recent_tasks,
    create_queued_task,
    enqueue_task,
    get_user_task_by_id,
    format_task_details,
    normalize_task_plan,
    cancel_task,
    list_pending_approvals_for_owner,
    approval_manager_decide_token,
    dispatch_incoming_message,
    unpause_task_after_approval,
    protocol_validate_payload,
    _safe_json_dict,
    truncate_text,
    clamp_int,
    ui_dist_ready,
    ui_not_built_response,
    resolve_ui_asset_path,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UiMeResponse(BaseModel):
    ok: bool
    owner_id: int | None = None
    username: str | None = None
    chat_id: str | None = None
    identity_summary: dict | None = None
    error: str | None = None


class UiTaskSummaryResponse(BaseModel):
    id: int
    title: str
    status: str
    created_at: str | None = None
    progress_done: int
    progress_total: int
    current_step: str | None = None


class UiTasksListResponse(BaseModel):
    ok: bool
    tasks: list[UiTaskSummaryResponse] = Field(default_factory=list)
    error: str | None = None


class UiTaskCreateRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    title: str
    goal: str


class UiTaskCreateResponse(BaseModel):
    ok: bool
    task_id: int | None = None
    created_new: bool = False
    status: str | None = None
    message: str | None = None
    error: str | None = None


class UiTaskDetailResponse(BaseModel):
    ok: bool
    task: UiTaskSummaryResponse | None = None
    detail_text: str | None = None
    plan: list[dict] = Field(default_factory=list)
    error: str | None = None


class UiTaskCancelRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None


class UiTaskCancelResponse(BaseModel):
    ok: bool
    status: str | None = None
    message: str | None = None
    error: str | None = None


class UiApprovalItemResponse(BaseModel):
    token: str
    tool_name: str
    source_type: str
    source_ref: str | None = None
    step_id: str | None = None
    created_at: str | None = None
    expires_at: str | None = None


class UiApprovalsPendingResponse(BaseModel):
    ok: bool
    approvals: list[UiApprovalItemResponse] = Field(default_factory=list)
    error: str | None = None


# --- Direct API endpoint (for testing without Telegram) ---
class ChatRequest(BaseModel):
    chat_id: str
    message: str
    username: str = "api_user"
    agent_key: str | None = None


class ApprovalDecisionRequest(BaseModel):
    chat_id: str
    token: str
    approve: bool = True
    username: str = "api_user"
    agent_key: str | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# UI endpoints
# ---------------------------------------------------------------------------

@router.get("/ui/me", response_model=UiMeResponse)
def ui_me_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        user, owner_id, normalized_chat_id = resolve_ui_user_context(
            db, chat_id, username, agent_key=agent_key
        )
    except ValueError as exc:
        return UiMeResponse(ok=False, error=str(exc))

    identity = load_identity(db, owner_id)
    identity_summary = None
    if identity:
        identity_summary = {
            "agent_uuid": identity.get("agent_uuid"),
            "origin_statement": truncate_text(str(identity.get("origin_statement") or ""), 500),
            "core_values": list(identity.get("core_values") or []),
            "authority_bounds": dict(identity.get("authority_bounds") or {}),
        }

    return UiMeResponse(
        ok=True,
        owner_id=owner_id,
        username=user.username,
        chat_id=normalized_chat_id,
        identity_summary=identity_summary,
    )


@router.get("/ui/tasks", response_model=UiTasksListResponse)
def ui_tasks_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiTasksListResponse(ok=False, error=str(exc))

    rows = list_recent_tasks(db, owner_id, limit=clamp_int(limit, 1, 100, 20))
    payload = [UiTaskSummaryResponse(**serialize_task_summary(row)) for row in rows]
    return UiTasksListResponse(ok=True, tasks=payload)


@router.post("/ui/tasks", response_model=UiTaskCreateResponse)
def ui_task_create_endpoint(req: UiTaskCreateRequest, db: Session = Depends(get_db)):
    title = truncate_text(str(req.title or "").strip(), 140)
    goal = truncate_text(str(req.goal or "").strip(), 6000)
    if not title or not goal:
        return UiTaskCreateResponse(ok=False, error="Both title and goal are required.")

    try:
        _, owner_id, _ = resolve_ui_user_context(
            db, req.chat_id, req.username, agent_key=req.agent_key
        )
    except ValueError as exc:
        return UiTaskCreateResponse(ok=False, error=str(exc))

    task, created_new = create_queued_task(db, owner_id, title, goal)
    if created_new:
        enqueue_task(task.id)
        message = f"Task #{task.id} created and queued."
    else:
        message = f"Duplicate detected, reusing task #{task.id} ({task.status})."

    return UiTaskCreateResponse(
        ok=True,
        task_id=int(task.id),
        created_new=bool(created_new),
        status=task.status,
        message=message,
    )


@router.get("/ui/tasks/{task_id}", response_model=UiTaskDetailResponse)
def ui_task_detail_endpoint(
    task_id: int,
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiTaskDetailResponse(ok=False, error=str(exc))

    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return UiTaskDetailResponse(ok=False, error=f"Task #{task_id} not found.")

    return UiTaskDetailResponse(
        ok=True,
        task=UiTaskSummaryResponse(**serialize_task_summary(task)),
        detail_text=format_task_details(task),
        plan=normalize_task_plan(task.plan),
    )


@router.post("/ui/tasks/{task_id}/cancel", response_model=UiTaskCancelResponse)
def ui_task_cancel_endpoint(task_id: int, req: UiTaskCancelRequest, db: Session = Depends(get_db)):
    try:
        _, owner_id, _ = resolve_ui_user_context(
            db, req.chat_id, req.username, agent_key=req.agent_key
        )
    except ValueError as exc:
        return UiTaskCancelResponse(ok=False, error=str(exc))

    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return UiTaskCancelResponse(ok=False, error=f"Task #{task_id} not found.")

    ok, message = cancel_task(db, task)
    return UiTaskCancelResponse(
        ok=bool(ok),
        status=task.status,
        message=message,
        error=None if ok else message,
    )


@router.get("/ui/approvals/pending", response_model=UiApprovalsPendingResponse)
def ui_pending_approvals_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiApprovalsPendingResponse(ok=False, error=str(exc))

    approvals = list_pending_approvals_for_owner(db, owner_id, limit=limit)
    payload = [UiApprovalItemResponse(**item) for item in approvals]
    return UiApprovalsPendingResponse(ok=True, approvals=payload)


@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    req_payload = req.model_dump()
    ok_req, err_req = protocol_validate_payload("chat.request", req_payload, direction="request")
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=req.chat_id,
        username=req.username,
        text=req.message,
        source="api",
        expect_response=True,
    )
    if result.get("ok"):
        response_payload = {"ok": True, "response": result.get("response", "")}
        protocol_validate_payload("chat.response", response_payload, direction="response")
        return response_payload
    response_payload = {"ok": False, "error": result.get("error", "Unknown error")}
    protocol_validate_payload("chat.response", response_payload, direction="response")
    return response_payload


@router.post("/approval/decision")
async def approval_decision_endpoint(req: ApprovalDecisionRequest):
    req_payload = req.model_dump()
    ok_req, err_req = protocol_validate_payload(
        "approval.decision.request", req_payload, direction="request"
    )
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = approval_manager_decide_token(
        owner_id=owner_id,
        token=req.token,
        approve=bool(req.approve),
        reason=req.reason,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Failed to process approval decision.")}

    token_owner_id = int(result.get("owner_id") or owner_id)
    if result.get("status") == "approved":
        payload = _safe_json_dict(result.get("resume_payload"), {})
        kind = str(payload.get("kind") or "")
        if kind == "task_step":
            task_id = int(payload.get("task_id") or 0)
            step_id = str(payload.get("step_id") or "") or None
            ok, msg = unpause_task_after_approval(
                owner_id=token_owner_id, task_id=task_id, step_id=step_id
            )
            return {"ok": ok, "status": result.get("status"), "message": msg}
        if kind == "chat_message":
            user_message = str(payload.get("user_message") or "").strip()
            if user_message:
                await dispatch_incoming_message(
                    owner_id=token_owner_id,
                    chat_id=req.chat_id,
                    username=req.username,
                    text=user_message,
                    source="api",
                    expect_response=False,
                )
                return {"ok": True, "status": result.get("status"), "resumed": "chat_message"}
    return {"ok": True, "status": result.get("status"), "token": result.get("token")}


# ---------------------------------------------------------------------------
# UI static asset serving
# ---------------------------------------------------------------------------

@router.get("/ui", include_in_schema=False)
@router.get("/ui/", include_in_schema=False)
def ui_root():
    _, _, ready = ui_dist_ready()
    if not ready:
        return ui_not_built_response()
    entry = resolve_ui_asset_path("")
    if entry is None:
        return ui_not_built_response()
    return FileResponse(str(entry))


@router.get("/ui/{path:path}", include_in_schema=False)
def ui_assets(path: str):
    _, _, ready = ui_dist_ready()
    if not ready:
        return ui_not_built_response()

    asset = resolve_ui_asset_path(path)
    if asset is None:
        raise HTTPException(status_code=404, detail="UI asset not found.")
    return FileResponse(str(asset))

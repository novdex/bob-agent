from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ._shared import (
    SessionLocal,
    get_db,
    require_ops_auth,
    resolve_owner_id,
    resolve_owner_context,
    resolve_root_ui_user_context,
    resolve_ui_user_context,
    resolve_team_agent_owner_for_request,
    get_team_agent_with_user,
    serialize_team_agent,
    list_team_agents_for_owner,
    _resolve_identity_owner,
    _ensure_team_agent_owner,
    _upsert_identity_link,
    normalize_agent_key,
    team_spawn_policy_allows,
    TEAM_MODE_ENABLED,
    TEAM_AGENT_DEFAULT_KEY,
    TEAM_BROADCAST_ENABLED,
    IDENTITY_SCOPE_MODE,
    WORKFLOW_V2_ENABLED,
    WORKFLOW_LOOP_MAX_ITERATIONS,
    WORKFLOW_MAX_STEPS,
    RUNTIME_STATE,
    IdentityLink,
    ConversationMessage,
    WorkflowProgram,
    HostExecGrant,
    create_host_exec_grant,
    memory_vault_bootstrap,
    memory_vault_backup,
    memory_vault_restore,
    parse_workflow_program_text,
    _workflow_render_template,
    _workflow_eval_condition,
    _count_workflow_actions,
    create_queued_task,
    enqueue_task,
    dispatch_incoming_message,
    list_context_snapshots,
    get_context_snapshot,
    iso_datetime_or_none,
    truncate_text,
    clamp_int,
    _safe_json_list,
)

router = APIRouter()


class IdentityLinkRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    target_chat_id: str
    target_username: str | None = None


@router.post("/identity/link")
def identity_link_endpoint(req: IdentityLinkRequest, db: Session = Depends(get_db)):
    root_owner, _, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    target_chat = str(req.target_chat_id or "").strip()
    if not target_chat:
        return {"ok": False, "error": "target_chat_id is required."}
    _upsert_identity_link(
        db=db,
        canonical_owner_id=int(root_owner.id),
        linked_chat_id=target_chat,
        linked_username=req.target_username,
        scope_mode="linked_explicit",
    )
    return {
        "ok": True,
        "canonical_owner_id": int(root_owner.id),
        "linked_chat_id": target_chat,
        "scope_mode": "linked_explicit",
    }


@router.get("/identity/links")
def identity_links_endpoint(
    chat_id: str, username: str = "api_user", db: Session = Depends(get_db)
):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    rows = (
        db.query(IdentityLink)
        .filter(IdentityLink.canonical_owner_id == int(root_owner_id))
        .order_by(IdentityLink.id.asc())
        .all()
    )
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "scope_mode": IDENTITY_SCOPE_MODE,
        "links": [
            {
                "linked_chat_id": str(row.linked_chat_id),
                "linked_username": row.linked_username,
                "scope_mode": row.scope_mode,
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ],
    }


@router.get("/context/list")
def context_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    items = list_context_snapshots(ctx["owner_id"], limit=limit)
    return {"ok": True, "owner_id": ctx["owner_id"], "agent_key": ctx["agent_key"], "items": items}


@router.get("/context/detail")
def context_detail_endpoint(
    chat_id: str,
    snapshot_id: int,
    username: str = "api_user",
    agent_key: str | None = None,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    item = get_context_snapshot(ctx["owner_id"], snapshot_id)
    if not item:
        return {"ok": False, "error": f"Snapshot #{snapshot_id} not found."}
    return {"ok": True, "snapshot": item}


@router.get("/context/json")
def context_json_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 5,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    items = list_context_snapshots(ctx["owner_id"], limit=limit)
    detailed: list[dict] = []
    for row in items:
        item = get_context_snapshot(ctx["owner_id"], int(row.get("snapshot_id", 0)))
        if item:
            detailed.append(item)
    return {
        "ok": True,
        "owner_id": ctx["owner_id"],
        "agent_key": ctx["agent_key"],
        "count": len(detailed),
        "snapshots": detailed,
    }


class TeamAgentSpawnRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    display_name: str | None = None


class TeamAgentSendRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    message: str
    expect_response: bool = True


class TeamAgentStopRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    stop: bool = True


@router.post("/agents/spawn")
def team_agent_spawn_endpoint(req: TeamAgentSpawnRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    if not TEAM_MODE_ENABLED:
        return {"ok": False, "error": "Team mode is disabled."}
    key = normalize_agent_key(req.agent_key)
    if key == TEAM_AGENT_DEFAULT_KEY:
        return {
            "ok": False,
            "error": f"'{TEAM_AGENT_DEFAULT_KEY}' is reserved for the primary agent.",
        }
    if not team_spawn_policy_allows(TEAM_AGENT_DEFAULT_KEY, key):
        return {"ok": False, "error": f"Spawn policy blocked creation of '{key}'."}
    user = _ensure_team_agent_owner(db, root_owner, key, display_name=req.display_name)
    row, _ = get_team_agent_with_user(db, root_owner_id, key)
    if row is None:
        return {"ok": False, "error": "Failed to create team agent."}
    row.status = "active"
    row.last_seen_at = datetime.utcnow()
    if req.display_name:
        row.display_name = truncate_text(str(req.display_name), 80)
    db.commit()
    return {"ok": True, "agent": serialize_team_agent(row, user)}


@router.get("/agents/list")
def team_agent_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    include_stopped: bool = True,
    db: Session = Depends(get_db),
):
    _, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    payload = list_team_agents_for_owner(db, root_owner_id, include_stopped=bool(include_stopped))
    return {"ok": True, "count": len(payload), "agents": payload}


@router.post("/agents/send")
async def team_agent_send_endpoint(req: TeamAgentSendRequest, db: Session = Depends(get_db)):
    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
        db=db,
        chat_id=req.chat_id,
        username=req.username,
        agent_key=req.agent_key,
        create_if_missing=False,
        require_active=True,
    )
    text = truncate_text(str(req.message or "").strip(), 6000)
    if not text:
        return {"ok": False, "error": "message is required."}
    result = await dispatch_incoming_message(
        owner_id=int(agent_user.id),
        chat_id=req.chat_id,
        username=str(agent_user.username or req.username),
        text=text,
        source="api",
        expect_response=bool(req.expect_response),
    )
    return {
        "ok": bool(result.get("ok", False)),
        "agent_key": normalize_agent_key(req.agent_key),
        "owner_id": int(agent_user.id),
        **result,
    }


@router.get("/agents/log")
def team_agent_log_endpoint(
    chat_id: str,
    agent_key: str,
    username: str = "api_user",
    limit: int = 40,
    db: Session = Depends(get_db),
):
    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
        db=db,
        chat_id=chat_id,
        username=username,
        agent_key=agent_key,
        create_if_missing=False,
        require_active=False,
    )
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.owner_id == int(agent_user.id))
        .order_by(ConversationMessage.id.desc())
        .limit(clamp_int(limit, 1, 200, 40))
        .all()
    )
    rows.reverse()
    items = []
    for row in rows:
        items.append(
            {
                "id": int(row.id),
                "role": row.role,
                "content": truncate_text(str(row.content or ""), 2400),
                "tool_call_id": row.tool_call_id,
                "created_at": iso_datetime_or_none(row.created_at),
            }
        )
    return {
        "ok": True,
        "agent_key": normalize_agent_key(agent_key),
        "count": len(items),
        "items": items,
    }


@router.post("/agents/stop")
def team_agent_stop_endpoint(req: TeamAgentStopRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    key = normalize_agent_key(req.agent_key)
    row, user = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        return {"ok": False, "error": f"Agent '{key}' not found."}
    row.status = "stopped" if bool(req.stop) else "active"
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "agent": serialize_team_agent(row, user), "owner_id": int(root_owner.id)}


@router.get("/team/presence")
def team_presence_endpoint(chat_id: str, username: str = "api_user", db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    agents = list_team_agents_for_owner(db, root_owner_id, include_stopped=True)
    active = [row for row in agents if row.get("status") == "active"]
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "team_mode_enabled": bool(TEAM_MODE_ENABLED),
        "active_agents": len(active),
        "total_agents": len(agents),
        "agents": agents,
    }


class TeamBroadcastRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    message: str
    include_main: bool = False


@router.post("/team/broadcast")
async def team_broadcast_endpoint(req: TeamBroadcastRequest, db: Session = Depends(get_db)):
    if not TEAM_BROADCAST_ENABLED:
        return {"ok": False, "error": "Team broadcast is disabled."}
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    message = truncate_text(str(req.message or "").strip(), 6000)
    if not message:
        return {"ok": False, "error": "message is required."}
    agents = list_team_agents_for_owner(db, root_owner_id, include_stopped=False)
    targets = list(agents)
    if req.include_main:
        targets.insert(
            0,
            {
                "agent_key": TEAM_AGENT_DEFAULT_KEY,
                "agent_owner_id": int(root_owner.id),
                "username": root_owner.username,
                "status": "active",
            },
        )
    responses = []
    for target in targets:
        if target.get("status") != "active":
            continue
        target_owner_id = int(target.get("agent_owner_id") or root_owner.id)
        result = await dispatch_incoming_message(
            owner_id=target_owner_id,
            chat_id=req.chat_id,
            username=str(target.get("username") or req.username),
            text=message,
            source="api",
            expect_response=True,
        )
        responses.append(
            {
                "agent_key": target.get("agent_key"),
                "owner_id": target_owner_id,
                "ok": bool(result.get("ok", False)),
                "response": truncate_text(str(result.get("response") or ""), 2000),
                "error": result.get("error"),
            }
        )
    RUNTIME_STATE["team_broadcasts_total"] = int(RUNTIME_STATE.get("team_broadcasts_total", 0)) + 1
    return {"ok": True, "count": len(responses), "responses": responses}


class HostExecGrantRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    node_name: str = "local"
    command_prefix: str
    ttl_minutes: int | None = None


@router.post("/ops/host_exec/grant")
def host_exec_grant_endpoint(req: HostExecGrantRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    prefix = truncate_text(str(req.command_prefix or "").strip().lower(), 80)
    if not prefix:
        return {"ok": False, "error": "command_prefix is required."}
    return create_host_exec_grant(
        owner_id=owner_id,
        node_name=req.node_name,
        command_prefix=prefix,
        created_by="ops_api",
        ttl_minutes=req.ttl_minutes,
    )


@router.get("/ops/host_exec/grants")
def host_exec_grants_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    db = SessionLocal()
    try:
        rows = (
            db.query(HostExecGrant)
            .filter((HostExecGrant.owner_id == int(owner_id)) | (HostExecGrant.owner_id.is_(None)))
            .order_by(HostExecGrant.id.desc())
            .limit(clamp_int(limit, 1, 200, 20))
            .all()
        )
        items = [
            {
                "token": row.token,
                "owner_id": row.owner_id,
                "node_name": row.node_name,
                "command_prefix": row.command_prefix,
                "status": row.status,
                "expires_at": iso_datetime_or_none(row.expires_at),
                "consumed_at": iso_datetime_or_none(row.consumed_at),
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ]
        return {"ok": True, "count": len(items), "items": items}
    finally:
        db.close()


class MemoryVaultRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    message: str | None = None
    ref: str | None = None


@router.post("/vault/bootstrap")
def vault_bootstrap_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_bootstrap(owner_id)


@router.post("/vault/backup")
def vault_backup_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_backup(owner_id, message=str(req.message or "vault backup"))


@router.post("/vault/restore")
def vault_restore_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_restore(owner_id, ref=str(req.ref or "HEAD"))


class WorkflowProgramRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    name: str
    body: str


class WorkflowRunRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    name: str | None = None
    body: str | None = None


@router.post("/workflow/programs")
def workflow_program_upsert_endpoint(req: WorkflowProgramRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    name = truncate_text(str(req.name or "").strip().lower(), 80)
    if not name:
        return {"ok": False, "error": "name is required."}
    body = str(req.body or "")
    try:
        parse_workflow_program_text(body)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    row = (
        db.query(WorkflowProgram)
        .filter(
            WorkflowProgram.owner_id == int(root_owner_id),
            WorkflowProgram.name == name,
        )
        .first()
    )
    if row:
        row.body_text = body
    else:
        row = WorkflowProgram(owner_id=int(root_owner_id), name=name, body_text=body)
        db.add(row)
    db.commit()
    RUNTIME_STATE["workflow_programs_total"] = int(
        db.query(WorkflowProgram).filter(WorkflowProgram.owner_id == int(root_owner_id)).count()
    )
    return {"ok": True, "owner_id": int(root_owner.id), "name": name}


@router.get("/workflow/programs")
def workflow_program_list_endpoint(
    chat_id: str, username: str = "api_user", db: Session = Depends(get_db)
):
    _, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    rows = (
        db.query(WorkflowProgram)
        .filter(WorkflowProgram.owner_id == int(root_owner_id))
        .order_by(WorkflowProgram.id.asc())
        .all()
    )
    return {
        "ok": True,
        "count": len(rows),
        "programs": [
            {
                "name": row.name,
                "created_at": iso_datetime_or_none(row.created_at),
                "updated_at": iso_datetime_or_none(row.updated_at),
                "preview": truncate_text(row.body_text or "", 300),
            }
            for row in rows
        ],
    }


@router.post("/workflow/run")
async def workflow_run_endpoint(req: WorkflowRunRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    body = str(req.body or "").strip()
    if not body:
        name = truncate_text(str(req.name or "").strip().lower(), 80)
        row = (
            db.query(WorkflowProgram)
            .filter(
                WorkflowProgram.owner_id == int(root_owner_id),
                WorkflowProgram.name == name,
            )
            .first()
        )
        if not row:
            return {"ok": False, "error": "Workflow program not found."}
        body = row.body_text or ""
    try:
        steps = parse_workflow_program_text(body)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    events: list[dict] = []
    event_no = 0
    v2_used = False
    variables: dict[str, str] = {
        "owner_id": str(root_owner.id),
        "chat_id": str(req.chat_id),
        "username": str(req.username or "api_user"),
    }

    def next_event_no() -> int:
        nonlocal event_no
        event_no += 1
        return event_no

    async def run_steps(step_list: list[dict], depth: int = 0):
        nonlocal v2_used
        if depth > 8:
            raise ValueError("Workflow nesting depth is too high.")
        for step in step_list:
            kind = str(step.get("kind") or "").strip().lower()
            if kind == "set":
                v2_used = True
                key = str(step.get("name") or "").strip()
                value = _workflow_render_template(str(step.get("value") or ""), variables)
                variables[key] = value
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "set",
                        "name": key,
                        "value": truncate_text(value, 240),
                        "ok": True,
                    }
                )
                continue
            if kind == "if":
                v2_used = True
                condition = str(step.get("condition") or "")
                try:
                    matched = bool(_workflow_eval_condition(condition, variables))
                except Exception as exc:
                    events.append(
                        {
                            "step": next_event_no(),
                            "kind": "if",
                            "condition": condition,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
                    continue
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "if",
                        "condition": condition,
                        "matched": matched,
                        "ok": True,
                    }
                )
                if matched:
                    await run_steps(_safe_json_list(step.get("steps"), []), depth=depth + 1)
                continue
            if kind == "loop":
                v2_used = True
                iterations = clamp_int(step.get("count"), 1, WORKFLOW_LOOP_MAX_ITERATIONS, 1)
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "loop",
                        "iterations": int(iterations),
                        "ok": True,
                    }
                )
                for idx in range(iterations):
                    variables["loop_index"] = str(idx + 1)
                    variables["loop_count"] = str(iterations)
                    await run_steps(_safe_json_list(step.get("steps"), []), depth=depth + 1)
                variables.pop("loop_index", None)
                variables.pop("loop_count", None)
                continue
            if kind == "sleep":
                seconds = float(step.get("seconds") or 0.0)
                await asyncio.sleep(seconds)
                events.append(
                    {"step": next_event_no(), "kind": "sleep", "seconds": seconds, "ok": True}
                )
                continue
            if kind == "task":
                key = normalize_agent_key(
                    _workflow_render_template(str(step.get("agent_key") or ""), variables)
                )
                title = _workflow_render_template(str(step.get("title") or ""), variables)
                goal = _workflow_render_template(str(step.get("goal") or ""), variables)
                _, owner_user, _, _ = resolve_team_agent_owner_for_request(
                    db=db,
                    chat_id=req.chat_id,
                    username=req.username,
                    agent_key=key,
                    create_if_missing=True,
                    require_active=True,
                )
                task, created_new = create_queued_task(
                    db,
                    int(owner_user.id),
                    truncate_text(title, 140),
                    truncate_text(goal, 6000),
                )
                if created_new:
                    enqueue_task(int(task.id))
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "task",
                        "agent_key": key,
                        "task_id": int(task.id),
                        "created_new": bool(created_new),
                        "ok": True,
                    }
                )
                continue
            if kind in {"send", "broadcast"}:
                message = _workflow_render_template(str(step.get("message") or ""), variables)
                if kind == "broadcast":
                    team_rows = list_team_agents_for_owner(
                        db, int(root_owner_id), include_stopped=False
                    )
                    targets = [normalize_agent_key(row.get("agent_key")) for row in team_rows]
                    if not targets:
                        targets = [TEAM_AGENT_DEFAULT_KEY]
                else:
                    targets = [
                        normalize_agent_key(
                            _workflow_render_template(str(step.get("agent_key") or ""), variables)
                        )
                    ]
                for target_key in targets:
                    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
                        db=db,
                        chat_id=req.chat_id,
                        username=req.username,
                        agent_key=target_key,
                        create_if_missing=True,
                        require_active=True,
                    )
                    result = await dispatch_incoming_message(
                        owner_id=int(agent_user.id),
                        chat_id=req.chat_id,
                        username=str(agent_user.username or req.username),
                        text=truncate_text(message, 4000),
                        source="api",
                        expect_response=True,
                    )
                    events.append(
                        {
                            "step": next_event_no(),
                            "kind": kind,
                            "agent_key": target_key,
                            "ok": bool(result.get("ok", False)),
                            "response": truncate_text(str(result.get("response") or ""), 1200),
                            "error": result.get("error"),
                        }
                    )
                continue
            events.append(
                {"step": next_event_no(), "kind": kind, "ok": False, "error": "Unsupported step"}
            )

    try:
        await run_steps(steps, depth=0)
    except Exception as exc:
        return {"ok": False, "error": truncate_text(str(exc), 240), "events": events}

    RUNTIME_STATE["workflow_runs_total"] = int(RUNTIME_STATE.get("workflow_runs_total", 0)) + 1
    if v2_used:
        RUNTIME_STATE["workflow_v2_runs"] = int(RUNTIME_STATE.get("workflow_v2_runs", 0)) + 1
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "steps": int(_count_workflow_actions(steps)),
        "workflow_v2_used": bool(v2_used),
        "events": events,
    }

"""Node control-plane routes."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ._shared import (
    NODE_AUTO_CAPABILITY_DEFAULT,
    NODE_CONTROL_LOCK,
    NODE_CONTROL_PLANE_ENABLED,
    NODE_HEARTBEAT_MAP,
    NODE_SCHEDULER_FAILURE_PENALTY,
    NODE_SCHEDULER_FAILURE_WINDOW_SECONDS,
    NODE_SCHEDULER_LATENCY_PENALTY,
    NODE_SCHEDULER_LEASE_PENALTY,
    NODE_SCHEDULER_RECOVERY_BONUS,
    NodeLease,
    NodeRegistration,
    SessionLocal,
    _candidate_node_scores,
    _normalize_capability_list,
    _refresh_node_runtime_metrics,
    apply_url_safety_guard,
    claim_node_lease,
    cleanup_expired_node_leases,
    clamp_int,
    iso_datetime_or_none,
    load_remote_node_registry,
    release_node_lease,
    require_ops_auth,
    resolve_owner_id,
    tool_list_execution_nodes,
    truncate_text,
)

router = APIRouter()


class NodeRegisterRequest(BaseModel):
    node_name: str
    base_url: str
    auth_token: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True


class NodeHeartbeatRequest(BaseModel):
    node_name: str
    healthy: bool = True
    last_error: str | None = None


class NodeLeaseClaimRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    capability: str = "general"
    node_name: str | None = None
    ttl_seconds: int | None = None


class NodeLeaseReleaseRequest(BaseModel):
    lease_token: str


@router.get("/nodes")
def list_nodes_endpoint(_ops=Depends(require_ops_auth)):
    return tool_list_execution_nodes()


@router.post("/nodes/register")
def node_register_endpoint(req: NodeRegisterRequest, _ops=Depends(require_ops_auth)):
    if not NODE_CONTROL_PLANE_ENABLED:
        return {"ok": False, "error": "Node control-plane is disabled."}
    name = str(req.node_name or "").strip().lower()
    base_url = str(req.base_url or "").strip().rstrip("/")
    if not name or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", name):
        return {"ok": False, "error": "Invalid node_name."}
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        return {"ok": False, "error": "base_url must start with http:// or https://"}
    safe_ok, safe_reason = apply_url_safety_guard(base_url, source=f"node_register:{name}")
    if not safe_ok:
        return {"ok": False, "error": safe_reason}
    capabilities = _normalize_capability_list(req.capabilities)
    db = SessionLocal()
    try:
        row = db.query(NodeRegistration).filter(NodeRegistration.node_name == name).first()
        if row is None:
            row = NodeRegistration(node_name=name, base_url=base_url)
            db.add(row)
        row.base_url = base_url
        row.auth_token = truncate_text(str(req.auth_token or "").strip(), 240) or None
        row.capabilities_json = json.dumps(capabilities, ensure_ascii=False)
        row.enabled = 1 if bool(req.enabled) else 0
        row.last_error = None
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 260)}
    finally:
        db.close()
    load_remote_node_registry()
    return {
        "ok": True,
        "node_name": name,
        "enabled": bool(req.enabled),
        "capabilities": capabilities,
        "source": "control_plane",
    }


@router.post("/nodes/heartbeat")
def node_heartbeat_endpoint(req: NodeHeartbeatRequest, _ops=Depends(require_ops_auth)):
    if not NODE_CONTROL_PLANE_ENABLED:
        return {"ok": False, "error": "Node control-plane is disabled."}
    name = str(req.node_name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "node_name is required."}
    heartbeat_at = datetime.utcnow()
    db = SessionLocal()
    try:
        row = db.query(NodeRegistration).filter(NodeRegistration.node_name == name).first()
        if row is None:
            return {"ok": False, "error": f"Node '{name}' is not registered."}
        row.last_heartbeat_at = heartbeat_at
        row.last_error = truncate_text(str(req.last_error or "").strip(), 500) or None
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 260)}
    finally:
        db.close()
    with NODE_CONTROL_LOCK:
        NODE_HEARTBEAT_MAP[name] = {
            "last_heartbeat_at": heartbeat_at.replace(tzinfo=timezone.utc).isoformat(),
            "healthy": bool(req.healthy),
            "last_error": truncate_text(str(req.last_error or "").strip(), 220) or None,
        }
    load_remote_node_registry()
    return {"ok": True, "node_name": name, "healthy": bool(req.healthy)}


@router.get("/nodes/control_plane")
def node_control_plane_status_endpoint(
    limit: int = 50,
    capability: str | None = None,
    preferred_node: str | None = None,
    _ops=Depends(require_ops_auth),
):
    db = SessionLocal()
    try:
        cleanup_expired_node_leases(db)
        db.commit()
        rows = (
            db.query(NodeLease)
            .order_by(NodeLease.id.desc())
            .limit(clamp_int(limit, 1, 500, 50))
            .all()
        )
        leases = [
            {
                "lease_token": row.lease_token,
                "node_name": row.node_name,
                "owner_id": row.owner_id,
                "capability": row.capability,
                "status": row.status,
                "expires_at": iso_datetime_or_none(row.expires_at),
                "released_at": iso_datetime_or_none(row.released_at),
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ]
    finally:
        db.close()
    required_capability = str(capability or "").strip().lower()
    candidate_scores = _candidate_node_scores(
        capability=required_capability or NODE_AUTO_CAPABILITY_DEFAULT,
        preferred_node=preferred_node,
    )
    candidate_map = {
        str(item.get("node_name")): float(item.get("score", 0.0)) for item in candidate_scores
    }
    nodes_payload = tool_list_execution_nodes().get("nodes", [])
    for row in nodes_payload:
        node_name = str(row.get("name") or "")
        row["scheduler_score"] = candidate_map.get(node_name)
    _refresh_node_runtime_metrics()
    return {
        "ok": True,
        "enabled": bool(NODE_CONTROL_PLANE_ENABLED),
        "nodes": nodes_payload,
        "leases": leases,
        "lease_count": len(leases),
        "recommended_node": candidate_scores[0]["node_name"] if candidate_scores else None,
        "scheduler": {
            "capability": required_capability or None,
            "preferred_node": str(preferred_node or "").strip().lower() or None,
            "lease_penalty": float(NODE_SCHEDULER_LEASE_PENALTY),
            "failure_penalty": float(NODE_SCHEDULER_FAILURE_PENALTY),
            "latency_penalty": float(NODE_SCHEDULER_LATENCY_PENALTY),
            "recovery_bonus": float(NODE_SCHEDULER_RECOVERY_BONUS),
            "failure_window_seconds": int(NODE_SCHEDULER_FAILURE_WINDOW_SECONDS),
            "candidates": [
                {
                    "node_name": str(item.get("node_name")),
                    "score": float(item.get("score", 0.0)),
                    "healthy": bool(item.get("healthy", False)),
                    "exact_capability": bool(item.get("exact_capability", False)),
                    "lease_count": int(item.get("lease_count", 0)),
                    "stats": item.get("stats", {}),
                }
                for item in candidate_scores
            ],
        },
    }


@router.post("/nodes/lease/claim")
def node_lease_claim_endpoint(req: NodeLeaseClaimRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    capability = (
        str(req.capability or NODE_AUTO_CAPABILITY_DEFAULT).strip().lower()
        or NODE_AUTO_CAPABILITY_DEFAULT
    )
    node_name = str(req.node_name or "auto").strip().lower() or "auto"
    result = claim_node_lease(
        owner_id=owner_id,
        capability=capability,
        node_name=node_name,
        ttl_seconds=req.ttl_seconds,
    )
    return result


@router.post("/nodes/lease/release")
def node_lease_release_endpoint(req: NodeLeaseReleaseRequest, _ops=Depends(require_ops_auth)):
    return release_node_lease(req.lease_token)

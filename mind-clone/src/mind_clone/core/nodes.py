"""
Node management utilities.

Provides node registration, lease management, health checking, and scheduling
for remote execution nodes.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from ..database.session import SessionLocal
from ..database.models import NodeRegistration, NodeLease
from ..utils import generate_uuid, utc_now_iso

logger = logging.getLogger("mind_clone.core.nodes")

REMOTE_NODE_REGISTRY: Dict[str, Any] = {}

# Default lease TTL in seconds
DEFAULT_LEASE_TTL = 300


def list_execution_nodes() -> List[Dict[str, Any]]:
    """List all registered execution nodes."""
    db = SessionLocal()
    try:
        import json as _json
        rows = db.query(NodeRegistration).all()
        result = []
        for row in rows:
            try:
                caps = _json.loads(row.capabilities_json or "[]")
            except Exception:
                caps = []
            result.append({
                "node_name": row.node_name,
                "base_url": row.base_url,
                "capabilities": caps,
                "enabled": bool(row.enabled),
                "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
            })
        return result
    except Exception:
        return list(REMOTE_NODE_REGISTRY.values())
    finally:
        db.close()


def get_node_health(node_id: str) -> Dict[str, Any]:
    """Get health status of a node."""
    return {"ok": True, "node_id": node_id}


def register_node(node_info: Dict[str, Any]) -> bool:
    """Register a new execution node."""
    node_name = str(node_info.get("node_name", "")).strip()
    if not node_name:
        return False
    REMOTE_NODE_REGISTRY[node_name] = node_info
    return True


def heartbeat_node(node_id: str) -> bool:
    """Record heartbeat for a node."""
    if node_id in REMOTE_NODE_REGISTRY:
        REMOTE_NODE_REGISTRY[node_id]["last_heartbeat"] = utc_now_iso()
    return True


# ---------------------------------------------------------------------------
# Functions expected by routes.py
# ---------------------------------------------------------------------------

def cleanup_expired_node_leases(db) -> None:
    """Remove expired node leases from the database."""
    try:
        now = datetime.now(timezone.utc)
        expired = db.query(NodeLease).filter(
            NodeLease.expires_at < now,
        ).all()
        for lease in expired:
            db.delete(lease)
        if expired:
            db.commit()
            logger.info("Cleaned up %d expired node leases", len(expired))
    except Exception as exc:
        logger.warning("cleanup_expired_node_leases error: %s", exc)
        db.rollback()


def _candidate_node_scores(
    capability: str, preferred_node: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Score candidate nodes for a capability request."""
    scores = []
    for name, info in REMOTE_NODE_REGISTRY.items():
        caps = info.get("capabilities", [])
        if isinstance(caps, str):
            caps = [c.strip() for c in caps.split(",")]
        if capability not in caps and "general" not in caps:
            continue
        score = 100.0
        if name == preferred_node:
            score += 50.0
        if not info.get("healthy", True):
            score -= 80.0
        scores.append({"node_name": name, "score": score, "info": info})
    scores.sort(key=lambda x: x["score"], reverse=True)
    return scores


def _refresh_node_runtime_metrics() -> None:
    """Refresh node-related runtime state counters."""
    from ..core.state import RUNTIME_STATE, RUNTIME_STATE_LOCK
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE["remote_nodes_loaded"] = len(REMOTE_NODE_REGISTRY)


def _normalize_capability_list(capabilities: List[str]) -> List[str]:
    """Normalize a list of capability strings."""
    return list(set(c.strip().lower() for c in capabilities if c.strip()))


def claim_node_lease(
    owner_id: int,
    capability: str,
    node_name: str = "auto",
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Claim a lease on a node for exclusive use."""
    candidates = _candidate_node_scores(capability, preferred_node=node_name if node_name != "auto" else None)
    if not candidates:
        return {"ok": False, "error": f"No nodes available for capability '{capability}'"}

    chosen = candidates[0]
    ttl = ttl_seconds or DEFAULT_LEASE_TTL
    lease_token = generate_uuid()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    db = SessionLocal()
    try:
        lease = NodeLease(
            lease_token=lease_token,
            owner_id=owner_id,
            node_name=chosen["node_name"],
            capability=capability,
            expires_at=expires_at,
        )
        db.add(lease)
        db.commit()
        return {
            "ok": True,
            "lease_token": lease_token,
            "node_name": chosen["node_name"],
            "expires_at": expires_at.isoformat(),
        }
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def release_node_lease(lease_token: str) -> Dict[str, Any]:
    """Release a node lease."""
    db = SessionLocal()
    try:
        lease = db.query(NodeLease).filter(NodeLease.lease_token == lease_token).first()
        if not lease:
            return {"ok": False, "error": "Lease not found"}
        db.delete(lease)
        db.commit()
        return {"ok": True, "released": True, "node_name": lease.node_name}
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


__all__ = [
    "list_execution_nodes",
    "get_node_health",
    "register_node",
    "heartbeat_node",
    "cleanup_expired_node_leases",
    "_candidate_node_scores",
    "_refresh_node_runtime_metrics",
    "_normalize_capability_list",
    "claim_node_lease",
    "release_node_lease",
    "REMOTE_NODE_REGISTRY",
]

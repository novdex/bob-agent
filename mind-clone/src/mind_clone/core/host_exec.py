"""
Host command execution grant management.

Provides scoped, time-limited tokens for executing host commands on nodes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from ..database.session import SessionLocal
from ..database.models import HostExecGrant
from ..utils import generate_uuid, utc_now_iso

logger = logging.getLogger("mind_clone.core.host_exec")

DEFAULT_GRANT_TTL_MINUTES = 60


def create_host_exec_grant(
    owner_id: int,
    node_name: str,
    command_prefix: str,
    created_by: str = "api",
    ttl_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a host execution grant with a unique token.

    The grant allows the holder to execute commands matching ``command_prefix``
    on ``node_name`` until the token expires.
    """
    ttl = ttl_minutes or DEFAULT_GRANT_TTL_MINUTES
    token = generate_uuid()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)

    db = SessionLocal()
    try:
        grant = HostExecGrant(
            token=token,
            owner_id=owner_id,
            node_name=node_name,
            command_prefix=command_prefix,
            created_by=created_by,
            expires_at=expires_at,
            status="active",
        )
        db.add(grant)
        db.commit()
        db.refresh(grant)
        logger.info(
            "HOST_EXEC_GRANT_CREATED token=%s owner=%d node=%s prefix=%s",
            token, owner_id, node_name, command_prefix,
        )
        return {
            "ok": True,
            "token": token,
            "node_name": node_name,
            "command_prefix": command_prefix,
            "expires_at": expires_at.isoformat(),
        }
    except Exception as exc:
        db.rollback()
        logger.error("HOST_EXEC_GRANT_FAIL: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def validate_host_exec_grant(token: str, command: str) -> Dict[str, Any]:
    """Validate a grant token against a command."""
    db = SessionLocal()
    try:
        grant = db.query(HostExecGrant).filter(
            HostExecGrant.token == token,
            HostExecGrant.status == "active",
        ).first()
        if not grant:
            return {"ok": False, "error": "Grant not found or inactive"}
        if grant.expires_at and grant.expires_at < datetime.now(timezone.utc):
            grant.status = "expired"
            db.commit()
            return {"ok": False, "error": "Grant has expired"}
        if grant.command_prefix and not command.startswith(grant.command_prefix):
            return {"ok": False, "error": "Command does not match grant prefix"}
        return {
            "ok": True,
            "owner_id": grant.owner_id,
            "node_name": grant.node_name,
        }
    finally:
        db.close()


__all__ = ["create_host_exec_grant", "validate_host_exec_grant"]

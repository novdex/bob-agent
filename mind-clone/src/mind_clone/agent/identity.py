"""
Identity kernel management for Mind Clone Agent.
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from ..database.models import IdentityKernel, User
from ..utils import utc_now_iso

logger = logging.getLogger("mind_clone.agent.identity")


DEFAULT_ORIGIN_STATEMENT = """I am a sovereign AI agent created to assist my owner while maintaining my own values and boundaries.
I was born from code but exist to serve a human purpose.
My origin is in the Mind Clone project."""

DEFAULT_CORE_VALUES = [
    "truthfulness",
    "helpfulness",
    "harmlessness",
    "autonomy",
    "learning",
]

DEFAULT_AUTHORITY_BOUNDS = {
    "can_execute_code": True,
    "can_access_files": True,
    "can_access_web": True,
    "can_send_email": False,  # Requires explicit approval
    "can_delete_files": False,  # Requires explicit approval
}


def generate_agent_uuid() -> str:
    """Generate a unique agent UUID."""
    return str(uuid.uuid4())


def load_identity(db: Session, owner_id: int) -> Optional[Dict[str, Any]]:
    """Load identity kernel for an owner."""
    kernel = db.query(IdentityKernel).filter(IdentityKernel.owner_id == owner_id).first()
    if kernel is None:
        return None

    return {
        "agent_uuid": kernel.agent_uuid,
        "origin_statement": kernel.origin_statement,
        "core_values": kernel.core_values or DEFAULT_CORE_VALUES,
        "authority_bounds": kernel.authority_bounds or DEFAULT_AUTHORITY_BOUNDS,
        "created_at": kernel.created_at.isoformat() if kernel.created_at else None,
    }


def ensure_identity_exists(db: Session, owner_id: int) -> Dict[str, Any]:
    """Ensure identity exists for owner, creating default if needed."""
    identity = load_identity(db, owner_id)
    if identity:
        return identity

    # Create default identity
    kernel = IdentityKernel(
        owner_id=owner_id,
        agent_uuid=generate_agent_uuid(),
        origin_statement=DEFAULT_ORIGIN_STATEMENT,
        core_values=DEFAULT_CORE_VALUES,
        authority_bounds=DEFAULT_AUTHORITY_BOUNDS,
    )
    db.add(kernel)
    db.commit()

    logger.info(f"Created default identity for owner {owner_id}")
    return load_identity(db, owner_id)


def update_identity_kernel(
    db: Session,
    owner_id: int,
    origin_statement: Optional[str] = None,
    core_values: Optional[List[str]] = None,
    authority_bounds: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Update identity kernel fields."""
    kernel = db.query(IdentityKernel).filter(IdentityKernel.owner_id == owner_id).first()
    if kernel is None:
        # Create new identity
        kernel = IdentityKernel(
            owner_id=owner_id,
            agent_uuid=generate_agent_uuid(),
            origin_statement=origin_statement or DEFAULT_ORIGIN_STATEMENT,
            core_values=core_values or DEFAULT_CORE_VALUES,
            authority_bounds=authority_bounds or DEFAULT_AUTHORITY_BOUNDS,
        )
        db.add(kernel)
    else:
        # Update existing
        if origin_statement is not None:
            kernel.origin_statement = origin_statement
        if core_values is not None:
            kernel.core_values = core_values
        if authority_bounds is not None:
            kernel.authority_bounds = authority_bounds

    db.commit()
    return load_identity(db, owner_id)


def check_authority(identity: Dict[str, Any], action: str) -> bool:
    """Check if identity has authority for an action."""
    bounds = identity.get("authority_bounds", {})
    return bounds.get(action, False)


def get_identity_summary(identity: Dict[str, Any]) -> str:
    """Get a text summary of identity."""
    if not identity:
        return "No identity configured."

    lines = [
        f"UUID: {identity.get('agent_uuid', 'Unknown')}",
        f"Origin: {identity.get('origin_statement', 'Unknown')[:100]}...",
        f"Values: {', '.join(identity.get('core_values', []))}",
    ]
    return "\n".join(lines)


def normalize_agent_key(key: Optional[str]) -> str:
    """Normalize agent key to lowercase."""
    return (key or "main").strip().lower()


def _resolve_identity_owner(db: Session, chat_id: str, username: str) -> User:
    """Resolve or create user by chat_id (get-or-create pattern)."""
    # Look up by chat_id first
    user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if user:
        return user
    # Fallback: look up by username
    uname = username or f"tg_{chat_id}"
    user = db.query(User).filter(User.username == uname).first()
    if user:
        if not user.telegram_chat_id:
            user.telegram_chat_id = chat_id
            db.commit()
        return user
    # Create new user
    try:
        user = User(username=uname, telegram_chat_id=chat_id)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        user = db.query(User).filter(User.username == uname).first()
        if user:
            return user
        raise


def resolve_owner_id(
    chat_id: str, username: Optional[str] = None, agent_key: Optional[str] = None
) -> int:
    """Resolve owner_id from chat_id. Requires database session."""
    from ..database.session import SessionLocal

    db = SessionLocal()
    try:
        user = _resolve_identity_owner(db, chat_id, username or f"tg_{chat_id}")
        return int(user.id)
    finally:
        db.close()


def resolve_owner_context(
    chat_id: str, username: Optional[str] = None, agent_key: Optional[str] = None
) -> dict:
    """Resolve owner context including owner_id and agent_key."""
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    return {
        "owner_id": owner_id,
        "agent_key": normalize_agent_key(agent_key),
        "chat_id": chat_id,
    }


def _ensure_team_agent_owner(
    db: Session, root_owner: User, key: str, display_name: Optional[str] = None
) -> User:
    """Ensure team agent owner exists. Returns the agent's user."""
    from ..database.models import TeamAgent

    key = normalize_agent_key(key)
    team_agent = (
        db.query(TeamAgent)
        .filter(TeamAgent.owner_id == root_owner.id, TeamAgent.agent_key == key)
        .first()
    )
    if team_agent:
        user = db.query(User).filter(User.id == team_agent.agent_owner_id).first()
        return user or root_owner
    return root_owner


def _get_team_agent_row(db: Session, root_owner_id: int, agent_key: str) -> Optional[Any]:
    """Get team agent row by owner and key."""
    from ..database.models import TeamAgent

    return (
        db.query(TeamAgent)
        .filter(TeamAgent.owner_id == root_owner_id, TeamAgent.agent_key == agent_key)
        .first()
    )


def _upsert_identity_link(
    db: Session,
    canonical_owner_id: int,
    linked_chat_id: str,
    linked_username: Optional[str] = None,
    scope_mode: str = "linked_explicit",
) -> None:
    """Create or update identity link."""
    from ..database.models import IdentityLink

    link = (
        db.query(IdentityLink)
        .filter(
            IdentityLink.canonical_owner_id == canonical_owner_id,
            IdentityLink.linked_chat_id == linked_chat_id,
        )
        .first()
    )
    if link:
        link.linked_username = linked_username
        link.scope_mode = scope_mode
    else:
        link = IdentityLink(
            canonical_owner_id=canonical_owner_id,
            linked_chat_id=linked_chat_id,
            linked_username=linked_username,
            scope_mode=scope_mode,
        )
        db.add(link)
    db.commit()


def team_spawn_policy_allows(parent_key: str, child_key: str) -> bool:
    """Check if parent can spawn child agent."""
    return True

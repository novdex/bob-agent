"""
Role-based authorization for multi-user and team features.

User roles: admin, user, viewer
Team roles: owner, admin, member, viewer

Permission matrix:
    admin  — full control, manage users, manage teams
    user   — normal access, use tools, create tasks, join teams
    viewer — read-only access, no tool execution, no task creation

Team permissions:
    owner  — full control of team, manage members, delete team
    admin  — manage members, manage team memory
    member — read/write shared memory, create team tasks
    viewer — read-only access to team resources
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger("mind_clone.core.authorization")

# Role hierarchy (higher index = more permissions)
USER_ROLE_HIERARCHY = ["viewer", "user", "admin"]
TEAM_ROLE_HIERARCHY = ["viewer", "member", "admin", "owner"]

# Permission definitions
_USER_PERMISSIONS: Dict[str, set] = {
    "admin": {
        "chat", "use_tools", "create_tasks", "manage_tasks",
        "create_teams", "manage_teams", "manage_users",
        "view_runtime", "manage_runtime", "use_codebase_tools",
    },
    "user": {
        "chat", "use_tools", "create_tasks", "manage_tasks",
        "create_teams", "view_runtime",
    },
    "viewer": {
        "chat", "view_runtime",
    },
}

_TEAM_PERMISSIONS: Dict[str, set] = {
    "owner": {
        "read_memory", "write_memory", "delete_memory",
        "manage_members", "manage_team", "delete_team",
        "create_team_tasks",
    },
    "admin": {
        "read_memory", "write_memory", "delete_memory",
        "manage_members", "create_team_tasks",
    },
    "member": {
        "read_memory", "write_memory", "create_team_tasks",
    },
    "viewer": {
        "read_memory",
    },
}


def check_user_permission(user_role: str, permission: str) -> bool:
    """Check if a user role has a specific permission."""
    role = (user_role or "user").lower()
    perms = _USER_PERMISSIONS.get(role, _USER_PERMISSIONS["user"])
    return permission in perms


def check_team_permission(team_role: str, permission: str) -> bool:
    """Check if a team role has a specific permission."""
    role = (team_role or "member").lower()
    perms = _TEAM_PERMISSIONS.get(role, _TEAM_PERMISSIONS["member"])
    return permission in perms


def user_role_at_least(user_role: str, minimum_role: str) -> bool:
    """Check if user role meets a minimum threshold."""
    try:
        current_idx = USER_ROLE_HIERARCHY.index(user_role.lower())
        min_idx = USER_ROLE_HIERARCHY.index(minimum_role.lower())
        return current_idx >= min_idx
    except ValueError:
        return False


def get_user_role(db: Session, owner_id: int) -> str:
    """Get the role for a user from the database."""
    from ..database.models import User
    user = db.query(User).filter(User.id == owner_id).first()
    if user:
        return getattr(user, "role", "user") or "user"
    return "user"


def get_team_role(db: Session, team_id: int, user_id: int) -> Optional[str]:
    """Get the team role for a user. Returns None if not a member."""
    from ..database.models import TeamMembership
    membership = db.query(TeamMembership).filter(
        TeamMembership.team_id == team_id,
        TeamMembership.user_id == user_id,
    ).first()
    if membership:
        return membership.role
    return None


def get_user_teams(db: Session, user_id: int) -> List[Dict]:
    """Get all teams a user belongs to."""
    from ..database.models import Team, TeamMembership
    memberships = (
        db.query(TeamMembership, Team)
        .join(Team, TeamMembership.team_id == Team.id)
        .filter(TeamMembership.user_id == user_id)
        .all()
    )
    return [
        {
            "team_id": team.id,
            "team_name": team.name,
            "role": membership.role,
        }
        for membership, team in memberships
    ]


def authorize_tool_use(db: Session, owner_id: int, tool_name: str) -> Tuple[bool, str]:
    """Check if a user is authorized to use a specific tool.

    Returns (allowed, reason).
    """
    role = get_user_role(db, owner_id)

    if not check_user_permission(role, "use_tools"):
        return False, f"Role '{role}' cannot use tools (read-only access)"

    # Codebase tools require admin
    codebase_tools = {
        "codebase_read", "codebase_search", "codebase_structure",
        "codebase_edit", "codebase_write", "codebase_run_tests",
        "codebase_git_status",
    }
    if tool_name in codebase_tools and not check_user_permission(role, "use_codebase_tools"):
        return False, f"Role '{role}' cannot use codebase tools (admin only)"

    return True, "ok"


def inject_team_memory_context(
    db: Session, owner_id: int, messages: List[Dict], user_message: str
) -> int:
    """Inject relevant team shared memory into the conversation context.

    Searches all teams the user belongs to for relevant entries
    and adds them as context. Returns number of entries injected.
    """
    from ..database.models import TeamMemory, TeamMembership
    import numpy as np

    teams = get_user_teams(db, owner_id)
    if not teams:
        return 0

    team_ids = [t["team_id"] for t in teams]

    # Get recent team memories (simple retrieval, no semantic search for now)
    memories = (
        db.query(TeamMemory)
        .filter(TeamMemory.team_id.in_(team_ids))
        .order_by(TeamMemory.updated_at.desc())
        .limit(5)
        .all()
    )

    if not memories:
        return 0

    # Format and inject as system context
    lines = ["[Team Shared Knowledge]"]
    for mem in memories:
        team_name = next(
            (t["team_name"] for t in teams if t["team_id"] == mem.team_id), "?"
        )
        lines.append(f"- [{team_name}/{mem.category}] {mem.title}: {mem.content[:300]}")

    context_block = "\n".join(lines)

    # Inject after system message
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] += f"\n\n{context_block}"
    else:
        messages.insert(0, {"role": "system", "content": context_block})

    return len(memories)

"""
Tests for authorization module (role-based access control).

Covers: user and team role validation, permission checking, role hierarchy,
        and authorization checks with hardening.
"""

import pytest
from unittest.mock import MagicMock, patch

from mind_clone.core.authorization import (
    validate_role,
    check_user_permission,
    check_team_permission,
    user_role_at_least,
    USER_ROLE_HIERARCHY,
    TEAM_ROLE_HIERARCHY,
)


# ---------------------------------------------------------------------------
# Role Validation
# ---------------------------------------------------------------------------

class TestValidateRole:
    """Test role validation for user and team roles."""

    def test_valid_user_roles(self):
        """All valid user roles pass validation."""
        for role in USER_ROLE_HIERARCHY:
            valid, msg = validate_role(role, "user")
            assert valid is True, f"Role '{role}' should be valid"

    def test_valid_team_roles(self):
        """All valid team roles pass validation."""
        for role in TEAM_ROLE_HIERARCHY:
            valid, msg = validate_role(role, "team")
            assert valid is True, f"Role '{role}' should be valid"

    def test_unknown_user_role_rejected(self):
        """Unknown user role is rejected."""
        valid, msg = validate_role("superuser", "user")
        assert valid is False
        assert "Unknown" in msg or "unknown" in msg.lower()

    def test_unknown_team_role_rejected(self):
        """Unknown team role is rejected."""
        valid, msg = validate_role("lead", "team")
        assert valid is False
        assert "Unknown" in msg or "unknown" in msg.lower()

    def test_none_role_rejected(self):
        """None role is rejected."""
        valid, msg = validate_role(None, "user")
        assert valid is False
        assert "None" in msg or "empty" in msg.lower()

    def test_empty_role_rejected(self):
        """Empty string role is rejected."""
        valid, msg = validate_role("", "user")
        assert valid is False

    def test_whitespace_only_role_rejected(self):
        """Whitespace-only role is rejected."""
        valid, msg = validate_role("   ", "user")
        assert valid is False
        assert "whitespace" in msg.lower()

    def test_non_string_role_rejected(self):
        """Non-string role is rejected."""
        valid, msg = validate_role(123, "user")
        assert valid is False
        assert "string" in msg.lower()

    def test_case_insensitive_validation(self):
        """Role validation is case-insensitive."""
        valid, msg = validate_role("ADMIN", "user")
        assert valid is True

        valid, msg = validate_role("User", "user")
        assert valid is True

    def test_whitespace_trimmed(self):
        """Whitespace around role is trimmed."""
        valid, msg = validate_role("  admin  ", "user")
        assert valid is True

    def test_invalid_role_type_rejected(self):
        """Invalid role_type parameter is rejected."""
        valid, msg = validate_role("admin", "invalid_type")
        assert valid is False
        assert "role_type" in msg.lower()


# ---------------------------------------------------------------------------
# User Permission Checking (with validation)
# ---------------------------------------------------------------------------

class TestCheckUserPermissionWithValidation:
    """Test user permission checking with role validation."""

    def test_admin_can_manage_users(self):
        """Admin user can manage users."""
        assert check_user_permission("admin", "manage_users") is True

    def test_viewer_cannot_use_tools(self):
        """Viewer user cannot use tools."""
        assert check_user_permission("viewer", "use_tools") is False

    def test_invalid_role_returns_false(self):
        """Invalid role returns False (secure default)."""
        assert check_user_permission("invalid_role", "chat") is False

    def test_none_role_returns_false(self):
        """None role returns False (secure default)."""
        assert check_user_permission(None, "chat") is False

    def test_empty_role_returns_false(self):
        """Empty role returns False (secure default)."""
        assert check_user_permission("", "chat") is False

    def test_whitespace_role_returns_false(self):
        """Whitespace-only role returns False."""
        assert check_user_permission("   ", "chat") is False


# ---------------------------------------------------------------------------
# Team Permission Checking (with validation)
# ---------------------------------------------------------------------------

class TestCheckTeamPermissionWithValidation:
    """Test team permission checking with role validation."""

    def test_owner_can_delete_team(self):
        """Team owner can delete team."""
        assert check_team_permission("owner", "delete_team") is True

    def test_viewer_cannot_write_memory(self):
        """Team viewer cannot write memory."""
        assert check_team_permission("viewer", "write_memory") is False

    def test_invalid_role_returns_false(self):
        """Invalid team role returns False (secure default)."""
        assert check_team_permission("leader", "read_memory") is False

    def test_none_role_returns_false(self):
        """None team role returns False."""
        assert check_team_permission(None, "read_memory") is False

    def test_empty_role_returns_false(self):
        """Empty team role returns False."""
        assert check_team_permission("", "read_memory") is False


# ---------------------------------------------------------------------------
# Role Hierarchy
# ---------------------------------------------------------------------------

class TestUserRoleHierarchy:
    """Test user role hierarchy enforcement."""

    def test_admin_at_least_admin(self):
        """Admin meets admin requirement."""
        assert user_role_at_least("admin", "admin") is True

    def test_admin_exceeds_user(self):
        """Admin exceeds user requirement."""
        assert user_role_at_least("admin", "user") is True

    def test_user_cannot_meet_admin(self):
        """User cannot meet admin requirement."""
        assert user_role_at_least("user", "admin") is False

    def test_viewer_cannot_meet_user(self):
        """Viewer cannot meet user requirement."""
        assert user_role_at_least("viewer", "user") is False

    def test_invalid_role_fails_check(self):
        """Invalid role fails hierarchy check."""
        assert user_role_at_least("invalid", "user") is False

    def test_none_role_fails_check(self):
        """None role fails hierarchy check."""
        assert user_role_at_least(None, "user") is False


# ---------------------------------------------------------------------------
# Role Hierarchy Ordering
# ---------------------------------------------------------------------------

class TestRoleHierarchyOrdering:
    """Verify role hierarchy has correct ordering."""

    def test_user_hierarchy_order(self):
        """User role hierarchy is in ascending order of privilege."""
        assert USER_ROLE_HIERARCHY == ["viewer", "user", "admin"]
        assert len(USER_ROLE_HIERARCHY) == 3

    def test_team_hierarchy_order(self):
        """Team role hierarchy is in ascending order of privilege."""
        assert TEAM_ROLE_HIERARCHY == ["viewer", "member", "admin", "owner"]
        assert len(TEAM_ROLE_HIERARCHY) == 4

    def test_no_duplicate_roles_user(self):
        """User role hierarchy has no duplicates."""
        assert len(set(USER_ROLE_HIERARCHY)) == len(USER_ROLE_HIERARCHY)

    def test_no_duplicate_roles_team(self):
        """Team role hierarchy has no duplicates."""
        assert len(set(TEAM_ROLE_HIERARCHY)) == len(TEAM_ROLE_HIERARCHY)

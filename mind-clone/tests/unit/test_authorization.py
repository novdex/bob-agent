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


# ---------------------------------------------------------------------------
# DB-dependent function tests with mocks (authorization.py mutations)
# ---------------------------------------------------------------------------

class TestGetUserRole:
    """Test get_user_role function with DB mocks."""

    def test_get_user_role_returns_user_role(self):
        """get_user_role returns the user's role from DB."""
        from mind_clone.core.authorization import get_user_role

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_db.query(MagicMock).filter(MagicMock).first.return_value = mock_user

        result = get_user_role(mock_db, 1)
        assert result == "admin"

    def test_get_user_role_with_filter_equals(self):
        """get_user_role uses == filter (not !=) on User.id."""
        from mind_clone.core.authorization import get_user_role

        # This test ensures the equality operator is being used correctly
        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.role = "user"

        # Setup the query chain
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = mock_user

        result = get_user_role(mock_db, 42)
        assert result == "user"
        # Verify filter was called with owner_id
        assert mock_query.filter.called

    def test_get_user_role_defaults_to_user(self):
        """get_user_role returns 'user' when user not found."""
        from mind_clone.core.authorization import get_user_role

        mock_db = MagicMock()
        mock_db.query(MagicMock).filter(MagicMock).first.return_value = None

        result = get_user_role(mock_db, 999)
        assert result == "user"

    def test_get_user_role_defaults_to_user_when_role_missing(self):
        """get_user_role returns 'user' when role attribute is missing."""
        from mind_clone.core.authorization import get_user_role

        mock_db = MagicMock()
        mock_user = MagicMock(spec=[])  # No role attribute

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = mock_user

        result = get_user_role(mock_db, 1)
        assert result == "user"

    def test_get_user_role_defaults_to_user_when_role_none(self):
        """get_user_role returns 'user' when role is None."""
        from mind_clone.core.authorization import get_user_role

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.role = None

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = mock_user

        result = get_user_role(mock_db, 1)
        assert result == "user"


class TestGetTeamRole:
    """Test get_team_role function with DB mocks."""

    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_team_role_returns_membership_role(self, mock_membership_class):
        """get_team_role returns the membership role."""
        from mind_clone.core.authorization import get_team_role

        mock_db = MagicMock()
        mock_membership = MagicMock()
        mock_membership.role = "owner"

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = mock_membership

        result = get_team_role(mock_db, 1, 1)
        assert result == "owner"

    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_team_role_with_team_id_filter(self, mock_membership_class):
        """get_team_role filters by team_id using == (not !=)."""
        from mind_clone.core.authorization import get_team_role

        mock_db = MagicMock()
        mock_membership = MagicMock()
        mock_membership.role = "admin"

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = mock_membership

        result = get_team_role(mock_db, 5, 3)
        assert result == "admin"
        assert mock_query.filter.called

    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_team_role_returns_none_not_found(self, mock_membership_class):
        """get_team_role returns None when membership not found."""
        from mind_clone.core.authorization import get_team_role

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = None

        result = get_team_role(mock_db, 1, 999)
        assert result is None


class TestGetUserTeams:
    """Test get_user_teams function with DB mocks."""

    @patch("mind_clone.database.models.Team", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_user_teams_returns_list(self, mock_membership_class, mock_team_class):
        """get_user_teams returns list of team dicts."""
        from mind_clone.core.authorization import get_user_teams

        mock_db = MagicMock()
        mock_membership = MagicMock()
        mock_membership.role = "admin"
        mock_team = MagicMock()
        mock_team.id = 10
        mock_team.name = "DevTeam"

        mock_query = MagicMock()
        mock_joined = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_joined
        mock_joined.filter.return_value = mock_filtered
        mock_filtered.all.return_value = [(mock_membership, mock_team)]

        result = get_user_teams(mock_db, 5)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["team_id"] == 10
        assert result[0]["team_name"] == "DevTeam"
        assert result[0]["role"] == "admin"

    @patch("mind_clone.database.models.Team", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_user_teams_filters_by_user_id(self, mock_membership_class, mock_team_class):
        """get_user_teams filters by user_id using == (not !=)."""
        from mind_clone.core.authorization import get_user_teams

        mock_db = MagicMock()
        mock_membership = MagicMock()
        mock_membership.role = "member"
        mock_team = MagicMock()
        mock_team.id = 20
        mock_team.name = "QATeam"

        mock_query = MagicMock()
        mock_joined = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_joined
        mock_joined.filter.return_value = mock_filtered
        mock_filtered.all.return_value = [(mock_membership, mock_team)]

        result = get_user_teams(mock_db, 7)
        assert len(result) == 1
        assert mock_joined.filter.called

    @patch("mind_clone.database.models.Team", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_get_user_teams_empty_list(self, mock_membership_class, mock_team_class):
        """get_user_teams returns empty list when user has no teams."""
        from mind_clone.core.authorization import get_user_teams

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_joined = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_joined
        mock_joined.filter.return_value = mock_filtered
        mock_filtered.all.return_value = []

        result = get_user_teams(mock_db, 999)
        assert result == []


class TestAuthorizeToolUse:
    """Test authorize_tool_use function with mocks."""

    def test_viewer_cannot_use_tools(self):
        """authorize_tool_use returns False for viewer."""
        from mind_clone.core.authorization import authorize_tool_use

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_role", return_value="viewer"):
            allowed, reason = authorize_tool_use(mock_db, 1, "search_web")
            assert allowed is False
            assert "cannot use tools" in reason.lower()

    def test_user_can_use_regular_tools(self):
        """authorize_tool_use returns True for user using regular tools."""
        from mind_clone.core.authorization import authorize_tool_use

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_role", return_value="user"):
            allowed, reason = authorize_tool_use(mock_db, 1, "search_web")
            assert allowed is True
            assert reason == "ok"

    def test_user_cannot_use_codebase_tools(self):
        """authorize_tool_use returns False for user trying to use codebase tools."""
        from mind_clone.core.authorization import authorize_tool_use

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_role", return_value="user"):
            allowed, reason = authorize_tool_use(mock_db, 1, "codebase_edit")
            assert allowed is False
            assert "codebase tools" in reason.lower()

    def test_admin_can_use_codebase_tools(self):
        """authorize_tool_use returns True for admin using codebase tools."""
        from mind_clone.core.authorization import authorize_tool_use

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_role", return_value="admin"):
            allowed, reason = authorize_tool_use(mock_db, 1, "codebase_read")
            assert allowed is True

    def test_admin_can_use_all_codebase_tools(self):
        """authorize_tool_use returns True for admin on all codebase tools."""
        from mind_clone.core.authorization import authorize_tool_use

        codebase_tools = [
            "codebase_read", "codebase_search", "codebase_structure",
            "codebase_edit", "codebase_write", "codebase_run_tests",
            "codebase_git_status",
        ]

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_role", return_value="admin"):
            for tool in codebase_tools:
                allowed, reason = authorize_tool_use(mock_db, 1, tool)
                assert allowed is True, f"Admin should be able to use {tool}"


class TestInjectTeamMemoryContext:
    """Test inject_team_memory_context function with mocks."""

    @patch("mind_clone.database.models.TeamMemory", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_returns_0_when_no_teams(self, mock_mem_class, mock_mem_memory_class):
        """inject_team_memory_context returns 0 when user has no teams."""
        from mind_clone.core.authorization import inject_team_memory_context

        mock_db = MagicMock()
        with patch("mind_clone.core.authorization.get_user_teams", return_value=[]):
            result = inject_team_memory_context(mock_db, 1, [], "test message")
            assert result == 0

    @patch("mind_clone.database.models.TeamMemory", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_returns_0_when_no_memories(self, mock_mem_class, mock_mem_memory_class):
        """inject_team_memory_context returns 0 when no memories found."""
        from mind_clone.core.authorization import inject_team_memory_context

        mock_db = MagicMock()
        teams = [{"team_id": 1, "team_name": "TestTeam", "role": "member"}]

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.order_by.return_value.limit.return_value.all.return_value = []

        with patch("mind_clone.core.authorization.get_user_teams", return_value=teams):
            messages = []
            result = inject_team_memory_context(mock_db, 1, messages, "test")
            assert result == 0

    @patch("mind_clone.database.models.TeamMemory", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_injects_team_memory_into_system_message(self, mock_mem_class, mock_mem_memory_class):
        """inject_team_memory_context injects into existing system message."""
        from mind_clone.core.authorization import inject_team_memory_context

        mock_db = MagicMock()
        teams = [{"team_id": 1, "team_name": "TestTeam", "role": "member"}]

        mock_memory = MagicMock()
        mock_memory.team_id = 1
        mock_memory.category = "lesson"
        mock_memory.title = "Best Practices"
        mock_memory.content = "Always validate inputs" * 100

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.order_by.return_value.limit.return_value.all.return_value = [mock_memory]

        with patch("mind_clone.core.authorization.get_user_teams", return_value=teams):
            messages = [{"role": "system", "content": "You are helpful"}]
            result = inject_team_memory_context(mock_db, 1, messages, "test")

            assert result == 1
            assert "Team Shared Knowledge" in messages[0]["content"]
            assert "TestTeam" in messages[0]["content"]

    @patch("mind_clone.database.models.TeamMemory", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_creates_system_message_when_missing(self, mock_mem_class, mock_mem_memory_class):
        """inject_team_memory_context creates system message if not present."""
        from mind_clone.core.authorization import inject_team_memory_context

        mock_db = MagicMock()
        teams = [{"team_id": 1, "team_name": "TestTeam", "role": "member"}]

        mock_memory = MagicMock()
        mock_memory.team_id = 1
        mock_memory.category = "lesson"
        mock_memory.title = "Best Practices"
        mock_memory.content = "Always validate" * 100

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.order_by.return_value.limit.return_value.all.return_value = [mock_memory]

        with patch("mind_clone.core.authorization.get_user_teams", return_value=teams):
            messages = [{"role": "user", "content": "hello"}]
            result = inject_team_memory_context(mock_db, 1, messages, "test")

            assert result == 1
            assert messages[0]["role"] == "system"
            assert "Team Shared Knowledge" in messages[0]["content"]

    @patch("mind_clone.database.models.TeamMemory", create=True)
    @patch("mind_clone.database.models.TeamMembership", create=True)
    def test_returns_correct_count_of_memories(self, mock_mem_class, mock_mem_memory_class):
        """inject_team_memory_context returns correct count of injected memories."""
        from mind_clone.core.authorization import inject_team_memory_context

        mock_db = MagicMock()
        teams = [{"team_id": 1, "team_name": "TestTeam", "role": "member"}]

        # Create multiple memories
        memories = []
        for i in range(3):
            mem = MagicMock()
            mem.team_id = 1
            mem.category = f"lesson{i}"
            mem.title = f"Title{i}"
            mem.content = f"Content{i}" * 50
            memories.append(mem)

        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.order_by.return_value.limit.return_value.all.return_value = memories

        with patch("mind_clone.core.authorization.get_user_teams", return_value=teams):
            messages = []
            result = inject_team_memory_context(mock_db, 1, messages, "test")

            assert result == 3

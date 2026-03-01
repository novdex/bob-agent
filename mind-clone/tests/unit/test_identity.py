"""
Tests for agent/identity.py — Identity kernel management.
"""
import pytest
from mind_clone.agent.identity import (
    generate_agent_uuid,
    check_authority,
    get_identity_summary,
    normalize_agent_key,
    DEFAULT_ORIGIN_STATEMENT,
    DEFAULT_CORE_VALUES,
    DEFAULT_AUTHORITY_BOUNDS,
    load_identity,
    ensure_identity_exists,
    update_identity_kernel,
    team_spawn_policy_allows,
)


class TestGenerateAgentUUID:
    """Test UUID generation."""

    def test_returns_string(self):
        uid = generate_agent_uuid()
        assert isinstance(uid, str)
        assert len(uid) == 36  # UUID4 format

    def test_unique(self):
        uids = {generate_agent_uuid() for _ in range(100)}
        assert len(uids) == 100


class TestCheckAuthority:
    """Test authority checking."""

    def test_allowed_action(self):
        identity = {"authority_bounds": {"can_execute_code": True}}
        assert check_authority(identity, "can_execute_code") is True

    def test_denied_action(self):
        identity = {"authority_bounds": {"can_send_email": False}}
        assert check_authority(identity, "can_send_email") is False

    def test_unknown_action_defaults_false(self):
        identity = {"authority_bounds": {}}
        assert check_authority(identity, "can_launch_missiles") is False

    def test_empty_identity(self):
        assert check_authority({}, "anything") is False

    def test_default_bounds(self):
        identity = {"authority_bounds": DEFAULT_AUTHORITY_BOUNDS}
        assert check_authority(identity, "can_execute_code") is True
        assert check_authority(identity, "can_access_files") is True
        assert check_authority(identity, "can_send_email") is False
        assert check_authority(identity, "can_delete_files") is False


class TestGetIdentitySummary:
    """Test identity summary generation."""

    def test_with_identity(self):
        identity = {
            "agent_uuid": "test-uuid-1234",
            "origin_statement": "I am Bob",
            "core_values": ["truth", "help"],
        }
        summary = get_identity_summary(identity)
        assert "test-uuid-1234" in summary
        assert "I am Bob" in summary
        assert "truth" in summary

    def test_empty_identity(self):
        summary = get_identity_summary({})
        assert "No identity configured" in summary or "Unknown" in summary

    def test_none_identity(self):
        summary = get_identity_summary(None)
        assert "No identity configured" in summary


class TestNormalizeAgentKey:
    """Test agent key normalization."""

    def test_lowercase(self):
        assert normalize_agent_key("MAIN") == "main"

    def test_strip_whitespace(self):
        assert normalize_agent_key("  bob  ") == "bob"

    def test_none_defaults_to_main(self):
        assert normalize_agent_key(None) == "main"

    def test_empty_defaults_to_main(self):
        assert normalize_agent_key("") == "main"


class TestDefaults:
    """Test default constants."""

    def test_origin_statement_nonempty(self):
        assert len(DEFAULT_ORIGIN_STATEMENT) > 20

    def test_core_values_list(self):
        assert isinstance(DEFAULT_CORE_VALUES, list)
        assert "truthfulness" in DEFAULT_CORE_VALUES

    def test_authority_bounds_dict(self):
        assert isinstance(DEFAULT_AUTHORITY_BOUNDS, dict)
        assert "can_execute_code" in DEFAULT_AUTHORITY_BOUNDS


class TestIdentityDB:
    """Test identity DB operations."""

    def test_load_identity_none(self, db_session):
        """No identity exists yet."""
        result = load_identity(db_session, owner_id=9999)
        assert result is None

    def test_ensure_creates_default(self, db_session):
        """ensure_identity_exists should create default identity."""
        result = ensure_identity_exists(db_session, owner_id=1)
        assert result is not None
        assert "agent_uuid" in result
        assert result["core_values"] == DEFAULT_CORE_VALUES

    def test_ensure_idempotent(self, db_session):
        """Calling ensure twice returns same identity."""
        r1 = ensure_identity_exists(db_session, owner_id=1)
        r2 = ensure_identity_exists(db_session, owner_id=1)
        assert r1["agent_uuid"] == r2["agent_uuid"]

    def test_update_identity(self, db_session):
        """Update identity fields."""
        ensure_identity_exists(db_session, owner_id=1)
        result = update_identity_kernel(
            db_session, owner_id=1,
            origin_statement="Updated origin",
            core_values=["new_value"],
        )
        assert result is not None
        assert result["origin_statement"] == "Updated origin"
        assert result["core_values"] == ["new_value"]

    def test_update_creates_if_missing(self, db_session):
        """Update on nonexistent owner creates new identity."""
        result = update_identity_kernel(
            db_session, owner_id=777,
            origin_statement="New agent",
        )
        assert result is not None
        assert result["origin_statement"] == "New agent"


class TestTeamSpawnPolicy:
    """Test team spawn policy."""

    def test_always_allows(self):
        assert team_spawn_policy_allows("main", "researcher") is True
        assert team_spawn_policy_allows("", "") is True

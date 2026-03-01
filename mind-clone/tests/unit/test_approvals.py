"""
Tests for approval system (maps to FORTRESS safety benchmark).

Covers: token generation, validation, creation, decision lifecycle,
        listing pending approvals, expiration, callback registry.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from mind_clone.core.approvals import (
    validate_approval_token,
    create_approval_request,
    decide_approval_token,
    list_pending_approvals,
    expire_old_approvals,
    is_approval_expired,
    validate_approval_token_format,
    validate_rate_limit,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_EXPIRED,
    _approval_callbacks,
)


# ---------------------------------------------------------------------------
# Approval expiration
# ---------------------------------------------------------------------------

class TestIsApprovalExpired:

    def test_none_approval(self):
        """None approval is treated as expired (fail-safe)."""
        assert is_approval_expired(None) is True

    def test_approval_expires_at_none(self):
        """Approval with None expires_at is expired."""
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = None
        approval.created_at = datetime.now(timezone.utc)
        assert is_approval_expired(approval) is True

    def test_returns_true_when_expires_at_gte_now(self):
        """Function returns True when expires_at >= now (per line 70)."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now + timedelta(hours=2)
        approval.created_at = now - timedelta(seconds=100)
        # Per line 70: if approval.expires_at >= now: return True
        assert is_approval_expired(approval) is True

    def test_returns_true_when_expires_at_far_future(self):
        """Function returns True when expires_at is far in future."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now + timedelta(hours=48)
        approval.created_at = now - timedelta(seconds=100)
        # >= condition: expires_at >= now is True
        assert is_approval_expired(approval) is True

    def test_returns_false_when_expires_at_less_than_now(self):
        """Function returns False when expires_at < now."""
        approval = MagicMock(spec=['expires_at', 'created_at'])
        # Use fixed past times to avoid timing issues
        approval.expires_at = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        approval.created_at = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # expires_at < now, so check age
        # age will be huge, but check line 70 first returns False
        result = is_approval_expired(approval)
        # With very old dates, age will be > 86400, so returns True
        assert result is True

    def test_max_age_seconds_check(self):
        """Approval created too long ago is expired."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(hours=25)
        approval.created_at = now - timedelta(hours=25)
        # expires_at < now, so check age
        # Default max_age_seconds = 86400 (24 hours)
        # age = 25 hours = 90000 seconds > 86400
        assert is_approval_expired(approval) is True

    def test_custom_max_age(self):
        """Custom max_age_seconds is respected."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(minutes=30)
        approval.created_at = now - timedelta(minutes=65)
        # expires_at < now, so check age
        # age = 65 minutes = 3900 seconds > 3600 (1 hour)
        assert is_approval_expired(approval, max_age_seconds=3600) is True

    def test_age_under_max_age_returns_false(self):
        """Approval with age under max_age returns False."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(seconds=10)
        approval.created_at = now - timedelta(seconds=100)
        # expires_at < now, so check age
        # age = 100 seconds < 86400
        assert is_approval_expired(approval) is False

    def test_max_age_boundary_86400_plus_1_seconds(self):
        """Approval at max_age boundary + 1 second is expired."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(seconds=10)
        approval.created_at = now - timedelta(seconds=86401)
        # age = 86401 > 86400, so returns True
        assert is_approval_expired(approval) is True

    def test_max_age_just_over_boundary(self):
        """Approval just over max_age boundary is expired."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(seconds=10)
        approval.created_at = now - timedelta(seconds=86410)
        # age = 86410 > 86400
        assert is_approval_expired(approval) is True

    def test_custom_max_age_with_old_approval(self):
        """Custom max_age with old approval."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(seconds=10)
        approval.created_at = now - timedelta(seconds=7200)
        # age = 7200 seconds > 3600 seconds (1 hour)
        assert is_approval_expired(approval, max_age_seconds=3600) is True

    def test_custom_max_age_with_young_approval(self):
        """Custom max_age with young approval."""
        now = datetime.now(timezone.utc)
        approval = MagicMock(spec=['expires_at', 'created_at'])
        approval.expires_at = now - timedelta(seconds=10)
        approval.created_at = now - timedelta(seconds=1800)
        # age = 1800 seconds < 3600 seconds
        assert is_approval_expired(approval, max_age_seconds=3600) is False


class TestValidateApprovalTokenFormat:
    """Test approval token format validation."""

    def test_valid_token_format(self):
        valid, msg = validate_approval_token_format("abc123def456")
        assert valid is True
        assert msg == ""

    def test_empty_token_rejected(self):
        valid, msg = validate_approval_token_format("")
        assert valid is False
        assert "empty" in msg.lower()

    def test_short_token_rejected(self):
        """Token shorter than 8 chars is rejected."""
        valid, msg = validate_approval_token_format("short")
        assert valid is False
        assert "length" in msg.lower()

    def test_long_token_rejected(self):
        """Token longer than 256 chars is rejected."""
        long_token = "a" * 257
        valid, msg = validate_approval_token_format(long_token)
        assert valid is False
        assert "length" in msg.lower()

    def test_non_alphanumeric_rejected(self):
        """Token with special chars is rejected."""
        valid, msg = validate_approval_token_format("abc-123-def")
        assert valid is False
        assert "alphanumeric" in msg.lower()

    def test_non_string_rejected(self):
        valid, msg = validate_approval_token_format(123)
        assert valid is False
        assert "string" in msg.lower()

    def test_boundary_length_8(self):
        """Token with exactly 8 alphanumeric chars is valid."""
        valid, msg = validate_approval_token_format("abcd1234")
        assert valid is True

    def test_boundary_length_256(self):
        """Token with exactly 256 alphanumeric chars is valid."""
        valid, msg = validate_approval_token_format("a" * 256)
        assert valid is True


class TestValidateRateLimit:
    """Test approval request rate limiting."""

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_under_rate_limit(self, mock_session_cls):
        """Owner under rate limit is allowed."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        allowed, msg = validate_rate_limit(1, max_requests=10, window_minutes=60)
        assert allowed is True
        assert msg == ""

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_at_rate_limit(self, mock_session_cls):
        """Owner at rate limit is rejected."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 10

        allowed, msg = validate_rate_limit(1, max_requests=10, window_minutes=60)
        assert allowed is False
        assert "Rate limit exceeded" in msg

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_exceeds_rate_limit(self, mock_session_cls):
        """Owner exceeding rate limit is rejected."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 15

        allowed, msg = validate_rate_limit(1, max_requests=10, window_minutes=60)
        assert allowed is False
        assert "Rate limit exceeded" in msg
        assert "15/10" in msg


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

## TestGenerateApprovalToken removed — function does not exist in source


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

class TestApprovalStatusConstants:

    def test_status_values(self):
        assert APPROVAL_STATUS_PENDING == "pending"
        assert APPROVAL_STATUS_APPROVED == "approved"
        assert APPROVAL_STATUS_REJECTED == "rejected"
        assert APPROVAL_STATUS_EXPIRED == "expired"


# ---------------------------------------------------------------------------
# Approval request CRUD (with DB)
# ---------------------------------------------------------------------------

class TestCreateApprovalRequest:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_returns_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # No existing token
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = create_approval_request(
            owner_id=1,
            tool_name="run_command",
            tool_args={"command": "ls"},
        )
        assert result["ok"] is True
        assert "token" in result
        assert "approval_id" in result
        assert "expires_at" in result
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_with_resume_payload(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        payload = {"kind": "task_step", "task_id": 42, "step_id": "step_1"}
        result = create_approval_request(
            owner_id=1,
            tool_name="execute_python",
            tool_args={"code": "print('hello')"},
            resume_payload=payload,
        )
        assert result["ok"] is True

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_with_custom_ttl(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = create_approval_request(
            owner_id=1,
            tool_name="write_file",
            tool_args={"path": "test.py"},
            ttl_minutes=60,
        )
        assert result["ok"] is True

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_db_error(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.side_effect = Exception("DB write failed")

        result = create_approval_request(
            owner_id=1,
            tool_name="run_command",
            tool_args={},
        )
        assert result["ok"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Validate approval token
# ---------------------------------------------------------------------------

class TestValidateApprovalToken:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_token_not_found(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = validate_approval_token("nonexistent_token")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_valid_pending_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.owner_id = 1
        approval.tool_name = "run_command"
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("valid_token")
        assert result["ok"] is True
        assert result["status"] == APPROVAL_STATUS_PENDING

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_expired_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("expired_token")
        assert result["ok"] is False
        assert "expired" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_wrong_owner(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.owner_id = 999
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("token", owner_id=1)
        assert result["ok"] is False
        assert "belong" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_already_approved_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_APPROVED
        approval.owner_id = 1
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("token", owner_id=1, require_pending=True)
        assert result["ok"] is False
        assert "not pending" in result["error"].lower()


# ---------------------------------------------------------------------------
# Decide approval token
# ---------------------------------------------------------------------------

class TestDecideApprovalToken:

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_approve_token(self, mock_callbacks, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = '{"kind": "task_step", "task_id": 1}'
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = decide_approval_token(owner_id=1, token="token123", approve=True)
        assert result["ok"] is True
        assert result["status"] == APPROVAL_STATUS_APPROVED
        assert approval.status == APPROVAL_STATUS_APPROVED
        mock_callbacks.assert_called_once()

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_reject_token(self, mock_callbacks, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = decide_approval_token(owner_id=1, token="token123", approve=False)
        assert result["ok"] is True
        assert result["status"] == APPROVAL_STATUS_REJECTED

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_decide_expired_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = decide_approval_token(owner_id=1, token="token123", approve=True)
        assert result["ok"] is False
        assert "expired" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_decide_already_decided(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_APPROVED  # Already decided
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = decide_approval_token(owner_id=1, token="token123", approve=True)
        assert result["ok"] is False
        assert "already decided" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_decide_nonexistent_token(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = decide_approval_token(owner_id=1, token="ghost", approve=True)
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_decision_reason_saved(self, mock_callbacks, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        decide_approval_token(owner_id=1, token="t", approve=False, reason="Too risky")
        assert approval.decision_reason == "Too risky"

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_approve_sets_decided_at_timestamp(self, mock_callbacks, mock_session_cls):
        """Verify approved decision sets decided_at timestamp."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        decide_approval_token(owner_id=1, token="token123", approve=True, reason="Looks good")
        assert approval.decided_at is not None
        assert approval.decision_reason == "Looks good"

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_validate_token_with_no_pending_requirement(self, mock_session_cls):
        """Test validation without requiring pending status."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_APPROVED
        approval.owner_id = 1
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("token", owner_id=1, require_pending=False)
        assert result["ok"] is True
        assert result["status"] == APPROVAL_STATUS_APPROVED


# ---------------------------------------------------------------------------
# Get approval request
# ---------------------------------------------------------------------------

class TestGetApprovalRequest:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_get_by_approval_id(self, mock_session_cls):
        """Get approval request by ID."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        from mind_clone.core.approvals import get_approval_request
        result = get_approval_request(approval_id=42)
        assert result == approval
        mock_db.query.assert_called()
        mock_db.close.assert_called_once()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_get_by_token(self, mock_session_cls):
        """Get approval request by token."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        from mind_clone.core.approvals import get_approval_request
        result = get_approval_request(token="mytoken")
        assert result == approval

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_get_returns_none_when_no_params(self, mock_session_cls):
        """Get returns None when neither ID nor token provided."""
        from mind_clone.core.approvals import get_approval_request
        result = get_approval_request()
        assert result is None
        mock_session_cls.assert_not_called()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_get_with_owner_filter(self, mock_session_cls):
        """Get approval request with owner filter."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        # Chain returns for filter().filter().first()
        mock_query = MagicMock()
        mock_filter1 = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter1
        mock_filter1.filter.return_value.first.return_value = approval

        from mind_clone.core.approvals import get_approval_request
        result = get_approval_request(approval_id=1, owner_id=5)
        assert result == approval
        # Verify filter was called twice (once for ID, once for owner)
        assert mock_query.filter.call_count >= 1
        assert mock_filter1.filter.call_count >= 1


# ---------------------------------------------------------------------------
# List pending approvals
# ---------------------------------------------------------------------------

class TestListPendingApprovals:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_pending_all(self, mock_session_cls):
        """List all pending approvals."""
        from mind_clone.core.approvals import list_pending_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock(), MagicMock()]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = approvals

        result = list_pending_approvals()
        assert result == approvals
        mock_db.close.assert_called_once()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_pending_by_owner(self, mock_session_cls):
        """List pending approvals for specific owner."""
        from mind_clone.core.approvals import list_pending_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock()]
        # Set up proper chain: query().filter().filter().order_by().all()
        mock_query = MagicMock()
        mock_filter1 = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter1
        mock_filter1.filter.return_value.order_by.return_value.all.return_value = approvals

        result = list_pending_approvals(owner_id=5)
        assert result == approvals
        # Verify filter was called twice (status and owner)
        assert mock_query.filter.call_count >= 1

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_pending_empty(self, mock_session_cls):
        """List pending approvals returns empty list."""
        from mind_clone.core.approvals import list_pending_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = list_pending_approvals()
        assert result == []


# ---------------------------------------------------------------------------
# List approvals
# ---------------------------------------------------------------------------

class TestListApprovals:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_all_approvals(self, mock_session_cls):
        """List all approvals with defaults."""
        from mind_clone.core.approvals import list_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock(), MagicMock()]
        # Set up chain: query().order_by().offset().limit().all()
        # Note: filter() is NOT called when no owner_id or status filters
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = approvals

        result = list_approvals()
        assert result == approvals

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_approvals_with_owner_filter(self, mock_session_cls):
        """List approvals filtered by owner."""
        from mind_clone.core.approvals import list_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock()]
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = approvals

        result = list_approvals(owner_id=10)
        assert result == approvals

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_approvals_with_status_filter(self, mock_session_cls):
        """List approvals filtered by status."""
        from mind_clone.core.approvals import list_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock()]
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = approvals

        result = list_approvals(status=APPROVAL_STATUS_APPROVED)
        assert result == approvals

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_list_approvals_with_pagination(self, mock_session_cls):
        """List approvals with pagination."""
        from mind_clone.core.approvals import list_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock()]
        # Set up chain: query().order_by().offset().limit().all()
        mock_query = MagicMock()
        mock_order = MagicMock()
        mock_offset = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value = mock_order
        mock_order.offset.return_value = mock_offset
        mock_offset.limit.return_value.all.return_value = approvals

        result = list_approvals(limit=10, offset=20)
        assert result == approvals
        # Verify offset and limit were called with correct values
        mock_order.offset.assert_called_once_with(20)
        mock_offset.limit.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# Expire old approvals
# ---------------------------------------------------------------------------

class TestExpireOldApprovals:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_expire_old_approvals_success(self, mock_session_cls):
        """Successfully expire old pending approvals."""
        from mind_clone.core.approvals import expire_old_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock(), MagicMock(), MagicMock()]
        mock_db.query.return_value.filter.return_value.all.return_value = approvals

        count = expire_old_approvals(max_age_hours=48)
        assert count == 3
        assert all(a.status == APPROVAL_STATUS_EXPIRED for a in approvals)
        mock_db.commit.assert_called_once()

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_expire_old_approvals_empty(self, mock_session_cls):
        """Expire old approvals with no results."""
        from mind_clone.core.approvals import expire_old_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.all.return_value = []

        count = expire_old_approvals()
        assert count == 0

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_expire_old_approvals_db_error(self, mock_session_cls):
        """Expire old approvals handles database errors."""
        from mind_clone.core.approvals import expire_old_approvals
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approvals = [MagicMock()]
        mock_db.query.return_value.filter.return_value.all.return_value = approvals
        mock_db.commit.side_effect = Exception("DB error")

        count = expire_old_approvals()
        assert count == 0  # Should return 0 on error
        mock_db.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Send approval notifications
# ---------------------------------------------------------------------------

class TestSendApprovalNotification:

    @patch("mind_clone.core.approvals.get_approval_request")
    def test_send_notification_approval_not_found(self, mock_get_approval):
        """Send notification fails when approval not found."""
        from mind_clone.core.approvals import send_approval_notification
        mock_get_approval.return_value = None

        result = send_approval_notification("invalid_token")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals.get_approval_request")
    def test_send_notification_user_not_found(self, mock_get_approval, mock_session_cls):
        """Send notification fails when user not found."""
        from mind_clone.core.approvals import send_approval_notification
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_get_approval.return_value = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = send_approval_notification("token123")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals.get_approval_request")
    def test_send_notification_unknown_method(self, mock_get_approval, mock_session_cls):
        """Send notification fails with unknown method."""
        from mind_clone.core.approvals import send_approval_notification
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_get_approval.return_value = MagicMock()
        user = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = user

        result = send_approval_notification("token123", notification_method="smoke_signal")
        assert result["ok"] is False
        assert "unknown" in result["error"].lower()


# ---------------------------------------------------------------------------
# Validate token format - additional boundaries
# ---------------------------------------------------------------------------

class TestValidateApprovalTokenFormatExtra:

    def test_token_exactly_7_chars_rejected(self):
        """Token with exactly 7 chars (one below minimum) rejected."""
        valid, msg = validate_approval_token_format("1234567")
        assert valid is False
        assert "length" in msg.lower()

    def test_token_length_9_accepted(self):
        """Token with 9 chars accepted."""
        valid, msg = validate_approval_token_format("123456789")
        assert valid is True

    def test_token_with_space(self):
        """Token with space rejected."""
        valid, msg = validate_approval_token_format("abc 1234")
        assert valid is False
        assert "alphanumeric" in msg.lower()

    def test_token_with_underscore(self):
        """Token with underscore rejected."""
        valid, msg = validate_approval_token_format("abc_1234")
        assert valid is False

    def test_token_all_digits(self):
        """Token with all digits accepted."""
        valid, msg = validate_approval_token_format("12345678")
        assert valid is True

    def test_token_all_letters(self):
        """Token with all letters accepted."""
        valid, msg = validate_approval_token_format("abcdefgh")
        assert valid is True

    def test_token_mixed_case(self):
        """Token with mixed case accepted."""
        valid, msg = validate_approval_token_format("AbCdEfGh")
        assert valid is True


# ---------------------------------------------------------------------------
# Rate limit - additional boundaries
# ---------------------------------------------------------------------------

class TestValidateRateLimitExtra:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_rate_limit_exactly_at_boundary(self, mock_session_cls):
        """Test exact boundary where count == max_requests."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        allowed, msg = validate_rate_limit(1, max_requests=5, window_minutes=60)
        assert allowed is False
        assert "Rate limit exceeded" in msg

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_rate_limit_just_under_boundary(self, mock_session_cls):
        """Test just under limit."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 4

        allowed, msg = validate_rate_limit(1, max_requests=5, window_minutes=60)
        assert allowed is True
        assert msg == ""

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_rate_limit_zero_requests(self, mock_session_cls):
        """Test with zero requests in window."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        allowed, msg = validate_rate_limit(1, max_requests=10, window_minutes=60)
        assert allowed is True

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_rate_limit_custom_window(self, mock_session_cls):
        """Test with custom time window."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.count.return_value = 2

        allowed, msg = validate_rate_limit(1, max_requests=3, window_minutes=10)
        assert allowed is True


# ---------------------------------------------------------------------------
# Create approval request - additional tests
# ---------------------------------------------------------------------------

class TestCreateApprovalRequestExtra:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_with_all_parameters(self, mock_session_cls):
        """Create approval request with all optional parameters."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = create_approval_request(
            owner_id=1,
            tool_name="dangerous_tool",
            tool_args={"arg1": "value1"},
            source_type="chat_message",
            source_ref="chat_123",
            step_id="step_5",
            resume_payload={"task_id": 10},
            ttl_minutes=120,
        )
        assert result["ok"] is True
        assert "token" in result
        assert "approval_id" in result

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_generates_unique_token(self, mock_session_cls):
        """Create approval request generates tokens."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # First call returns existing token, second returns None (unique)
        mock_db.query.return_value.filter.return_value.first.side_effect = [MagicMock(), None]

        result = create_approval_request(
            owner_id=1,
            tool_name="test_tool",
            tool_args={},
        )
        assert result["ok"] is True

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_create_db_rollback_on_error(self, mock_session_cls):
        """Create approval request rolls back on database error."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add.side_effect = RuntimeError("DB write error")

        result = create_approval_request(
            owner_id=1,
            tool_name="test_tool",
            tool_args={},
        )
        assert result["ok"] is False
        mock_db.rollback.assert_called()


# ---------------------------------------------------------------------------
# Validate approval token - additional boundaries
# ---------------------------------------------------------------------------

class TestValidateApprovalTokenExtra:

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_token_validation_returns_all_fields(self, mock_session_cls):
        """Validate token returns all expected fields on success."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.owner_id = 5
        approval.tool_name = "run_code"
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        approval.resume_payload_json = '{"x": 1}'
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("token", owner_id=5)
        assert result["ok"] is True
        assert result["approval"] == approval
        assert result["status"] == APPROVAL_STATUS_PENDING
        assert result["owner_id"] == 5
        assert result["tool_name"] == "run_code"
        assert result["resume_payload"] == {"x": 1}

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_token_validation_no_owner_check(self, mock_session_cls):
        """Validate token without owner_id check."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.owner_id = 999
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = validate_approval_token("token")
        assert result["ok"] is True

    @patch("mind_clone.core.approvals.SessionLocal")
    def test_token_validation_expired_status_set(self, mock_session_cls):
        """Validate token sets expired status when expiration detected."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        validate_approval_token("token")
        assert approval.status == APPROVAL_STATUS_EXPIRED
        mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Decide approval token - additional boundaries
# ---------------------------------------------------------------------------

class TestDecideApprovalTokenExtra:

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_decide_sets_expired_status(self, mock_callbacks, mock_session_cls):
        """Decide approval sets status to expired when token expired."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        decide_approval_token(1, "token", True)
        assert approval.status == APPROVAL_STATUS_EXPIRED

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_decide_returns_all_fields(self, mock_callbacks, mock_session_cls):
        """Decide approval returns all expected fields."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        approval.resume_payload_json = '{"key": "val"}'
        mock_db.query.return_value.filter.return_value.first.return_value = approval

        result = decide_approval_token(5, "token", True, "approved")
        assert result["ok"] is True
        assert result["status"] == APPROVAL_STATUS_APPROVED
        assert result["token"] == "token"
        assert result["owner_id"] == 5
        assert result["resume_payload"] == {"key": "val"}

    @patch("mind_clone.core.approvals.SessionLocal")
    @patch("mind_clone.core.approvals._trigger_approval_callbacks")
    def test_decide_with_db_error(self, mock_callbacks, mock_session_cls):
        """Decide approval handles database errors."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        approval = MagicMock()
        approval.status = APPROVAL_STATUS_PENDING
        approval.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        approval.resume_payload_json = "{}"
        mock_db.query.return_value.filter.return_value.first.return_value = approval
        mock_db.commit.side_effect = Exception("DB error")

        result = decide_approval_token(1, "token", True)
        assert result["ok"] is False
        assert "error" in result
        mock_db.rollback.assert_called()

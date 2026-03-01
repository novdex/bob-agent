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
    generate_approval_token,
    validate_approval_token,
    create_approval_request,
    decide_approval_token,
    list_pending_approvals,
    expire_old_approvals,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_EXPIRED,
    _approval_callbacks,
)


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

class TestGenerateApprovalToken:

    def test_default_length_16(self):
        token = generate_approval_token()
        assert len(token) == 16

    def test_custom_length(self):
        token = generate_approval_token(length=32)
        assert len(token) == 32

    def test_alphanumeric_only(self):
        token = generate_approval_token(length=100)
        assert token.isalnum()

    def test_unique_tokens(self):
        tokens = {generate_approval_token() for _ in range(100)}
        assert len(tokens) == 100  # All unique

    def test_length_1(self):
        token = generate_approval_token(length=1)
        assert len(token) == 1


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

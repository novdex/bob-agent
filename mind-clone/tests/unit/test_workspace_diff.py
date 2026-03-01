"""
Tests for core/workspace_diff.py — Workspace diff utilities.
"""
import pytest
from mind_clone.core.workspace_diff import (
    compute_workspace_diff,
    approve_workspace_diff,
    reject_workspace_diff,
    list_pending_diffs,
    evaluate_workspace_diff_gate,
)


class TestWorkspaceDiff:
    """Test workspace diff operations."""

    def test_compute_diff_returns_dict(self):
        result = compute_workspace_diff(1)
        assert isinstance(result, dict)
        assert "files_changed" in result
        assert "lines_added" in result
        assert "lines_removed" in result

    def test_compute_diff_with_since(self):
        result = compute_workspace_diff(1, since="2024-01-01")
        assert isinstance(result, dict)

    def test_approve_diff(self):
        assert approve_workspace_diff(1, "diff_123") is True

    def test_reject_diff(self):
        assert reject_workspace_diff(1, "diff_123") is True

    def test_list_pending_diffs_empty(self):
        result = list_pending_diffs()
        assert isinstance(result, list)

    def test_list_pending_diffs_with_owner(self):
        result = list_pending_diffs(owner_id=1)
        assert isinstance(result, list)

    def test_evaluate_gate(self):
        result = evaluate_workspace_diff_gate(1)
        assert result["ok"] is True
        assert "needs_approval" in result

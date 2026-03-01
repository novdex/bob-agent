"""
Tests for core/tasks.py — Task management functions.
"""
import pytest
from mind_clone.core.tasks import (
    TASK_STATUS_OPEN,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELLED,
    _get_valid_transitions,
    normalize_task_plan,
    _get_task_queue,
    mark_owner_active,
    get_owner_execution_lock,
)


class TestStatusConstants:
    """Test task status constants."""

    def test_status_values(self):
        assert TASK_STATUS_OPEN == "open"
        assert TASK_STATUS_QUEUED == "queued"
        assert TASK_STATUS_RUNNING == "running"
        assert TASK_STATUS_BLOCKED == "blocked"
        assert TASK_STATUS_DONE == "done"
        assert TASK_STATUS_FAILED == "failed"
        assert TASK_STATUS_CANCELLED == "cancelled"


class TestStatusTransitions:
    """Test valid status transitions."""

    def test_open_transitions(self):
        valid = _get_valid_transitions(TASK_STATUS_OPEN)
        assert TASK_STATUS_QUEUED in valid
        assert TASK_STATUS_CANCELLED in valid
        assert TASK_STATUS_DONE not in valid

    def test_queued_transitions(self):
        valid = _get_valid_transitions(TASK_STATUS_QUEUED)
        assert TASK_STATUS_RUNNING in valid
        assert TASK_STATUS_CANCELLED in valid

    def test_running_transitions(self):
        valid = _get_valid_transitions(TASK_STATUS_RUNNING)
        assert TASK_STATUS_DONE in valid
        assert TASK_STATUS_FAILED in valid
        assert TASK_STATUS_BLOCKED in valid
        assert TASK_STATUS_CANCELLED in valid

    def test_done_is_terminal(self):
        valid = _get_valid_transitions(TASK_STATUS_DONE)
        assert valid == []

    def test_cancelled_is_terminal(self):
        valid = _get_valid_transitions(TASK_STATUS_CANCELLED)
        assert valid == []

    def test_failed_can_retry(self):
        valid = _get_valid_transitions(TASK_STATUS_FAILED)
        assert TASK_STATUS_QUEUED in valid

    def test_blocked_can_requeue(self):
        valid = _get_valid_transitions(TASK_STATUS_BLOCKED)
        assert TASK_STATUS_QUEUED in valid

    def test_unknown_status(self):
        valid = _get_valid_transitions("nonexistent_status")
        assert valid == []


class TestNormalizeTaskPlan:
    """Test task plan normalization."""

    def test_empty_plan(self):
        assert normalize_task_plan(None) == []
        assert normalize_task_plan([]) == []

    def test_dict_steps(self):
        plan = [
            {"description": "Step 1", "status": "pending"},
            {"description": "Step 2", "tool": "search_web"},
        ]
        result = normalize_task_plan(plan)
        assert len(result) == 2
        assert result[0]["description"] == "Step 1"
        assert result[0]["status"] == "pending"
        assert result[1]["tool"] == "search_web"

    def test_string_steps(self):
        plan = ["Do thing one", "Do thing two"]
        result = normalize_task_plan(plan)
        assert len(result) == 2
        assert result[0]["description"] == "Do thing one"
        assert result[0]["status"] == "pending"
        assert result[0]["tool"] is None

    def test_step_id_generation(self):
        plan = [{"description": "A"}, {"description": "B"}]
        result = normalize_task_plan(plan)
        assert result[0]["step_id"] == "step_0"
        assert result[1]["step_id"] == "step_1"

    def test_preserves_existing_step_id(self):
        plan = [{"step_id": "custom_id", "description": "X"}]
        result = normalize_task_plan(plan)
        assert result[0]["step_id"] == "custom_id"

    def test_default_fields(self):
        plan = [{}]
        result = normalize_task_plan(plan)
        step = result[0]
        assert step["status"] == "pending"
        assert step["args"] == {}
        assert step["depends_on"] == []
        assert step["tool"] is None
        assert step["started_at"] is None
        assert step["completed_at"] is None
        assert step["error"] is None


class TestTaskQueue:
    """Test task queue management."""

    def test_get_task_queue_returns_queue(self):
        from queue import Queue
        q = _get_task_queue()
        assert isinstance(q, Queue)

    def test_get_task_queue_singleton(self):
        q1 = _get_task_queue()
        q2 = _get_task_queue()
        assert q1 is q2


class TestOwnerTracking:
    """Test owner tracking utilities."""

    def test_mark_owner_active(self):
        # Should not raise
        mark_owner_active(999)

    def test_get_owner_execution_lock(self):
        import threading
        lock = get_owner_execution_lock(999)
        assert hasattr(lock, 'acquire') and hasattr(lock, 'release')

    def test_same_owner_same_lock(self):
        lock1 = get_owner_execution_lock(888)
        lock2 = get_owner_execution_lock(888)
        assert lock1 is lock2

    def test_different_owners_different_locks(self):
        lock1 = get_owner_execution_lock(111)
        lock2 = get_owner_execution_lock(222)
        assert lock1 is not lock2

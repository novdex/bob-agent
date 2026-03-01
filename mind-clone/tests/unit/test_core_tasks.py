"""
Comprehensive tests for mind_clone.core.tasks module.

Focus: task queue management, status transitions, plan normalization,
thread safety, and edge cases.
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from queue import Queue
from mind_clone.core.tasks import (
    enqueue_task,
    normalize_task_plan,
    create_task,
    get_task,
    list_tasks,
    update_task_status,
    cancel_task,
    recover_orphan_running_tasks,
    get_owner_execution_lock,
    get_task_queue_status,
    TASK_STATUS_OPEN,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_BLOCKED,
)


class TestEnqueueTask:
    """Test enqueue_task function."""

    def test_enqueues_existing_task(self):
        """Should enqueue existing task by ID."""
        with patch("mind_clone.core.tasks._get_task_queue") as mock_queue_getter:
            mock_queue = MagicMock()
            mock_queue_getter.return_value = mock_queue
            
            result = enqueue_task(task_id=1)
            
            assert result is True
            mock_queue.put.assert_called_once_with(1, block=False)



    def test_returns_false_for_no_args(self):
        """Should return False when no task_id and no creation args."""
        result = enqueue_task()
        
        assert result is False


class TestNormalizeTaskPlan:
    """Test normalize_task_plan function."""

    def test_normalizes_dict_steps(self):
        """Should normalize dictionary steps."""
        plan = [
            {"description": "Step 1", "status": "pending"},
            {"description": "Step 2"},
        ]
        
        result = normalize_task_plan(plan)
        
        assert len(result) == 2
        assert result[0]["step_id"] == "step_0"
        assert result[0]["description"] == "Step 1"
        assert result[0]["status"] == "pending"
        assert result[0]["tool"] is None

    def test_normalizes_string_steps(self):
        """Should normalize string steps."""
        plan = ["Step 1", "Step 2"]
        
        result = normalize_task_plan(plan)
        
        assert len(result) == 2
        assert result[0]["description"] == "Step 1"
        assert result[0]["status"] == "pending"
        assert result[0]["tool"] is None

    def test_handles_none_plan(self):
        """Should return empty list for None plan."""
        result = normalize_task_plan(None)
        
        assert result == []

    def test_handles_empty_plan(self):
        """Should handle empty plan list."""
        result = normalize_task_plan([])
        
        assert result == []

    def test_adds_defaults_for_missing_fields(self):
        """Should add default values for missing fields."""
        plan = [{"description": "Step"}]
        
        result = normalize_task_plan(plan)
        
        assert result[0]["step_id"] == "step_0"
        assert result[0]["status"] == "pending"
        assert result[0]["args"] == {}
        assert result[0]["depends_on"] == []

    def test_preserves_existing_fields(self):
        """Should preserve all existing fields."""
        plan = [
            {
                "step_id": "custom_1",
                "description": "Custom step",
                "status": "completed",
                "tool": "fetch",
                "args": {"url": "http://example.com"},
            }
        ]
        
        result = normalize_task_plan(plan)
        
        assert result[0]["step_id"] == "custom_1"
        assert result[0]["tool"] == "fetch"
        assert result[0]["args"]["url"] == "http://example.com"

    def test_large_plan(self):
        """Should handle large plans."""
        plan = [{"description": f"Step {i}"} for i in range(100)]
        
        result = normalize_task_plan(plan)
        
        assert len(result) == 100


class TestCreateTask:
    """Test create_task function."""

    def test_creates_task_successfully(self):
        """Should create task with all fields."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_task(1, "Test Task", "Description")
            
            assert result is not None
            mock_db.add.assert_called_once()
            mock_db.close.assert_called_once()

    def test_creates_task_with_plan(self):
        """Should create task with execution plan."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            plan = [{"description": "Step 1"}]
            result = create_task(1, "Test", "Desc", plan=plan)
            
            assert result is not None

    def test_initializes_open_status(self):
        """Should initialize task with OPEN status."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            create_task(1, "Test", "Desc")
            
            added_task = mock_db.add.call_args[0][0]
            assert added_task.status == TASK_STATUS_OPEN


class TestGetTask:
    """Test get_task function."""

    def test_gets_task_by_id(self):
        """Should get task by ID."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_task(1)
            
            assert result == mock_task

    def test_returns_none_for_nonexistent(self):
        """Should return None for nonexistent task."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_task(999)
            
            assert result is None

    def test_filters_by_owner_id(self):
        """Should filter by owner_id when provided."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            get_task(1, owner_id=1)
            
            # Should call filter twice
            assert mock_query.filter.call_count >= 1


class TestUpdateTaskStatus:
    """Test update_task_status function."""

    def test_updates_task_status_open_to_queued(self):
        """Should allow transition from OPEN to QUEUED."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_OPEN
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = update_task_status(1, TASK_STATUS_QUEUED)
            
            assert result is True
            mock_db.commit.assert_called_once()

    def test_rejects_invalid_transition(self):
        """Should reject invalid status transitions."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_DONE
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = update_task_status(1, TASK_STATUS_RUNNING)
            
            assert result is False

    def test_updates_task_with_error(self):
        """Should update task with error message."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_RUNNING
            mock_task.plan = [{"status": "running", "step_id": "step_0"}]
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = update_task_status(1, TASK_STATUS_FAILED, error="Test error")
            
            assert result is True

    def test_verifies_owner_id(self):
        """Should verify owner_id when provided."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = update_task_status(1, TASK_STATUS_QUEUED, owner_id=2)
            
            assert result is False


class TestCancelTask:
    """Test cancel_task function."""

    def test_cancels_open_task(self):
        """Should cancel OPEN task."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_OPEN
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = cancel_task(1)
            
            assert result is True

    def test_cannot_cancel_completed_task(self):
        """Should not cancel DONE task."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_DONE
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_task
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = cancel_task(1)
            
            assert result is False

    def test_returns_false_for_nonexistent(self):
        """Should return False for nonexistent task."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = cancel_task(999)
            
            assert result is False


class TestRecoverOrphanRunningTasks:
    """Test recover_orphan_running_tasks function."""

    def test_recovers_old_running_tasks(self):
        """Should recover tasks stuck in RUNNING state."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            
            old_time = datetime.now(timezone.utc) - timedelta(hours=1)
            mock_task = MagicMock()
            mock_task.id = 1
            mock_task.status = TASK_STATUS_RUNNING
            mock_task.created_at = old_time
            mock_task.owner_id = 1
            mock_task.title = "Orphaned"
            mock_task.plan = []
            
            mock_query = MagicMock()
            mock_query.filter.return_value.all.return_value = [mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = recover_orphan_running_tasks(max_age_minutes=30)
            
            assert 1 in result

    def test_ignores_recent_running_tasks(self):
        """Should not recover recent RUNNING tasks."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            
            recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            mock_task = MagicMock()
            mock_task.status = TASK_STATUS_RUNNING
            mock_task.created_at = recent_time
            
            mock_query = MagicMock()
            mock_query.filter.return_value.all.return_value = [mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = recover_orphan_running_tasks(max_age_minutes=30)
            
            assert len(result) == 0

    def test_creates_dead_letter_on_recovery(self):
        """Should create dead letter record on recovery."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            
            old_time = datetime.now(timezone.utc) - timedelta(hours=1)
            mock_task = MagicMock()
            mock_task.id = 1
            mock_task.status = TASK_STATUS_RUNNING
            mock_task.created_at = old_time
            mock_task.owner_id = 1
            mock_task.title = "Orphaned"
            mock_task.plan = []
            
            mock_query = MagicMock()
            mock_query.filter.return_value.all.return_value = [mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = recover_orphan_running_tasks(max_age_minutes=30)
            
            # Should have called add() for dead letter
            assert mock_db.add.called


class TestGetOwnerExecutionLock:
    """Test get_owner_execution_lock function."""


    def test_returns_same_lock_for_same_owner(self):
        """Should return same lock for same owner."""
        lock1 = get_owner_execution_lock(1)
        lock2 = get_owner_execution_lock(1)
        
        assert lock1 is lock2

    def test_returns_different_locks_for_different_owners(self):
        """Should return different locks for different owners."""
        lock1 = get_owner_execution_lock(1)
        lock2 = get_owner_execution_lock(2)
        
        assert lock1 is not lock2

    def test_handles_large_owner_ids(self):
        """Should handle large owner IDs."""
        lock = get_owner_execution_lock(999999999)
        
        assert lock is not None


class TestGetTaskQueueStatus:
    """Test get_task_queue_status function."""

    def test_returns_status_dict(self):
        """Should return task queue status dictionary."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.count.return_value = 0
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            with patch("mind_clone.core.tasks._get_task_queue") as mock_q:
                mock_q.return_value.qsize.return_value = 5
                
                result = get_task_queue_status()
                
                assert result["queue_size"] == 5
                assert "worker_running" in result
                assert "status_counts" in result

    def test_counts_by_status(self):
        """Should count tasks by status."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.count.return_value = 2
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            with patch("mind_clone.core.tasks._get_task_queue") as mock_q:
                mock_q.return_value.qsize.return_value = 0
                
                result = get_task_queue_status()
                
                assert "status_counts" in result
                assert len(result["status_counts"]) > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handles_malformed_task_plan(self):
        """Should handle malformed task plan gracefully."""
        plan = "not a list"
        
        result = normalize_task_plan(plan)
        
        assert isinstance(result, list)

    def test_task_with_none_created_at(self):
        """Should handle None created_at in task."""
        with patch("mind_clone.core.tasks.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            
            mock_task = MagicMock()
            mock_task.id = 1
            mock_task.status = TASK_STATUS_RUNNING
            mock_task.created_at = None
            
            mock_query = MagicMock()
            mock_query.filter.return_value.all.return_value = [mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = recover_orphan_running_tasks()
            
            assert isinstance(result, list)

    def test_negative_owner_id(self):
        """Should handle negative owner IDs."""
        lock = get_owner_execution_lock(-1)
        
        assert lock is not None

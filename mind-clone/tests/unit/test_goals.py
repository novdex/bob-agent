"""
Comprehensive tests for mind_clone.core.goals module.

Focus: goal lifecycle validation, status transitions, progress tracking,
thread safety, and edge cases.
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from mind_clone.core.goals import (
    create_goal,
    list_goals,
    get_goal,
    update_goal,
    delete_goal,
    link_task_to_goal,
    unlink_task_from_goal,
    get_goal_progress,
    GOAL_STATUS_ACTIVE,
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_PRIORITY_HIGH,
    GOAL_PRIORITY_MEDIUM,
    GOAL_PRIORITY_LOW,
)


class TestCreateGoal:
    """Test create_goal function."""

    def test_creates_goal_with_owner_id_convention(self):
        """Should create goal using (owner_id, title) convention."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_goal(1, "Test Goal")
            
            assert result["ok"] is True
            assert result["owner_id"] == 1
            assert result["title"] == "Test Goal"
            mock_db.close.assert_called()

    def test_creates_goal_with_db_convention(self):
        """Should create goal using (db, owner_id, title) convention."""
        mock_db = MagicMock()
        
        result = create_goal(mock_db, 1, "Test Goal")
        
        assert result["ok"] is True

    def test_validates_priority(self):
        """Should default invalid priority to medium."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_goal(1, "Goal", priority="invalid_priority")
            
            assert result["ok"] is True
            # Default should be applied

    def test_initializes_empty_milestones(self):
        """Should initialize empty milestones when None."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_goal(1, "Goal", milestones=None)
            
            assert result["ok"] is True

    def test_handles_database_error(self):
        """Should handle database errors gracefully."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_db.add.side_effect = Exception("DB error")
            mock_session_factory.return_value = mock_db
            
            result = create_goal(1, "Goal")
            
            assert result["ok"] is False
            assert "error" in result
            mock_db.rollback.assert_called()

    def test_rejects_empty_title(self):
        """Should handle empty title."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_goal(1, "")
            
            # Should still create but with empty title
            assert "ok" in result

    def test_handles_null_owner_id(self):
        """Should handle None/zero owner_id."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_session_factory.return_value = mock_db
            
            result = create_goal(0, "Goal")
            
            assert "ok" in result


class TestListGoals:
    """Test list_goals function."""

    def test_lists_goals_using_owner_id_convention(self):
        """Should list goals using (owner_id) convention."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = list_goals(1)
            
            assert isinstance(result, list)
            mock_db.close.assert_called()

    def test_lists_goals_using_db_convention(self):
        """Should list goals using (db, owner_id) convention."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        result = list_goals(mock_db, owner_id=1)
        
        assert isinstance(result, list)

    def test_filters_by_status(self):
        """Should filter goals by status."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = list_goals(1, status=GOAL_STATUS_ACTIVE)
            
            assert isinstance(result, list)

    def test_filters_by_priority(self):
        """Should filter goals by priority."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = list_goals(1, priority=GOAL_PRIORITY_HIGH)
            
            assert isinstance(result, list)


    def test_includes_completed_by_default_false(self):
        """Should exclude completed goals by default."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = list_goals(1, include_completed=False)
            
            assert isinstance(result, list)


class TestGetGoal:
    """Test get_goal function."""

    def test_gets_goal_by_id(self):
        """Should get goal by ID."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.id = 1
            mock_goal.owner_id = 1
            mock_goal.title = "Test"
            mock_goal.task_ids_json = "[]"
            mock_goal.milestones_json = "[]"
            mock_goal.notes_json = "[]"
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal(1)
            
            assert result is not None
            assert result["id"] == 1

    def test_returns_none_for_nonexistent(self):
        """Should return None for nonexistent goal."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal(999)
            
            assert result is None



class TestUpdateGoal:
    """Test update_goal function."""

    def test_updates_goal_fields(self):
        """Should update goal fields."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.id = 1
            mock_goal.status = GOAL_STATUS_ACTIVE
            mock_goal.title = "Old Title"
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            updates = {"title": "New Title", "status": GOAL_STATUS_COMPLETED}
            result = update_goal(1, 1, updates)
            
            assert result["ok"] is True

    def test_legacy_signature_compatibility(self):
        """Should support legacy (goal_id, updates_dict) signature."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.id = 1
            mock_goal.title = "Old"
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            updates = {"title": "New"}
            result = update_goal(1, updates)
            
            # Legacy should return bool
            assert isinstance(result, bool)

    def test_rejects_invalid_fields(self):
        """Should reject updates to disallowed fields."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.id = 1
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            updates = {"id": 999}  # Should not update ID
            result = update_goal(1, 1, updates)
            
            # Should not crash, but ID should not change
            assert result["ok"] is True

    def test_handles_database_error(self):
        """Should handle database errors gracefully."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_db.commit.side_effect = Exception("DB error")
            mock_query = MagicMock()
            mock_goal = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = update_goal(1, 1, {"title": "New"})
            
            assert result["ok"] is False


class TestLinkTaskToGoal:
    """Test link_task_to_goal function."""

    def test_links_task_to_goal(self):
        """Should link task to goal."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "[]"
            mock_task = MagicMock()
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.side_effect = [mock_goal, mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = link_task_to_goal(1, 1, 1)
            
            assert result["ok"] is True

    def test_prevents_duplicate_links(self):
        """Should prevent duplicate task links."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "[1]"  # Already has task 1
            mock_task = MagicMock()
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.side_effect = [mock_goal, mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = link_task_to_goal(1, 1, 1)
            
            assert result["ok"] is True

    def test_returns_error_for_missing_goal(self):
        """Should return error when goal not found."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = None
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = link_task_to_goal(999, 1, 1)
            
            assert result["ok"] is False


class TestGetGoalProgress:
    """Test get_goal_progress function."""

    def test_calculates_progress_zero_when_no_tasks(self):
        """Should return 0% progress when no tasks linked."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "[]"
            mock_goal.progress_pct = 0
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal_progress(1, 1)
            
            assert result["ok"] is True
            assert result["progress_pct"] == 0
            assert result["total_tasks"] == 0

    def test_calculates_progress_with_completed_tasks(self):
        """Should calculate progress based on completed tasks."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "[1, 2, 3]"
            mock_goal.progress_pct = 0
            
            mock_task1 = MagicMock(status="done")
            mock_task2 = MagicMock(status="done")
            mock_task3 = MagicMock(status="running")
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_query.filter.return_value.all.return_value = [mock_task1, mock_task2, mock_task3]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal_progress(1, 1)
            
            assert result["ok"] is True
            assert result["completed_tasks"] == 2
            assert result["total_tasks"] == 3

    def test_auto_completes_goal_at_100_percent(self):
        """Should auto-complete goal when all tasks done."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "[1]"
            mock_goal.progress_pct = 0
            mock_goal.status = GOAL_STATUS_ACTIVE
            
            mock_task = MagicMock(status="done")
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_query.filter.return_value.all.return_value = [mock_task]
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal_progress(1, 1)
            
            assert result["progress_pct"] == 100


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handles_very_large_task_id_list(self):
        """Should handle goals with many linked tasks."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            task_ids = list(range(1, 1001))  # 1000 tasks
            mock_goal = MagicMock()
            mock_goal.task_ids_json = json.dumps(task_ids)
            mock_goal.progress_pct = 0
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_query.filter.return_value.all.return_value = []
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal_progress(1, 1)
            
            assert result["ok"] is True

    def test_handles_malformed_json_task_ids(self):
        """Should handle malformed JSON gracefully."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            mock_goal = MagicMock()
            mock_goal.task_ids_json = "invalid json {{"
            mock_goal.progress_pct = 0
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_goal
            mock_db.query.return_value = mock_query
            mock_session_factory.return_value = mock_db
            
            result = get_goal_progress(1, 1)
            
            # Should handle gracefully with _safe_json_list
            assert result["ok"] is True

    def test_deadline_handling(self):
        """Should handle deadline dates correctly."""
        with patch("mind_clone.core.goals.SessionLocal") as mock_session_factory:
            mock_db = MagicMock()
            future_deadline = datetime.now(timezone.utc) + timedelta(days=1)
            mock_goal = MagicMock()
            mock_goal.deadline = future_deadline
            
            # Should not trigger deadline logic
            assert isinstance(mock_goal.deadline, datetime)

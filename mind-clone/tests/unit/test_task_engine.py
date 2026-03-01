"""
Tests for services/task_engine.py — Task engine CRUD and helpers.
"""
import pytest

try:
    from mind_clone.services.task_engine import (
    TASK_STATUS_OPEN,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELLED,
    create_task,
    get_task,
    list_tasks,
    update_task_status,
    cancel_task,
    execute_task_step,
    run_task,
    format_task_details,
    task_to_dict,
    enqueue_task,
    task_progress,
    current_task_step,
    normalize_task_plan,
    create_queued_task,
    get_user_task_by_id,
    list_recent_tasks,
    _validate_checkpoint_replay_state,
    )
    _IMPORT_OK = True
except (SyntaxError, ImportError):
    _IMPORT_OK = False

from mind_clone.database.models import Task

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="services.task_engine import failed (Python 3.10 compat)")


class TestStatusConstants:
    """Test status constants match expected values."""

    def test_statuses(self):
        assert TASK_STATUS_OPEN == "open"
        assert TASK_STATUS_QUEUED == "queued"
        assert TASK_STATUS_RUNNING == "running"
        assert TASK_STATUS_DONE == "done"
        assert TASK_STATUS_FAILED == "failed"
        assert TASK_STATUS_CANCELLED == "cancelled"


class TestCreateTask:
    """Test task creation."""

    def test_creates_task(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Test", "Do something")
        assert task.id is not None
        assert task.title == "Test"
        assert task.description == "Do something"
        assert task.status == TASK_STATUS_OPEN
        assert task.owner_id == sample_user.id

    def test_creates_with_plan(self, db_session, sample_user):
        plan = [{"description": "Step 1"}, {"description": "Step 2"}]
        task = create_task(db_session, sample_user.id, "Planned", "With plan", plan=plan)
        assert len(task.plan) == 2

    def test_creates_with_empty_plan(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "No plan", "Desc")
        assert task.plan == []


class TestGetTask:
    """Test task retrieval."""

    def test_gets_existing_task(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Find me", "desc")
        found = get_task(db_session, task.id, sample_user.id)
        assert found is not None
        assert found.id == task.id

    def test_returns_none_for_wrong_owner(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Find me", "desc")
        found = get_task(db_session, task.id, 99999)
        assert found is None

    def test_returns_none_for_nonexistent(self, db_session, sample_user):
        found = get_task(db_session, 99999, sample_user.id)
        assert found is None


class TestListTasks:
    """Test task listing."""

    def test_lists_tasks(self, db_session, sample_user):
        create_task(db_session, sample_user.id, "T1", "d1")
        create_task(db_session, sample_user.id, "T2", "d2")
        tasks = list_tasks(db_session, sample_user.id)
        assert len(tasks) >= 2

    def test_filters_by_status(self, db_session, sample_user):
        t1 = create_task(db_session, sample_user.id, "Open", "d")
        t2 = create_task(db_session, sample_user.id, "Done", "d")
        t2.status = TASK_STATUS_DONE
        db_session.commit()
        open_tasks = list_tasks(db_session, sample_user.id, status=TASK_STATUS_OPEN)
        assert all(t.status == TASK_STATUS_OPEN for t in open_tasks)

    def test_respects_limit(self, db_session, sample_user):
        for i in range(5):
            create_task(db_session, sample_user.id, f"T{i}", "d")
        tasks = list_tasks(db_session, sample_user.id, limit=2)
        assert len(tasks) == 2


class TestUpdateTaskStatus:
    """Test status updates."""

    def test_updates_status(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d")
        update_task_status(db_session, task, TASK_STATUS_RUNNING)
        db_session.refresh(task)
        assert task.status == TASK_STATUS_RUNNING


class TestCancelTask:
    """Test task cancellation."""

    def test_cancels_open_task(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d")
        ok, msg = cancel_task(db_session, task)
        assert ok is True
        assert task.status == TASK_STATUS_CANCELLED

    def test_cannot_cancel_done_task(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d")
        task.status = TASK_STATUS_DONE
        db_session.commit()
        ok, msg = cancel_task(db_session, task)
        assert ok is False
        assert "terminal" in msg.lower()

    def test_cannot_cancel_failed_task(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d")
        task.status = TASK_STATUS_FAILED
        db_session.commit()
        ok, msg = cancel_task(db_session, task)
        assert ok is False


class TestExecuteTaskStep:
    """Test single step execution."""

    def test_out_of_range(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d", plan=[])
        result = execute_task_step(db_session, task, 0)
        assert result["ok"] is False
        assert "out of range" in result["error"].lower()

    def test_executes_step(self, db_session, sample_user):
        plan = [{"description": "Step 1", "status": "pending"}]
        task = create_task(db_session, sample_user.id, "T", "d", plan=plan)
        result = execute_task_step(db_session, task, 0)
        assert result["ok"] is True


class TestRunTask:
    """Test full task execution."""

    def test_runs_empty_plan(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "T", "d", plan=[])
        result = run_task(db_session, task)
        assert result["ok"] is True
        assert task.status == TASK_STATUS_DONE

    def test_runs_plan_steps(self, db_session, sample_user):
        plan = [{"description": "S1", "status": "pending"}, {"description": "S2", "status": "pending"}]
        task = create_task(db_session, sample_user.id, "T", "d", plan=plan)
        result = run_task(db_session, task)
        assert result["ok"] is True
        assert task.status == TASK_STATUS_DONE


class TestFormatTaskDetails:
    """Test task formatting."""

    def test_format_basic(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Format Test", "A description")
        text = format_task_details(task)
        assert "Format Test" in text
        assert "open" in text.lower()

    def test_format_with_plan(self, db_session, sample_user):
        plan = [{"description": "Do X", "status": "pending"}]
        task = create_task(db_session, sample_user.id, "Plan Task", "desc", plan=plan)
        text = format_task_details(task)
        assert "Do X" in text
        assert "1 steps" in text


class TestTaskToDict:
    """Test task serialization."""

    def test_converts_to_dict(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Dict Test", "desc")
        d = task_to_dict(task)
        assert d["id"] == task.id
        assert d["title"] == "Dict Test"
        assert d["status"] == "open"
        assert isinstance(d["plan"], list)


class TestTaskProgress:
    """Test progress calculation."""

    def test_empty_plan(self):
        assert task_progress(None) == (0, 0)
        assert task_progress([]) == (0, 0)

    def test_no_done(self):
        plan = [{"status": "pending"}, {"status": "running"}]
        assert task_progress(plan) == (0, 2)

    def test_some_done(self):
        plan = [{"status": "done"}, {"status": "completed"}, {"status": "pending"}]
        assert task_progress(plan) == (2, 3)

    def test_all_done(self):
        plan = [{"status": "done"}, {"status": "completed"}]
        assert task_progress(plan) == (2, 2)


class TestCurrentTaskStep:
    """Test current step detection."""

    def test_empty_plan(self):
        assert current_task_step(None) is None
        assert current_task_step([]) is None

    def test_finds_pending_step(self):
        plan = [{"status": "done", "description": "S1"}, {"status": "pending", "description": "S2"}]
        assert current_task_step(plan) == "S2"

    def test_all_done_returns_none(self):
        plan = [{"status": "done", "description": "S1"}, {"status": "completed", "description": "S2"}]
        assert current_task_step(plan) is None

    def test_uses_name_field(self):
        plan = [{"status": "running", "name": "step_name"}]
        assert current_task_step(plan) == "step_name"


class TestNormalizeTaskPlan:
    """Test plan normalization."""

    def test_none_returns_empty(self):
        assert normalize_task_plan(None) == []

    def test_list_passthrough(self):
        plan = [{"a": 1}]
        assert normalize_task_plan(plan) == plan

    def test_non_list_returns_empty(self):
        assert normalize_task_plan("not a list") == []


class TestEnqueueTask:
    """Test task queue."""

    def test_enqueue_no_error(self):
        enqueue_task(99999)

    def test_enqueue_idempotent(self):
        enqueue_task(88888)
        enqueue_task(88888)  # Should not raise


class TestCreateQueuedTask:
    """Test create_queued_task helper."""

    def test_creates_queued(self, db_session, sample_user):
        task, ok = create_queued_task(db_session, sample_user.id, "QT", "goal")
        assert ok is True
        assert task.status == TASK_STATUS_QUEUED
        assert task.title == "QT"


class TestAliases:
    """Test alias functions."""

    def test_get_user_task_by_id(self, db_session, sample_user):
        task = create_task(db_session, sample_user.id, "Alias", "d")
        found = get_user_task_by_id(db_session, sample_user.id, task.id)
        assert found is not None
        assert found.id == task.id

    def test_list_recent_tasks(self, db_session, sample_user):
        create_task(db_session, sample_user.id, "Recent", "d")
        tasks = list_recent_tasks(db_session, sample_user.id)
        assert len(tasks) >= 1


class TestCheckpointValidation:
    """Test checkpoint replay validation."""

    def test_always_returns_true(self):
        ok, _, _ = _validate_checkpoint_replay_state(None, [], {})
        assert ok is True

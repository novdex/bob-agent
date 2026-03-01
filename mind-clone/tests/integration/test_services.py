"""
Integration tests for services.
"""
import pytest


class TestTaskEngine:
    """Test task engine service."""
    
    def test_create_task(self, db_session, sample_user):
        """Test creating a task through task engine."""
        from mind_clone.services.task_engine import create_task
        
        task = create_task(
            db=db_session,
            owner_id=sample_user.id,
            title="Test Task",
            description="Test description"
        )
        
        assert task is not None
        assert task.title == "Test Task"
        assert task.status == "open"
    
    def test_list_tasks(self, db_session, sample_user):
        """Test listing tasks."""
        from mind_clone.services.task_engine import create_task, list_tasks
        
        # Create a task
        create_task(db_session, sample_user.id, "Task 1", "Desc 1")
        create_task(db_session, sample_user.id, "Task 2", "Desc 2")
        
        # List tasks
        tasks = list_tasks(db_session, sample_user.id)
        assert len(tasks) == 2
    
    def test_cancel_task(self, db_session, sample_user):
        """Test cancelling a task."""
        from mind_clone.services.task_engine import create_task, cancel_task, get_task
        
        task = create_task(db_session, sample_user.id, "Task to cancel", "Desc")
        assert task.status == "open"
        
        success, msg = cancel_task(db_session, task)
        assert success is True
        assert task.status == "cancelled"


class TestScheduler:
    """Test scheduler service."""
    
    def test_create_job(self, db_session, sample_user):
        """Test creating a scheduled job."""
        from mind_clone.services.scheduler import create_job
        
        job = create_job(
            db=db_session,
            owner_id=sample_user.id,
            name="Test Job",
            command="echo test",
            schedule="0 9 * * *"
        )
        
        assert job is not None
        assert job.name == "Test Job"
        assert job.enabled is True
    
    def test_list_jobs(self, db_session, sample_user):
        """Test listing scheduled jobs."""
        from mind_clone.services.scheduler import create_job, list_jobs
        
        create_job(db_session, sample_user.id, "Job 1", "echo 1", "0 9 * * *")
        create_job(db_session, sample_user.id, "Job 2", "echo 2", "0 10 * * *")
        
        jobs = list_jobs(db_session, sample_user.id)
        assert len(jobs) == 2
    
    def test_disable_job(self, db_session, sample_user):
        """Test disabling a job."""
        from mind_clone.services.scheduler import create_job, disable_job
        
        job = create_job(db_session, sample_user.id, "Job to disable", "echo test", "0 9 * * *")
        assert job.enabled is True
        
        success = disable_job(db_session, job.id, sample_user.id)
        assert success is True
        assert job.enabled is False


class TestCoreTasks:
    """Test core tasks module."""
    
    def test_enqueue_task(self, db_session, sample_user):
        """Test enqueueing a task."""
        from mind_clone.core.tasks import enqueue_task
        
        task = enqueue_task(
            owner_id=sample_user.id,
            title="Enqueued Task",
            description="Test",
        )
        
        assert task is not None
        assert task.title == "Enqueued Task"
    
    def test_goal_lifecycle(self, db_session, sample_user):
        """Test full goal lifecycle."""
        from mind_clone.core.goals import create_goal, get_goal, list_goals, update_goal
        
        # Create
        goal = create_goal(sample_user.id, "Test Goal", "Description")
        assert goal is not None
        
        # Get
        fetched = get_goal(goal["id"])
        assert fetched is not None
        
        # Update
        success = update_goal(goal["id"], {"status": "completed"})
        assert success is True
        
        # List
        goals = list_goals(sample_user.id)
        assert len(goals) >= 1

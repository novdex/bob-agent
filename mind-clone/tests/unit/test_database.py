"""
Tests for database models.
"""
import pytest
from datetime import datetime
from mind_clone.database.models import (
    User, Task, Goal, ConversationMessage,
    ScheduledJob, ApprovalRequest
)


class TestUserModel:
    """Test User model."""
    
    def test_user_creation(self, db_session):
        """Test creating a user."""
        import uuid
        unique = str(uuid.uuid4())[:8]
        user = User(
            username=f"testuser_{unique}",
            telegram_chat_id=f"chat_{unique}",
        )
        db_session.add(user)
        db_session.commit()
        
        assert user.id is not None
        assert user.telegram_chat_id == f"chat_{unique}"
        assert user.created_at is not None
    
    def test_user_unique_username(self, db_session):
        """Test that username must be unique."""
        from sqlalchemy.exc import IntegrityError
        
        user1 = User(username="uniqueuser", telegram_chat_id="chat1")
        db_session.add(user1)
        db_session.commit()
        
        user2 = User(username="uniqueuser", telegram_chat_id="chat2")
        db_session.add(user2)
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestTaskModel:
    """Test Task model."""
    
    def test_task_creation(self, db_session, sample_user):
        """Test creating a task."""
        task = Task(
            owner_id=sample_user.id,
            title="Test Task",
            description="Test description",
            status="open",
            plan=[{"step": 1, "action": "test"}],
        )
        db_session.add(task)
        db_session.commit()
        
        assert task.id is not None
        assert task.title == "Test Task"
        assert task.status == "open"
        assert len(task.plan) == 1
    
    def test_task_status_transitions(self, db_session, sample_user):
        """Test task status can be updated."""
        task = Task(
            owner_id=sample_user.id,
            title="Test Task",
            status="open",
        )
        db_session.add(task)
        db_session.commit()
        
        # Update status
        task.status = "running"
        db_session.commit()
        db_session.refresh(task)
        
        assert task.status == "running"


class TestGoalModel:
    """Test Goal model."""
    
    def test_goal_creation(self, db_session, sample_user):
        """Test creating a goal."""
        goal = Goal(
            owner_id=sample_user.id,
            title="Test Goal",
            description="Test goal description",
            status="active",
        )
        db_session.add(goal)
        db_session.commit()
        
        assert goal.id is not None
        assert goal.title == "Test Goal"
        assert goal.status == "active"

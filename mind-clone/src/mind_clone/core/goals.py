"""
Goal management system.

Provides CRUD operations, goal supervisor logic, and goal-task linking.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable

from sqlalchemy.orm import Session

from ..database.models import Goal, Task, User
from ..database.session import SessionLocal
from ..config import settings
from ..utils import utc_now_iso, _safe_json_list, truncate_text

logger = logging.getLogger("mind_clone.core.goals")

# Goal status constants
GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_PAUSED = "paused"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_FAILED = "failed"
GOAL_STATUS_CANCELLED = "cancelled"

# Priority constants
GOAL_PRIORITY_LOW = "low"
GOAL_PRIORITY_MEDIUM = "medium"
GOAL_PRIORITY_HIGH = "high"
GOAL_PRIORITY_CRITICAL = "critical"

# Supervisor state
_supervisor_running = False
_supervisor_thread: Optional[threading.Thread] = None
_goal_callbacks: List[Callable] = []

__all__ = [
    "create_goal",
    "list_goals",
    "get_goal",
    "update_goal",
    "delete_goal",
    "run_goal_supervisor",
    "start_goal_supervisor",
    "stop_goal_supervisor",
    "link_task_to_goal",
    "unlink_task_from_goal",
    "get_goal_progress",
    "GOAL_STATUS_ACTIVE",
    "GOAL_STATUS_PAUSED",
    "GOAL_STATUS_COMPLETED",
    "GOAL_STATUS_FAILED",
    "GOAL_STATUS_CANCELLED",
    "GOAL_PRIORITY_LOW",
    "GOAL_PRIORITY_MEDIUM",
    "GOAL_PRIORITY_HIGH",
    "GOAL_PRIORITY_CRITICAL",
]


def create_goal(
    db_or_owner_id,
    owner_id_or_title = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    success_criteria: Optional[str] = None,
    priority: str = GOAL_PRIORITY_MEDIUM,
    deadline: Optional[datetime] = None,
    milestones: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Create a new goal.

    Accepts both ``create_goal(owner_id, title, ...)`` and
    ``create_goal(db, owner_id, title, ...)`` calling conventions
    for backward compatibility with routes.py.
    """
    # Detect calling convention
    if isinstance(db_or_owner_id, int):
        # create_goal(owner_id, title, ...)
        owner_id = db_or_owner_id
        title = str(owner_id_or_title or title or "")
        _own_db = True
        db = SessionLocal()
    else:
        # create_goal(db, owner_id, title, ...)
        db = db_or_owner_id
        owner_id = int(owner_id_or_title or 0)
        _own_db = False
    try:
        # Validate priority
        valid_priorities = [GOAL_PRIORITY_LOW, GOAL_PRIORITY_MEDIUM, GOAL_PRIORITY_HIGH, GOAL_PRIORITY_CRITICAL]
        if priority not in valid_priorities:
            priority = GOAL_PRIORITY_MEDIUM
        
        goal = Goal(
            owner_id=owner_id,
            title=title,
            description=description,
            success_criteria=success_criteria,
            status=GOAL_STATUS_ACTIVE,
            priority=priority,
            deadline=deadline,
            progress_pct=0,
            task_ids_json="[]",
            milestones_json=json.dumps(milestones or []),
            notes_json="[]",
        )
        
        db.add(goal)
        db.commit()
        db.refresh(goal)
        
        logger.info(f"Created goal {goal.id} for owner {owner_id}: {title}")
        
        return {
            "ok": True,
            "id": goal.id,
            "goal_id": goal.id,
            "owner_id": goal.owner_id,
            "title": goal.title,
            "status": goal.status,
            "priority": goal.priority,
            "created_at": goal.created_at.isoformat() if goal.created_at else None,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create goal: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if _own_db:
            db.close()


def list_goals(
    db_or_owner_id,
    owner_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_completed: bool = False,
) -> List[Dict[str, Any]]:
    """
    List goals for an owner with optional filtering.

    Accepts both ``list_goals(owner_id, ...)`` and
    ``list_goals(db, owner_id, ...)`` calling conventions.
    """
    if isinstance(db_or_owner_id, int):
        real_owner_id = db_or_owner_id
        _own_db = True
        db = SessionLocal()
    else:
        db = db_or_owner_id
        real_owner_id = int(owner_id or 0)
        _own_db = False
    try:
        query = db.query(Goal).filter(Goal.owner_id == real_owner_id)

        if status:
            query = query.filter(Goal.status == status)
        elif not include_completed:
            query = query.filter(Goal.status != GOAL_STATUS_COMPLETED)

        if priority:
            query = query.filter(Goal.priority == priority)

        goals = query.order_by(Goal.created_at.desc()).offset(offset).limit(limit).all()

        return [_goal_to_dict(g) for g in goals]
    finally:
        if _own_db:
            db.close()


def get_goal(goal_id: int, owner_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Get a goal by ID with optional ownership verification.
    
    Args:
        goal_id: The goal ID
        owner_id: Optional owner ID to verify
        
    Returns:
        Goal dictionary or None
    """
    db = SessionLocal()
    try:
        query = db.query(Goal).filter(Goal.id == goal_id)
        if owner_id:
            query = query.filter(Goal.owner_id == owner_id)
        
        goal = query.first()
        return _goal_to_dict(goal) if goal else None
    finally:
        db.close()


def update_goal(
    goal_id: int,
    owner_id: int | Dict[str, Any],
    updates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any] | bool:
    """
    Update a goal with partial updates.
    
    Args:
        goal_id: The goal ID
        owner_id: The owner ID for verification
        updates: Dictionary of fields to update
        
    Returns:
        Update result
    """
    legacy_bool_result = False
    resolved_owner_id: Optional[int]
    resolved_updates: Dict[str, Any]
    if updates is None and isinstance(owner_id, dict):
        # Backward-compatible signature: update_goal(goal_id, updates) -> bool
        legacy_bool_result = True
        resolved_owner_id = None
        resolved_updates = owner_id
    else:
        resolved_owner_id = int(owner_id) if owner_id is not None and not isinstance(owner_id, dict) else None
        resolved_updates = dict(updates or {})

    db = SessionLocal()
    try:
        query = db.query(Goal).filter(Goal.id == goal_id)
        if resolved_owner_id is not None:
            query = query.filter(Goal.owner_id == resolved_owner_id)
        goal = query.first()
        
        if not goal:
            return False if legacy_bool_result else {"ok": False, "error": "Goal not found"}
        
        # Update allowed fields
        allowed_fields = {
            "title", "description", "success_criteria", "status",
            "priority", "deadline", "progress_pct"
        }
        
        for field, value in resolved_updates.items():
            if field in allowed_fields and hasattr(goal, field):
                setattr(goal, field, value)
        
        # Handle special fields
        if "milestones" in resolved_updates:
            goal.milestones_json = json.dumps(resolved_updates["milestones"])
        
        if "notes" in resolved_updates:
            goal.notes_json = json.dumps(resolved_updates["notes"])
        
        goal.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        logger.info(f"Updated goal {goal_id}")
        if legacy_bool_result:
            return True
        return {"ok": True, "goal": _goal_to_dict(goal)}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update goal {goal_id}: {e}")
        return False if legacy_bool_result else {"ok": False, "error": str(e)}
    finally:
        db.close()


def delete_goal(goal_id: int, owner_id: int) -> Dict[str, Any]:
    """
    Delete a goal.
    
    Args:
        goal_id: The goal ID
        owner_id: The owner ID for verification
        
    Returns:
        Delete result
    """
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(
            Goal.id == goal_id,
            Goal.owner_id == owner_id,
        ).first()
        
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        
        db.delete(goal)
        db.commit()
        
        logger.info(f"Deleted goal {goal_id}")
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete goal {goal_id}: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def link_task_to_goal(goal_id: int, task_id: int, owner_id: int) -> Dict[str, Any]:
    """
    Link a task to a goal.
    
    Args:
        goal_id: The goal ID
        task_id: The task ID to link
        owner_id: The owner ID for verification
        
    Returns:
        Link result
    """
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(
            Goal.id == goal_id,
            Goal.owner_id == owner_id,
        ).first()
        
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.owner_id == owner_id,
        ).first()
        
        if not task:
            return {"ok": False, "error": "Task not found"}
        
        # Add task to goal's task list
        task_ids = _safe_json_list(goal.task_ids_json)
        if task_id not in task_ids:
            task_ids.append(task_id)
            goal.task_ids_json = json.dumps(task_ids)
            db.commit()
        
        logger.info(f"Linked task {task_id} to goal {goal_id}")
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to link task to goal: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def unlink_task_from_goal(goal_id: int, task_id: int, owner_id: int) -> Dict[str, Any]:
    """
    Unlink a task from a goal.
    
    Args:
        goal_id: The goal ID
        task_id: The task ID to unlink
        owner_id: The owner ID for verification
        
    Returns:
        Unlink result
    """
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(
            Goal.id == goal_id,
            Goal.owner_id == owner_id,
        ).first()
        
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        
        task_ids = _safe_json_list(goal.task_ids_json)
        if task_id in task_ids:
            task_ids.remove(task_id)
            goal.task_ids_json = json.dumps(task_ids)
            db.commit()
        
        logger.info(f"Unlinked task {task_id} from goal {goal_id}")
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to unlink task from goal: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def get_goal_progress(goal_id: int, owner_id: int) -> Dict[str, Any]:
    """
    Calculate goal progress based on linked tasks.
    
    Args:
        goal_id: The goal ID
        owner_id: The owner ID for verification
        
    Returns:
        Progress information
    """
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(
            Goal.id == goal_id,
            Goal.owner_id == owner_id,
        ).first()
        
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        
        task_ids = _safe_json_list(goal.task_ids_json)
        
        if not task_ids:
            return {
                "ok": True,
                "goal_id": goal_id,
                "progress_pct": goal.progress_pct or 0,
                "total_tasks": 0,
                "completed_tasks": 0,
            }
        
        # Get task statuses
        tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
        
        total = len(tasks)
        completed = sum(1 for t in tasks if t.status == "done")
        failed = sum(1 for t in tasks if t.status == "failed")
        in_progress = sum(1 for t in tasks if t.status == "running")
        
        # Calculate percentage
        if total > 0:
            calculated_pct = int((completed / total) * 100)
        else:
            calculated_pct = 0
        
        # Update goal if percentage changed significantly
        if abs(calculated_pct - (goal.progress_pct or 0)) >= 5:
            goal.progress_pct = calculated_pct
            if calculated_pct == 100 and goal.status == GOAL_STATUS_ACTIVE:
                goal.status = GOAL_STATUS_COMPLETED
            db.commit()
        
        return {
            "ok": True,
            "goal_id": goal_id,
            "progress_pct": calculated_pct,
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "in_progress_tasks": in_progress,
        }
    except Exception as e:
        logger.error(f"Failed to get goal progress: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def run_goal_supervisor() -> None:
    """
    Run the goal supervisor to monitor and manage goals.
    
    This function performs periodic checks on goals:
    - Updates progress for active goals
    - Checks for expired deadlines
    - Triggers notifications for milestones
    """
    global _supervisor_running
    
    if not settings.GOAL_SYSTEM_ENABLED:
        logger.debug("Goal system disabled, skipping supervisor")
        return
    
    _supervisor_running = True
    logger.info("Goal supervisor running")
    
    db = SessionLocal()
    try:
        # Update progress for active goals
        active_goals = db.query(Goal).filter(
            Goal.status == GOAL_STATUS_ACTIVE,
        ).all()
        
        for goal in active_goals:
            try:
                # Check deadline
                if goal.deadline and goal.deadline < datetime.now(timezone.utc):
                    logger.warning(f"Goal {goal.id} deadline passed")
                    # Could trigger notifications here
                
                # Update progress
                task_ids = _safe_json_list(goal.task_ids_json)
                if task_ids:
                    tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
                    if tasks:
                        completed = sum(1 for t in tasks if t.status == "done")
                        progress = int((completed / len(tasks)) * 100)
                        
                        if progress != goal.progress_pct:
                            goal.progress_pct = progress
                            
                            # Auto-complete if all tasks done
                            if progress == 100:
                                goal.status = GOAL_STATUS_COMPLETED
                                logger.info(f"Goal {goal.id} auto-completed")
                        
                        db.commit()
                
            except Exception as e:
                logger.error(f"Error processing goal {goal.id}: {e}")
        
        # Trigger callbacks
        for callback in _goal_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Goal callback error: {e}")
        
        logger.debug("Goal supervisor cycle completed")
        
    except Exception as e:
        logger.error(f"Goal supervisor error: {e}")
    finally:
        db.close()
        _supervisor_running = False


def start_goal_supervisor(interval_seconds: int = 300) -> bool:
    """
    Start the goal supervisor in a background thread.
    
    Args:
        interval_seconds: Seconds between supervisor runs
        
    Returns:
        True if started successfully
    """
    global _supervisor_thread
    
    def supervisor_loop():
        while True:
            try:
                run_goal_supervisor()
            except Exception as e:
                logger.error(f"Supervisor loop error: {e}")
            time.sleep(interval_seconds)
    
    if _supervisor_thread is None or not _supervisor_thread.is_alive():
        _supervisor_thread = threading.Thread(
            target=supervisor_loop,
            name="GoalSupervisor",
            daemon=True,
        )
        _supervisor_thread.start()
        logger.info("Goal supervisor started")
        return True
    
    return False


def stop_goal_supervisor() -> bool:
    """Stop the goal supervisor."""
    global _supervisor_thread, _supervisor_running
    
    _supervisor_running = False
    # Note: Thread will exit on next sleep
    return True


def register_goal_callback(callback: Callable) -> None:
    """Register a callback to be called during supervisor runs."""
    _goal_callbacks.append(callback)


# ---------------------------------------------------------------------------
# Aliases expected by routes.py
# ---------------------------------------------------------------------------

def update_goal_progress(db: Session, goal: Goal) -> None:
    """Update a goal's progress based on linked tasks (called from routes)."""
    try:
        result = get_goal_progress(goal.id, goal.owner_id)
        if result.get("ok"):
            goal.progress_pct = result.get("progress_pct", goal.progress_pct)
            db.commit()
    except Exception as exc:
        logger.warning("update_goal_progress failed goal=%d: %s", goal.id, exc)


def decompose_goal_into_tasks(
    db: Session, goal: Goal, identity: Optional[Dict] = None,
) -> List[int]:
    """Decompose a goal into sub-tasks. Returns list of created task IDs.

    Currently a placeholder — full decomposition requires LLM call.
    """
    return []


def _goal_to_dict(goal: Goal) -> Dict[str, Any]:
    """Convert Goal model to dictionary."""
    return {
        "id": goal.id,
        "owner_id": goal.owner_id,
        "title": goal.title,
        "description": goal.description,
        "success_criteria": goal.success_criteria,
        "status": goal.status,
        "progress_pct": goal.progress_pct,
        "priority": goal.priority,
        "deadline": goal.deadline.isoformat() if goal.deadline else None,
        "task_ids": _safe_json_list(goal.task_ids_json),
        "milestones": _safe_json_list(goal.milestones_json),
        "notes": _safe_json_list(goal.notes_json),
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }

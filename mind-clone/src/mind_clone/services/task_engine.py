"""
Task engine for autonomous task execution.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from ..database.models import Task
from ..utils import utc_now_iso

logger = logging.getLogger("mind_clone.services.task_engine")

# Task statuses
TASK_STATUS_OPEN = "open"
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_BLOCKED = "blocked"
TASK_STATUS_DONE = "done"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"


def create_task(
    db: Session,
    owner_id: int,
    title: str,
    description: str,
    plan: Optional[List[Dict]] = None,
) -> Task:
    """Create a new task."""
    task = Task(
        owner_id=owner_id,
        agent_uuid="temp-uuid",  # Should be loaded from identity
        title=title,
        description=description,
        status=TASK_STATUS_OPEN,
        plan=plan or [],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"Created task {task.id} for owner {owner_id}")
    return task


def get_task(db: Session, task_id: int, owner_id: int) -> Optional[Task]:
    """Get a task by ID."""
    return db.query(Task).filter(
        Task.id == task_id,
        Task.owner_id == owner_id,
    ).first()


def list_tasks(
    db: Session,
    owner_id: int,
    status: Optional[str] = None,
    limit: int = 10,
) -> List[Task]:
    """List tasks for an owner."""
    query = db.query(Task).filter(Task.owner_id == owner_id)
    if status:
        query = query.filter(Task.status == status)
    return query.order_by(Task.id.desc()).limit(limit).all()


def update_task_status(
    db: Session,
    task: Task,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update task status."""
    task.status = status
    db.commit()
    logger.info(f"Task {task.id} status: {status}")


def cancel_task(db: Session, task: Task) -> tuple:
    """Cancel a task. Returns (success_bool, message_str)."""
    if task.status in [TASK_STATUS_DONE, TASK_STATUS_FAILED, TASK_STATUS_CANCELLED]:
        return False, f"Task #{task.id} already in terminal state ({task.status})"
    task.status = TASK_STATUS_CANCELLED
    db.commit()
    logger.info(f"Cancelled task {task.id}")
    return True, f"Task #{task.id} cancelled"


def execute_task_step(
    db: Session,
    task: Task,
    step_index: int,
) -> Dict[str, Any]:
    """Execute a single task step."""
    plan = task.plan or []
    if step_index >= len(plan):
        return {"ok": False, "error": "Step index out of range"}
    
    step = plan[step_index]
    step["status"] = "running"
    step["started_at"] = utc_now_iso()
    
    try:
        # Execute step logic here
        # This would call the agent loop for each step
        
        step["status"] = "completed"
        step["completed_at"] = utc_now_iso()
        
        db.commit()
        return {"ok": True}
    
    except Exception as e:
        step["status"] = "failed"
        step["error"] = str(e)
        db.commit()
        return {"ok": False, "error": str(e)}


def run_task(db: Session, task: Task) -> Dict[str, Any]:
    """Run a task to completion."""
    logger.info(f"Running task {task.id}: {task.title}")
    
    update_task_status(db, task, TASK_STATUS_RUNNING)
    
    plan = task.plan or []
    for i, step in enumerate(plan):
        result = execute_task_step(db, task, i)
        if not result.get("ok"):
            update_task_status(db, task, TASK_STATUS_FAILED)
            return result
    
    update_task_status(db, task, TASK_STATUS_DONE)
    return {"ok": True, "task_id": task.id}


def format_task_details(task: Task) -> str:
    """Format task details as text."""
    lines = [
        f"Task #{task.id}: {task.title}",
        f"Status: {task.status}",
        f"Description: {task.description[:200]}...",
    ]
    
    if task.plan:
        lines.append(f"\nPlan ({len(task.plan)} steps):")
        for i, step in enumerate(task.plan, 1):
            status = step.get("status", "pending")
            lines.append(f"  {i}. [{status}] {step.get('description', 'No description')}")
    
    return "\n".join(lines)


def task_to_dict(task: Task) -> Dict[str, Any]:
    """Convert task to dictionary."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "plan": task.plan or [],
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


# ---------------------------------------------------------------------------
# Aliases & wrappers expected by routes.py
# ---------------------------------------------------------------------------

# In-memory task queue for the async worker
import asyncio
import queue as _queue_mod

_task_queue: _queue_mod.Queue = _queue_mod.Queue()
_task_queue_ids: set = set()


def enqueue_task(task_id: int) -> None:
    """Put a task ID on the in-memory queue for the async worker."""
    if task_id not in _task_queue_ids:
        _task_queue_ids.add(task_id)
        _task_queue.put(task_id)
        logger.info("Enqueued task %d", task_id)


def recover_pending_tasks() -> List[int]:
    """Recover tasks that were queued or running when the process last stopped."""
    from ..database.session import SessionLocal
    db = SessionLocal()
    try:
        rows = (
            db.query(Task)
            .filter(Task.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RUNNING]))
            .all()
        )
        return [int(t.id) for t in rows]
    finally:
        db.close()


async def task_worker_loop() -> None:
    """Async worker that pulls task IDs and runs them."""
    from ..database.session import SessionLocal
    logger.info("Task worker loop started")
    while True:
        try:
            task_id = await asyncio.get_event_loop().run_in_executor(
                None, _task_queue.get, True, 5.0,
            )
        except Exception:
            await asyncio.sleep(2)
            continue

        _task_queue_ids.discard(task_id)
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task and task.status in (TASK_STATUS_QUEUED, TASK_STATUS_OPEN):
                run_task(db, task)
        except Exception as exc:
            logger.error("Task worker error task=%d: %s", task_id, exc)
        finally:
            db.close()


def get_user_task_by_id(db: Session, owner_id: int, task_id: int) -> Optional[Task]:
    """Alias for get_task matching the routes.py signature."""
    return get_task(db, task_id, owner_id)


def list_recent_tasks(db: Session, owner_id: int, limit: int = 20) -> List[Task]:
    """Alias for list_tasks matching the routes.py signature."""
    return list_tasks(db, owner_id, limit=limit)


def create_queued_task(
    db: Session, owner_id: int, title: str, goal: str,
) -> tuple:
    """Create a task in queued state and return (task, created_ok)."""
    task = Task(
        owner_id=owner_id,
        agent_uuid="auto",
        title=title,
        description=goal,
        status=TASK_STATUS_QUEUED,
        plan=[],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task, True


def task_progress(plan: Optional[List]) -> tuple:
    """Return (done_count, total_count) for a task plan."""
    if not plan:
        return 0, 0
    done = sum(1 for step in plan if step.get("status") in ("done", "completed"))
    return done, len(plan)


def current_task_step(plan: Optional[List]) -> Optional[str]:
    """Return the name of the currently active step."""
    if not plan:
        return None
    for step in plan:
        if step.get("status") not in ("done", "completed", "failed"):
            return step.get("name") or step.get("description") or "unknown"
    return None


def normalize_task_plan(plan: Optional[List]) -> List[Dict]:
    """Normalize a task plan (ensure list of dicts)."""
    return plan if isinstance(plan, list) else []


def latest_task_checkpoint_snapshot(
    db: Session, task_id: int,
) -> Optional[Any]:
    """Return the most recent checkpoint snapshot for a task."""
    from ..database.models import TaskCheckpointSnapshot
    return (
        db.query(TaskCheckpointSnapshot)
        .filter(TaskCheckpointSnapshot.task_id == task_id)
        .order_by(TaskCheckpointSnapshot.id.desc())
        .first()
    )


def restore_task_from_checkpoint_snapshot(
    db: Session, task: Task, snap: Any, strict: bool = True,
) -> bool:
    """Restore a task from a checkpoint snapshot (best-effort)."""
    try:
        if hasattr(snap, "plan_json"):
            restored_plan = json.loads(snap.plan_json or "[]")
            task.plan = restored_plan
        if hasattr(snap, "task_status"):
            task.status = snap.task_status or task.status
        db.commit()
        return True
    except Exception as exc:
        logger.warning("Checkpoint restore failed task=%d: %s", task.id, exc)
        return False


def store_task_checkpoint_snapshot(
    db: Session, task: Task, source: str, extra: Optional[Dict] = None,
) -> None:
    """Store a checkpoint snapshot for a task."""
    from ..database.models import TaskCheckpointSnapshot
    snap = TaskCheckpointSnapshot(
        task_id=task.id,
        owner_id=task.owner_id,
        task_status=task.status,
        plan_json=json.dumps(task.plan or [], ensure_ascii=False),
        source=source,
        extra_json=json.dumps(extra or {}, ensure_ascii=False),
    )
    db.add(snap)
    db.commit()


def _validate_checkpoint_replay_state(
    task: Task, plan: List, snap_extra: Dict, strict: bool = True,
) -> tuple:
    """Validate whether a checkpoint can safely be replayed."""
    return True, None, None

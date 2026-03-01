"""
Task functions for full task management.

Provides task queue management, status transitions, worker loop, and orphan recovery.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable
from queue import Queue, Empty
from contextlib import contextmanager

from sqlalchemy.orm import Session

from ..database.models import Task, TaskDeadLetter
from ..database.session import SessionLocal
from ..config import settings
from ..utils import utc_now_iso, generate_uuid, _safe_json_list

logger = logging.getLogger("mind_clone.core.tasks")

# Task status constants (defined locally to avoid circular import)
TASK_STATUS_OPEN = "open"
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_BLOCKED = "blocked"
TASK_STATUS_DONE = "done"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"

# Task queue management
_task_queue: Optional[Queue] = None
_task_queue_lock = threading.Lock()
_task_worker_thread: Optional[threading.Thread] = None
_task_worker_running = False

# Owner execution tracking
_owner_last_active: Dict[int, float] = {}
_owner_execution_locks: Dict[int, threading.Lock] = {}
_owner_locks_master_lock = threading.Lock()

__all__ = [
    "enqueue_task",
    "normalize_task_plan",
    "TASK_STATUS_OPEN",
    "TASK_STATUS_QUEUED",
    "TASK_STATUS_RUNNING",
    "TASK_STATUS_BLOCKED",
    "TASK_STATUS_DONE",
    "TASK_STATUS_FAILED",
    "TASK_STATUS_CANCELLED",
    "recover_orphan_running_tasks",
    "task_worker_loop",
    "mark_owner_active",
    "get_owner_execution_lock",
    "create_task",
    "get_task",
    "list_tasks",
    "update_task_status",
    "cancel_task",
    "run_task",
    "get_task_queue_status",
    "pause_task_worker",
    "resume_task_worker",
]


def _get_task_queue() -> Queue:
    """Get or create the global task queue."""
    global _task_queue
    with _task_queue_lock:
        if _task_queue is None:
            _task_queue = Queue(maxsize=1000)
        return _task_queue


def enqueue_task(
    task_id: Optional[int] = None,
    *,
    owner_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    plan: Optional[List[Dict]] = None,
) -> bool | Task:
    """
    Add a task to the execution queue.

    Args:
        task_id: Existing task ID to enqueue.
        owner_id/title/description/plan: Optional compatibility path to create a task
            and enqueue it in one call.

    Returns:
        True/False for task_id mode, or Task instance for create+enqueue mode.
    """
    if task_id is None and owner_id is not None and title:
        db = SessionLocal()
        try:
            new_task = Task(
                owner_id=int(owner_id),
                agent_uuid=generate_uuid(),
                title=str(title),
                description=str(description or ""),
                status=TASK_STATUS_QUEUED,
                plan=plan or [],
            )
            db.add(new_task)
            db.commit()
            db.refresh(new_task)
            queue = _get_task_queue()
            queue.put(int(new_task.id), block=False)
            logger.info(f"Created and enqueued task {new_task.id} for owner {owner_id}")
            return new_task
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create/enqueue task for owner {owner_id}: {e}")
            raise
        finally:
            db.close()

    if task_id is None:
        return False

    try:
        queue = _get_task_queue()
        queue.put(int(task_id), block=False)
        logger.info(f"Task {task_id} enqueued for execution")
        return True
    except Exception as e:
        logger.error(f"Failed to enqueue task {task_id}: {e}")
        return False


def normalize_task_plan(plan: Optional[List[Dict]]) -> List[Dict]:
    """
    Normalize a task plan to ensure proper structure.

    Args:
        plan: Raw task plan from database

    Returns:
        Normalized plan list with proper step structure
    """
    if not plan:
        return []

    normalized = []
    for i, step in enumerate(plan):
        if isinstance(step, dict):
            normalized_step = {
                "step_id": step.get("step_id", f"step_{i}"),
                "description": step.get("description", f"Step {i + 1}"),
                "status": step.get("status", "pending"),
                "tool": step.get("tool"),
                "args": step.get("args", {}),
                "depends_on": step.get("depends_on", []),
                "started_at": step.get("started_at"),
                "completed_at": step.get("completed_at"),
                "error": step.get("error"),
            }
            normalized.append(normalized_step)
        else:
            # Handle string steps
            normalized.append(
                {
                    "step_id": f"step_{i}",
                    "description": str(step),
                    "status": "pending",
                    "tool": None,
                    "args": {},
                    "depends_on": [],
                }
            )

    return normalized


def create_task(
    owner_id: int,
    title: str,
    description: str,
    plan: Optional[List[Dict]] = None,
) -> Task:
    """
    Create a new task with full database persistence.

    Args:
        owner_id: The owner/user ID
        title: Task title
        description: Task description
        plan: Optional task execution plan

    Returns:
        Created Task instance
    """
    db = SessionLocal()
    try:
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
    finally:
        db.close()


def get_task(task_id: int, owner_id: Optional[int] = None) -> Optional[Task]:
    """
    Get a task by ID with optional owner filtering.

    Args:
        task_id: The task ID
        owner_id: Optional owner ID to filter by

    Returns:
        Task instance or None if not found
    """
    db = SessionLocal()
    try:
        query = db.query(Task).filter(Task.id == task_id)
        if owner_id is not None:
            query = query.filter(Task.owner_id == owner_id)
        return query.first()
    finally:
        db.close()


def list_tasks(
    owner_id: int,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Task]:
    """
    List tasks for an owner with optional filtering.

    Args:
        owner_id: The owner/user ID
        status: Optional status filter
        limit: Maximum number of results
        offset: Pagination offset

    Returns:
        List of Task instances
    """
    db = SessionLocal()
    try:
        query = db.query(Task).filter(Task.owner_id == owner_id)
        if status:
            query = query.filter(Task.status == status)
        return query.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
    finally:
        db.close()


def _get_valid_transitions(current_status: str) -> List[str]:
    """Get valid status transitions from a given status."""
    transitions = {
        TASK_STATUS_OPEN: [TASK_STATUS_QUEUED, TASK_STATUS_CANCELLED],
        TASK_STATUS_QUEUED: [TASK_STATUS_RUNNING, TASK_STATUS_CANCELLED],
        TASK_STATUS_RUNNING: [
            TASK_STATUS_DONE,
            TASK_STATUS_FAILED,
            TASK_STATUS_BLOCKED,
            TASK_STATUS_CANCELLED,
        ],
        TASK_STATUS_BLOCKED: [TASK_STATUS_QUEUED, TASK_STATUS_CANCELLED],
        TASK_STATUS_DONE: [],  # Terminal state
        TASK_STATUS_FAILED: [TASK_STATUS_QUEUED, TASK_STATUS_CANCELLED],  # Can retry
        TASK_STATUS_CANCELLED: [],  # Terminal state
    }
    return transitions.get(current_status, [])


def update_task_status(
    task_id: int,
    status: str,
    error: Optional[str] = None,
    owner_id: Optional[int] = None,
) -> bool:
    """
    Update task status with transition validation.

    Args:
        task_id: The task ID
        status: New status value
        error: Optional error message
        owner_id: Optional owner ID for verification

    Returns:
        True if successfully updated
    """
    db = SessionLocal()
    try:
        query = db.query(Task).filter(Task.id == task_id)
        if owner_id is not None:
            query = query.filter(Task.owner_id == owner_id)
        task = query.first()
        if not task:
            logger.warning(f"Task {task_id} not found for status update")
            return False

        # Validate status transition
        valid_transitions = _get_valid_transitions(task.status)
        if status not in valid_transitions:
            logger.warning(
                f"Invalid status transition: {task.status} -> {status} for task {task_id}"
            )
            return False

        task.status = status

        # Update plan step if error provided
        if error and task.plan:
            plan = normalize_task_plan(task.plan)
            for step in plan:
                if step.get("status") == "running":
                    step["status"] = "failed"
                    step["error"] = error
                    step["completed_at"] = utc_now_iso()
                    break
            task.plan = plan

        db.commit()
        logger.info(f"Task {task_id} status updated to {status}")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update task {task_id} status: {e}")
        return False
    finally:
        db.close()


def cancel_task(task_id: int, owner_id: Optional[int] = None) -> bool:
    """
    Cancel a task if it can be cancelled.

    Args:
        task_id: The task ID
        owner_id: Optional owner ID for verification

    Returns:
        True if successfully cancelled
    """
    db = SessionLocal()
    try:
        query = db.query(Task).filter(Task.id == task_id)
        if owner_id is not None:
            query = query.filter(Task.owner_id == owner_id)
        task = query.first()
        if not task:
            return False

        terminal_states = [TASK_STATUS_DONE, TASK_STATUS_FAILED, TASK_STATUS_CANCELLED]
        if task.status in terminal_states:
            logger.info(f"Task {task_id} already in terminal state: {task.status}")
            return False

        task.status = TASK_STATUS_CANCELLED
        db.commit()
        logger.info(f"Task {task_id} cancelled")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cancel task {task_id}: {e}")
        return False
    finally:
        db.close()


def format_task_details(task: Task) -> str:
    """Format task details as text."""
    lines = [
        f"Task #{task.id}: {task.title}",
        f"Status: {task.status}",
        f"Description: {task.description[:200]}..."
        if len(task.description) > 200
        else f"Description: {task.description}",
    ]

    if task.plan:
        lines.append(f"\nPlan ({len(task.plan)} steps):")
        for i, step in enumerate(task.plan, 1):
            status = step.get("status", "pending") if isinstance(step, dict) else "pending"
            desc = step.get("description", str(step)) if isinstance(step, dict) else str(step)
            lines.append(f"  {i}. [{status}] {desc}")

    return "\n".join(lines)


def task_to_dict(task: Task) -> Dict[str, Any]:
    """Convert task to dictionary."""
    return {
        "id": task.id,
        "owner_id": task.owner_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "plan": task.plan or [],
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def execute_task_step(
    task: Task,
    step_index: int,
) -> Dict[str, Any]:
    """
    Execute a single task step.

    Args:
        task: The task
        step_index: Step index to execute

    Returns:
        Execution result
    """
    plan = normalize_task_plan(task.plan)
    if step_index >= len(plan):
        return {"ok": False, "error": "Step index out of range"}

    step = plan[step_index]
    step["status"] = "running"
    step["started_at"] = utc_now_iso()

    try:
        # Execute step logic here
        # This would call the agent loop for each step
        # For now, mark as completed

        step["status"] = "completed"
        step["completed_at"] = utc_now_iso()

        # Update task plan
        db = SessionLocal()
        try:
            db_task = db.query(Task).filter(Task.id == task.id).first()
            if db_task:
                db_task.plan = plan
                db.commit()
        finally:
            db.close()

        return {"ok": True}

    except Exception as e:
        step["status"] = "failed"
        step["error"] = str(e)

        # Update task plan with error
        db = SessionLocal()
        try:
            db_task = db.query(Task).filter(Task.id == task.id).first()
            if db_task:
                db_task.plan = plan
                db.commit()
        finally:
            db.close()

        return {"ok": False, "error": str(e)}


def run_task(task_id: int) -> Dict[str, Any]:
    """
    Run a task to completion.

    Args:
        task_id: The task ID

    Returns:
        Execution result dictionary
    """
    logger.info(f"Running task {task_id}")

    task = get_task(task_id)
    if not task:
        return {"ok": False, "error": f"Task {task_id} not found"}

    # Update status to running
    if not update_task_status(task_id, TASK_STATUS_RUNNING):
        return {"ok": False, "error": f"Failed to set task {task_id} to running"}

    plan = normalize_task_plan(task.plan)

    for i, step in enumerate(plan):
        result = execute_task_step(task, i)
        if not result.get("ok"):
            update_task_status(task_id, TASK_STATUS_FAILED, error=result.get("error"))
            return result

    update_task_status(task_id, TASK_STATUS_DONE)
    return {"ok": True, "task_id": task.id}


def recover_orphan_running_tasks(max_age_minutes: int = 30) -> List[int]:
    """
    Recover tasks stuck in 'running' state (e.g., after crash).

    Args:
        max_age_minutes: Maximum age in minutes to consider a task orphaned

    Returns:
        List of recovered task IDs
    """
    recovered = []

    db = SessionLocal()
    try:
        # Find tasks in running state that haven't been updated recently
        orphans = (
            db.query(Task)
            .filter(
                Task.status == TASK_STATUS_RUNNING,
            )
            .all()
        )

        for task in orphans:
            # Check if task has been running too long
            task_age = datetime.now(timezone.utc) - (task.created_at or datetime.now(timezone.utc))
            if task_age > timedelta(minutes=max_age_minutes):
                # Move to failed state and create dead letter
                task.status = TASK_STATUS_FAILED

                dead_letter = TaskDeadLetter(
                    task_id=task.id,
                    owner_id=task.owner_id,
                    title=task.title,
                    reason="Orphaned task recovered - agent may have crashed",
                    snapshot_json=json.dumps(
                        {
                            "original_status": TASK_STATUS_RUNNING,
                            "recovered_at": utc_now_iso(),
                            "plan": task.plan,
                        }
                    ),
                )
                db.add(dead_letter)
                recovered.append(task.id)
                logger.warning(f"Recovered orphaned task {task.id}")

        db.commit()
        return recovered
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to recover orphan tasks: {e}")
        return []
    finally:
        db.close()


def task_worker_loop(
    stop_event: Optional[threading.Event] = None,
    task_processor: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Main task worker loop that processes queued tasks.

    Args:
        stop_event: Optional event to signal worker to stop
        task_processor: Optional custom task processor function
    """
    global _task_worker_running

    _task_worker_running = True
    logger.info("Task worker loop started")

    queue = _get_task_queue()

    while _task_worker_running and (stop_event is None or not stop_event.is_set()):
        try:
            # Wait for a task with timeout to allow checking stop_event
            task_id = queue.get(timeout=1.0)

            # Get task details
            task = get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found in queue processing")
                queue.task_done()
                continue

            # Update status to running
            if not update_task_status(task_id, TASK_STATUS_RUNNING):
                logger.error(f"Failed to set task {task_id} to running")
                queue.task_done()
                continue

            # Mark owner active
            mark_owner_active(task.owner_id)

            try:
                if task_processor:
                    task_processor(task_id)
                else:
                    _default_task_processor(task_id)
            except Exception as e:
                logger.error(f"Task {task_id} processing failed: {e}")
                update_task_status(task_id, TASK_STATUS_FAILED, error=str(e))
            finally:
                queue.task_done()

        except Empty:
            # No tasks in queue, continue loop
            continue
        except Exception as e:
            logger.error(f"Task worker loop error: {e}")
            time.sleep(1)  # Brief pause on error

    logger.info("Task worker loop stopped")
    _task_worker_running = False


def _default_task_processor(task_id: int) -> None:
    """Default task processor that runs task via task engine."""
    result = run_task(task_id)
    if not result.get("ok"):
        logger.error(f"Task {task_id} failed: {result.get('error')}")


def start_task_worker() -> bool:
    """Start the background task worker thread."""
    global _task_worker_thread, _task_worker_running

    with _task_queue_lock:
        if _task_worker_thread is not None and _task_worker_thread.is_alive():
            logger.info("Task worker already running")
            return True

        _task_worker_running = True
        _task_worker_thread = threading.Thread(
            target=task_worker_loop,
            name="TaskWorker",
            daemon=True,
        )
        _task_worker_thread.start()
        logger.info("Task worker started")
        return True


def stop_task_worker(timeout: float = 5.0) -> bool:
    """Stop the background task worker thread."""
    global _task_worker_running, _task_worker_thread

    _task_worker_running = False

    if _task_worker_thread and _task_worker_thread.is_alive():
        _task_worker_thread.join(timeout=timeout)
        if _task_worker_thread.is_alive():
            logger.warning("Task worker did not stop gracefully")
            return False

    logger.info("Task worker stopped")
    return True


def pause_task_worker() -> bool:
    """Pause task worker (stop processing new tasks)."""
    global _task_worker_running
    _task_worker_running = False
    logger.info("Task worker paused")
    return True


def resume_task_worker() -> bool:
    """Resume task worker."""
    return start_task_worker()


def get_task_queue_status() -> Dict[str, Any]:
    """Get current task queue status."""
    queue = _get_task_queue()

    # Count tasks by status
    db = SessionLocal()
    try:
        status_counts = {}
        for status in [
            TASK_STATUS_OPEN,
            TASK_STATUS_QUEUED,
            TASK_STATUS_RUNNING,
            TASK_STATUS_BLOCKED,
            TASK_STATUS_DONE,
            TASK_STATUS_FAILED,
            TASK_STATUS_CANCELLED,
        ]:
            status_counts[status] = db.query(Task).filter(Task.status == status).count()

        return {
            "queue_size": queue.qsize(),
            "worker_running": _task_worker_running,
            "worker_alive": _task_worker_thread is not None and _task_worker_thread.is_alive(),
            "status_counts": status_counts,
        }
    finally:
        db.close()


def mark_owner_active(owner_id: int, active: bool = True) -> None:
    """Mark an owner as recently active."""
    _owner_last_active[owner_id] = time.monotonic()


def get_owner_execution_lock(owner_id: int) -> threading.Lock:
    """
    Get or create an execution lock for an owner.

    Args:
        owner_id: The owner ID

    Returns:
        Threading lock for the owner
    """
    with _owner_locks_master_lock:
        if owner_id not in _owner_execution_locks:
            _owner_execution_locks[owner_id] = threading.Lock()
        return _owner_execution_locks[owner_id]


@contextmanager
def owner_execution_context(owner_id: int):
    """
    Context manager for owner execution locking.

    Usage:
        with owner_execution_context(owner_id):
            # Execute owner-specific task
            pass
    """
    lock = get_owner_execution_lock(owner_id)
    lock.acquire()
    try:
        mark_owner_active(owner_id)
        yield
    finally:
        lock.release()

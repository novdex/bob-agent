"""
Scheduler service for cron jobs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..database.models import ScheduledJob
from ..database.session import SessionLocal
from ..utils import parse_cron_expression

logger = logging.getLogger("mind_clone.services.scheduler")

# Global scheduler state
_scheduler_task: Optional[asyncio.Task] = None
_running = False

# Interest keywords for proactive monitoring - consolidated here to avoid duplication
INTEREST_KEYWORDS = ["coding", "bob_project"]

# Default monitoring intervals (in seconds)
INTEREST_MONITOR_INTERVAL = 3600  # 1 hour


async def scheduler_loop(interval_seconds: int = 60):
    """Main scheduler loop."""
    global _running
    _running = True
    
    logger.info(f"Scheduler started (interval: {interval_seconds}s)")
    
    while _running:
        try:
            await run_due_jobs()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        
        await asyncio.sleep(interval_seconds)
    
    logger.info("Scheduler stopped")


async def run_due_jobs():
    """Run jobs that are due."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        
        # Get due jobs
        jobs = db.query(ScheduledJob).filter(
            ScheduledJob.enabled.is_(True),
            ScheduledJob.next_run_at <= now,
        ).all()
        
        for job in jobs:
            try:
                # Execute job
                logger.info(f"Running scheduled job {job.id}: {job.name}")
                
                # Check for interest keyword matches in the message
                alert_data = check_interest_keywords(job.message, job.owner_id, db)
                if alert_data and alert_data.get("triggered"):
                    logger.info(
                        f"Interest alert triggered for job {job.id} "
                        f"with keywords: {alert_data.get('matched_keywords')}"
                    )
                
                # Update job
                job.last_run_at = now
                job.run_count += 1
                
                # Schedule next run
                job.next_run_at = now + timedelta(seconds=job.interval_seconds)
                
                db.commit()
            
            except Exception as e:
                logger.error(f"Job {job.id} failed: {e}")
                job.last_error = str(e)[:300]
                db.commit()
    
    finally:
        db.close()


def check_interest_keywords(message: str, owner_id: int, db: Session) -> dict:
    """
    Check if a message contains any interest keywords and trigger alert if found.
    
    Args:
        message: The message/job content to check
        owner_id: The owner ID for the alert
        
    Returns:
        Dict with 'triggered' bool and alert details if triggered
    """
    if not message:
        return {"triggered": False}
    
    message_lower = message.lower()
    matched = [kw for kw in INTEREST_KEYWORDS if kw in message_lower]
    
    if matched:
        return create_interest_alert(
            owner_id=owner_id,
            message=message,
            matched_keywords=matched,
            source="scheduler_job",
        )
    
    return {"triggered": False}


def create_interest_alert(
    owner_id: int,
    message: str,
    matched_keywords: List[str],
    source: str = "scheduler_job",
    db: Optional[Session] = None,
) -> dict:
    """
    Create an interest alert for matched keywords.
    
    Args:
        owner_id: The user/owner ID
        message: The triggering message
        matched_keywords: List of matched interest keywords
        source: Source identifier (e.g., 'scheduler_job', 'user_message')
        db: Optional existing database session
        
    Returns:
        Dict with alert details and triggered status
    """
    from ..database.models import InterestAlert
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        now = datetime.now(timezone.utc)
        
        alert = InterestAlert(
            owner_id=owner_id,
            keyword=", ".join(matched_keywords),
            message=message[:1000] if message else "",
            source=source,
            triggered_at=now,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        
        logger.info(
            f"Interest alert created: id={alert.id}, "
            f"keywords={matched_keywords}, owner={owner_id}"
        )
        
        return {
            "triggered": True,
            "alert_id": alert.id,
            "owner_id": owner_id,
            "matched_keywords": matched_keywords,
            "message": message,
            "source": source,
            "triggered_at": now.isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to create interest alert: {e}")
        return {"triggered": False, "error": str(e)[:300]}
    finally:
        if should_close:
            db.close()


def setup_interest_monitoring(db: Session, owner_id: int) -> List[ScheduledJob]:
    """
    Set up proactive monitoring jobs for recurring interests.
    
    Creates scheduled jobs for:
    1) 'coding' interest - periodic checks
    2) 'bob_project' interest - periodic checks
    
    Args:
        db: Database session
        owner_id: The owner ID for the monitoring jobs
        
    Returns:
        List of created ScheduledJob instances
    """
    created_jobs = []
    
    monitoring_jobs = [
        {
            "name": "Interest Monitor: Coding",
            "message": "periodic_coding_check",
            "interval_seconds": INTEREST_MONITOR_INTERVAL,
            "lane": "interest_monitoring",
        },
        {
            "name": "Interest Monitor: Bob Project",
            "message": "periodic_bob_project_check",
            "interval_seconds": INTEREST_MONITOR_INTERVAL,
            "lane": "interest_monitoring",
        },
    ]
    
    for job_config in monitoring_jobs:
        try:
            job = create_job(
                db=db,
                owner_id=owner_id,
                name=job_config["name"],
                message=job_config["message"],
                interval_seconds=job_config["interval_seconds"],
                lane=job_config["lane"],
            )
            created_jobs.append(job)
            logger.info(f"Created interest monitoring job: {job.name} (id={job.id})")
        except Exception as e:
            logger.error(f"Failed to create monitoring job {job_config['name']}: {e}")
    
    return created_jobs


def create_job(
    db: Session,
    owner_id: int,
    name: str,
    message: Optional[str] = None,
    interval_seconds: Optional[int | str] = None,
    *,
    command: Optional[str] = None,
    schedule: Optional[str] = None,
    lane: str = "cron",
) -> ScheduledJob:
    """Create a new scheduled job with interval or cron-style schedule compatibility."""
    now = datetime.now(timezone.utc)

    # Backward-compatible aliasing from older interfaces.
    if isinstance(interval_seconds, str) and schedule is None:
        schedule = interval_seconds
        interval_seconds = None
    if (message is None or not str(message).strip()) and command:
        message = command

    resolved_message = str(message or "").strip()
    if not resolved_message:
        raise ValueError("message/command is required")

    run_at_time: Optional[str] = None
    if schedule:
        run_at_time = str(schedule).strip()
        interval_value = 86400  # daily cadence for cron-style entries in this simplified scheduler
        next_run_at = _next_run_from_schedule(run_at_time, now)
    else:
        interval_value = _coerce_interval_seconds(interval_seconds)
        next_run_at = now + timedelta(seconds=interval_value)

    job = ScheduledJob(
        owner_id=owner_id,
        name=name,
        message=resolved_message,
        lane=str(lane or "cron"),
        interval_seconds=interval_value,
        run_at_time=run_at_time,
        next_run_at=next_run_at,
        enabled=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(f"Created scheduled job {job.id}")
    return job


def list_jobs(
    db: Session,
    owner_id: int,
    include_disabled: bool = False,
) -> List[ScheduledJob]:
    """List scheduled jobs."""
    query = db.query(ScheduledJob).filter(ScheduledJob.owner_id == owner_id)
    if not include_disabled:
        query = query.filter(ScheduledJob.enabled.is_(True))
    return query.order_by(ScheduledJob.id.desc()).all()


def disable_job(db: Session, job_id: int, owner_id: int) -> bool:
    """Disable a scheduled job."""
    job = db.query(ScheduledJob).filter(
        ScheduledJob.id == job_id,
        ScheduledJob.owner_id == owner_id,
    ).first()
    
    if not job:
        return False
    
    job.enabled = False
    db.commit()
    logger.info(f"Disabled job {job_id}")
    return True


def _coerce_interval_seconds(raw_value: Optional[int | str], default_value: int = 300) -> int:
    """Normalize interval to a positive integer with sane floor."""
    if raw_value is None:
        return default_value
    try:
        parsed = int(str(raw_value).strip())
    except Exception:
        return default_value
    return max(60, parsed)


def _next_run_from_schedule(schedule: str, now_utc: datetime) -> datetime:
    """
    Compute next run time from a simple cron expression.

    Supported shape: `minute hour * * *` with exact integer minute/hour.
    Fallback: +60 seconds if expression is invalid.
    """
    try:
        parsed = parse_cron_expression(schedule)
        minute_raw = str(parsed.get("minute", "")).strip()
        hour_raw = str(parsed.get("hour", "")).strip()
        if minute_raw == "*" or hour_raw == "*":
            return now_utc + timedelta(minutes=1)
        minute = int(minute_raw)
        hour = int(hour_raw)
        if minute < 0 or minute > 59 or hour < 0 or hour > 23:
            raise ValueError("Invalid minute/hour in cron schedule")
        candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_utc:
            candidate = candidate + timedelta(days=1)
        return candidate
    except Exception:
        return now_utc + timedelta(seconds=60)


async def start_scheduler(interval_seconds: int = 60):
    """Start the scheduler."""
    global _scheduler_task
    
    if _scheduler_task and not _scheduler_task.done():
        logger.warning("Scheduler already running")
        return
    
    _scheduler_task = asyncio.create_task(scheduler_loop(interval_seconds))


async def stop_scheduler():
    """Stop the scheduler."""
    global _running, _scheduler_task
    
    _running = False
    
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass


def get_scheduler_status() -> dict:
    """Get scheduler status."""
    return {
        "running": _running,
        "task_running": _scheduler_task is not None and not _scheduler_task.done(),
    }


# ---------------------------------------------------------------------------
# Aliases expected by routes.py
# ---------------------------------------------------------------------------

async def cron_supervisor_loop() -> None:
    """Alias for scheduler_loop matching the routes.py import name."""
    await scheduler_loop()


def tool_schedule_job(
    owner_id: int,
    name: str,
    message: str,
    interval_seconds: int,
    lane: str = "cron",
) -> dict:
    """Create a scheduled job (LLM-callable wrapper)."""
    db = SessionLocal()
    try:
        job = create_job(
            db, owner_id, name,
            message=message,
            interval_seconds=interval_seconds,
            lane=lane,
        )
        return {
            "ok": True,
            "job_id": int(job.id),
            "name": job.name,
            "interval_seconds": job.interval_seconds,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def tool_list_scheduled_jobs(
    owner_id: int,
    include_disabled: bool = False,
    limit: int = 20,
) -> dict:
    """List scheduled jobs (LLM-callable wrapper)."""
    db = SessionLocal()
    try:
        jobs = list_jobs(db, owner_id, include_disabled=include_disabled)
        # Apply limit
        jobs = jobs[:limit] if limit > 0 else jobs
        return {
            "ok": True,
            "jobs": [
                {
                    "id": int(j.id),
                    "name": j.name,
                    "message": j.message,
                    "interval_seconds": j.interval_seconds,
                    "enabled": j.enabled,
                    "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
                    "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                    "run_count": j.run_count,
                    "lane": j.lane,
                }
                for j in jobs
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()
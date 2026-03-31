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

# Interest keywords for proactive monitoring alerts
INTEREST_KEYWORDS = ['coding', 'bob_project']

# Lazy import for InterestAlert to handle missing model gracefully
_InterestAlert = None


def _get_interest_alert_model():
    """Get InterestAlert model with lazy loading and graceful fallback."""
    global _InterestAlert
    if _InterestAlert is None:
        try:
            from ..database.models import InterestAlert
            _InterestAlert = InterestAlert
        except ImportError:
            logger.warning("InterestAlert model not available - alerts will be logged only")
            _InterestAlert = False
    return _InterestAlert


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
                
                # Check for interest keywords and create alert if matched
                job_message = (job.message or "").lower()
                for keyword in INTEREST_KEYWORDS:
                    if keyword in job_message:
                        logger.info(f"Interest keyword '{keyword}' detected in job {job.id}")
                        create_interest_alert(
                            db=db,
                            owner_id=job.owner_id,
                            interest_keyword=keyword,
                            job_id=job.id,
                            job_name=job.name,
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


def create_interest_alert(
    db: Session,
    owner_id: int,
    interest_keyword: str,
    job_id: int,
    job_name: str,
    message: Optional[str] = None,
) -> Optional[dict]:
    """
    Create an interest alert when a monitoring job detects a matching keyword.
    
    Args:
        db: Database session
        owner_id: ID of the job owner
        interest_keyword: The keyword that triggered the alert (e.g., 'coding', 'bob_project')
        job_id: ID of the scheduled job that detected the interest
        job_name: Name of the scheduled job
        message: Optional custom alert message
        
    Returns:
        Dictionary with alert info if created, None if InterestAlert model unavailable
    """
    InterestAlert = _get_interest_alert_model()
    
    now = datetime.now(timezone.utc)
    alert_message = message or f"Proactive monitoring detected interest in '{interest_keyword}' via job '{job_name}'"
    
    if InterestAlert is False:
        # Model not available - log alert only
        logger.info(f"INTEREST ALERT [no DB]: owner={owner_id}, keyword={interest_keyword}, job={job_name}, msg={alert_message}")
        return None
    
    try:
        alert = InterestAlert(
            owner_id=owner_id,
            keyword=interest_keyword,
            trigger_job_id=job_id,
            message=alert_message,
            created_at=now,
            is_read=False,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        
        logger.info(f"Created interest alert {alert.id} for owner {owner_id}: {interest_keyword}")
        return {
            "id": int(alert.id),
            "owner_id": int(alert.owner_id),
            "keyword": alert.keyword,
            "trigger_job_id": alert.trigger_job_id,
            "message": alert.message,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        }
    except Exception as e:
        logger.error(f"Failed to create interest alert: {e}")
        # Log as fallback
        logger.info(f"INTEREST ALERT [fallback]: owner={owner_id}, keyword={interest_keyword}, job={job_name}, msg={alert_message}")
        return None


def setup_interest_monitoring(
    db: Session,
    owner_id: int,
    check_interval_seconds: int = 3600,
) -> dict:
    """
    Set up proactive monitoring jobs for recurring interests.
    
    Creates scheduled jobs for:
    1. 'coding' interest - periodic checks for coding-related activities
    2. 'bob_project' interest - periodic checks for bob project-related activities
    
    Args:
        db: Database session
        owner_id: ID of the owner creating the monitoring jobs
        check_interval_seconds: Interval between checks (default: 1 hour)
        
    Returns:
        Dictionary with status of created jobs
    """
    monitoring_jobs = [
        {
            "name": "Interest Monitor: Coding",
            "message": "proactive_interest_check:coding",
            "description": "Proactive monitoring for coding-related interests",
        },
        {
            "name": "Interest Monitor: Bob Project",
            "message": "proactive_interest_check:bob_project",
            "description": "Proactive monitoring for bob project-related interests",
        },
    ]
    
    created_jobs = []
    errors = []
    
    for job_config in monitoring_jobs:
        try:
            # Check if job already exists
            existing = db.query(ScheduledJob).filter(
                ScheduledJob.owner_id == owner_id,
                ScheduledJob.name == job_config["name"],
                ScheduledJob.enabled.is_(True),
            ).first()
            
            if existing:
                logger.info(f"Monitoring job already exists: {job_config['name']}")
                created_jobs.append({
                    "name": job_config["name"],
                    "id": int(existing.id),
                    "status": "already_exists",
                })
                continue
            
            # Create the monitoring job
            job = create_job(
                db=db,
                owner_id=owner_id,
                name=job_config["name"],
                message=job_config["message"],
                interval_seconds=check_interval_seconds,
                lane="interest_monitor",
            )
            
            created_jobs.append({
                "name": job_config["name"],
                "id": int(job.id),
                "interval_seconds": job.interval_seconds,
                "status": "created",
            })
            logger.info(f"Created interest monitoring job: {job_config['name']} (id={job.id})")
            
        except Exception as e:
            error_msg = f"Failed to create {job_config['name']}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
    
    return {
        "ok": True,
        "owner_id": owner_id,
        "jobs_created": len([j for j in created_jobs if j.get("status") == "created"]),
        "jobs_already_existed": len([j for j in created_jobs if j.get("status") == "already_exists"]),
        "jobs": created_jobs,
        "errors": errors,
    }


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
        
        # Handle wildcard values - use next minute
        if minute_raw == "*" or hour_raw == "*":
            return now_utc + timedelta(minutes=1)
        
        # Parse and validate minute and hour
        minute = int(minute_raw)
        hour = int(hour_raw)
        
        if minute < 0 or minute > 59 or hour < 0 or hour > 23:
            raise ValueError("Invalid minute/hour in cron schedule")
        
        # Build candidate datetime
        candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If candidate is in the past, move to next day
        if candidate <= now_utc:
            candidate = candidate + timedelta(days=1)
        
        return candidate
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid cron schedule '{schedule}': {e}")
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
        return {
            "ok": True,
            "jobs": [
                {
                    "id": int(j.id),
                    "name": j.name,
                    "message": j.message,
                    "interval_seconds": j.interval_seconds,
                    "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
                    "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                    "enabled": j.enabled,
                    "run_count": j.run_count,
                }
                for j in jobs[:limit]
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()


def tool_setup_interest_monitoring(
    owner_id: int,
    check_interval_seconds: int = 3600,
) -> dict:
    """Set up proactive interest monitoring (LLM-callable wrapper)."""
    db = SessionLocal()
    try:
        result = setup_interest_monitoring(
            db=db,
            owner_id=owner_id,
            check_interval_seconds=check_interval_seconds,
        )
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        db.close()
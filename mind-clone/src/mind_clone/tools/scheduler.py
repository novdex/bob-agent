"""
Scheduler tools (cron jobs, scheduled tasks).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..database.session import SessionLocal

logger = logging.getLogger("mind_clone.tools.scheduler")


def tool_schedule_job(args: dict) -> dict:
    """Schedule a job to run periodically."""
    name = str(args.get("name", "")).strip()
    message = str(args.get("message", "")).strip()
    interval_seconds = int(args.get("interval_seconds", 300))
    lane = str(args.get("lane", "cron")).strip()
    run_at_time = args.get("run_at_time")
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if owner_id is None:
        return {"ok": False, "error": "owner_id is required"}
    if not name or not message:
        return {"ok": False, "error": "name and message are required"}

    db = SessionLocal()
    try:
        from ..services.scheduler import create_job

        job = create_job(
            db=db,
            owner_id=int(owner_id),
            name=name,
            message=message,
            interval_seconds=int(interval_seconds),
            schedule=str(run_at_time).strip() if run_at_time else None,
            lane=lane,
        )
        return {
            "ok": True,
            "job_id": int(job.id),
            "name": str(job.name),
            "interval_seconds": int(job.interval_seconds),
            "lane": str(job.lane),
            "run_at_time": str(job.run_at_time or ""),
            "enabled": bool(job.enabled),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def tool_list_scheduled_jobs(args: dict) -> dict:
    """List scheduled jobs."""
    include_disabled = bool(args.get("include_disabled", False))
    limit = int(args.get("limit", 20))
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if owner_id is None:
        return {"ok": False, "error": "owner_id is required"}

    db = SessionLocal()
    try:
        from ..services.scheduler import list_jobs

        rows = list_jobs(db=db, owner_id=int(owner_id), include_disabled=include_disabled)
        payload = []
        for row in rows[: max(1, int(limit))]:
            payload.append(
                {
                    "id": int(row.id),
                    "name": str(row.name),
                    "message": str(row.message),
                    "lane": str(row.lane),
                    "interval_seconds": int(row.interval_seconds),
                    "run_at_time": str(row.run_at_time or ""),
                    "enabled": bool(row.enabled),
                    "run_count": int(row.run_count or 0),
                }
            )
        return {"ok": True, "jobs": payload}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def tool_disable_scheduled_job(args: dict) -> dict:
    """Disable a scheduled job."""
    job_id = args.get("job_id")
    owner_id = args.get("owner_id") or args.get("_owner_id")

    if owner_id is None:
        return {"ok": False, "error": "owner_id is required"}
    if job_id is None:
        return {"ok": False, "error": "job_id is required"}

    db = SessionLocal()
    try:
        from ..services.scheduler import disable_job

        ok = disable_job(db=db, job_id=int(job_id), owner_id=int(owner_id))
        if not ok:
            return {"ok": False, "error": "job not found"}
        return {"ok": True, "job_id": int(job_id), "disabled": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()

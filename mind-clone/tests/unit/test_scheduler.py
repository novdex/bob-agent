"""
Tests for services/scheduler.py — Scheduler service.
"""
import pytest
from datetime import datetime, timedelta, timezone

try:
    from mind_clone.services.scheduler import (
        create_job,
        list_jobs,
        disable_job,
        get_scheduler_status,
        _coerce_interval_seconds,
        _next_run_from_schedule,
    )
    _IMPORT_OK = True
except (SyntaxError, ImportError):
    _IMPORT_OK = False

from mind_clone.database.models import ScheduledJob

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="services.scheduler import failed (Python 3.10 compat)")


class TestCoerceIntervalSeconds:
    """Test interval normalization."""

    def test_none_returns_default(self):
        assert _coerce_interval_seconds(None) == 300

    def test_valid_int(self):
        assert _coerce_interval_seconds(3600) == 3600

    def test_string_int(self):
        assert _coerce_interval_seconds("3600") == 3600

    def test_below_floor_clamped(self):
        assert _coerce_interval_seconds(10) == 60

    def test_invalid_string(self):
        assert _coerce_interval_seconds("abc") == 300

    def test_custom_default(self):
        assert _coerce_interval_seconds(None, default_value=600) == 600


class TestNextRunFromSchedule:
    """Test cron-style schedule parsing."""

    def test_valid_schedule(self):
        now = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        # Schedule for 09:30 — should be today since now is 08:00
        result = _next_run_from_schedule("30 9 * * *", now)
        assert result.hour == 9
        assert result.minute == 30
        assert result >= now

    def test_past_time_rolls_to_tomorrow(self):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        # Schedule for 09:00 — already passed today
        result = _next_run_from_schedule("0 9 * * *", now)
        assert result > now
        assert result.day == 2

    def test_wildcard_schedule(self):
        now = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        result = _next_run_from_schedule("* * * * *", now)
        # Should return now + 1 minute for wildcard
        assert result > now

    def test_invalid_schedule_fallback(self):
        now = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        result = _next_run_from_schedule("garbage", now)
        assert result > now


class TestCreateJob:
    """Test job creation."""

    def test_creates_job_with_interval(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "Test Job", message="do stuff", interval_seconds=300)
        assert job.id is not None
        assert job.name == "Test Job"
        assert job.message == "do stuff"
        assert job.interval_seconds == 300
        assert job.enabled is True

    def test_creates_job_with_command_alias(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "Cmd Job", command="run_backup", interval_seconds=600)
        assert job.message == "run_backup"

    def test_requires_message_or_command(self, db_session, sample_user):
        with pytest.raises(ValueError, match="required"):
            create_job(db_session, sample_user.id, "Bad Job", interval_seconds=300)

    def test_creates_job_with_schedule(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "Cron Job", message="daily", schedule="0 9 * * *")
        assert job.run_at_time == "0 9 * * *"
        assert job.next_run_at is not None


class TestListJobs:
    """Test job listing."""

    def test_lists_enabled_jobs(self, db_session, sample_user):
        create_job(db_session, sample_user.id, "J1", message="m1", interval_seconds=300)
        create_job(db_session, sample_user.id, "J2", message="m2", interval_seconds=600)
        jobs = list_jobs(db_session, sample_user.id)
        assert len(jobs) >= 2

    def test_excludes_disabled(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "Disabled", message="m", interval_seconds=300)
        job.enabled = False
        db_session.commit()
        jobs = list_jobs(db_session, sample_user.id, include_disabled=False)
        assert all(j.enabled for j in jobs)

    def test_includes_disabled_when_asked(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "IncDis", message="m", interval_seconds=300)
        job.enabled = False
        db_session.commit()
        jobs = list_jobs(db_session, sample_user.id, include_disabled=True)
        disabled = [j for j in jobs if not j.enabled]
        assert len(disabled) >= 1


class TestDisableJob:
    """Test job disabling."""

    def test_disables_existing_job(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "DisMe", message="m", interval_seconds=300)
        result = disable_job(db_session, job.id, sample_user.id)
        assert result is True
        db_session.refresh(job)
        assert job.enabled is False

    def test_returns_false_for_nonexistent(self, db_session, sample_user):
        result = disable_job(db_session, 99999, sample_user.id)
        assert result is False

    def test_returns_false_for_wrong_owner(self, db_session, sample_user):
        job = create_job(db_session, sample_user.id, "WrongOwner", message="m", interval_seconds=300)
        result = disable_job(db_session, job.id, 99999)
        assert result is False


class TestGetSchedulerStatus:
    """Test scheduler status reporting."""

    def test_returns_dict(self):
        status = get_scheduler_status()
        assert isinstance(status, dict)
        assert "running" in status
        assert "task_running" in status

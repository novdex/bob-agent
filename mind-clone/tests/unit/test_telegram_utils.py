"""
Tests for Telegram adapter utility functions (maps to t2-bench).

Covers: utc_now_iso, iso_after_seconds, _normalize_schedule_lane,
        _compute_next_run_at_time, clamp_int, parse_approval_token,
        parse_command_id.
"""

import pytest
from datetime import datetime, timezone, timedelta

from mind_clone.services.telegram.utils import (
    utc_now_iso,
    iso_after_seconds,
    _normalize_schedule_lane,
    _compute_next_run_at_time,
    clamp_int,
    parse_approval_token,
    parse_command_id,
)


# ---------------------------------------------------------------------------
# utc_now_iso
# ---------------------------------------------------------------------------

class TestUtcNowIso:

    def test_returns_iso_string(self):
        result = utc_now_iso()
        assert isinstance(result, str)
        # Should be parseable
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None

    def test_is_utc(self):
        result = utc_now_iso()
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# iso_after_seconds
# ---------------------------------------------------------------------------

class TestIsoAfterSeconds:

    def test_positive_seconds(self):
        before = datetime.now(timezone.utc)
        result = iso_after_seconds(60)
        dt = datetime.fromisoformat(result)
        assert dt > before
        assert dt < before + timedelta(seconds=120)

    def test_zero_seconds(self):
        before = datetime.now(timezone.utc)
        result = iso_after_seconds(0)
        dt = datetime.fromisoformat(result)
        assert abs((dt - before).total_seconds()) < 2

    def test_negative_clamped_to_zero(self):
        before = datetime.now(timezone.utc)
        result = iso_after_seconds(-100)
        dt = datetime.fromisoformat(result)
        # Negative clamped to max(0, -100) = 0
        assert abs((dt - before).total_seconds()) < 2


# ---------------------------------------------------------------------------
# _normalize_schedule_lane
# ---------------------------------------------------------------------------

class TestNormalizeScheduleLane:

    def test_valid_lanes(self):
        for lane in ("default", "interactive", "background", "cron", "agent", "research"):
            assert _normalize_schedule_lane(lane) == lane

    def test_invalid_lane_defaults_to_cron(self):
        assert _normalize_schedule_lane("invalid_lane") == "cron"
        assert _normalize_schedule_lane("xyz") == "cron"

    def test_empty_defaults_to_cron(self):
        assert _normalize_schedule_lane("") == "cron"

    def test_none_defaults_to_cron(self):
        assert _normalize_schedule_lane(None) == "cron"

    def test_case_insensitive(self):
        assert _normalize_schedule_lane("INTERACTIVE") == "interactive"
        assert _normalize_schedule_lane("Background") == "background"

    def test_strips_whitespace(self):
        assert _normalize_schedule_lane("  cron  ") == "cron"


# ---------------------------------------------------------------------------
# _compute_next_run_at_time
# ---------------------------------------------------------------------------

class TestComputeNextRunAtTime:

    def test_none_returns_none(self):
        assert _compute_next_run_at_time(None) is None

    def test_empty_returns_none(self):
        assert _compute_next_run_at_time("") is None

    def test_valid_time_returns_datetime(self):
        result = _compute_next_run_at_time("14:30")
        assert isinstance(result, datetime)
        assert result.minute == 30
        assert result.hour == 14

    def test_hour_only(self):
        result = _compute_next_run_at_time("10")
        # Should parse hour=10, minute=0
        assert result is not None
        assert result.hour == 10
        assert result.minute == 0

    def test_invalid_time_returns_none(self):
        assert _compute_next_run_at_time("not_a_time") is None
        assert _compute_next_run_at_time("99:99") is None

    def test_result_is_in_future(self):
        now = datetime.now(timezone.utc)
        result = _compute_next_run_at_time("00:00")
        assert result is not None
        assert result > now or result.day > now.day


# ---------------------------------------------------------------------------
# clamp_int
# ---------------------------------------------------------------------------

class TestClampInt:

    def test_within_range(self):
        assert clamp_int(5, 0, 10, 0) == 5

    def test_below_min(self):
        assert clamp_int(-5, 0, 10, 0) == 0

    def test_above_max(self):
        assert clamp_int(15, 0, 10, 0) == 10

    def test_at_min(self):
        assert clamp_int(0, 0, 10, 5) == 0

    def test_at_max(self):
        assert clamp_int(10, 0, 10, 5) == 10

    def test_string_number(self):
        assert clamp_int("7", 0, 10, 0) == 7

    def test_invalid_returns_default(self):
        assert clamp_int("abc", 0, 10, 5) == 5

    def test_none_returns_default(self):
        assert clamp_int(None, 0, 10, 5) == 5


# ---------------------------------------------------------------------------
# parse_approval_token (maps to FORTRESS approval gates)
# ---------------------------------------------------------------------------

class TestParseApprovalToken:

    def test_valid_token(self):
        result = parse_approval_token("/approve abc123DEF456", "/approve")
        assert result == "abc123DEF456"

    def test_valid_reject_token(self):
        result = parse_approval_token("/reject myToken_test-1", "/reject")
        assert result == "myToken_test-1"

    def test_no_token_returns_none(self):
        assert parse_approval_token("/approve", "/approve") is None

    def test_wrong_command_returns_none(self):
        assert parse_approval_token("/reject abc123", "/approve") is None

    def test_empty_string(self):
        assert parse_approval_token("", "/approve") is None

    def test_none_input(self):
        assert parse_approval_token(None, "/approve") is None

    def test_token_too_short(self):
        assert parse_approval_token("/approve ab", "/approve") is None  # < 4 chars

    def test_token_too_long(self):
        long_token = "a" * 65  # > 64 chars
        assert parse_approval_token(f"/approve {long_token}", "/approve") is None

    def test_token_with_special_chars(self):
        # Only alphanumeric + _ + - allowed
        assert parse_approval_token("/approve abc!@#$", "/approve") is None

    def test_case_insensitive_command(self):
        result = parse_approval_token("/APPROVE myToken1234", "/approve")
        assert result == "myToken1234"


# ---------------------------------------------------------------------------
# parse_command_id
# ---------------------------------------------------------------------------

class TestParseCommandId:

    def test_valid_id(self):
        assert parse_command_id("/cancel 123", "/cancel") == 123

    def test_no_id(self):
        assert parse_command_id("/cancel", "/cancel") is None

    def test_non_integer(self):
        assert parse_command_id("/cancel abc", "/cancel") is None

    def test_wrong_command(self):
        assert parse_command_id("/task 123", "/cancel") is None

    def test_negative_id(self):
        assert parse_command_id("/cancel -1", "/cancel") == -1

    def test_zero_id(self):
        assert parse_command_id("/cancel 0", "/cancel") == 0

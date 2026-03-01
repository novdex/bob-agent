"""
Tests for core/queue.py — Command queue utilities.
"""
import pytest
from mind_clone.core.state import OWNER_QUEUE_COUNTS, OWNER_STATE_LOCK
from mind_clone.core.queue import (
    command_queue_enabled,
    classify_message_lane,
    normalize_queue_lane,
    should_enqueue_message,
    is_owner_busy_or_backlogged,
    increment_owner_queue,
    decrement_owner_queue,
    owner_active_count,
    queue_stats,
    MAX_QUEUE_CAPACITY_PER_OWNER,
    VALID_QUEUE_MODES,
    VALID_LANES,
    _collect_buffer_append,
    _collect_buffer_pop,
)


class TestQueueModes:
    """Test queue mode validation."""

    def test_valid_queue_modes(self):
        expected = {"off", "on", "auto", "steer", "followup", "collect"}
        assert VALID_QUEUE_MODES == expected

    def test_valid_lanes(self):
        assert "default" in VALID_LANES
        assert "interactive" in VALID_LANES
        assert "background" in VALID_LANES
        assert "telegram" in VALID_LANES


class TestClassifyMessageLane:
    """Test message lane classification."""

    def test_cron_source(self):
        assert classify_message_lane("cron", "") == "cron"

    def test_scheduler_source(self):
        assert classify_message_lane("scheduler", "") == "cron"

    def test_telegram_source(self):
        assert classify_message_lane("telegram", "") == "telegram"

    def test_api_source(self):
        assert classify_message_lane("api", "") == "api"

    def test_research_in_text(self):
        assert classify_message_lane("", "please do deep_research on AI") == "research"

    def test_research_in_source(self):
        assert classify_message_lane("research", "") == "research"

    def test_task_in_text(self):
        assert classify_message_lane("", "/task run something") == "task"

    def test_urgent_message(self):
        assert classify_message_lane("", "this is urgent please help") == "interactive"

    def test_emergency_message(self):
        assert classify_message_lane("", "emergency fix needed") == "interactive"

    def test_default_lane(self):
        assert classify_message_lane("", "hello world") == "default"

    def test_empty_inputs(self):
        assert classify_message_lane("", "") == "default"

    def test_none_inputs(self):
        assert classify_message_lane(None, None) == "default"


class TestNormalizeQueueLane:
    """Test lane normalization."""

    def test_valid_lane_unchanged(self):
        assert normalize_queue_lane("interactive") == "interactive"
        assert normalize_queue_lane("research") == "research"

    def test_invalid_lane_becomes_default(self):
        assert normalize_queue_lane("invalid_lane") == "default"
        assert normalize_queue_lane("") == "default"


class TestShouldEnqueueMessage:
    """Test queue enqueueing logic."""

    def setup_method(self):
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS.clear()

    def test_off_mode_never_enqueues(self):
        assert should_enqueue_message("off", "telegram", "hello", 1) is False

    def test_on_mode_always_enqueues(self):
        assert should_enqueue_message("on", "", "hello", 1) is True

    def test_collect_mode_always_enqueues(self):
        assert should_enqueue_message("collect", "", "hello", 1) is True

    def test_steer_mode_enqueues_research(self):
        assert should_enqueue_message("steer", "research", "", 1) is True

    def test_steer_mode_enqueues_cron(self):
        assert should_enqueue_message("steer", "cron", "", 1) is True

    def test_steer_mode_does_not_enqueue_default(self):
        assert should_enqueue_message("steer", "", "hello", 1) is False

    def test_followup_mode_enqueues_when_busy(self):
        owner = 12345
        increment_owner_queue(owner)
        assert should_enqueue_message("followup", "", "hello", owner) is True

    def test_followup_mode_skips_when_idle(self):
        owner = 12346
        assert should_enqueue_message("followup", "", "hello", owner) is False

    def test_auto_mode_enqueues_when_backlogged(self):
        owner = 12347
        increment_owner_queue(owner)
        assert should_enqueue_message("auto", "", "hello", owner) is True

    def test_auto_mode_skips_when_idle(self):
        owner = 12348
        assert should_enqueue_message("auto", "", "hello", owner) is False


class TestOwnerQueueCounts:
    """Test owner queue management."""

    def setup_method(self):
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS.clear()

    def test_increment_and_decrement(self):
        assert increment_owner_queue(1) == 1
        assert increment_owner_queue(1) == 2
        assert decrement_owner_queue(1) == 1
        assert decrement_owner_queue(1) == 0

    def test_decrement_floor_zero(self):
        assert decrement_owner_queue(999) == 0

    def test_owner_active_count(self):
        increment_owner_queue(5)
        increment_owner_queue(5)
        assert owner_active_count(5) == 2

    def test_is_owner_busy(self):
        assert is_owner_busy_or_backlogged(888) is False
        increment_owner_queue(888)
        assert is_owner_busy_or_backlogged(888) is True


class TestCollectBuffers:
    """Test collect buffer append/pop."""

    def test_append_and_pop(self):
        _collect_buffer_append(1, "test_key", "value1")
        _collect_buffer_append(1, "test_key", "value2")
        result = _collect_buffer_pop(1, "test_key")
        assert result == ["value1", "value2"]

    def test_pop_nonexistent(self):
        result = _collect_buffer_pop(99999, "nonexistent")
        assert result is None


class TestQueueBoundsChecking:
    """Test queue capacity bounds checking."""

    def setup_method(self):
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS.clear()

    def test_increment_below_capacity(self):
        """increment_owner_queue should work normally below capacity."""
        owner = 111
        for i in range(10):
            result = increment_owner_queue(owner)
            assert result == i + 1

    def test_increment_at_capacity_raises(self):
        """increment_owner_queue should raise ValueError at max capacity."""
        owner = 222
        # Manually set to max capacity
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS[owner] = MAX_QUEUE_CAPACITY_PER_OWNER
        with pytest.raises(ValueError):
            increment_owner_queue(owner)

    def test_queue_stats_empty(self):
        """queue_stats should report zero for empty queue."""
        stats = queue_stats()
        assert stats["owner_count"] == 0
        assert stats["total_queued"] == 0
        assert stats["owners_at_capacity"] == 0
        assert stats["max_capacity"] == MAX_QUEUE_CAPACITY_PER_OWNER

    def test_queue_stats_with_data(self):
        """queue_stats should aggregate queue information."""
        increment_owner_queue(1)
        increment_owner_queue(1)
        increment_owner_queue(2)
        stats = queue_stats()
        assert stats["owner_count"] == 2
        assert stats["total_queued"] == 3

    def test_queue_stats_at_capacity(self):
        """queue_stats should track owners at capacity."""
        owner = 333
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS[owner] = MAX_QUEUE_CAPACITY_PER_OWNER
        stats = queue_stats()
        assert stats["owners_at_capacity"] >= 1

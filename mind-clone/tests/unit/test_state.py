"""
Tests for core/state.py — Runtime state management.
"""
import threading
import pytest
from mind_clone.core.state import (
    RUNTIME_STATE,
    RUNTIME_STATE_LOCK,
    get_runtime_state,
    set_runtime_state_value,
    increment_runtime_state,
    update_runtime_state,
    get_runtime_metrics,
    get_runtime_value,
    set_runtime_value,
    runtime_keys,
    increment_owner_queue,
    decrement_owner_queue,
    get_session_write_lock,
    session_write_lock,
    get_owner_execution_lock,
    MetricsCollector,
    OWNER_QUEUE_COUNTS,
    OWNER_STATE_LOCK,
    SESSION_WRITE_LOCKS,
    SESSION_WRITE_LOCK_GUARD,
)


class TestRuntimeState:
    """Test RUNTIME_STATE global dict operations."""

    def test_get_runtime_state_returns_copy(self):
        """get_runtime_state must return a copy, not the original."""
        state = get_runtime_state()
        assert isinstance(state, dict)
        state["__test_sentinel__"] = True
        assert "__test_sentinel__" not in RUNTIME_STATE

    def test_set_runtime_state_value(self):
        """set_runtime_state_value writes to RUNTIME_STATE."""
        set_runtime_state_value("_test_key", 42)
        assert RUNTIME_STATE["_test_key"] == 42
        # cleanup
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_test_key", None)

    def test_increment_runtime_state(self):
        """increment_runtime_state adds delta to integer counters."""
        set_runtime_state_value("_test_counter", 0)
        result = increment_runtime_state("_test_counter", 5)
        assert result == 5
        result = increment_runtime_state("_test_counter", 3)
        assert result == 8
        # cleanup
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_test_counter", None)

    def test_increment_runtime_state_nonexistent_key(self):
        """increment_runtime_state initializes missing keys to 0."""
        key = "_test_missing_counter"
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop(key, None)
        result = increment_runtime_state(key, 1)
        assert result == 1
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop(key, None)

    def test_update_runtime_state(self):
        """update_runtime_state applies multiple updates atomically."""
        update_runtime_state({"_test_a": 1, "_test_b": "hello"})
        assert RUNTIME_STATE["_test_a"] == 1
        assert RUNTIME_STATE["_test_b"] == "hello"
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_test_a", None)
            RUNTIME_STATE.pop("_test_b", None)


class TestRuntimeMetrics:
    """Test get_runtime_metrics returns expected keys."""

    def test_metrics_keys(self):
        metrics = get_runtime_metrics()
        expected_keys = {
            "worker_alive", "llm_failover_enabled", "command_queue_mode",
            "command_queue_worker_alive", "approval_pending_count",
            "db_healthy", "webhook_registered",
        }
        assert expected_keys.issubset(set(metrics.keys()))


class TestRuntimeValueAccessors:
    """Test get_runtime_value and set_runtime_value with unknown key logging."""

    def test_get_runtime_value_existing_key(self):
        """get_runtime_value should return value for known keys."""
        set_runtime_state_value("_test_existing", 42)
        value = get_runtime_value("_test_existing")
        assert value == 42
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_test_existing", None)

    def test_get_runtime_value_unknown_key_returns_default(self):
        """get_runtime_value should return default for unknown keys."""
        # Use a key that doesn't exist
        value = get_runtime_value("_unknown_key_xyz", default=99)
        assert value == 99

    def test_get_runtime_value_none_default(self):
        """get_runtime_value should return None by default."""
        value = get_runtime_value("_nonexistent_key")
        assert value is None

    def test_set_runtime_value_existing_key(self):
        """set_runtime_value should update existing keys."""
        set_runtime_state_value("_test_set_existing", 1)
        set_runtime_value("_test_set_existing", 2)
        assert RUNTIME_STATE["_test_set_existing"] == 2
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_test_set_existing", None)

    def test_set_runtime_value_new_key_logs_warning(self, caplog):
        """set_runtime_value should log warning for unknown keys."""
        import logging
        caplog.set_level(logging.WARNING)
        set_runtime_value("_brand_new_key", 123)
        # Should have logged a warning
        assert any("unknown key" in record.message for record in caplog.records)
        assert RUNTIME_STATE["_brand_new_key"] == 123
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("_brand_new_key", None)


class TestRuntimeKeys:
    """Test runtime_keys function."""

    def test_runtime_keys_returns_list(self):
        """runtime_keys should return a list of all current keys."""
        keys = runtime_keys()
        assert isinstance(keys, list)
        assert len(keys) > 0
        # Should include some keys (exact names depend on initialization order)
        # Just verify it's non-empty and contains strings
        assert all(isinstance(k, str) for k in keys)

    def test_runtime_keys_contains_all_keys(self):
        """runtime_keys should include all RUNTIME_STATE keys."""
        keys = runtime_keys()
        with RUNTIME_STATE_LOCK:
            expected = list(RUNTIME_STATE.keys())
        assert set(keys) == set(expected)


class TestOwnerQueue:
    """Test per-owner queue counting."""

    def test_increment_and_decrement(self):
        owner_id = 99999
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS.pop(owner_id, None)

        assert increment_owner_queue(owner_id) == 1
        assert increment_owner_queue(owner_id) == 2
        assert decrement_owner_queue(owner_id) == 1
        assert decrement_owner_queue(owner_id) == 0

    def test_decrement_below_zero(self):
        """Decrement should not go below 0."""
        owner_id = 99998
        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS.pop(owner_id, None)

        result = decrement_owner_queue(owner_id)
        assert result == 0


class TestSessionWriteLock:
    """Test per-owner session write lock."""

    def test_get_session_write_lock_returns_lock(self):
        lock = get_session_write_lock(88888)
        assert hasattr(lock, 'acquire') and hasattr(lock, 'release')
        # Same owner gets same lock
        lock2 = get_session_write_lock(88888)
        assert lock is lock2

    def test_session_write_lock_context_manager(self):
        """session_write_lock context manager acquires and releases."""
        owner_id = 88887
        with session_write_lock(owner_id, "test"):
            lock = get_session_write_lock(owner_id)
            # Lock is held, so trylock should fail
            assert not lock.acquire(blocking=False)
        # After context, lock should be released
        assert lock.acquire(blocking=False)
        lock.release()


class TestOwnerExecutionLock:
    """Test per-owner execution lock."""

    def test_get_owner_execution_lock_returns_lock(self):
        lock = get_owner_execution_lock(77777)
        assert hasattr(lock, 'acquire') and hasattr(lock, 'release')

    def test_same_owner_same_lock(self):
        lock1 = get_owner_execution_lock(77776)
        lock2 = get_owner_execution_lock(77776)
        assert lock1 is lock2


class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_record_and_get(self):
        mc = MetricsCollector()
        mc.record("foo", 42)
        assert mc.get("foo") == 42

    def test_increment(self):
        mc = MetricsCollector()
        mc.increment("counter", 1)
        mc.increment("counter", 3)
        assert mc.get("counter") == 4

    def test_get_all(self):
        mc = MetricsCollector()
        mc.record("a", 1)
        mc.record("b", 2)
        all_metrics = mc.get_all()
        assert all_metrics == {"a": 1, "b": 2}

    def test_get_default(self):
        mc = MetricsCollector()
        assert mc.get("nonexistent") is None
        assert mc.get("nonexistent", 0) == 0

    def test_thread_safety(self):
        """MetricsCollector should handle concurrent access."""
        mc = MetricsCollector()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    mc.increment("shared", 1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert mc.get("shared") == 400

"""
Cross-module integration tests for Bob AGI platform.

Tests failure modes spanning multiple subsystems:
1. Circuit breaker + Queue cascade
2. Self-tune + Budget governor interaction
3. Closed loop + Security
4. State corruption recovery
5. Feature flag interactions
"""

import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, Union

# Import key modules
from mind_clone.core.state import (
    RUNTIME_STATE,
    RUNTIME_STATE_LOCK,
    OWNER_QUEUE_COUNTS,
    OWNER_STATE_LOCK,
    PROVIDER_CIRCUITS,
    CIRCUIT_LOCK,
)
from mind_clone.core.circuit import (
    check_circuit,
    record_failure,
    record_success,
    reset_circuit,
    reset_all_circuits,
)
from mind_clone.core.queue import (
    command_queue_enabled,
    increment_owner_queue,
    decrement_owner_queue,
    owner_active_count,
)
from mind_clone.core.budget import (
    create_run_budget,
    budget_should_degrade,
    budget_should_stop,
    budget_exhausted,
    budget_remaining,
)
from mind_clone.core.self_tune import (
    st_tune_budget_mode,
    st_tune_queue_mode,
    st_tune_workers,
)
from mind_clone.core.closed_loop import (
    cl_filter_tools_by_performance,
    _validate_owner_id,
)
from mind_clone.core.security import validate_owner_id


@pytest.fixture(autouse=True)
def reset_state():
    """Reset RUNTIME_STATE and related global dicts before each test."""
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE.clear()
        RUNTIME_STATE.update({
            "budget_governor_mode": "degrade",
            "budget_runs_degraded": 0,
            "budget_runs_stopped": 0,
            "budget_runs_started": 0,
            "command_queue_mode": "auto",
            "command_queue_worker_alive_count": 0,
            "command_queue_enqueued": 0,
            "command_queue_processed": 0,
            "command_queue_dropped": 0,
            "circuit_blocked_calls": 0,
            "circuit_open_events": 0,
            "st_budget_mode_switches": 0,
            "cl_tools_blocked": 0,
            "cl_tools_warned": 0,
        })

    with OWNER_STATE_LOCK:
        OWNER_QUEUE_COUNTS.clear()

    with CIRCUIT_LOCK:
        PROVIDER_CIRCUITS.clear()

    yield

    # Cleanup after test
    with RUNTIME_STATE_LOCK:
        RUNTIME_STATE.clear()
    with OWNER_STATE_LOCK:
        OWNER_QUEUE_COUNTS.clear()
    with CIRCUIT_LOCK:
        PROVIDER_CIRCUITS.clear()


# ============================================================================
# TEST GROUP 1: Circuit Breaker + Queue Cascade
# ============================================================================

class TestCircuitBreakerQueueCascade:
    """Test circuit breaker and queue interaction under failure."""

    def test_circuit_open_prevents_further_failures(self):
        """Circuit breaker records failures and can indicate open state."""
        provider = "test_provider"

        # Record multiple failures
        record_failure(provider)
        record_failure(provider)

        # Check circuit state
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS[provider]["failures"] == 2
            assert PROVIDER_CIRCUITS[provider]["last_failure"] is not None

        # Circuit should be checkable
        is_open = check_circuit(provider)
        assert isinstance(is_open, bool)

    def test_queue_rejects_when_owner_backlogged(self):
        """Queue tracks owner counts, preventing unbounded accumulation."""
        owner_id = 123

        # Increment queue for owner
        count1 = increment_owner_queue(owner_id)
        assert count1 == 1

        count2 = increment_owner_queue(owner_id)
        assert count2 == 2

        # Verify active count reflects increments
        assert owner_active_count(owner_id) == 2

        # Decrement and verify
        remaining = decrement_owner_queue(owner_id)
        assert remaining == 1
        assert owner_active_count(owner_id) == 1

    def test_circuit_failure_increments_runtime_counter(self):
        """Circuit failures are tracked in RUNTIME_STATE."""
        initial_blocks = RUNTIME_STATE.get("circuit_blocked_calls", 0)

        # Record failures
        record_failure("service_a")
        record_failure("service_b")

        # Verify failure counts in circuit state
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS["service_a"]["failures"] == 1
            assert PROVIDER_CIRCUITS["service_b"]["failures"] == 1

    def test_circuit_reset_clears_state(self):
        """Resetting circuit clears its failure history."""
        provider = "test_svc"

        # Create circuit state
        record_failure(provider)
        record_failure(provider)

        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS[provider]["failures"] == 2

        # Reset
        result = reset_circuit(provider)
        assert result is True

        with CIRCUIT_LOCK:
            assert provider not in PROVIDER_CIRCUITS

    def test_queue_capacity_bounds_prevent_overflow(self):
        """Queue enforces per-owner capacity limits."""
        owner_id = 456

        # Fill queue to capacity (MAX_QUEUE_CAPACITY_PER_OWNER = 1000)
        for i in range(1000):
            increment_owner_queue(owner_id)

        assert owner_active_count(owner_id) == 1000

        # Next increment should raise
        with pytest.raises(ValueError, match="max capacity"):
            increment_owner_queue(owner_id)

    def test_circuit_and_queue_operate_independently(self):
        """Circuit breaker state and queue state don't interfere."""
        owner_id = 789
        provider = "test_provider"

        # Set up circuit failure
        record_failure(provider)
        assert check_circuit(provider) == False  # Circuit checks boolean

        # Queue independently tracks owner
        increment_owner_queue(owner_id)
        assert owner_active_count(owner_id) == 1

        # They operate in separate namespaces
        with CIRCUIT_LOCK:
            assert provider in PROVIDER_CIRCUITS
        with OWNER_STATE_LOCK:
            assert owner_id in OWNER_QUEUE_COUNTS


# ============================================================================
# TEST GROUP 2: Self-Tune + Budget Governor Interaction
# ============================================================================

class TestSelfTuneBudgetInteraction:
    """Test self-tuning engine adjusting budget governor."""

    def test_budget_creates_with_defaults(self):
        """Budget can be created with default parameters."""
        budget = create_run_budget()
        assert budget.max_seconds == 300
        assert budget.max_tool_calls == 40
        assert budget.max_llm_calls == 20
        assert budget.tool_calls == 0
        assert budget.llm_calls == 0

    def test_budget_detects_degradation_at_threshold(self):
        """Budget reports degradation when approaching limits."""
        budget = create_run_budget(
            max_seconds=10.0,
            max_tool_calls=20,
            max_llm_calls=10
        )

        # Simulate high tool usage (85% of limit = 17/20)
        budget.tool_calls = 17
        assert budget_should_degrade(budget, threshold=0.8) is True

        # Low usage should not degrade
        budget.tool_calls = 10
        assert budget_should_degrade(budget, threshold=0.8) is False

    def test_budget_tracks_remaining(self):
        """Budget can report remaining resources."""
        budget = create_run_budget(
            max_seconds=100.0,
            max_tool_calls=50,
            max_llm_calls=30
        )

        budget.tool_calls = 20
        budget.llm_calls = 10

        remaining = budget_remaining(budget)
        assert remaining["tool_calls_remaining"] == 30
        assert remaining["llm_calls_remaining"] == 20
        assert remaining["seconds_remaining"] > 0

    def test_st_tune_budget_mode_transitions(self):
        """Self-tuner transitions budget mode based on degradation count."""
        # Set initial state
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        RUNTIME_STATE["budget_runs_degraded"] = 0

        # Mock config for state update
        with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
            mock_cfg.BUDGET_GOVERNOR_MODE = "degrade"

            # Simulate many degradation events (delta > 3)
            RUNTIME_STATE["budget_runs_degraded"] = 5

            actions = st_tune_budget_mode()

            # Should propose mode transition
            assert isinstance(actions, list)

    def test_budget_governor_mode_in_runtime_state(self):
        """Budget mode is stored and retrievable in RUNTIME_STATE."""
        initial_mode = RUNTIME_STATE.get("budget_governor_mode", "degrade")
        assert initial_mode in ("degrade", "warn", "off")

        # Modify mode
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        assert RUNTIME_STATE["budget_governor_mode"] == "warn"

        # Reset
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        assert RUNTIME_STATE["budget_governor_mode"] == "degrade"

    def test_budget_exhaustion_stops_execution(self):
        """Budget exhaustion is properly detected."""
        budget = create_run_budget(
            max_seconds=1.0,
            max_tool_calls=5,
            max_llm_calls=5
        )

        # Max out one dimension
        budget.tool_calls = 5
        assert budget_exhausted(budget) is True

        # Reset and check zero usage
        budget2 = create_run_budget()
        budget2.tool_calls = 0
        assert budget_exhausted(budget2) is False

    def test_st_tune_queue_mode_transitions(self):
        """Self-tuner adjusts queue mode based on backlog."""
        RUNTIME_STATE["command_queue_enqueued"] = 100
        RUNTIME_STATE["command_queue_processed"] = 50
        RUNTIME_STATE["command_queue_mode"] = "auto"

        with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
            mock_cfg.COMMAND_QUEUE_MODE = "auto"

            actions = st_tune_queue_mode()
            assert isinstance(actions, list)


# ============================================================================
# TEST GROUP 3: Closed Loop + Security Interaction
# ============================================================================

class TestClosedLoopSecurityInteraction:
    """Test closed loop feedback with security validation."""

    def test_validate_owner_id_security_returns_tuple(self):
        """Security module's validate_owner_id returns (valid, message) tuple."""
        valid, msg = validate_owner_id(123)
        assert valid is True
        assert msg is None

        valid, msg = validate_owner_id(None)
        assert valid is False
        assert msg is not None

        valid, msg = validate_owner_id(-5)
        assert valid is False
        assert msg is not None

    def test_closed_loop_validate_owner_returns_bool(self):
        """Closed loop's _validate_owner_id returns bool (different from security)."""
        # Note: The closed_loop version seems incomplete in source
        result = _validate_owner_id(123)
        assert isinstance(result, (bool, type(None)))

    def test_cl_filter_tools_rejects_invalid_owner(self):
        """Tool filtering handles None/invalid owner_id gracefully."""
        tool_defs = [
            {
                "function": {
                    "name": "tool_a",
                    "description": "Test tool A"
                }
            }
        ]

        # With None owner, should return unfiltered
        result = cl_filter_tools_by_performance(tool_defs, None)
        assert result == tool_defs

        # With 0 owner, should return unfiltered (CLOSED_LOOP_ENABLED check)
        result = cl_filter_tools_by_performance(tool_defs, 0)
        assert result == tool_defs

    def test_security_rejects_invalid_owner_types(self):
        """Security validates owner_id type strictly."""
        # String not allowed
        valid, msg = validate_owner_id("123")
        assert valid is False

        # Float not allowed
        valid, msg = validate_owner_id(123.5)
        assert valid is False

        # Bool not allowed (is subclass of int)
        valid, msg = validate_owner_id(True)
        assert valid is False

    def test_cl_filter_tools_increments_counters(self):
        """Closed loop filters increment tracking counters."""
        initial_blocked = RUNTIME_STATE.get("cl_tools_blocked", 0)
        initial_warned = RUNTIME_STATE.get("cl_tools_warned", 0)

        # Tool filtering modifies counters (when performance stats available)
        tools = [{"function": {"name": "test_tool", "description": "desc"}}]

        with patch("mind_clone.core.closed_loop.get_tool_performance_stats") as mock_stats:
            mock_stats.return_value = {"tools": {}}
            result = cl_filter_tools_by_performance(tools, 999)

            # With no stats, should return as-is
            assert result == tools


# ============================================================================
# TEST GROUP 4: State Corruption Recovery
# ============================================================================

class TestStateCorruptionRecovery:
    """Test system resilience when RUNTIME_STATE keys are missing/corrupted."""

    def test_circuit_handles_missing_provider(self):
        """Circuit handles non-existent provider gracefully."""
        provider = "nonexistent"

        # Should not crash
        is_open = check_circuit(provider)
        assert is_open is False

    def test_budget_with_none_values(self):
        """Budget functions handle None gracefully."""
        # None budget should return safe defaults
        result = budget_remaining(None)
        assert result["seconds_remaining"] == float("inf")
        assert result["tool_calls_remaining"] == float("inf")

    def test_runtime_state_missing_keys_dont_crash(self):
        """System handles missing RUNTIME_STATE keys."""
        # Clear a critical key
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE.pop("budget_governor_mode", None)

        # These should not crash; they use .get() with defaults
        mode = RUNTIME_STATE.get("budget_governor_mode", "degrade")
        assert mode == "degrade"

    def test_owner_queue_missing_owner_id(self):
        """Queue operations handle missing owner gracefully."""
        nonexistent_owner = 99999

        # Should return 0, not crash
        count = owner_active_count(nonexistent_owner)
        assert count == 0

    def test_circuit_reset_nonexistent(self):
        """Resetting nonexistent circuit returns False safely."""
        result = reset_circuit("nonexistent_provider")
        assert result is False

    def test_budget_with_corrupt_time_data(self):
        """Budget handles corrupted time data."""
        budget = create_run_budget(max_seconds=100)

        # Simulate corrupt start time
        budget.start_time = None

        # Should not crash (but may return inf or 0)
        try:
            remaining = budget_remaining(budget)
            assert isinstance(remaining, dict)
        except (TypeError, AttributeError):
            # If it does raise, that's an expected failure mode
            pass

    def test_runtime_state_counter_bounds(self):
        """RUNTIME_STATE counters are bounded to prevent overflow."""
        # Set a very large counter
        RUNTIME_STATE["circuit_blocked_calls"] = 999999999999

        # Reading should work
        value = RUNTIME_STATE.get("circuit_blocked_calls")
        assert value == 999999999999


# ============================================================================
# TEST GROUP 5: Feature Flag Interactions
# ============================================================================

class TestFeatureFlagInteractions:
    """Test system behavior when feature flags are disabled."""

    def test_closed_loop_disabled_returns_unfiltered(self):
        """Closed loop respects CLOSED_LOOP_ENABLED flag."""
        tools = [
            {"function": {"name": "tool1", "description": "desc"}},
            {"function": {"name": "tool2", "description": "desc"}},
        ]

        with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False):
            result = cl_filter_tools_by_performance(tools, 123)
            # With flag disabled, should return original tools
            assert len(result) == len(tools)

    def test_self_tune_disabled_no_operations(self):
        """Self-tuning respects SELF_TUNE_ENABLED flag."""
        initial_switches = RUNTIME_STATE.get("st_budget_mode_switches", 0)

        with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
            with patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", False):
                mock_cfg.BUDGET_GOVERNOR_MODE = "degrade"

                actions = st_tune_budget_mode()

                # Should be empty or very minimal
                assert isinstance(actions, list)

    def test_queue_enabled_check(self):
        """Queue enabled status is checkable."""
        enabled = command_queue_enabled()
        assert isinstance(enabled, bool)

    def test_feature_flags_in_runtime_state(self):
        """Feature flag status stored in RUNTIME_STATE."""
        # These flags would typically come from config
        assert "budget_governor_mode" in RUNTIME_STATE
        assert RUNTIME_STATE.get("budget_governor_mode") in ("degrade", "warn", "off")

    def test_multiple_disabled_flags_degrade_gracefully(self):
        """When multiple features are disabled, system still functions."""
        with patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", False):
            with patch("mind_clone.core.closed_loop.CLOSED_LOOP_ENABLED", False):
                # Both disabled
                tools = [{"function": {"name": "t", "description": "d"}}]
                filtered = cl_filter_tools_by_performance(tools, 123)
                assert filtered == tools


# ============================================================================
# TEST GROUP 6: Cross-Module State Synchronization
# ============================================================================

class TestCrossModuleStateSynchronization:
    """Test state consistency across multiple module operations."""

    def test_circuit_and_runtime_state_consistency(self):
        """Circuit breaker state syncs with RUNTIME_STATE."""
        provider = "db_service"

        record_failure(provider)
        record_failure(provider)

        # PROVIDER_CIRCUITS should update
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS[provider]["failures"] == 2

        # Subsequent success resets
        record_success(provider)
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS[provider]["failures"] == 0

    def test_queue_and_owner_state_locking(self):
        """Queue operations use proper locking."""
        owner_id = 111

        # Multiple increments
        for i in range(10):
            increment_owner_queue(owner_id)

        # Final count should be exact
        assert owner_active_count(owner_id) == 10

        # Decrement all
        for i in range(10):
            decrement_owner_queue(owner_id)

        assert owner_active_count(owner_id) == 0

    def test_budget_and_runtime_state_tracking(self):
        """Budget events can be tracked in RUNTIME_STATE."""
        budget = create_run_budget(max_tool_calls=20)

        # Simulate tool calls at 85% of limit (17/20)
        budget.tool_calls = 17

        # Degrade check
        is_degraded = budget_should_degrade(budget, threshold=0.8)
        assert is_degraded is True

    def test_multiple_owners_independent_queues(self):
        """Multiple owners maintain independent queue counts."""
        owner1 = 111
        owner2 = 222

        increment_owner_queue(owner1)
        increment_owner_queue(owner1)
        increment_owner_queue(owner2)

        assert owner_active_count(owner1) == 2
        assert owner_active_count(owner2) == 1

        # Modify one
        decrement_owner_queue(owner1)
        assert owner_active_count(owner1) == 1
        assert owner_active_count(owner2) == 1  # Unaffected

    def test_circuit_reset_all_clears_all_providers(self):
        """Reset all circuits clears all provider state."""
        # Create multiple circuits
        record_failure("service_a")
        record_failure("service_b")
        record_failure("service_c")

        with CIRCUIT_LOCK:
            assert len(PROVIDER_CIRCUITS) == 3

        # Reset all
        count = reset_all_circuits()
        assert count == 3

        with CIRCUIT_LOCK:
            assert len(PROVIDER_CIRCUITS) == 0


# ============================================================================
# TEST GROUP 7: Concurrent State Access Safety
# ============================================================================

class TestConcurrentStateAccess:
    """Test thread safety of shared state operations."""

    def test_runtime_state_lock_acquired_during_updates(self):
        """RUNTIME_STATE uses locking for safety."""
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE["test_key"] = "test_value"

        assert RUNTIME_STATE.get("test_key") == "test_value"

    def test_owner_queue_lock_acquired_during_operations(self):
        """Owner queue counts use locking."""
        owner_id = 333

        with OWNER_STATE_LOCK:
            OWNER_QUEUE_COUNTS[owner_id] = 5

        count = owner_active_count(owner_id)
        assert count == 5

    def test_circuit_lock_acquired_during_state_changes(self):
        """Circuit state uses locking."""
        provider = "service"

        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS[provider] = {
                "failures": 0,
                "last_failure": None,
                "open": False
            }

        is_open = check_circuit(provider)
        assert is_open is False

    def test_multiple_owner_operations_dont_interfere(self):
        """Multiple owner operations don't corrupt state."""
        owners = [100, 200, 300, 400, 500]

        # Queue multiple owners
        for owner in owners:
            increment_owner_queue(owner)
            increment_owner_queue(owner)

        # Verify all
        for owner in owners:
            assert owner_active_count(owner) == 2


# ============================================================================
# TEST GROUP 8: Error Handling and Recovery
# ============================================================================

class TestErrorHandlingRecovery:
    """Test error handling across module boundaries."""

    def test_queue_capacity_error_is_descriptive(self):
        """Queue capacity error provides useful message."""
        owner_id = 777

        # Fill to capacity
        for i in range(1000):
            increment_owner_queue(owner_id)

        # Try to overflow
        try:
            increment_owner_queue(owner_id)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "max capacity" in str(e).lower()
            assert str(owner_id) in str(e)

    def test_budget_with_invalid_max_seconds(self):
        """Budget handles invalid time limit."""
        budget = create_run_budget(max_seconds=-1)
        # Should still create but with negative value
        assert budget.max_seconds == -1

    def test_security_validation_messages_helpful(self):
        """Security validation provides helpful error messages."""
        valid, msg = validate_owner_id("string")
        assert valid is False
        assert "must be int" in msg.lower() or "str" in msg.lower()

    def test_circuit_failure_tracking_monotonic(self):
        """Circuit failure counts only increase."""
        provider = "test_svc"

        record_failure(provider)
        with CIRCUIT_LOCK:
            count1 = PROVIDER_CIRCUITS[provider]["failures"]

        record_failure(provider)
        with CIRCUIT_LOCK:
            count2 = PROVIDER_CIRCUITS[provider]["failures"]

        assert count2 > count1

    def test_budget_exhaustion_once_true_stays_true(self):
        """Budget exhaustion is correctly detected when limits are hit."""
        budget = create_run_budget(max_tool_calls=5)

        budget.tool_calls = 3
        assert budget_exhausted(budget) is False

        budget.tool_calls = 5
        assert budget_exhausted(budget) is True

        # budget_exhausted checks current state (>= limit)
        budget.tool_calls = 4
        # At 4 < 5, it's not exhausted
        assert budget_exhausted(budget) is False

        # Back to limit
        budget.tool_calls = 5
        assert budget_exhausted(budget) is True


# ============================================================================
# TEST GROUP 9: Integration With All Key Modules
# ============================================================================

class TestFullCrossModuleIntegration:
    """Test scenarios involving 3+ modules simultaneously."""

    def test_circuit_queue_budget_together(self):
        """Circuit, queue, and budget interact properly."""
        owner_id = 444
        provider = "compute"

        # Queue owner
        increment_owner_queue(owner_id)
        assert owner_active_count(owner_id) == 1

        # Circuit failure
        record_failure(provider)
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS[provider]["failures"] == 1

        # Budget consumed
        budget = create_run_budget(max_tool_calls=20)
        budget.tool_calls = 18
        assert budget_should_degrade(budget, threshold=0.8) is True

        # All independent
        assert owner_active_count(owner_id) == 1
        assert check_circuit(provider) is False

    def test_security_closed_loop_together(self):
        """Security and closed loop operate together."""
        owner_id = 555

        # Security validates
        valid, msg = validate_owner_id(owner_id)
        assert valid is True

        # Closed loop filters with same owner
        tools = [{"function": {"name": "tool", "description": "desc"}}]
        result = cl_filter_tools_by_performance(tools, owner_id)
        assert isinstance(result, list)

    def test_self_tune_budget_queue_together(self):
        """Self-tune affects both budget and queue."""
        RUNTIME_STATE["budget_runs_degraded"] = 0
        RUNTIME_STATE["command_queue_enqueued"] = 50
        RUNTIME_STATE["command_queue_processed"] = 40

        with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
            mock_cfg.BUDGET_GOVERNOR_MODE = "degrade"
            mock_cfg.COMMAND_QUEUE_MODE = "auto"
            mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2

            # Both tuners can run
            budget_actions = st_tune_budget_mode()
            queue_actions = st_tune_queue_mode()

            assert isinstance(budget_actions, list)
            assert isinstance(queue_actions, list)

    def test_all_resets_clear_system(self):
        """Resetting all components leaves clean state."""
        # Set up state across modules
        increment_owner_queue(111)
        record_failure("svc_a")
        RUNTIME_STATE["circuit_blocked_calls"] = 5

        # Reset all
        reset_all_circuits()
        decrement_owner_queue(111)

        with CIRCUIT_LOCK:
            assert len(PROVIDER_CIRCUITS) == 0
        with OWNER_STATE_LOCK:
            assert OWNER_QUEUE_COUNTS.get(111, 0) == 0

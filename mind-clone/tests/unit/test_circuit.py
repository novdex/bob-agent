"""
Tests for core/circuit.py — Circuit breaker utilities.
"""
import pytest
from mind_clone.core.state import CIRCUIT_LOCK, PROVIDER_CIRCUITS
from mind_clone.core.circuit import (
    circuit_snapshot,
    check_circuit,
    record_failure,
    record_success,
    reset_circuit,
    reset_all_circuits,
    circuit_status,
)


class TestCircuitBreaker:
    """Test circuit breaker functions."""

    def setup_method(self):
        """Clear circuit state before each test."""
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS.clear()

    def test_check_circuit_unknown_provider(self):
        """Unknown provider should return False (circuit closed)."""
        assert check_circuit("unknown_provider") is False

    def test_record_failure_creates_entry(self):
        """record_failure should create circuit entry if none exists."""
        record_failure("test_provider")
        with CIRCUIT_LOCK:
            entry = PROVIDER_CIRCUITS.get("test_provider")
        assert entry is not None
        assert entry["failures"] == 1
        assert entry["last_failure"] is not None

    def test_record_multiple_failures(self):
        """Multiple failures should increment counter."""
        record_failure("test_provider")
        record_failure("test_provider")
        record_failure("test_provider")
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS["test_provider"]["failures"] == 3

    def test_record_success_resets_failures(self):
        """record_success should reset failure count and close circuit."""
        record_failure("test_provider")
        record_failure("test_provider")
        record_success("test_provider")
        with CIRCUIT_LOCK:
            entry = PROVIDER_CIRCUITS["test_provider"]
        assert entry["failures"] == 0
        assert entry["open"] is False

    def test_record_success_nonexistent_provider(self):
        """record_success on unknown provider should not crash."""
        record_success("nonexistent")
        with CIRCUIT_LOCK:
            assert "nonexistent" not in PROVIDER_CIRCUITS

    def test_circuit_snapshot_returns_deep_copy(self):
        """circuit_snapshot must return a deep copy — mutations must not affect original."""
        record_failure("snap_test")
        snap = circuit_snapshot()
        assert "snap_test" in snap
        assert isinstance(snap, dict)
        assert "failures" in snap["snap_test"]
        # Mutate the snapshot
        snap["snap_test"]["failures"] = 999
        # Original must be untouched
        with CIRCUIT_LOCK:
            assert PROVIDER_CIRCUITS["snap_test"]["failures"] != 999

    def test_check_circuit_open(self):
        """check_circuit should detect open circuit."""
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS["open_test"] = {"failures": 10, "last_failure": 0, "open": True}
        assert check_circuit("open_test") is True

    def test_check_circuit_closed(self):
        """check_circuit should detect closed circuit."""
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS["closed_test"] = {"failures": 0, "last_failure": None, "open": False}
        assert check_circuit("closed_test") is False


class TestCircuitReset:
    """Test circuit reset functions."""

    def setup_method(self):
        """Clear circuit state before each test."""
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS.clear()

    def test_reset_circuit_existing_provider(self):
        """reset_circuit should remove a provider from the registry."""
        record_failure("to_reset")
        with CIRCUIT_LOCK:
            assert "to_reset" in PROVIDER_CIRCUITS
        result = reset_circuit("to_reset")
        assert result is True
        with CIRCUIT_LOCK:
            assert "to_reset" not in PROVIDER_CIRCUITS

    def test_reset_circuit_nonexistent_provider(self):
        """reset_circuit should return False for unknown providers."""
        result = reset_circuit("never_existed")
        assert result is False

    def test_reset_all_circuits(self):
        """reset_all_circuits should clear all circuits."""
        record_failure("prov1")
        record_failure("prov2")
        record_failure("prov3")
        with CIRCUIT_LOCK:
            assert len(PROVIDER_CIRCUITS) == 3
        count = reset_all_circuits()
        assert count == 3
        with CIRCUIT_LOCK:
            assert len(PROVIDER_CIRCUITS) == 0

    def test_reset_all_circuits_empty(self):
        """reset_all_circuits should return 0 when registry is empty."""
        count = reset_all_circuits()
        assert count == 0


class TestCircuitStatus:
    """Test circuit_status function."""

    def setup_method(self):
        """Clear circuit state before each test."""
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS.clear()

    def test_circuit_status_open(self):
        """circuit_status should return correct status for open circuit."""
        record_failure("open_prov")
        with CIRCUIT_LOCK:
            PROVIDER_CIRCUITS["open_prov"]["open"] = True
        status = circuit_status("open_prov")
        assert status["provider"] == "open_prov"
        assert status["open"] is True
        assert status["failures"] == 1

    def test_circuit_status_closed(self):
        """circuit_status should return correct status for closed circuit."""
        record_failure("closed_prov")
        record_success("closed_prov")
        status = circuit_status("closed_prov")
        assert status["provider"] == "closed_prov"
        assert status["open"] is False
        assert status["failures"] == 0

    def test_circuit_status_unknown_provider(self):
        """circuit_status should return default values for unknown providers."""
        status = circuit_status("unknown_prov")
        assert status["provider"] == "unknown_prov"
        assert status["open"] is False
        assert status["failures"] == 0
        assert status["last_failure"] is None

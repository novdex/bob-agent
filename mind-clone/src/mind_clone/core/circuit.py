"""
Circuit breaker utilities.

Thin wrappers around ``core.state.PROVIDER_CIRCUITS`` for the secondary
circuit-breaker state dict (used by the node control plane and heartbeat).

The *primary* circuit breaker used by tool execution lives in
``core.security`` (``circuit_allow_call`` / ``circuit_record_*``).
This module manages the *runtime dashboard* view and manual reset API.
"""
import copy
import logging
import time
from typing import Dict, Any

from .state import CIRCUIT_LOCK, PROVIDER_CIRCUITS
from ..config import settings

logger = logging.getLogger("mind_clone.circuit")


def _cb_threshold() -> int:
    return getattr(settings, "circuit_breaker_failure_threshold", 5)


def _cb_cooldown() -> float:
    return float(getattr(settings, "circuit_breaker_cooldown_seconds", 60))


def circuit_snapshot() -> Dict[str, Any]:
    """Get a deep copy of the current circuit state."""
    with CIRCUIT_LOCK:
        return copy.deepcopy(PROVIDER_CIRCUITS)


def check_circuit(provider: str) -> bool:
    """Check if circuit is open (True = open/failing, calls blocked)."""
    with CIRCUIT_LOCK:
        circuit = PROVIDER_CIRCUITS.get(provider, {})
        return circuit.get("open", False)


def record_failure(provider: str, error: str = "") -> None:
    """Record a failure for a provider — trips circuit at threshold."""
    threshold = _cb_threshold()
    with CIRCUIT_LOCK:
        if provider not in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider] = {"failures": 0, "last_failure": None, "open": False, "opened_at": None}
        PROVIDER_CIRCUITS[provider]["failures"] += 1
        PROVIDER_CIRCUITS[provider]["last_failure"] = error or time.time()
        if PROVIDER_CIRCUITS[provider]["failures"] >= threshold and not PROVIDER_CIRCUITS[provider]["open"]:
            PROVIDER_CIRCUITS[provider]["open"] = True
            PROVIDER_CIRCUITS[provider]["opened_at"] = time.monotonic()
            logger.warning("Circuit OPENED for %s (failures=%d >= %d)", provider, PROVIDER_CIRCUITS[provider]["failures"], threshold)


def record_success(provider: str) -> None:
    """Record a success for a provider, resetting failure count."""
    with CIRCUIT_LOCK:
        if provider in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider]["failures"] = 0
            PROVIDER_CIRCUITS[provider]["open"] = False
            PROVIDER_CIRCUITS[provider]["opened_at"] = None


def reset_circuit(provider: str) -> bool:
    """Clear circuit state for a single provider.

    Returns:
        True if the provider was in the circuit registry, False otherwise.
    """
    with CIRCUIT_LOCK:
        if provider in PROVIDER_CIRCUITS:
            del PROVIDER_CIRCUITS[provider]
            logger.info("reset_circuit: provider=%s", provider)
            return True
        return False


def reset_all_circuits() -> int:
    """Clear all circuit breaker state.

    Returns:
        Count of circuits that were cleared.
    """
    with CIRCUIT_LOCK:
        count = len(PROVIDER_CIRCUITS)
        PROVIDER_CIRCUITS.clear()
        if count > 0:
            logger.info("reset_all_circuits: count=%d", count)
        return count


def circuit_status(provider: str) -> Dict[str, Any]:
    """Get circuit status for a provider as a clean dict."""
    with CIRCUIT_LOCK:
        circuit = PROVIDER_CIRCUITS.get(provider, {})
    return {
        "provider": provider,
        "open": circuit.get("open", False),
        "failures": circuit.get("failures", 0),
        "last_failure": circuit.get("last_failure", None),
        "threshold": _cb_threshold(),
        "cooldown_seconds": _cb_cooldown(),
    }


_default_circuit_state = {"failures": 0, "last_failure": None, "open": False, "opened_at": None}

__all__ = [
    "circuit_snapshot",
    "check_circuit",
    "record_failure",
    "record_success",
    "reset_circuit",
    "reset_all_circuits",
    "circuit_status",
    "_default_circuit_state",
]

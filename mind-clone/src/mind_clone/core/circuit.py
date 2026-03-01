"""
Circuit breaker utilities.
"""
import copy
import logging
from typing import Dict, Any, Optional
from .state import CIRCUIT_LOCK, PROVIDER_CIRCUITS

logger = logging.getLogger("mind_clone.circuit")

def circuit_snapshot() -> Dict[str, Any]:
    """Get a deep copy of the current circuit state."""
    with CIRCUIT_LOCK:
        return copy.deepcopy(PROVIDER_CIRCUITS)

def check_circuit(provider: str) -> bool:
    """Check if circuit is open (True = open/failing)."""
    with CIRCUIT_LOCK:
        circuit = PROVIDER_CIRCUITS.get(provider, {})
        return circuit.get("open", False)

def record_failure(provider: str) -> None:
    """Record a failure for a provider."""
    with CIRCUIT_LOCK:
        if provider not in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider] = {"failures": 0, "last_failure": None, "open": False}
        PROVIDER_CIRCUITS[provider]["failures"] += 1
        PROVIDER_CIRCUITS[provider]["last_failure"] = __import__("time").time()

def record_success(provider: str) -> None:
    """Record a success for a provider, resetting failure count."""
    with CIRCUIT_LOCK:
        if provider in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider]["failures"] = 0
            PROVIDER_CIRCUITS[provider]["open"] = False

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
    """Get circuit status for a provider as a clean dict.

    Args:
        provider: The provider name

    Returns:
        Dict with keys: provider, open, failures, last_failure
    """
    with CIRCUIT_LOCK:
        circuit = PROVIDER_CIRCUITS.get(provider, {})
    return {
        "provider": provider,
        "open": circuit.get("open", False),
        "failures": circuit.get("failures", 0),
        "last_failure": circuit.get("last_failure", None),
    }

_default_circuit_state = {"failures": 0, "last_failure": None, "open": False}

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

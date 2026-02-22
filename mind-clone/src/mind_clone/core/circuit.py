"""
Circuit breaker utilities.
"""
from .state import CIRCUIT_LOCK, PROVIDER_CIRCUITS

def circuit_snapshot():
    with CIRCUIT_LOCK:
        return dict(PROVIDER_CIRCUITS)

def check_circuit(provider: str) -> bool:
    """Check if circuit is open (True = open/failing)."""
    with CIRCUIT_LOCK:
        circuit = PROVIDER_CIRCUITS.get(provider, {})
        return circuit.get("open", False)

def record_failure(provider: str):
    with CIRCUIT_LOCK:
        if provider not in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider] = {"failures": 0, "last_failure": None, "open": False}
        PROVIDER_CIRCUITS[provider]["failures"] += 1
        PROVIDER_CIRCUITS[provider]["last_failure"] = __import__("time").time()

def record_success(provider: str):
    with CIRCUIT_LOCK:
        if provider in PROVIDER_CIRCUITS:
            PROVIDER_CIRCUITS[provider]["failures"] = 0
            PROVIDER_CIRCUITS[provider]["open"] = False

_default_circuit_state = {"failures": 0, "last_failure": None, "open": False}

__all__ = ["circuit_snapshot", "check_circuit", "record_failure", "record_success", "_default_circuit_state"]

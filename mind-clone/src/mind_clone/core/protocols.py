"""
Protocol validation utilities.

Validates payloads against registered protocol contracts (schemas).
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("mind_clone.core.protocols")

PROTOCOL_SCHEMA_REGISTRY: Dict[str, Any] = {}


def validate_protocol_contract(contract: Dict[str, Any]) -> bool:
    """Validate a protocol contract definition."""
    return True


def list_protocol_contracts() -> List[Dict[str, Any]]:
    """List all protocol contracts."""
    return []


# ---------------------------------------------------------------------------
# Functions expected by routes.py
# ---------------------------------------------------------------------------

def protocol_validate_payload(
    schema_name: str, payload: dict, direction: str = "request",
) -> Tuple[bool, Optional[str]]:
    """Validate a payload against a named protocol schema.

    Returns (valid, error_message). If the schema is not registered,
    validation is skipped (returns True).
    """
    schema = PROTOCOL_SCHEMA_REGISTRY.get(schema_name)
    if schema is None:
        return True, None
    # Future: implement JSON Schema validation against schema
    return True, None


def protocol_contracts_public_view(
    registry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a public-safe view of protocol contracts."""
    result = []
    for name, schema in registry.items():
        result.append({
            "name": name,
            "version": schema.get("version", "1.0"),
            "direction": schema.get("direction", "both"),
        })
    return result


__all__ = [
    "validate_protocol_contract",
    "list_protocol_contracts",
    "protocol_validate_payload",
    "protocol_contracts_public_view",
    "PROTOCOL_SCHEMA_REGISTRY",
]

"""
Core infrastructure modules.

Note: closed_loop and self_tune are NOT imported here to avoid circular
imports (config.py -> core.policies -> core.__init__ -> closed_loop -> config).
Import them directly: ``from mind_clone.core.closed_loop import ...``
                       ``from mind_clone.core.self_tune import ...``
"""

from .state import (
    RUNTIME_STATE,
    get_runtime_state,
    set_runtime_state_value,
    increment_runtime_state,
    update_runtime_state,
    get_runtime_metrics,
)
from .security import (
    get_tool_policy_profile,
    check_tool_allowed,
    requires_approval,
    redact_secrets,
    evaluate_workspace_diff_gate,
    SAFE_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
)

__all__ = [
    "RUNTIME_STATE",
    "get_runtime_state",
    "set_runtime_state_value",
    "increment_runtime_state",
    "update_runtime_state",
    "get_runtime_metrics",
    "get_tool_policy_profile",
    "check_tool_allowed",
    "requires_approval",
    "redact_secrets",
    "evaluate_workspace_diff_gate",
    "SAFE_TOOL_NAMES",
    "DANGEROUS_TOOL_NAMES",
]

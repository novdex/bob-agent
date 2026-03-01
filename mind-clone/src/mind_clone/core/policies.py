"""
Policy management utilities.
"""
from typing import Dict, Any, List

TOOL_POLICY_PROFILE_RAW = {
    "safe": {
        "allowed_tools": ["read_file", "search_web", "send_email"],
        "blocked_tools": ["run_command", "execute_python", "write_file"],
    },
    "balanced": {
        "allowed_tools": ["*"],
        "blocked_tools": [],
        "approval_required": ["run_command", "execute_python"],
    },
    "power": {
        "allowed_tools": ["*"],
        "blocked_tools": [],
    },
}

TOOL_POLICY_PROFILES = TOOL_POLICY_PROFILE_RAW

EXECUTION_SANDBOX_PROFILE_RAW = {
    "strict": {"docker": True, "network": False, "volumes": []},
    "balanced": {"docker": False, "network": True, "volumes": ["/tmp"]},
    "permissive": {"docker": False, "network": True, "volumes": ["/"]},
}

EXECUTION_SANDBOX_PROFILES = EXECUTION_SANDBOX_PROFILE_RAW

def get_active_tool_policy() -> Dict[str, Any]:
    """Get the currently active tool policy."""
    return {
        "profile": "balanced",
        "allowed_tools": ["*"],
        "blocked_tools": [],
    }

def get_tool_policy_profile(profile_name: str = None) -> Dict[str, Any]:
    """Get a specific tool policy profile."""
    profiles = {
        "safe": {
            "allowed_tools": ["read_file", "search_web", "send_email"],
            "blocked_tools": ["run_command", "execute_python", "write_file"],
        },
        "balanced": {
            "allowed_tools": ["*"],
            "blocked_tools": [],
            "approval_required": ["run_command", "execute_python"],
        },
        "power": {
            "allowed_tools": ["*"],
            "blocked_tools": [],
        },
    }
    return profiles.get(profile_name, profiles["balanced"])

def list_policy_profiles() -> List[str]:
    """List available policy profiles."""
    return ["safe", "balanced", "power"]

def active_tool_policy_profile() -> str:
    """Get the currently active tool policy profile name."""
    return "balanced"

def active_execution_sandbox_profile() -> str:
    """Get the currently active execution sandbox profile name."""
    return "balanced"


def validate_policy_name(policy_name: str) -> tuple[bool, str]:
    """
    Validate that a policy name is known and valid.

    Args:
        policy_name: Policy name to validate

    Returns:
        (is_valid, error_message)
    """
    valid_names = set(TOOL_POLICY_PROFILES.keys())
    if not policy_name or policy_name not in valid_names:
        return False, f"Unknown policy name '{policy_name}'. Valid: {sorted(valid_names)}"
    return True, ""


def get_policy_names() -> List[str]:
    """
    Get list of all valid policy profile names.

    Returns:
        Sorted list of policy names
    """
    return sorted(TOOL_POLICY_PROFILES.keys())


def validate_policy_bounds(policy_name: str) -> Dict[str, Any]:
    """
    Validate numeric parameters in a policy profile for bounds.

    Args:
        policy_name: Policy name to validate

    Returns:
        Validation result dict with any bounds issues
    """
    if policy_name not in TOOL_POLICY_PROFILES:
        return {"valid": False, "error": f"Unknown policy '{policy_name}'"}

    policy = TOOL_POLICY_PROFILES[policy_name]
    issues = []

    # Check numeric bounds
    for key in ["chat_tool_loops", "task_tool_loops"]:
        if key in policy:
            val = policy[key]
            if not isinstance(val, int) or val < 0 or val > 1000:
                issues.append(f"{key}: {val} (expected 0-1000)")

    for key in ["max_run_command_timeout", "max_execute_python_timeout"]:
        if key in policy:
            val = policy[key]
            if not isinstance(val, int) or val < 0 or val > 600:
                issues.append(f"{key}: {val} (expected 0-600 seconds)")

    return {
        "valid": len(issues) == 0,
        "policy": policy_name,
        "issues": issues,
    }


__all__ = [
    "get_active_tool_policy",
    "get_tool_policy_profile",
    "list_policy_profiles",
    "active_tool_policy_profile",
    "active_execution_sandbox_profile",
    "validate_policy_name",
    "get_policy_names",
    "validate_policy_bounds",
    "TOOL_POLICY_PROFILE_RAW",
    "TOOL_POLICY_PROFILES",
    "EXECUTION_SANDBOX_PROFILE_RAW",
    "EXECUTION_SANDBOX_PROFILES",
]

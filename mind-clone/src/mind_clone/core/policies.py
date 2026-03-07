"""
Policy management utilities.

Provides tool policy profiles (safe/balanced/power) and execution sandbox
profiles that control what the agent is allowed to do.

The active profile is driven by the TOOL_POLICY_PROFILE env var via
``settings.tool_policy_profile``.  All functions that return "the active
profile" MUST read from settings — never hardcode a default.
"""
from typing import Dict, Any, List

from ..config import settings

# ---------------------------------------------------------------------------
# Tool policy profiles — what tools are allowed / blocked / need approval
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Execution sandbox profiles — Docker / network / volume constraints
# ---------------------------------------------------------------------------

EXECUTION_SANDBOX_PROFILE_RAW = {
    "strict": {"docker": True, "network": False, "volumes": []},
    "balanced": {"docker": False, "network": True, "volumes": ["/tmp"]},
    "permissive": {"docker": False, "network": True, "volumes": ["/"]},
}

EXECUTION_SANDBOX_PROFILES = EXECUTION_SANDBOX_PROFILE_RAW


# ---------------------------------------------------------------------------
# Active-profile accessors (driven by env / settings)
# ---------------------------------------------------------------------------

def active_tool_policy_profile() -> str:
    """Return the name of the currently active tool policy profile.

    Reads from ``settings.tool_policy_profile`` (env TOOL_POLICY_PROFILE).
    Falls back to ``"balanced"`` only when the configured value is unknown.
    """
    name = getattr(settings, "tool_policy_profile", "balanced")
    if name not in TOOL_POLICY_PROFILES:
        return "balanced"
    return name


def active_execution_sandbox_profile() -> str:
    """Return the name of the currently active execution sandbox profile.

    Reads from ``settings.execution_sandbox_profile`` (env EXECUTION_SANDBOX_PROFILE).
    """
    name = getattr(settings, "execution_sandbox_profile", "default")
    if name not in EXECUTION_SANDBOX_PROFILES:
        return "balanced"
    return name


def get_active_tool_policy() -> Dict[str, Any]:
    """Return the full dict for the currently active tool policy."""
    name = active_tool_policy_profile()
    policy = TOOL_POLICY_PROFILES.get(name, TOOL_POLICY_PROFILES["balanced"])
    return {"profile": name, **policy}


def get_tool_policy_profile(profile_name: str = None) -> Dict[str, Any]:
    """Get a specific tool policy profile by name."""
    if profile_name is None:
        profile_name = active_tool_policy_profile()
    return TOOL_POLICY_PROFILES.get(profile_name, TOOL_POLICY_PROFILES["balanced"])


def is_tool_blocked_by_policy(tool_name: str) -> bool:
    """Quick check: is *tool_name* in the blocked list of the active profile?

    Returns True if blocked, False if allowed (or wildcard).
    """
    policy = get_active_tool_policy()
    blocked = policy.get("blocked_tools", [])
    if tool_name in blocked:
        return True

    allowed = policy.get("allowed_tools", ["*"])
    if "*" in allowed:
        return False
    return tool_name not in allowed


def is_tool_approval_required(tool_name: str) -> bool:
    """Check if the active profile requires approval for *tool_name*."""
    policy = get_active_tool_policy()
    return tool_name in policy.get("approval_required", [])


def list_policy_profiles() -> List[str]:
    """List available policy profiles."""
    return sorted(TOOL_POLICY_PROFILES.keys())


def get_policy_names() -> List[str]:
    """Get list of all valid policy profile names."""
    return sorted(TOOL_POLICY_PROFILES.keys())


def validate_policy_name(policy_name: str) -> tuple:
    """Validate that a policy name is known and valid.

    Returns:
        (is_valid, error_message)
    """
    valid_names = set(TOOL_POLICY_PROFILES.keys())
    if not policy_name or policy_name not in valid_names:
        return False, f"Unknown policy name '{policy_name}'. Valid: {sorted(valid_names)}"
    return True, ""


def validate_policy_bounds(policy_name: str) -> Dict[str, Any]:
    """Validate numeric parameters in a policy profile for bounds."""
    if policy_name not in TOOL_POLICY_PROFILES:
        return {"valid": False, "error": f"Unknown policy '{policy_name}'"}

    policy = TOOL_POLICY_PROFILES[policy_name]
    issues = []

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
    "is_tool_blocked_by_policy",
    "is_tool_approval_required",
    "validate_policy_name",
    "get_policy_names",
    "validate_policy_bounds",
    "TOOL_POLICY_PROFILE_RAW",
    "TOOL_POLICY_PROFILES",
    "EXECUTION_SANDBOX_PROFILE_RAW",
    "EXECUTION_SANDBOX_PROFILES",
]

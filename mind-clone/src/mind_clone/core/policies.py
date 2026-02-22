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

__all__ = ["get_active_tool_policy", "get_tool_policy_profile", "list_policy_profiles", "active_tool_policy_profile", "active_execution_sandbox_profile", "TOOL_POLICY_PROFILE_RAW", "TOOL_POLICY_PROFILES", "EXECUTION_SANDBOX_PROFILE_RAW", "EXECUTION_SANDBOX_PROFILES"]

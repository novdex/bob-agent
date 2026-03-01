"""
Tests for core/policies.py — Policy management utilities.
"""
import pytest
from mind_clone.core.policies import (
    get_active_tool_policy,
    get_tool_policy_profile,
    list_policy_profiles,
    active_tool_policy_profile,
    active_execution_sandbox_profile,
    validate_policy_name,
    get_policy_names,
    validate_policy_bounds,
    TOOL_POLICY_PROFILE_RAW,
    TOOL_POLICY_PROFILES,
    EXECUTION_SANDBOX_PROFILE_RAW,
    EXECUTION_SANDBOX_PROFILES,
)


class TestToolPolicies:
    """Test tool policy profiles."""

    def test_raw_profiles_exist(self):
        assert "safe" in TOOL_POLICY_PROFILE_RAW
        assert "balanced" in TOOL_POLICY_PROFILE_RAW
        assert "power" in TOOL_POLICY_PROFILE_RAW

    def test_safe_profile_blocks_dangerous_tools(self):
        safe = TOOL_POLICY_PROFILE_RAW["safe"]
        assert "run_command" in safe["blocked_tools"]
        assert "execute_python" in safe["blocked_tools"]

    def test_power_profile_no_blocks(self):
        power = TOOL_POLICY_PROFILE_RAW["power"]
        assert len(power["blocked_tools"]) == 0

    def test_balanced_profile_requires_approval(self):
        balanced = TOOL_POLICY_PROFILE_RAW["balanced"]
        assert "approval_required" in balanced
        assert "run_command" in balanced["approval_required"]

    def test_get_active_policy(self):
        policy = get_active_tool_policy()
        assert "profile" in policy
        assert "allowed_tools" in policy
        assert "blocked_tools" in policy

    def test_get_policy_profile_safe(self):
        profile = get_tool_policy_profile("safe")
        assert "blocked_tools" in profile
        assert "run_command" in profile["blocked_tools"]

    def test_get_policy_profile_unknown_returns_balanced(self):
        profile = get_tool_policy_profile("nonexistent")
        assert profile == get_tool_policy_profile("balanced")

    def test_list_profiles(self):
        profiles = list_policy_profiles()
        assert "safe" in profiles
        assert "balanced" in profiles
        assert "power" in profiles

    def test_active_tool_policy_profile_name(self):
        name = active_tool_policy_profile()
        assert name in ["safe", "balanced", "power"]


class TestValidatePolicyName:
    """Test policy name validation."""

    def test_valid_policy_names(self):
        for name in ["safe", "balanced", "power"]:
            valid, msg = validate_policy_name(name)
            assert valid is True, f"Policy '{name}' should be valid"

    def test_unknown_policy_rejected(self):
        valid, msg = validate_policy_name("unknown_policy")
        assert valid is False
        assert "Unknown" in msg

    def test_empty_policy_rejected(self):
        valid, msg = validate_policy_name("")
        assert valid is False

    def test_none_policy_rejected(self):
        valid, msg = validate_policy_name(None)
        assert valid is False


class TestGetPolicyNames:
    """Test policy names listing."""

    def test_get_policy_names_returns_list(self):
        names = get_policy_names()
        assert isinstance(names, list)
        assert len(names) > 0

    def test_policy_names_sorted(self):
        names = get_policy_names()
        assert names == sorted(names)

    def test_policy_names_includes_all(self):
        names = get_policy_names()
        assert "safe" in names
        assert "balanced" in names
        assert "power" in names


class TestValidatePolicyBounds:
    """Test policy parameter bounds validation."""

    def test_valid_policy_bounds(self):
        result = validate_policy_bounds("balanced")
        assert result["valid"] is True
        assert result["policy"] == "balanced"
        assert len(result["issues"]) == 0

    def test_unknown_policy_fails(self):
        result = validate_policy_bounds("nonexistent")
        assert result["valid"] is False
        assert "Unknown" in result["error"]

    def test_all_valid_policies(self):
        for name in ["safe", "balanced", "power"]:
            result = validate_policy_bounds(name)
            assert result["valid"] is True, f"Policy '{name}' bounds invalid"


class TestSandboxProfiles:
    """Test execution sandbox profiles."""

    def test_sandbox_profiles_exist(self):
        assert "strict" in EXECUTION_SANDBOX_PROFILE_RAW
        assert "balanced" in EXECUTION_SANDBOX_PROFILE_RAW
        assert "permissive" in EXECUTION_SANDBOX_PROFILE_RAW

    def test_strict_profile_has_docker(self):
        strict = EXECUTION_SANDBOX_PROFILE_RAW["strict"]
        assert strict["docker"] is True
        assert strict["network"] is False

    def test_active_sandbox_profile_name(self):
        name = active_execution_sandbox_profile()
        assert name in ["strict", "balanced", "permissive"]

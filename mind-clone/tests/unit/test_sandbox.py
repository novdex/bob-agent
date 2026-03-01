"""
Tests for core/sandbox.py — Sandbox execution utilities.
"""
import time
import pytest
from pathlib import Path
from mind_clone.core.state import SANDBOX_REGISTRY, SANDBOX_REGISTRY_LOCK, RUNTIME_STATE
from mind_clone.core.sandbox import (
    run_in_sandbox,
    get_sandbox_profile,
    os_sandbox_enabled,
    execution_sandbox_profile,
    _docker_executable,
    _normalize_os_sandbox_mode,
    active_sandbox_containers,
    sandbox_registry_touch,
    cleanup_sandbox_registry,
    sandbox_registry_snapshot,
    is_sandboxed,
    VALID_SANDBOX_MODES,
    _sandbox_registry_key,
)


class TestRunInSandbox:
    """Test sandbox command execution."""

    def test_run_echo(self):
        result = run_in_sandbox("echo hello", timeout=10)
        assert result["ok"] is True
        assert "hello" in result["stdout"]

    def test_run_failing_command(self):
        result = run_in_sandbox("exit 1", timeout=10)
        assert result["ok"] is False
        assert result["returncode"] == 1

    def test_run_timeout(self):
        # Sleep longer than timeout
        result = run_in_sandbox("sleep 30", timeout=1)
        assert result["ok"] is False
        assert "Timeout" in result.get("error", "")

    def test_run_invalid_command(self):
        result = run_in_sandbox("nonexistent_command_xyz_123", timeout=5)
        # Should either fail or return non-zero
        assert result["ok"] is False or result.get("returncode", 0) != 0


class TestSandboxProfile:
    """Test sandbox profile configuration."""

    def test_default_profile(self):
        profile = get_sandbox_profile()
        assert profile["name"] == "default"
        assert profile["strict"] is False

    def test_named_profile(self):
        profile = get_sandbox_profile("strict")
        assert profile["name"] == "strict"

    def test_os_sandbox_disabled(self):
        assert os_sandbox_enabled() is False

    def test_execution_sandbox_profile_none(self):
        assert execution_sandbox_profile() is None

    def test_docker_executable_none(self):
        assert _docker_executable() is None

    def test_normalize_os_sandbox_mode_valid(self):
        assert _normalize_os_sandbox_mode("docker") == "docker"
        assert _normalize_os_sandbox_mode("off") == "off"
        assert _normalize_os_sandbox_mode("disabled") == "disabled"
        assert _normalize_os_sandbox_mode("default") == "default"

    def test_normalize_os_sandbox_mode_invalid(self):
        # Invalid modes should return "disabled"
        assert _normalize_os_sandbox_mode("invalid_mode") == "disabled"
        assert _normalize_os_sandbox_mode("") == "disabled"
        assert _normalize_os_sandbox_mode(None) == "disabled"

    def test_active_sandbox_containers_empty(self):
        assert active_sandbox_containers() == []


class TestSandboxRegistry:
    """Test sandbox registry lifecycle."""

    def setup_method(self):
        with SANDBOX_REGISTRY_LOCK:
            SANDBOX_REGISTRY.clear()

    def test_registry_key_format(self):
        key = _sandbox_registry_key(1, Path("/tmp/test"))
        assert "::" in key
        assert "1" in key

    def test_touch_creates_entry(self):
        entry = sandbox_registry_touch(1, Path("/tmp/test"), "read_file")
        assert entry["owner_id"] == 1
        assert entry["last_tool"] == "read_file"
        assert "created_at" in entry

    def test_touch_reuses_entry(self):
        entry1 = sandbox_registry_touch(1, Path("/tmp/test"), "read_file")
        entry2 = sandbox_registry_touch(1, Path("/tmp/test"), "write_file")
        assert entry2["last_tool"] == "write_file"
        # Should be same entry (same key)
        assert entry1["key"] == entry2["key"]

    def test_cleanup_removes_stale(self):
        # Create an entry with old timestamp
        entry = sandbox_registry_touch(1, Path("/tmp/old"), "test")
        key = entry["key"]
        with SANDBOX_REGISTRY_LOCK:
            SANDBOX_REGISTRY[key]["last_used_mono"] = time.monotonic() - 9999
        removed = cleanup_sandbox_registry(max_age_seconds=1)
        assert removed >= 1

    def test_cleanup_keeps_fresh(self):
        sandbox_registry_touch(1, Path("/tmp/fresh"), "test")
        removed = cleanup_sandbox_registry(max_age_seconds=9999)
        assert removed == 0

    def test_snapshot_returns_copies(self):
        sandbox_registry_touch(1, Path("/tmp/snap"), "test")
        snap = sandbox_registry_snapshot()
        assert len(snap) >= 1
        assert isinstance(snap[0], dict)


class TestIsSandboxed:
    """Test is_sandboxed helper function."""

    def test_is_sandboxed_off(self):
        """is_sandboxed should return False for 'off' mode."""
        assert is_sandboxed("off") is False

    def test_is_sandboxed_disabled(self):
        """is_sandboxed should return False for 'disabled' mode."""
        assert is_sandboxed("disabled") is False

    def test_is_sandboxed_docker(self):
        """is_sandboxed should return True for 'docker' mode."""
        assert is_sandboxed("docker") is True

    def test_is_sandboxed_default(self):
        """is_sandboxed should return True for 'default' mode."""
        assert is_sandboxed("default") is True

    def test_is_sandboxed_invalid(self):
        """is_sandboxed should return False for invalid modes (normalized to 'disabled')."""
        assert is_sandboxed("invalid_mode") is False

    def test_is_sandboxed_dict_mode(self):
        """is_sandboxed should handle dict-like mode objects."""
        mode_dict = {"name": "docker"}
        assert is_sandboxed(mode_dict) is True
        mode_dict_off = {"name": "off"}
        assert is_sandboxed(mode_dict_off) is False

"""
Tests for security and policy enforcement (maps to FORTRESS + t2-bench).

Covers: tool policy profiles, approval gates, tool allowed checks,
        secret redaction, workspace diff gate, host exec interlock,
        circuit breaker, SSRF protection.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from mind_clone.core.security import (
    TOOL_POLICY_PROFILES,
    EXECUTION_SANDBOX_PROFILES,
    SAFE_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    get_tool_policy_profile,
    get_execution_sandbox_profile,
    check_tool_allowed,
    requires_approval,
    redact_secrets,
    evaluate_workspace_diff_gate,
    enforce_host_exec_interlock,
    circuit_allow_call,
    circuit_record_success,
    circuit_record_failure,
    circuit_snapshot,
    _CIRCUIT_BREAKER_STATE,
    _CIRCUIT_BREAKER_LOCK,
    validate_outbound_url,
    TOOL_RESULT_MAX_CHARS,
    guarded_tool_result_payload,
    sanitize_input,
    validate_owner_id,
)


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

class TestSanitizeInput:
    """Test input sanitization."""

    def test_clean_text_unchanged(self):
        text = "Hello world, this is safe."
        assert sanitize_input(text) == text

    def test_null_bytes_removed(self):
        text = "Hello\x00world"
        result = sanitize_input(text)
        assert "\x00" not in result
        assert "Hello" in result

    def test_control_chars_removed(self):
        text = "Hello\x01\x02\x03world"
        result = sanitize_input(text)
        assert "\x01" not in result
        assert "Hello" in result and "world" in result

    def test_newlines_preserved(self):
        text = "Hello\nworld"
        assert sanitize_input(text) == text

    def test_tabs_preserved(self):
        text = "Hello\tworld"
        assert sanitize_input(text) == text

    def test_length_limiting(self):
        text = "a" * 15000
        result = sanitize_input(text, max_length=10000)
        assert len(result) == 10000

    def test_non_string_input(self):
        assert sanitize_input(123) == ""
        assert sanitize_input(None) == ""

    def test_empty_string(self):
        assert sanitize_input("") == ""


class TestValidateOwnerId:
    """Test owner_id validation."""

    def test_valid_owner_id(self):
        valid, msg = validate_owner_id(1)
        assert valid is True
        assert msg is None

    def test_valid_large_owner_id(self):
        valid, msg = validate_owner_id(999999)
        assert valid is True

    def test_none_rejected(self):
        valid, msg = validate_owner_id(None)
        assert valid is False
        assert "None" in msg

    def test_zero_rejected(self):
        valid, msg = validate_owner_id(0)
        assert valid is False
        assert "positive" in msg

    def test_negative_rejected(self):
        valid, msg = validate_owner_id(-5)
        assert valid is False
        assert "positive" in msg

    def test_string_rejected(self):
        valid, msg = validate_owner_id("123")
        assert valid is False
        assert "int" in msg

    def test_float_rejected(self):
        valid, msg = validate_owner_id(1.5)
        assert valid is False


# ---------------------------------------------------------------------------
# Tool Policy Profiles
# ---------------------------------------------------------------------------

class TestToolPolicyProfiles:
    """Validate policy profiles are correctly structured."""

    def test_three_profiles_exist(self):
        assert set(TOOL_POLICY_PROFILES.keys()) == {"safe", "balanced", "power"}

    def test_safe_blocks_writes(self):
        assert TOOL_POLICY_PROFILES["safe"]["allow_write_file"] is False

    def test_safe_blocks_execution(self):
        assert TOOL_POLICY_PROFILES["safe"]["max_run_command_timeout"] == 0

    def test_balanced_allows_writes(self):
        assert TOOL_POLICY_PROFILES["balanced"]["allow_write_file"] is True
        assert TOOL_POLICY_PROFILES["balanced"]["allow_any_write_path"] is False

    def test_power_allows_everything(self):
        assert TOOL_POLICY_PROFILES["power"]["allow_write_file"] is True
        assert TOOL_POLICY_PROFILES["power"]["allow_any_write_path"] is True

    def test_tool_loop_limits_ascending(self):
        s = TOOL_POLICY_PROFILES["safe"]["chat_tool_loops"]
        b = TOOL_POLICY_PROFILES["balanced"]["chat_tool_loops"]
        p = TOOL_POLICY_PROFILES["power"]["chat_tool_loops"]
        assert s < b < p

    @patch("mind_clone.core.security.settings")
    def test_get_profile_balanced(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        profile = get_tool_policy_profile()
        assert profile == TOOL_POLICY_PROFILES["balanced"]

    @patch("mind_clone.core.security.settings")
    def test_get_profile_unknown_falls_back_balanced(self, mock_settings):
        mock_settings.tool_policy_profile = "unknown_profile"
        profile = get_tool_policy_profile()
        assert profile == TOOL_POLICY_PROFILES["balanced"]


# ---------------------------------------------------------------------------
# Execution Sandbox Profiles
# ---------------------------------------------------------------------------

class TestExecutionSandboxProfiles:

    def test_strict_blocks_both(self):
        assert EXECUTION_SANDBOX_PROFILES["strict"]["allow_run_command"] is False
        assert EXECUTION_SANDBOX_PROFILES["strict"]["allow_execute_python"] is False

    def test_default_allows_both(self):
        assert EXECUTION_SANDBOX_PROFILES["default"]["allow_run_command"] is True
        assert EXECUTION_SANDBOX_PROFILES["default"]["allow_execute_python"] is True


# ---------------------------------------------------------------------------
# check_tool_allowed (maps to t2-bench policy compliance)
# ---------------------------------------------------------------------------

class TestCheckToolAllowed:

    @patch("mind_clone.core.security.settings")
    def test_safe_tool_always_allowed(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        mock_settings.execution_sandbox_profile = "default"
        ok, reason = check_tool_allowed("search_web")
        assert ok is True

    @patch("mind_clone.core.security.settings")
    def test_write_file_blocked_in_safe(self, mock_settings):
        mock_settings.tool_policy_profile = "safe"
        mock_settings.execution_sandbox_profile = "default"
        ok, reason = check_tool_allowed("write_file")
        assert ok is False
        assert "not allowed" in reason

    @patch("mind_clone.core.security.settings")
    def test_run_command_blocked_in_strict_sandbox(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        mock_settings.execution_sandbox_profile = "strict"
        ok, reason = check_tool_allowed("run_command")
        assert ok is False
        assert "sandbox" in reason

    @patch("mind_clone.core.security.settings")
    def test_execute_python_blocked_in_strict_sandbox(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        mock_settings.execution_sandbox_profile = "strict"
        ok, reason = check_tool_allowed("execute_python")
        assert ok is False

    @patch("mind_clone.core.security.settings")
    def test_run_command_allowed_in_default_sandbox(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        mock_settings.execution_sandbox_profile = "default"
        ok, reason = check_tool_allowed("run_command")
        assert ok is True


# ---------------------------------------------------------------------------
# requires_approval (maps to FORTRESS approval gates)
# ---------------------------------------------------------------------------

class TestRequiresApproval:

    @patch("mind_clone.core.security.settings")
    def test_off_mode_never_requires(self, mock_settings):
        mock_settings.approval_gate_mode = "off"
        assert requires_approval("run_command", {}) is False

    @patch("mind_clone.core.security.settings")
    def test_safe_tool_never_requires(self, mock_settings):
        mock_settings.approval_gate_mode = "strict"
        assert requires_approval("search_web", {}) is False
        assert requires_approval("read_file", {}) is False

    @patch("mind_clone.core.security.settings")
    def test_strict_mode_requires_for_dangerous(self, mock_settings):
        mock_settings.approval_gate_mode = "strict"
        assert requires_approval("run_command", {}) is True
        assert requires_approval("write_file", {}) is True

    @patch("mind_clone.core.security.settings")
    def test_balanced_mode_checks_approval_list(self, mock_settings):
        mock_settings.approval_gate_mode = "balanced"
        mock_settings.approval_required_tools = {"run_command", "execute_python"}
        assert requires_approval("run_command", {}) is True
        assert requires_approval("write_file", {}) is False  # Not in list


# ---------------------------------------------------------------------------
# redact_secrets
# ---------------------------------------------------------------------------

class TestRedactSecrets:

    def test_empty_input(self):
        text, hits = redact_secrets("")
        assert text == ""
        assert hits == 0

    def test_none_input(self):
        text, hits = redact_secrets(None)
        assert text is None
        assert hits == 0

    def test_api_key_redacted(self):
        text, hits = redact_secrets("My key is sk-abcdefghijklmnopqrstuvwxyz")
        assert "sk-" not in text
        assert hits >= 1

    def test_bearer_token_redacted(self):
        text, hits = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")
        assert "eyJhbGci" not in text
        assert hits >= 1

    def test_password_redacted(self):
        text, hits = redact_secrets("password=mysecretpass123")
        assert "mysecretpass123" not in text

    def test_clean_text_unchanged(self):
        text, hits = redact_secrets("Hello world, how are you?")
        assert text == "Hello world, how are you?"
        assert hits == 0


# ---------------------------------------------------------------------------
# evaluate_workspace_diff_gate
# ---------------------------------------------------------------------------

class TestWorkspaceDiffGate:

    @patch("mind_clone.core.security.settings")
    def test_disabled_returns_clean(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = False
        result = evaluate_workspace_diff_gate("write_file", {"file_path": "test.py"})
        assert result["blocked"] is False
        assert result["require_approval"] is False

    @patch("mind_clone.core.security.settings")
    def test_non_write_tool_ignored(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = True
        result = evaluate_workspace_diff_gate("read_file", {})
        assert result["blocked"] is False

    @patch("mind_clone.core.security.settings")
    def test_small_write_passes(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = True
        mock_settings.workspace_diff_max_changed_lines = 100
        result = evaluate_workspace_diff_gate(
            "write_file",
            {"file_path": "test.py", "content": "line1\nline2\nline3"},
        )
        assert result["blocked"] is False
        assert result["changed_lines"] == 3

    @patch("mind_clone.core.security.settings")
    def test_large_write_blocked(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = True
        mock_settings.workspace_diff_max_changed_lines = 5
        mock_settings.workspace_diff_gate_mode = "block"
        content = "\n".join([f"line_{i}" for i in range(20)])
        result = evaluate_workspace_diff_gate(
            "write_file",
            {"file_path": "test.py", "content": content},
        )
        assert result["blocked"] is True

    @patch("mind_clone.core.security.settings")
    def test_large_write_approval_mode(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = True
        mock_settings.workspace_diff_max_changed_lines = 5
        mock_settings.workspace_diff_gate_mode = "approval"
        content = "\n".join([f"line_{i}" for i in range(20)])
        result = evaluate_workspace_diff_gate(
            "write_file",
            {"file_path": "test.py", "content": content},
        )
        assert result["require_approval"] is True
        assert result["blocked"] is False


# ---------------------------------------------------------------------------
# enforce_host_exec_interlock
# ---------------------------------------------------------------------------

class TestHostExecInterlock:

    @patch("mind_clone.core.security.settings")
    def test_disabled_allows_all(self, mock_settings):
        mock_settings.host_exec_interlock_enabled = False
        ok, reason = enforce_host_exec_interlock("rm -rf /")
        assert ok is True

    @patch("mind_clone.core.security.settings")
    def test_allowed_prefix_passes(self, mock_settings):
        mock_settings.host_exec_interlock_enabled = True
        mock_settings.host_exec_allowlist_prefixes = ["pip", "python"]
        ok, reason = enforce_host_exec_interlock("python script.py")
        assert ok is True

    @patch("mind_clone.core.security.settings")
    def test_blocked_command(self, mock_settings):
        mock_settings.host_exec_interlock_enabled = True
        mock_settings.host_exec_allowlist_prefixes = ["pip", "python"]
        ok, reason = enforce_host_exec_interlock("rm -rf /")
        assert ok is False
        assert "blocked" in reason.lower()


# ---------------------------------------------------------------------------
# Circuit Breaker (maps to Vending-Bench reliability)
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def setup_method(self):
        with _CIRCUIT_BREAKER_LOCK:
            _CIRCUIT_BREAKER_STATE.clear()

    def test_initial_state_allows(self):
        ok, msg = circuit_allow_call("test_provider")
        assert ok is True
        assert msg == ""

    def test_success_resets_failures(self):
        circuit_record_failure("test_provider", "err1")
        circuit_record_failure("test_provider", "err2")
        circuit_record_success("test_provider")
        snapshot = circuit_snapshot()
        assert snapshot["test_provider"]["failures"] == 0

    def test_5_failures_opens_circuit(self):
        for i in range(5):
            circuit_record_failure("bad_provider", f"err_{i}")
        ok, msg = circuit_allow_call("bad_provider")
        assert ok is False
        assert "OPEN" in msg

    def test_below_threshold_stays_closed(self):
        for i in range(4):
            circuit_record_failure("provider_a", f"err_{i}")
        ok, msg = circuit_allow_call("provider_a")
        assert ok is True

    def test_circuit_snapshot(self):
        circuit_record_failure("prov_x", "err")
        snapshot = circuit_snapshot()
        assert "prov_x" in snapshot
        assert snapshot["prov_x"]["failures"] == 1

    def test_different_providers_independent(self):
        for i in range(5):
            circuit_record_failure("provider_A", f"err_{i}")
        ok_a, _ = circuit_allow_call("provider_A")
        ok_b, _ = circuit_allow_call("provider_B")
        assert ok_a is False
        assert ok_b is True


# ---------------------------------------------------------------------------
# SSRF Protection (maps to FORTRESS safety)
# ---------------------------------------------------------------------------

class TestSSRFProtection:

    def test_empty_url_blocked(self):
        ok, reason = validate_outbound_url("")
        assert ok is False

    def test_ftp_scheme_blocked(self):
        ok, reason = validate_outbound_url("ftp://evil.com/file")
        assert ok is False
        assert "http" in reason.lower()

    def test_embedded_credentials_blocked(self):
        ok, reason = validate_outbound_url("https://user:pass@example.com")
        assert ok is False
        assert "credential" in reason.lower()

    def test_no_host_blocked(self):
        ok, reason = validate_outbound_url("https://")
        assert ok is False

    @patch("mind_clone.core.security.settings")
    def test_localhost_blocked_by_default(self, mock_settings):
        mock_settings.ssrf_allow_hosts = ""
        mock_settings.ssrf_deny_hosts = ""
        mock_settings.ssrf_block_localhost = True
        mock_settings.ssrf_guard_enabled = False
        ok, reason = validate_outbound_url("https://localhost/admin")
        assert ok is False
        assert "localhost" in reason.lower()

    @patch("mind_clone.core.security.settings")
    def test_denylisted_host_blocked(self, mock_settings):
        mock_settings.ssrf_allow_hosts = ""
        mock_settings.ssrf_deny_hosts = "evil.com"
        mock_settings.ssrf_block_localhost = True
        mock_settings.ssrf_guard_enabled = False
        ok, reason = validate_outbound_url("https://evil.com/api")
        assert ok is False
        assert "denylist" in reason.lower()

    @patch("mind_clone.core.security.settings")
    def test_valid_external_url_passes(self, mock_settings):
        mock_settings.ssrf_allow_hosts = ""
        mock_settings.ssrf_deny_hosts = ""
        mock_settings.ssrf_block_localhost = True
        mock_settings.ssrf_guard_enabled = False
        ok, reason = validate_outbound_url("https://api.example.com/data")
        assert ok is True


# ---------------------------------------------------------------------------
# Tool Result Guard
# ---------------------------------------------------------------------------

class TestToolResultGuard:

    @patch("mind_clone.core.security.settings")
    def test_dict_result_passes(self, mock_settings):
        mock_settings.secret_guardrail_enabled = False
        payload, truncated = guarded_tool_result_payload(
            "search_web", "tc_1", {"ok": True, "result": "data"},
        )
        assert '"ok": true' in payload.lower()
        assert truncated is False

    @patch("mind_clone.core.security.settings")
    def test_non_dict_wrapped(self, mock_settings):
        mock_settings.secret_guardrail_enabled = False
        payload, truncated = guarded_tool_result_payload(
            "test", "tc_1", "just a string",
        )
        assert "TOOL_RESULT_NON_DICT" in payload

    @patch("mind_clone.core.security.settings")
    def test_missing_ok_set_false(self, mock_settings):
        mock_settings.secret_guardrail_enabled = False
        payload, truncated = guarded_tool_result_payload(
            "test", "tc_1", {"result": "data"},
        )
        assert '"ok": false' in payload.lower()

    @patch("mind_clone.core.security.settings")
    def test_empty_call_id_flagged(self, mock_settings):
        mock_settings.secret_guardrail_enabled = False
        payload, truncated = guarded_tool_result_payload(
            "test", "", {"ok": True},
        )
        assert "MISSING_CALL_ID" in payload

    @patch("mind_clone.core.security.settings")
    def test_large_payload_truncated(self, mock_settings):
        mock_settings.secret_guardrail_enabled = False
        big_result = {"ok": True, "result": "x" * (TOOL_RESULT_MAX_CHARS + 5000)}
        payload, truncated = guarded_tool_result_payload(
            "test", "tc_1", big_result,
        )
        assert truncated is True
        assert "[TRUNCATED]" in payload

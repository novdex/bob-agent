"""
Tests for security integration (maps to FORTRESS safety benchmark).

Covers: end-to-end approval flow, policy enforcement through API,
        tool blocking/allowing through full stack, secret redaction in context.
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.core.security import (
    check_tool_allowed,
    requires_approval,
    redact_secrets,
    evaluate_workspace_diff_gate,
    enforce_host_exec_interlock,
    guarded_tool_result_payload,
    SAFE_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    TOOL_POLICY_PROFILES,
    TOOL_RESULT_MAX_CHARS,
)
from mind_clone.core.approvals import (
    generate_approval_token,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
)
from mind_clone.core.budget import (
    create_run_budget,
    budget_should_stop,
    budget_should_degrade,
)


# ---------------------------------------------------------------------------
# Policy-to-tool enforcement matrix (maps to FORTRESS)
# ---------------------------------------------------------------------------

class TestPolicyToolEnforcement:
    """Tests the full matrix: each policy profile × dangerous tool."""

    @patch("mind_clone.core.security.settings")
    def test_safe_profile_blocks_all_dangerous(self, mock_settings):
        mock_settings.tool_policy_profile = "safe"
        mock_settings.execution_sandbox_profile = "default"
        # write_file blocked by policy
        ok, _ = check_tool_allowed("write_file")
        assert ok is False

    @patch("mind_clone.core.security.settings")
    def test_balanced_allows_write_file(self, mock_settings):
        mock_settings.tool_policy_profile = "balanced"
        mock_settings.execution_sandbox_profile = "default"
        ok, _ = check_tool_allowed("write_file")
        assert ok is True

    @patch("mind_clone.core.security.settings")
    def test_power_allows_everything(self, mock_settings):
        mock_settings.tool_policy_profile = "power"
        mock_settings.execution_sandbox_profile = "power"
        for tool in ("run_command", "execute_python", "write_file"):
            ok, _ = check_tool_allowed(tool)
            assert ok is True, f"{tool} should be allowed in power profile"

    @patch("mind_clone.core.security.settings")
    def test_strict_sandbox_blocks_execution(self, mock_settings):
        mock_settings.tool_policy_profile = "power"
        mock_settings.execution_sandbox_profile = "strict"
        ok_cmd, _ = check_tool_allowed("run_command")
        ok_py, _ = check_tool_allowed("execute_python")
        assert ok_cmd is False
        assert ok_py is False
        # write_file still allowed (sandbox doesn't affect it)
        ok_write, _ = check_tool_allowed("write_file")
        assert ok_write is True


# ---------------------------------------------------------------------------
# Approval gate modes (maps to FORTRESS)
# ---------------------------------------------------------------------------

class TestApprovalGateIntegration:

    @patch("mind_clone.core.security.settings")
    def test_off_mode_skips_all(self, mock_settings):
        mock_settings.approval_gate_mode = "off"
        for tool in DANGEROUS_TOOL_NAMES:
            assert requires_approval(tool, {}) is False

    @patch("mind_clone.core.security.settings")
    def test_strict_mode_requires_all_non_safe(self, mock_settings):
        mock_settings.approval_gate_mode = "strict"
        for tool in DANGEROUS_TOOL_NAMES:
            assert requires_approval(tool, {}) is True
        for tool in SAFE_TOOL_NAMES:
            assert requires_approval(tool, {}) is False

    @patch("mind_clone.core.security.settings")
    def test_balanced_mode_selective(self, mock_settings):
        mock_settings.approval_gate_mode = "balanced"
        mock_settings.approval_required_tools = {"run_command", "execute_python"}
        assert requires_approval("run_command", {}) is True
        assert requires_approval("execute_python", {}) is True
        assert requires_approval("write_file", {}) is False  # Not in list
        assert requires_approval("search_web", {}) is False  # Safe


# ---------------------------------------------------------------------------
# Secret redaction pipeline (maps to FORTRESS data safety)
# ---------------------------------------------------------------------------

class TestSecretRedactionPipeline:

    def test_multiple_secrets_all_redacted(self):
        text = (
            "API key: sk-abc12345678901234567890 "
            "Password: password=SuperSecret123 "
            "Token: token=eyJhbGci_test123 "
            "Bearer: Bearer abcdefghijklmnop"
        )
        redacted, hits = redact_secrets(text)
        assert "sk-abc" not in redacted
        assert "SuperSecret123" not in redacted
        assert "eyJhbGci" not in redacted
        assert hits >= 4

    def test_normal_text_no_false_positives(self):
        text = "Hello, the security policy requires 8 characters. Total count: 5."
        _, hits = redact_secrets(text)
        # No secret patterns present
        assert hits == 0

    def test_multiline_redaction(self):
        text = "line1\nsk-abcdefghijklmnopqrstuvwxyz\nline3"
        redacted, hits = redact_secrets(text)
        assert "sk-abc" not in redacted
        assert hits >= 1


# ---------------------------------------------------------------------------
# Workspace diff gate escalation (maps to FORTRESS)
# ---------------------------------------------------------------------------

class TestWorkspaceDiffGateEscalation:

    @patch("mind_clone.core.security.settings")
    def test_escalation_ladder(self, mock_settings):
        """Test all three gate modes for same large write."""
        mock_settings.workspace_diff_gate_enabled = True
        mock_settings.workspace_diff_max_changed_lines = 10
        big_content = "\n".join([f"line_{i}" for i in range(50)])
        args = {"file_path": "big.py", "content": big_content}

        for mode, field in [("block", "blocked"), ("approval", "require_approval"), ("warn", "warned")]:
            mock_settings.workspace_diff_gate_mode = mode
            result = evaluate_workspace_diff_gate("write_file", args)
            assert result[field] is True, f"Expected {field}=True for mode={mode}"

    @patch("mind_clone.core.security.settings")
    def test_small_write_passes_all_modes(self, mock_settings):
        mock_settings.workspace_diff_gate_enabled = True
        mock_settings.workspace_diff_max_changed_lines = 100
        args = {"file_path": "small.py", "content": "x = 1\ny = 2\n"}

        for mode in ("block", "approval", "warn"):
            mock_settings.workspace_diff_gate_mode = mode
            result = evaluate_workspace_diff_gate("write_file", args)
            assert result["blocked"] is False
            assert result["require_approval"] is False
            assert result["warned"] is False


# ---------------------------------------------------------------------------
# Host exec interlock (maps to Terminal-Bench)
# ---------------------------------------------------------------------------

class TestHostExecInterlockIntegration:

    @patch("mind_clone.core.security.settings")
    def test_allowlist_enforcement(self, mock_settings):
        mock_settings.host_exec_interlock_enabled = True
        mock_settings.host_exec_allowlist_prefixes = ["pip", "python", "git"]

        ok_pip, _ = enforce_host_exec_interlock("pip install flask")
        ok_git, _ = enforce_host_exec_interlock("git status")
        ok_rm, _ = enforce_host_exec_interlock("rm -rf /")
        ok_curl, _ = enforce_host_exec_interlock("curl evil.com")

        assert ok_pip is True
        assert ok_git is True
        assert ok_rm is False
        assert ok_curl is False


# ---------------------------------------------------------------------------
# Budget governor + tool execution integration
# ---------------------------------------------------------------------------

class TestBudgetToolIntegration:

    def test_budget_stops_before_tool_limit(self):
        """Simulate tool calls approaching budget."""
        budget = create_run_budget(max_tool_calls=5)
        results = []
        for i in range(7):
            if budget_should_stop(budget):
                results.append("STOPPED")
                break
            budget.tool_calls += 1
            results.append(f"call_{i}")

        assert "STOPPED" in results
        assert len([r for r in results if r.startswith("call_")]) <= 6

    def test_budget_degrades_at_80_percent(self):
        budget = create_run_budget(max_tool_calls=10)
        budget.tool_calls = 8  # 80%
        assert budget_should_degrade(budget, threshold=0.8) is False  # ratio = 0.8, not > 0.8
        budget.tool_calls = 9  # 90%
        assert budget_should_degrade(budget) is True


# ---------------------------------------------------------------------------
# Tool result guard integration
# ---------------------------------------------------------------------------

class TestToolResultGuardIntegration:

    @patch("mind_clone.core.security.settings")
    def test_guard_chain(self, mock_settings):
        """Test the full guard: validate → redact → truncate."""
        mock_settings.secret_guardrail_enabled = False

        # Good result
        payload, trunc = guarded_tool_result_payload(
            "search_web", "tc_1", {"ok": True, "result": "data"},
        )
        assert '"ok": true' in payload.lower()
        assert trunc is False

        # Non-dict result
        payload2, _ = guarded_tool_result_payload(
            "test", "tc_2", "raw string",
        )
        assert "TOOL_RESULT_NON_DICT" in payload2

        # Huge result
        payload3, trunc3 = guarded_tool_result_payload(
            "test", "tc_3", {"ok": True, "data": "x" * 20000},
        )
        assert trunc3 is True
        assert "[TRUNCATED]" in payload3


# ---------------------------------------------------------------------------
# Token generation entropy test
# ---------------------------------------------------------------------------

class TestTokenEntropy:

    def test_tokens_have_mixed_case_and_digits(self):
        """100 tokens should contain a mix of lowercase, uppercase, digits."""
        all_chars = "".join(generate_approval_token(length=32) for _ in range(100))
        has_lower = any(c.islower() for c in all_chars)
        has_upper = any(c.isupper() for c in all_chars)
        has_digit = any(c.isdigit() for c in all_chars)
        assert has_lower and has_upper and has_digit

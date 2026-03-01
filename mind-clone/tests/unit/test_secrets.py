"""
Tests for core/secrets.py — Secret detection and redaction.
"""
import pytest
from mind_clone.core.secrets import (
    redact_secrets,
    detect_secrets,
    contains_secrets,
    redact_secret_data,
    SECRET_PATTERNS,
    validate_patterns,
)


class TestValidatePatterns:
    """Test secret pattern validation."""

    def test_all_patterns_compile(self):
        """Verify all regex patterns compile successfully."""
        results = validate_patterns()
        for result in results:
            assert result["compiled"] is True, f"Pattern {result['label']} failed to compile"

    def test_no_catastrophic_backtrack(self):
        """Verify patterns don't have catastrophic backtracking issues."""
        results = validate_patterns()
        for result in results:
            assert result["error"] is None, f"Pattern {result['label']} has issue: {result['error']}"

    def test_validate_patterns_returns_list(self):
        """Verify validate_patterns returns expected structure."""
        results = validate_patterns()
        assert isinstance(results, list)
        assert len(results) > 0
        for result in results:
            assert "label" in result
            assert "pattern" in result
            assert "compiled" in result
            assert "error" in result


class TestSecretDetection:
    """Test secret pattern detection."""

    def test_detect_anthropic_api_key(self):
        """Detect Anthropic API key (sk-ant-api03-...)."""
        text = "key: sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234"
        findings = detect_secrets(text)
        assert any(f["type"] == "ANTHROPIC_API_KEY" for f in findings)

    def test_detect_google_api_key(self):
        """Detect Google API key (AIza... 39+ chars)."""
        # Google API keys are typically 40+ chars after AIza
        text = "google_key = AIza1234567890abcdefghijklmnopqrstuvwxyzABC"
        findings = detect_secrets(text)
        assert any(f["type"] == "GOOGLE_API_KEY" for f in findings)

    def test_detect_jwt_token(self):
        """Detect JWT token (eyJ... base64)."""
        text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        findings = detect_secrets(text)
        assert any(f["type"] == "JWT_TOKEN" for f in findings)

    def test_detect_api_key(self):
        text = 'api_key = "sk_test_abc123def456789"'
        findings = detect_secrets(text)
        assert len(findings) > 0

    def test_detect_openai_classic_key(self):
        """sk- followed by 48 chars (classic format)."""
        text = "my key is sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234567ABCD"
        findings = detect_secrets(text)
        assert any(f["type"] == "OPENAI_API_KEY" for f in findings)

    def test_detect_openai_short_key(self):
        """sk- followed by fewer chars (still 20+)."""
        text = "key: sk-abcdef1234567890ABCDEF"
        findings = detect_secrets(text)
        assert any(f["type"] == "OPENAI_API_KEY" for f in findings)

    def test_detect_openai_proj_key(self):
        """sk-proj- keys (newer format, 100+ chars)."""
        text = "sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234567ABCD0123456789abcdefghijklmnopqrstuvwxyz012345678901234567"
        findings = detect_secrets(text)
        assert any(f["type"] == "OPENAI_API_KEY" for f in findings)

    def test_detect_github_classic_token(self):
        """ghp_ classic personal access token."""
        text = "token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        findings = detect_secrets(text)
        assert any(f["type"] == "GITHUB_TOKEN" for f in findings)

    def test_detect_github_fine_grained_token(self):
        """github_pat_ fine-grained token."""
        text = "github_pat_abcdefghij1234567890ABCDEFGHIJ1234567890zzzz"
        findings = detect_secrets(text)
        assert any(f["type"] == "GITHUB_TOKEN" for f in findings)

    def test_detect_github_oauth_token(self):
        """gho_ OAuth access token."""
        text = "gho_abcdefghij1234567890ABCDEFGHIJ"
        findings = detect_secrets(text)
        assert any(f["type"] == "GITHUB_TOKEN" for f in findings)

    def test_detect_aws_access_key(self):
        text = "AKIAIOSFODNN7EXAMPLE"
        findings = detect_secrets(text)
        assert any(f["type"] == "AWS_ACCESS_KEY" for f in findings)

    def test_detect_slack_bot_token(self):
        text = "xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwx"
        findings = detect_secrets(text)
        assert any(f["type"] == "SLACK_TOKEN" for f in findings)

    def test_detect_slack_user_token(self):
        text = "xoxp-123456789012-1234567890123-abcdefghijklmnopqrstuvwx"
        findings = detect_secrets(text)
        assert any(f["type"] == "SLACK_TOKEN" for f in findings)

    def test_detect_password(self):
        text = 'password = "mysecretpassword123"'
        findings = detect_secrets(text)
        assert len(findings) > 0

    def test_no_secrets_in_clean_text(self):
        text = "This is a normal message with no secrets."
        findings = detect_secrets(text)
        assert len(findings) == 0

    def test_sk_alone_too_short_not_detected(self):
        """sk- with very short suffix should not match."""
        text = "sk-abc"
        findings = detect_secrets(text)
        assert not any(f["type"] == "OPENAI_API_KEY" for f in findings)

    def test_contains_secrets_true(self):
        text = "api_key = 'abcdef1234567890abcdef'"
        assert contains_secrets(text) is True

    def test_contains_secrets_false(self):
        assert contains_secrets("hello world") is False


class TestSecretRedaction:
    """Test secret redaction."""

    def test_redact_api_key(self):
        text = 'api_key = "sk_test_abc123def456789"'
        redacted = redact_secrets(text)
        assert "sk_test_abc123" not in redacted
        assert "REDACTED" in redacted

    def test_redact_preserves_clean_text(self):
        text = "This is safe text."
        assert redact_secrets(text) == text

    def test_redact_openai_key(self):
        text = "key: sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234567ABCD"
        redacted = redact_secrets(text)
        assert "sk-aBcDe" not in redacted

    def test_redact_openai_proj_key(self):
        text = "sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234567ABCD"
        redacted = redact_secrets(text)
        assert "sk-proj" not in redacted

    def test_redact_github_token(self):
        text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        redacted = redact_secrets(text)
        assert "ghp_" not in redacted

    def test_redact_github_fine_grained(self):
        text = "github_pat_abcdefghij1234567890ABCDEFGHIJ1234567890zzzz"
        redacted = redact_secrets(text)
        assert "github_pat_" not in redacted

    def test_redact_aws_key(self):
        text = "aws key: AKIAIOSFODNN7EXAMPLE"
        redacted = redact_secrets(text)
        assert "AKIA" not in redacted

    def test_redact_slack_token(self):
        text = "xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwx"
        redacted = redact_secrets(text)
        assert "xoxb-" not in redacted

    def test_redact_anthropic_key(self):
        text = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678901234"
        redacted = redact_secrets(text)
        assert "sk-ant-api03" not in redacted

    def test_redact_google_key(self):
        # Google API keys are typically 40+ chars after AIza
        text = "google_key = AIza1234567890abcdefghijklmnopqrstuvwxyzABC"
        redacted = redact_secrets(text)
        assert "AIza" not in redacted

    def test_redact_jwt_token(self):
        text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        redacted = redact_secrets(text)
        assert "eyJ" not in redacted


class TestRedactSecretData:
    """Test recursive secret redaction on data structures."""

    def test_redact_string(self):
        result = redact_secret_data("api_key = 'abcdef1234567890abcdef'")
        assert "REDACTED" in result

    def test_redact_dict(self):
        data = {"config": "api_key = 'abcdef1234567890abcdef'", "safe": "hello"}
        result = redact_secret_data(data)
        assert "REDACTED" in result["config"]
        assert result["safe"] == "hello"

    def test_redact_list(self):
        data = ["safe text", "token = 'abcdef1234567890abcdef'"]
        result = redact_secret_data(data)
        assert result[0] == "safe text"
        assert "REDACTED" in result[1]

    def test_redact_nested(self):
        data = {"outer": {"inner": "api_secret = 'abcdef1234567890abcdef'"}}
        result = redact_secret_data(data)
        assert "REDACTED" in result["outer"]["inner"]

    def test_non_string_passthrough(self):
        assert redact_secret_data(42) == 42
        assert redact_secret_data(None) is None
        assert redact_secret_data(True) is True

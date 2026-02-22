"""
Tests for configuration module.
"""
import pytest
from mind_clone.config import Settings, settings


class TestConfig:
    """Test configuration settings."""
    
    def test_settings_load(self):
        """Test that settings load correctly."""
        assert settings is not None
        assert settings.app_dir is not None
    
    def test_policy_pack_presets(self):
        """Test policy pack presets returns dict."""
        presets = settings.policy_pack_preset
        assert isinstance(presets, dict)
        assert "approval_gate_mode" in presets
    
    def test_tool_policies(self):
        """Test tool policy profiles."""
        from mind_clone.config import POLICY_PACK_PRESETS
        assert POLICY_PACK_PRESETS is not None
        assert isinstance(POLICY_PACK_PRESETS, dict)


class TestEnvironmentVariables:
    """Test environment variable handling."""
    
    def test_default_values(self):
        """Test default configuration values."""
        s = Settings()
        assert isinstance(s.llm_temperature, float)
        assert s.llm_temperature > 0
        assert isinstance(s.llm_max_tokens, int)
        assert s.llm_max_tokens > 0
        assert s.approval_gate_mode in ["off", "balanced", "strict"]

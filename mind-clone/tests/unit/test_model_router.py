"""
Tests for core/model_router.py — Model routing utilities.
"""
import pytest
from mind_clone.core.model_router import (
    select_model_for_task,
    get_model_health,
    record_model_success,
    record_model_failure,
    configured_llm_profiles,
    llm_failover_active,
)


class TestModelRouter:
    """Test model routing logic."""

    def test_select_model_returns_string(self):
        model = select_model_for_task("translate text")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_select_model_different_complexity(self):
        # Both should return a valid model
        m1 = select_model_for_task("simple task", "simple")
        m2 = select_model_for_task("complex task", "complex")
        assert isinstance(m1, str)
        assert isinstance(m2, str)

    def test_get_model_health(self):
        health = get_model_health("test-model")
        assert health["ok"] is True
        assert health["model"] == "test-model"

    def test_record_model_success_no_crash(self):
        """record_model_success should not raise."""
        record_model_success("test-model")

    def test_record_model_failure_no_crash(self):
        """record_model_failure should not raise."""
        record_model_failure("test-model", "timeout")


class TestLLMProfiles:
    """Test LLM profile configuration."""

    def test_configured_profiles_has_primary(self):
        profiles = configured_llm_profiles()
        assert "primary" in profiles
        assert isinstance(profiles["primary"], str)

    def test_configured_profiles_has_fallback(self):
        profiles = configured_llm_profiles()
        assert "fallback" in profiles

    def test_llm_failover_active_returns_bool(self):
        result = llm_failover_active()
        assert isinstance(result, bool)

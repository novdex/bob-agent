"""
Tests for services/onboarding.py — Onboarding wizard.
"""
import pytest
import json

# The services/__init__.py imports telegram which uses Python 3.12+ syntax.
# Guard import for Python 3.10 compatibility.
try:
    from mind_clone.services.onboarding import (
        ONBOARDING_STEPS,
        get_onboarding_state,
        advance_onboarding,
        reset_onboarding,
    )
    _IMPORT_OK = True
except (SyntaxError, ImportError):
    _IMPORT_OK = False

from mind_clone.database.models import User

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="services.onboarding import failed (Python 3.10 compat)")


class TestOnboardingSteps:
    """Test step definitions."""

    def test_has_steps(self):
        assert len(ONBOARDING_STEPS) >= 4

    def test_first_step_is_welcome(self):
        assert ONBOARDING_STEPS[0]["key"] == "welcome"

    def test_last_step_is_complete(self):
        assert ONBOARDING_STEPS[-1]["key"] == "complete"

    def test_each_step_has_required_keys(self):
        for step in ONBOARDING_STEPS:
            assert "key" in step
            assert "title" in step
            assert "prompt" in step
            assert len(step["prompt"]) > 10


class TestGetOnboardingState:
    """Test state retrieval."""

    def test_nonexistent_user(self, db_session):
        state = get_onboarding_state(db_session, 99999)
        assert state["completed"] is False
        assert state["current_step"] == 0
        assert state["step_key"] == "welcome"

    def test_fresh_user(self, db_session, sample_user):
        state = get_onboarding_state(db_session, sample_user.id)
        assert state["completed"] is False
        assert state["current_step"] == 0
        assert state["total_steps"] == len(ONBOARDING_STEPS)


class TestAdvanceOnboarding:
    """Test step advancement."""

    def test_nonexistent_user(self, db_session):
        result = advance_onboarding(db_session, 99999, "response")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_advances_step(self, db_session, sample_user):
        result = advance_onboarding(db_session, sample_user.id, "My Name")
        assert result["ok"] is True
        assert result["current_step"] == 1
        assert result["completed"] is False

    def test_completes_after_all_steps(self, db_session, sample_user):
        """Advance through all steps — should complete now that User has meta_json."""
        for i in range(len(ONBOARDING_STEPS)):
            result = advance_onboarding(db_session, sample_user.id, f"response_{i}")
            assert result["ok"] is True
        assert result["completed"] is True


class TestResetOnboarding:
    """Test onboarding reset."""

    def test_resets_state(self, db_session, sample_user):
        advance_onboarding(db_session, sample_user.id, "My Name")
        result = reset_onboarding(db_session, sample_user.id)
        assert result["ok"] is True
        state = get_onboarding_state(db_session, sample_user.id)
        assert state["current_step"] == 0
        assert state["completed"] is False

    def test_reset_nonexistent_user(self, db_session):
        result = reset_onboarding(db_session, 99999)
        assert result["ok"] is False

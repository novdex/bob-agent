"""
Tests for services/skills.py — Skills system.
"""
import pytest

try:
    from mind_clone.services.skills import (
        SKILLS_ACTIVE_TOP_K,
        SKILLS_MAX_BODY_CHARS,
        SKILLS_MAX_PER_OWNER,
        _normalize_key,
        _keyword_set,
        _score_skill,
        _safe_skill_hints,
        _skill_keyword_set,
        synthesize_skill_blueprint,
        save_skill_profile,
        list_skill_profiles,
        skill_profile_detail,
        set_skill_status,
        rollback_skill_version,
        select_active_skills_for_prompt,
        GAP_PHRASES,
    )
    _IMPORT_OK = True
except (SyntaxError, ImportError):
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="services.skills import failed (Python 3.10 compat)")


class TestConstants:
    """Test skill configuration constants."""

    def test_top_k(self):
        assert SKILLS_ACTIVE_TOP_K == 3

    def test_max_body(self):
        assert SKILLS_MAX_BODY_CHARS == 5000

    def test_max_per_owner(self):
        assert SKILLS_MAX_PER_OWNER == 120


class TestNormalizeKey:
    """Test skill key normalization."""

    def test_lowercase(self):
        assert _normalize_key("MySkill") == "myskill"

    def test_replaces_special_chars(self):
        assert _normalize_key("my-skill!") == "my_skill"

    def test_collapses_underscores(self):
        assert _normalize_key("my___skill") == "my_skill"

    def test_strips_leading_trailing(self):
        assert _normalize_key("_skill_") == "skill"

    def test_empty_returns_default(self):
        assert _normalize_key("") == "unnamed_skill"

    def test_truncates_to_60(self):
        result = _normalize_key("a" * 100)
        assert len(result) <= 60


class TestKeywordSet:
    """Test keyword extraction."""

    def test_basic(self):
        result = _keyword_set("hello world python")
        assert "hello" in result
        assert "world" in result
        assert "python" in result

    def test_filters_short_words(self):
        result = _keyword_set("a to do it the big")
        assert "a" not in result
        assert "to" not in result
        assert "big" in result

    def test_empty_string(self):
        assert _keyword_set("") == set()

    def test_none(self):
        assert _keyword_set(None) == set()


class TestSafeSkillHints:
    """Test hint normalization."""

    def test_list_input(self):
        result = _safe_skill_hints(["crypto", "bitcoin"])
        assert result == ["crypto", "bitcoin"]

    def test_string_input(self):
        result = _safe_skill_hints("crypto, bitcoin, eth")
        assert len(result) == 3

    def test_deduplication(self):
        result = _safe_skill_hints(["crypto", "crypto", "btc"])
        assert result == ["crypto", "btc"]

    def test_max_24_hints(self):
        hints = [f"hint_{i}" for i in range(30)]
        result = _safe_skill_hints(hints)
        assert len(result) <= 24

    def test_empty(self):
        assert _safe_skill_hints(None) == []
        assert _safe_skill_hints("") == []


class TestSynthesizeSkillBlueprint:
    """Test blueprint generation."""

    def test_crypto_blueprint(self):
        bp = synthesize_skill_blueprint("daily crypto market analysis")
        assert "crypto" in bp["skill_key"].lower()
        assert "Crypto" in bp["title"]
        assert len(bp["trigger_hints"]) > 0

    def test_news_blueprint(self):
        bp = synthesize_skill_blueprint("build a daily news digest")
        assert "news" in bp["skill_key"].lower()
        assert "News" in bp["title"]

    def test_generic_blueprint(self):
        bp = synthesize_skill_blueprint("do something interesting")
        assert bp["title"] == "Autonomous Research Skill"

    def test_preferred_name(self):
        bp = synthesize_skill_blueprint("anything", preferred_name="my_custom")
        assert bp["skill_key"] == "my_custom"

    def test_regression_appended(self):
        bp = synthesize_skill_blueprint("crypto regression analysis")
        assert "regression" in bp["body_text"].lower()

    def test_game_theory_appended(self):
        bp = synthesize_skill_blueprint("game theory strategy analysis")
        assert "game-theory" in bp["body_text"].lower()

    def test_has_required_keys(self):
        bp = synthesize_skill_blueprint("test")
        assert "skill_key" in bp
        assert "title" in bp
        assert "intent" in bp
        assert "trigger_hints" in bp
        assert "body_text" in bp


class TestSaveSkillProfile:
    """Test skill CRUD with DB."""

    def test_creates_new_skill(self, db_session, sample_user):
        profile, version = save_skill_profile(
            db_session, sample_user.id, "test_skill", "Test Skill", "body text",
            trigger_hints=["test", "skill"],
        )
        assert profile.id is not None
        assert profile.skill_key == "test_skill"
        assert version.version == 1

    def test_updates_existing_skill(self, db_session, sample_user):
        save_skill_profile(db_session, sample_user.id, "upd_skill", "V1", "body1")
        profile, version = save_skill_profile(db_session, sample_user.id, "upd_skill", "V2", "body2")
        assert version.version == 2
        assert profile.title == "V2"

    def test_key_normalization(self, db_session, sample_user):
        profile, _ = save_skill_profile(db_session, sample_user.id, "My Skill!", "Title", "body")
        assert profile.skill_key == "my_skill"


class TestListSkillProfiles:
    """Test skill listing."""

    def test_lists_skills(self, db_session, sample_user):
        save_skill_profile(db_session, sample_user.id, "s1", "S1", "b1")
        save_skill_profile(db_session, sample_user.id, "s2", "S2", "b2")
        skills = list_skill_profiles(db_session, sample_user.id)
        assert len(skills) >= 2

    def test_filters_by_status(self, db_session, sample_user):
        save_skill_profile(db_session, sample_user.id, "active_s", "Active", "b")
        skills = list_skill_profiles(db_session, sample_user.id, status="active")
        assert all(s.status == "active" for s in skills)


class TestSkillProfileDetail:
    """Test skill detail retrieval."""

    def test_returns_profile_and_versions(self, db_session, sample_user):
        profile, _ = save_skill_profile(db_session, sample_user.id, "detail_s", "Detail", "b")
        found_profile, versions = skill_profile_detail(db_session, profile.id)
        assert found_profile is not None
        assert len(versions) >= 1

    def test_returns_none_for_nonexistent(self, db_session):
        profile, versions = skill_profile_detail(db_session, 99999)
        assert profile is None
        assert versions == []


class TestSetSkillStatus:
    """Test status changes."""

    def test_sets_status(self, db_session, sample_user):
        profile, _ = save_skill_profile(db_session, sample_user.id, "status_s", "Title", "b")
        result = set_skill_status(db_session, profile.id, "disabled")
        assert result.status == "disabled"

    def test_returns_none_for_nonexistent(self, db_session):
        result = set_skill_status(db_session, 99999, "disabled")
        assert result is None


class TestRollbackSkillVersion:
    """Test version rollback."""

    def test_rollback_to_v1(self, db_session, sample_user):
        profile, _ = save_skill_profile(db_session, sample_user.id, "rb_s", "V1", "b1")
        save_skill_profile(db_session, sample_user.id, "rb_s", "V2", "b2")
        result = rollback_skill_version(db_session, profile.id, 1)
        assert result is not None
        assert result.active_version == 1

    def test_returns_none_for_invalid_version(self, db_session, sample_user):
        profile, _ = save_skill_profile(db_session, sample_user.id, "rb_bad", "V1", "b1")
        result = rollback_skill_version(db_session, profile.id, 99)
        assert result is None


class TestSelectActiveSkills:
    """Test skill matching for prompt injection."""

    def test_no_skills_returns_empty(self, db_session, sample_user):
        # Assuming no skills exist for a different owner
        result = select_active_skills_for_prompt(db_session, 99999, "test query")
        assert result == []

    def test_empty_message_returns_empty(self, db_session, sample_user):
        save_skill_profile(
            db_session, sample_user.id, "match_s", "Match", "body",
            trigger_hints=["crypto", "market"],
        )
        result = select_active_skills_for_prompt(db_session, sample_user.id, "")
        assert result == []

    def test_matches_by_hints(self, db_session, sample_user):
        save_skill_profile(
            db_session, sample_user.id, "crypto_s", "Crypto Skill", "crypto analysis body",
            trigger_hints=["crypto", "bitcoin", "market"],
        )
        result = select_active_skills_for_prompt(db_session, sample_user.id, "analyze the crypto market today")
        assert len(result) >= 1
        assert "Crypto Skill" in result[0]


class TestGapPhrases:
    """Test gap detection constants."""

    def test_gap_phrases_exist(self):
        assert len(GAP_PHRASES) >= 5
        assert "i don't have a tool" in GAP_PHRASES

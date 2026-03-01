"""
Tests for database/session.py — Database session management.
"""
import pytest
from pathlib import Path

from mind_clone.database.session import (
    init_db,
    get_db,
    check_db_health,
    ensure_db_ready,
    SessionLocal,
    engine,
)


class TestInitDb:
    """Test database initialization."""

    def test_init_db_no_error(self):
        # Should not raise
        init_db()

    def test_idempotent(self):
        init_db()
        init_db()  # Should not raise on second call


class TestGetDb:
    """Test session generator."""

    def test_yields_session(self):
        gen = get_db()
        db = next(gen)
        assert db is not None
        # Clean up
        try:
            next(gen)
        except StopIteration:
            pass

    def test_session_closes(self):
        gen = get_db()
        db = next(gen)
        try:
            next(gen)
        except StopIteration:
            pass
        # After generator exhausts, session should be closed


class TestCheckDbHealth:
    """Test health check."""

    def test_healthy_db(self):
        ok, error = check_db_health()
        assert ok is True
        assert error is None


class TestEnsureDbReady:
    """Test readiness check."""

    def test_returns_true(self):
        result = ensure_db_ready()
        assert result is True


class TestSessionLocal:
    """Test session factory."""

    def test_creates_session(self):
        session = SessionLocal()
        assert session is not None
        session.close()


class TestEngine:
    """Test engine configuration."""

    def test_engine_exists(self):
        assert engine is not None

    def test_engine_is_sqlite(self):
        assert "sqlite" in str(engine.url)

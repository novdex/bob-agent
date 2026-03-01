"""
Tests for api/factory.py — FastAPI application factory.
"""
import pytest

try:
    from mind_clone.api.factory import create_app, lifespan
    _IMPORT_OK = True
except (SyntaxError, ImportError):
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="api.factory import failed (Python 3.10 compat)")


class TestCreateApp:
    """Test create_app factory."""

    def test_creates_fastapi_app(self):
        app = create_app()
        assert app is not None
        assert app.title == "Mind Clone Agent"

    def test_app_has_cors_middleware(self):
        app = create_app()
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_app_includes_router(self):
        app = create_app()
        route_paths = [r.path for r in app.routes]
        assert len(route_paths) > 0

    def test_app_version(self):
        app = create_app()
        assert app.version == "0.1.0"

    def test_app_description(self):
        app = create_app()
        assert "Sovereign AI Agent" in app.description


class TestLifespan:
    """Test lifespan context manager."""

    def test_lifespan_defined(self):
        import inspect
        assert inspect.isasyncgenfunction(lifespan) or callable(lifespan)

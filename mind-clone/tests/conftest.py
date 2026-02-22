"""
Pytest configuration and fixtures.
"""
import os
import sys
import tempfile
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set test environment variables
os.environ.setdefault('ENVIRONMENT', 'test')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test_token')
os.environ.setdefault('KIMI_API_KEY', 'test_key')


@pytest.fixture(scope='session')
def test_db_path():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except:
        pass


@pytest.fixture
def db_session(test_db_path):
    """Create a fresh database session for each test."""
    from mind_clone.config import Settings
    from mind_clone.database.models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # Create engine with test database
    engine = create_engine(f"sqlite:///{test_db_path}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create session
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Drop tables
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_client():
    """Create a FastAPI test client."""
    from fastapi.testclient import TestClient
    from mind_clone.api.factory import create_app
    from mind_clone.database.session import init_db
    
    # Initialize DB
    init_db()
    
    # Create app and client
    app = create_app()
    client = TestClient(app)
    return client


@pytest.fixture
def sample_user(db_session):
    """Create a sample user for testing."""
    from mind_clone.database.models import User
    
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        username=f"testuser_{unique_id}",
        telegram_chat_id=f"chat_{unique_id}",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

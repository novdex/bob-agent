"""
Database session management.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from .models import Base
from ..config import settings

logger = logging.getLogger("mind_clone.database")

# Create engine
engine = create_engine(
    f"sqlite:///{settings.db_file_path.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_pre_ping=True,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    # Migrate: add meta_json to users if missing (SQLite ALTER TABLE ADD COLUMN)
    try:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
            if "meta_json" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN meta_json TEXT"))
                conn.commit()
                logger.info("Migration: added meta_json column to users table")
    except Exception as e:
        logger.warning("Migration check for meta_json failed: %s", e)
    logger.info("Database initialized at %s", settings.db_file_path)


def get_db() -> Generator[Session, None, None]:
    """Get database session (for dependency injection)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> tuple[bool, str | None]:
    """Check database health."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).scalar_one()
        return True, None
    except Exception as e:
        return False, str(e)


def ensure_db_ready() -> bool:
    """Ensure database is ready for use."""
    try:
        init_db()
        return True
    except Exception as e:
        logger.error(f"Database readiness check failed: {e}")
        return False


def owner_workspace_root(
    owner_id: int,
    source_type: str | None = None,
    source_ref: str | None = None,
    session_id: str | None = None,
    agent_key: str | None = None,
) -> Path:
    """Get the workspace root directory for an owner."""
    from ..config import APP_DIR

    # Default workspace root
    default_root = APP_DIR.parent / "persist" / "workspaces"
    default_root.mkdir(parents=True, exist_ok=True)

    try:
        db = SessionLocal()
        from .models import TeamAgent

        # Try to get team agent workspace
        row = (
            db.query(TeamAgent)
            .filter(TeamAgent.agent_owner_id == int(owner_id))
            .order_by(TeamAgent.id.desc())
            .first()
        )

        if row and row.workspace_root:
            base_path = Path(str(row.workspace_root)).expanduser().resolve(strict=False)
        else:
            base_path = default_root / str(owner_id)

        db.close()
        base_path.mkdir(parents=True, exist_ok=True)
        return base_path
    except Exception:
        return default_root

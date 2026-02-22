"""
FastAPI application factory.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..database.session import init_db
from .routes import router

logger = logging.getLogger("mind_clone.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    logger.info("Starting up Mind Clone Agent API")
    init_db()

    # Load custom tools from DB into TOOL_DISPATCH
    try:
        from ..tools.registry import load_custom_tools_from_db
        loaded = load_custom_tools_from_db()
        logger.info("Loaded %d custom tools from database", loaded)
    except Exception as exc:
        logger.warning("Failed to load custom tools: %s", exc)

    yield
    
    # Shutdown
    logger.info("Shutting down Mind Clone Agent API")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Mind Clone Agent",
        description="Sovereign AI Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routes
    app.include_router(router)
    
    return app

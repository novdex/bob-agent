"""
API route assembly — combines all sub-routers into a single ``router``.

``factory.py`` imports ``from .routes import router`` which resolves here.
"""
from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router
from .debug import router as debug_router
from .nodes import router as nodes_router
from .ops import router as ops_router
from .ui import router as ui_router
from .telegram import router as telegram_router
from .workflow import router as workflow_router

# Re-export lifespan so factory or other entry-points can use it
from ._shared import app_lifespan  # noqa: F401

router = APIRouter()

router.include_router(health_router)
router.include_router(debug_router)
router.include_router(nodes_router)
router.include_router(ops_router)
router.include_router(ui_router)
router.include_router(telegram_router)
router.include_router(workflow_router)

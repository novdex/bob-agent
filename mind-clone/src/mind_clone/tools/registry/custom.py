"""
Custom tool runtime registry — loading, registration, and usage tracking.

Handles CUSTOM_TOOL_REGISTRY, load_custom_tools_from_db(),
custom_tool_definitions(), register_tool(), unregister_tool().
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Callable, Any, List

from ...config import settings

logger = logging.getLogger("mind_clone.tools.registry.custom")


# ---------------------------------------------------------------------------
# Custom tool runtime registry (loaded from DB + created at runtime)
# ---------------------------------------------------------------------------
CUSTOM_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def load_custom_tools_from_db() -> int:
    """Load all enabled+tested custom tools from DB into registries.

    Called once at startup. Returns count of loaded tools.
    """
    if not settings.custom_tool_enabled:
        return 0

    from ...database.session import SessionLocal
    from ...database.models import GeneratedTool
    from ...core.state import set_runtime_state_value
    from .definitions import _create_custom_tool_executor
    from .dispatch import TOOL_DISPATCH

    db = SessionLocal()
    loaded = 0
    try:
        tools = db.query(GeneratedTool).filter(
            GeneratedTool.enabled == 1,
            GeneratedTool.test_passed == 1,
        ).all()
        for t in tools:
            try:
                func = _create_custom_tool_executor(t.code)
                params = json.loads(t.parameters_json) if t.parameters_json else {"type": "object", "properties": {}}
                entry = {
                    "func": func,
                    "definition": {
                        "type": "function",
                        "function": {
                            "name": t.tool_name,
                            "description": t.description or "",
                            "parameters": params,
                        },
                    },
                    "owner_id": t.owner_id,
                }
                CUSTOM_TOOL_REGISTRY[t.tool_name] = entry
                TOOL_DISPATCH[t.tool_name] = func
                loaded += 1
            except Exception as exc:
                logger.warning("CUSTOM_TOOL_LOAD_FAIL name=%s error=%s", t.tool_name, str(exc)[:200])
    finally:
        db.close()

    set_runtime_state_value("custom_tools_loaded", loaded)
    logger.info("CUSTOM_TOOLS_LOADED count=%d", loaded)
    return loaded


def custom_tool_definitions() -> List[dict]:
    """Return OpenAI function-calling definitions for all loaded custom tools."""
    return [entry["definition"] for entry in CUSTOM_TOOL_REGISTRY.values()]


def _increment_custom_tool_usage(tool_name: str) -> None:
    """Increment usage_count for a custom tool in DB."""
    try:
        from ...database.session import SessionLocal
        from ...database.models import GeneratedTool

        db = SessionLocal()
        try:
            row = db.query(GeneratedTool).filter(GeneratedTool.tool_name == tool_name).first()
            if row:
                row.usage_count = int(row.usage_count or 0) + 1
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _record_custom_tool_error(tool_name: str, error: str) -> None:
    """Record last_error for a custom tool in DB."""
    try:
        from ...database.session import SessionLocal
        from ...database.models import GeneratedTool

        db = SessionLocal()
        try:
            row = db.query(GeneratedTool).filter(GeneratedTool.tool_name == tool_name).first()
            if row:
                row.last_error = str(error)[:2000]
                db.commit()
        finally:
            db.close()
    except Exception:
        pass

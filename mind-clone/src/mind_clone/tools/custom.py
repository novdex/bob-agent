"""
Custom and plugin tools — LLM-callable wrappers for custom tool CRUD.

These functions are registered in TOOL_DISPATCH and called directly by the
agent loop when the LLM invokes ``create_tool``, ``list_custom_tools``, or
``disable_custom_tool``.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..config import settings

logger = logging.getLogger("mind_clone.tools.custom")


def tool_list_plugin_tools(args: dict) -> dict:
    """List available plugin tools."""
    return {"ok": True, "plugins": [], "note": "Plugin tools require implementation"}


def tool_create_tool(args: dict) -> dict:
    """Create a custom tool at runtime.

    The LLM provides ``name``, ``description``, ``code`` (Python with a
    ``def tool_main(args: dict) -> dict:`` entry point), and optionally
    ``parameters`` (JSON Schema) and ``requirements`` (pip packages).
    """
    if not settings.custom_tool_enabled:
        return {"ok": False, "error": "Custom tool creation is disabled"}

    name = str(args.get("name", "")).strip()
    description = str(args.get("description", "")).strip()
    code = str(args.get("code", "")).strip()
    parameters_str = str(args.get("parameters", "{}")).strip()
    requirements = args.get("requirements")
    if requirements:
        requirements = str(requirements).strip()

    if not name or not description or not code:
        return {"ok": False, "error": "Missing required fields: name, description, code"}

    owner_id = int(args.get("_owner_id", 0) or 0)

    # Parse parameters
    try:
        parameters = json.loads(parameters_str) if parameters_str else {}
    except json.JSONDecodeError:
        parameters = {"type": "object", "properties": {}}

    # Create via CRUD layer
    from ..core.custom_tools import create_custom_tool
    result = create_custom_tool(
        owner_id=owner_id,
        name=name,
        code=code,
        description=description,
        parameters=parameters,
        requirements=requirements,
        run_test=True,
    )

    if not result.get("ok"):
        return result

    # Register the tool into the live dispatch table
    try:
        from .registry import (
            _create_custom_tool_executor,
            CUSTOM_TOOL_REGISTRY,
            TOOL_DISPATCH,
        )
        from ..core.state import increment_runtime_state

        func = _create_custom_tool_executor(code)
        entry = {
            "func": func,
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "owner_id": owner_id,
        }
        CUSTOM_TOOL_REGISTRY[name] = entry
        TOOL_DISPATCH[name] = func
        increment_runtime_state("custom_tools_created")
        logger.info("CUSTOM_TOOL_REGISTERED name=%s owner=%d", name, owner_id)
    except Exception as exc:
        logger.warning("CUSTOM_TOOL_REGISTER_FAIL name=%s error=%s", name, str(exc)[:200])
        # Tool was saved to DB but couldn't be loaded into memory.
        # It will be loaded on next restart.

    return {
        "ok": True,
        "tool_name": name,
        "message": f"Tool '{name}' created and registered successfully",
        "test_passed": result.get("test_passed", False),
    }


def tool_list_custom_tools(args: dict) -> dict:
    """List custom tools for the current owner."""
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    from ..core.custom_tools import list_custom_tools
    tools = list_custom_tools(owner_id=owner_id or None, enabled_only=True)

    return {
        "ok": True,
        "tools": [
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "enabled": t.get("enabled", False),
                "test_passed": t.get("test_passed", False),
                "usage_count": t.get("usage_count", 0),
            }
            for t in tools
        ],
        "count": len(tools),
    }


def tool_disable_custom_tool(args: dict) -> dict:
    """Disable a custom tool by name."""
    tool_name = str(args.get("tool_name") or args.get("name") or args.get("tool_id") or "").strip()
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 0)

    if not tool_name:
        return {"ok": False, "error": "tool_name is required"}

    from ..core.custom_tools import get_custom_tool, update_custom_tool

    tool = get_custom_tool(tool_name=tool_name, owner_id=owner_id or None)
    if not tool:
        return {"ok": False, "error": f"Tool '{tool_name}' not found"}

    result = update_custom_tool(
        tool_id=tool["id"],
        owner_id=owner_id,
        updates={"enabled": 0},
        run_test=False,
    )

    if result.get("ok"):
        # Remove from live registries
        from .registry import unregister_tool
        unregister_tool(tool_name)
        logger.info("CUSTOM_TOOL_DISABLED name=%s owner=%d", tool_name, owner_id)

    return {
        "ok": result.get("ok", False),
        "tool_name": tool_name,
        "disabled": True,
    }


def tool_llm_structured_task(args: dict) -> dict:
    """Execute a structured LLM task."""
    instruction = str(args.get("instruction", "")).strip()

    if not instruction:
        return {"ok": False, "error": "instruction is required"}

    return {"ok": False, "error": "LLM structured task requires LLM client implementation"}

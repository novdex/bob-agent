"""
Tool creation logic — CRUD operations for custom tools.

Handles creating, updating, deleting, and listing custom tools in the database.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from ...database.models import GeneratedTool
from ...database.session import SessionLocal

from .validator import validate_tool_code
from .executor import test_custom_tool

logger = logging.getLogger("mind_clone.core.custom_tools.creator")


def _tool_to_dict(tool: GeneratedTool) -> Optional[Dict[str, Any]]:
    """Convert a GeneratedTool model to a dictionary."""
    if tool is None:
        return None

    return {
        "id": tool.id,
        "owner_id": tool.owner_id,
        "tool_name": tool.tool_name,
        "description": tool.description,
        "parameters": json.loads(tool.parameters_json or "{}"),
        "code": tool.code,
        "requirements": tool.requirements,
        "enabled": bool(tool.enabled),
        "test_passed": bool(tool.test_passed),
        "usage_count": tool.usage_count or 0,
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
    }


def _validate_tool_name(name: str) -> bool:
    """Validate tool name format.

    Must be alphanumeric with underscores, start with a letter, max 64 chars.
    """
    if not name:
        return False
    import re
    pattern = r'^[a-zA-Z][a-zA-Z0-9_]*$'
    if not re.match(pattern, name):
        return False
    if len(name) > 64:
        return False
    return True


def list_custom_tools(
    owner_id: Optional[int] = None,
    enabled_only: bool = True,
    test_passed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List custom tools with optional filtering.

    Args:
        owner_id: Filter by owner
        enabled_only: Only show enabled tools
        test_passed_only: Only show tools that passed testing
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of custom tool dictionaries
    """
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)

        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        if enabled_only:
            query = query.filter(GeneratedTool.enabled == 1)
        if test_passed_only:
            query = query.filter(GeneratedTool.test_passed == 1)

        tools = query.order_by(GeneratedTool.updated_at.desc()).offset(offset).limit(limit).all()

        return [_tool_to_dict(t) for t in tools]
    finally:
        db.close()


def get_custom_tool(
    tool_id: Optional[int] = None,
    tool_name: Optional[str] = None,
    owner_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Get a custom tool by ID or name.

    Args:
        tool_id: Tool ID
        tool_name: Tool name
        owner_id: Optional owner verification

    Returns:
        Tool dictionary or None
    """
    if not tool_id and not tool_name:
        return None

    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)

        if tool_id:
            query = query.filter(GeneratedTool.id == tool_id)
        if tool_name:
            query = query.filter(GeneratedTool.tool_name == tool_name)
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)

        tool = query.first()
        return _tool_to_dict(tool) if tool else None
    finally:
        db.close()


def create_custom_tool(
    owner_id: int,
    name: str,
    code: str,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None,
    requirements: Optional[str] = None,
    run_test: bool = True,
) -> Dict[str, Any]:
    """Create a new custom tool.

    Args:
        owner_id: The owner ID
        name: Tool name (must be unique)
        code: Python code for the tool
        description: Tool description
        parameters: JSON schema for parameters
        requirements: pip requirements
        run_test: Whether to test the tool before saving

    Returns:
        Creation result with tool ID or error
    """
    # Validate name
    if not _validate_tool_name(name):
        return {"ok": False, "error": "Invalid tool name. Use alphanumeric and underscores only."}

    # Validate code
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": f"Code validation failed: {validation['error']}"}

    db = SessionLocal()
    try:
        # Check for existing tool with same name
        existing = db.query(GeneratedTool).filter(
            GeneratedTool.tool_name == name,
        ).first()

        if existing:
            return {"ok": False, "error": f"Tool '{name}' already exists"}

        # Test if requested
        test_passed = False
        if run_test:
            test_result = test_custom_tool(code, parameters or {})
            test_passed = test_result.get("ok", False)
            if not test_passed:
                logger.warning(f"Tool test failed for {name}: {test_result.get('error')}")

        tool = GeneratedTool(
            owner_id=owner_id,
            tool_name=name,
            description=description,
            parameters_json=json.dumps(parameters or {}),
            code=code,
            requirements=requirements,
            enabled=1,
            test_passed=1 if test_passed else 0,
            usage_count=0,
        )

        db.add(tool)
        db.commit()
        db.refresh(tool)

        logger.info(f"Created custom tool {tool.id}: {name}")

        return {
            "ok": True,
            "id": tool.id,
            "name": name,
            "test_passed": test_passed,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def update_custom_tool(
    tool_id: int,
    owner_id: int,
    updates: Dict[str, Any],
    run_test: bool = True,
) -> Dict[str, Any]:
    """Update a custom tool.

    Args:
        tool_id: Tool ID
        owner_id: Owner ID for verification
        updates: Fields to update
        run_test: Whether to retest if code changes

    Returns:
        Update result
    """
    db = SessionLocal()
    try:
        tool = db.query(GeneratedTool).filter(
            GeneratedTool.id == tool_id,
            GeneratedTool.owner_id == owner_id,
        ).first()

        if not tool:
            return {"ok": False, "error": "Tool not found"}

        # Update allowed fields
        allowed_fields = {
            "description", "code", "requirements", "enabled"
        }

        code_changed = False
        for field, value in updates.items():
            if field in allowed_fields and hasattr(tool, field):
                if field == "code" and value != tool.code:
                    code_changed = True
                if field == "enabled":
                    value = 1 if value else 0
                setattr(tool, field, value)

        # Retest if code changed
        test_passed = bool(tool.test_passed)
        if code_changed and run_test:
            validation = validate_tool_code(tool.code)
            if not validation["valid"]:
                db.rollback()
                return {"ok": False, "error": f"Code validation failed: {validation['error']}"}

            test_result = test_custom_tool(tool.code, json.loads(tool.parameters_json or "{}"))
            test_passed = test_result.get("ok", False)
            tool.test_passed = 1 if test_passed else 0

            if not test_passed:
                logger.warning(f"Tool test failed during update: {test_result.get('error')}")

        tool.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(tool)

        logger.info(f"Updated custom tool {tool_id}")

        return {
            "ok": True,
            "id": tool.id,
            "test_passed": test_passed,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def delete_custom_tool(
    tool_id: int,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Delete a custom tool.

    Args:
        tool_id: Tool ID to delete
        owner_id: Optional owner verification

    Returns:
        Deletion result
    """
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool).filter(GeneratedTool.id == tool_id)

        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)

        tool = query.first()
        if not tool:
            return {"ok": False, "error": "Tool not found"}

        tool_name = tool.tool_name
        db.delete(tool)
        db.commit()

        logger.info(f"Deleted custom tool {tool_id}: {tool_name}")

        return {"ok": True, "deleted": tool_id}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def prune_custom_tools(
    older_than_days: int = 90,
    enabled_only: bool = False,
) -> Dict[str, Any]:
    """Delete custom tools older than specified days.

    Args:
        older_than_days: Delete tools not updated in this many days
        enabled_only: Only prune disabled tools

    Returns:
        Prune result with count of deleted tools
    """
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)

        query = db.query(GeneratedTool).filter(
            GeneratedTool.updated_at < cutoff_date
        )

        if enabled_only:
            query = query.filter(GeneratedTool.enabled == 0)

        count = query.count()

        if count > 0:
            query.delete()
            db.commit()
            logger.info(f"Pruned {count} custom tools older than {older_than_days} days")

        return {
            "ok": True,
            "pruned_count": count,
            "older_than_days": older_than_days,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune custom tools: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()

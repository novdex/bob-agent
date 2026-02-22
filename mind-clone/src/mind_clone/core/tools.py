"""
Tool management utilities.

Provides custom tool loading from database, node registry management,
and performance tracking for tools.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable

from sqlalchemy.orm import Session

from ..database.models import GeneratedTool, ToolPerformanceLog, NodeRegistration
from ..database.session import SessionLocal
from ..config import settings, CUSTOM_TOOL_ENABLED
from ..utils import utc_now_iso, _safe_json_list, truncate_text

logger = logging.getLogger("mind_clone.core.tools")

# Registry for dynamically loaded custom tools
_custom_tool_registry: Dict[str, Dict[str, Any]] = {}
_remote_node_registry: Dict[str, Dict[str, Any]] = {}
_plugin_tools_registry: Dict[str, Dict[str, Any]] = {}

__all__ = [
    "load_custom_tools_from_db",
    "load_remote_node_registry",
    "load_plugin_tools_registry",
    "tool_list_execution_nodes",
    "tool_list_plugin_tools",
    "prune_tool_performance_logs",
    "register_custom_tool",
    "unregister_custom_tool",
    "get_custom_tool",
    "execute_custom_tool",
    "record_tool_performance",
    "get_tool_performance_stats",
    "get_tool_recommendations",
]


def load_custom_tools_from_db(enabled_only: bool = True) -> List[Dict[str, Any]]:
    """
    Load custom tools from database.

    Args:
        enabled_only: Only load enabled tools

    Returns:
        List of custom tool dictionaries
    """
    if not CUSTOM_TOOL_ENABLED:
        return []

    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)
        if enabled_only:
            query = query.filter(GeneratedTool.enabled == 1)

        tools = query.all()
        result = []

        for tool in tools:
            tool_dict = {
                "id": tool.id,
                "name": tool.tool_name,
                "description": tool.description,
                "parameters": json.loads(tool.parameters_json or "{}"),
                "code": tool.code,
                "requirements": tool.requirements,
                "enabled": bool(tool.enabled),
                "test_passed": bool(tool.test_passed),
                "usage_count": tool.usage_count,
                "last_error": tool.last_error,
                "created_at": tool.created_at.isoformat() if tool.created_at else None,
                "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
            }
            result.append(tool_dict)

            # Register in memory
            _custom_tool_registry[tool.tool_name] = tool_dict

        logger.info(f"Loaded {len(result)} custom tools from database")
        return result
    finally:
        db.close()


def load_remote_node_registry() -> Dict[str, Any]:
    """
    Load remote node registry from database.

    Returns:
        Dictionary of node registrations
    """
    db = SessionLocal()
    try:
        nodes = db.query(NodeRegistration).filter(NodeRegistration.enabled == 1).all()
        registry = {}

        for node in nodes:
            node_info = {
                "id": node.id,
                "name": node.node_name,
                "base_url": node.base_url,
                "capabilities": json.loads(node.capabilities_json or "[]"),
                "enabled": bool(node.enabled),
                "last_heartbeat": node.last_heartbeat_at.isoformat()
                if node.last_heartbeat_at
                else None,
                "last_error": node.last_error,
                "created_at": node.created_at.isoformat() if node.created_at else None,
            }
            registry[node.node_name] = node_info
            _remote_node_registry[node.node_name] = node_info

        return registry
    finally:
        db.close()


def load_plugin_tools_registry() -> Dict[str, Any]:
    """
    Load plugin tools registry.

    Returns:
        Dictionary of plugin tools
    """
    # This would typically load from a plugins directory or config
    # For now, return the in-memory registry
    return dict(_plugin_tools_registry)


def tool_list_execution_nodes(
    healthy_only: bool = False,
    capability: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List execution nodes with optional filtering.

    Args:
        healthy_only: Only return nodes with recent heartbeat
        capability: Filter by capability

    Returns:
        List of node dictionaries
    """
    db = SessionLocal()
    try:
        query = db.query(NodeRegistration)

        if healthy_only:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=settings.node_heartbeat_stale_seconds
            )
            query = query.filter(
                NodeRegistration.last_heartbeat_at >= cutoff,
            )

        nodes = query.all()
        result = []

        for node in nodes:
            capabilities = json.loads(node.capabilities_json or "[]")

            # Filter by capability if specified
            if capability and capability not in capabilities:
                continue

            # Determine health status
            is_healthy = False
            if node.last_heartbeat_at:
                stale_threshold = datetime.now(timezone.utc) - timedelta(
                    seconds=settings.node_heartbeat_stale_seconds
                )
                is_healthy = node.last_heartbeat_at >= stale_threshold

            result.append(
                {
                    "id": node.id,
                    "name": node.node_name,
                    "base_url": node.base_url,
                    "capabilities": capabilities,
                    "enabled": bool(node.enabled),
                    "healthy": is_healthy,
                    "last_heartbeat": node.last_heartbeat_at.isoformat()
                    if node.last_heartbeat_at
                    else None,
                    "last_error": node.last_error,
                }
            )

        return result
    finally:
        db.close()


def tool_list_plugin_tools() -> List[Dict[str, Any]]:
    """
    List all registered plugin tools.

    Returns:
        List of plugin tool dictionaries
    """
    return [{"name": name, **info} for name, info in _plugin_tools_registry.items()]


def register_custom_tool(
    name: str,
    handler: Callable,
    description: str = "",
    parameters: Optional[Dict] = None,
) -> bool:
    """
    Register a custom tool at runtime.

    Args:
        name: Tool name
        handler: Tool handler function
        description: Tool description
        parameters: Tool parameters schema

    Returns:
        True if registered successfully
    """
    _custom_tool_registry[name] = {
        "name": name,
        "handler": handler,
        "description": description,
        "parameters": parameters or {},
        "runtime_registered": True,
    }
    logger.info(f"Registered custom tool: {name}")
    return True


def unregister_custom_tool(name: str) -> bool:
    """
    Unregister a custom tool.

    Args:
        name: Tool name to unregister

    Returns:
        True if unregistered successfully
    """
    if name in _custom_tool_registry:
        del _custom_tool_registry[name]
        logger.info(f"Unregistered custom tool: {name}")
        return True
    return False


def get_custom_tool(name: str) -> Optional[Dict[str, Any]]:
    """
    Get a custom tool by name.

    Args:
        name: Tool name

    Returns:
        Tool dictionary or None
    """
    # Check runtime registry first
    if name in _custom_tool_registry:
        return _custom_tool_registry[name]

    # Load from database
    db = SessionLocal()
    try:
        tool = (
            db.query(GeneratedTool)
            .filter(
                GeneratedTool.tool_name == name,
                GeneratedTool.enabled == 1,
            )
            .first()
        )

        if tool:
            return {
                "id": tool.id,
                "name": tool.tool_name,
                "description": tool.description,
                "parameters": json.loads(tool.parameters_json or "{}"),
                "code": tool.code,
                "test_passed": bool(tool.test_passed),
            }
        return None
    finally:
        db.close()


def execute_custom_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a custom tool by name.

    Args:
        name: Tool name
        args: Tool arguments

    Returns:
        Execution result
    """
    tool = get_custom_tool(name)
    if not tool:
        return {"ok": False, "error": f"Tool not found: {name}"}

    start_time = time.time()
    success = False
    error_category = None

    try:
        if "handler" in tool:
            # Runtime registered tool
            handler = tool["handler"]
            result = handler(args)
            success = result.get("ok", True)
            return result
        else:
            # Database tool - execute code
            code = tool.get("code", "")
            if not code:
                return {"ok": False, "error": "Tool has no code"}

            # Create safe execution environment
            safe_globals = {
                "__builtins__": {
                    "len": len,
                    "range": range,
                    "enumerate": enumerate,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    "sum": sum,
                    "min": min,
                    "max": max,
                    "abs": abs,
                    "round": round,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "set": set,
                    "tuple": tuple,
                    "print": lambda *args, **kwargs: None,  # No-op print
                },
                "args": args,
                "result": None,
            }

            # Execute in restricted environment
            exec(code, safe_globals)
            result = safe_globals.get("result", {"ok": False, "error": "No result set"})
            success = result.get("ok", True)
            return result

    except Exception as e:
        success = False
        error_category = type(e).__name__
        return {"ok": False, "error": str(e), "error_category": error_category}
    finally:
        # Record performance
        duration_ms = int((time.time() - start_time) * 1000)
        # Update usage count if from database
        if tool and "id" in tool:
            _increment_tool_usage(tool["id"])


def _increment_tool_usage(tool_id: int) -> None:
    """Increment usage count for a tool."""
    db = SessionLocal()
    try:
        tool = db.query(GeneratedTool).filter(GeneratedTool.id == tool_id).first()
        if tool:
            tool.usage_count = (tool.usage_count or 0) + 1
            db.commit()
    except Exception as e:
        logger.error(f"Failed to increment tool usage: {e}")
    finally:
        db.close()


def record_tool_performance(
    owner_id: int,
    tool_name: str,
    success: bool,
    duration_ms: int,
    error_category: Optional[str] = None,
    source_type: str = "chat",
) -> bool:
    """
    Record tool performance metrics.

    Args:
        owner_id: The owner ID
        tool_name: Name of the tool
        success: Whether execution succeeded
        duration_ms: Execution duration in milliseconds
        error_category: Category of error if failed
        source_type: Source of the tool call

    Returns:
        True if recorded successfully
    """
    if not settings.TOOL_PERF_TRACKING_ENABLED:
        return False

    db = SessionLocal()
    try:
        log = ToolPerformanceLog(
            owner_id=owner_id,
            tool_name=tool_name,
            source_type=source_type,
            success=1 if success else 0,
            duration_ms=duration_ms,
            error_category=error_category,
        )
        db.add(log)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to record tool performance: {e}")
        return False
    finally:
        db.close()


def get_tool_performance_stats(
    tool_name: Optional[str] = None,
    owner_id: Optional[int] = None,
    days: int = 7,
) -> Dict[str, Any]:
    """
    Get performance statistics for tools.

    Args:
        tool_name: Optional tool name filter
        owner_id: Optional owner filter
        days: Number of days to analyze

    Returns:
        Statistics dictionary
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    db = SessionLocal()
    try:
        query = db.query(ToolPerformanceLog).filter(
            ToolPerformanceLog.created_at >= cutoff,
        )

        if tool_name:
            query = query.filter(ToolPerformanceLog.tool_name == tool_name)
        if owner_id:
            query = query.filter(ToolPerformanceLog.owner_id == owner_id)

        logs = query.all()

        if not logs:
            return {
                "total_calls": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0,
                "tools": {},
            }

        # Aggregate stats
        total = len(logs)
        successes = sum(1 for l in logs if l.success)
        failures = total - successes
        avg_duration = sum(l.duration_ms for l in logs) / total

        # Per-tool stats
        tool_stats = {}
        for log in logs:
            name = log.tool_name
            if name not in tool_stats:
                tool_stats[name] = {
                    "calls": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_duration_ms": 0,
                }
            tool_stats[name]["calls"] += 1
            if log.success:
                tool_stats[name]["successes"] += 1
            else:
                tool_stats[name]["failures"] += 1
            tool_stats[name]["total_duration_ms"] += log.duration_ms

        # Calculate rates and averages
        for name, stats in tool_stats.items():
            stats["success_rate"] = stats["successes"] / stats["calls"] if stats["calls"] > 0 else 0
            stats["avg_duration_ms"] = (
                stats["total_duration_ms"] // stats["calls"] if stats["calls"] > 0 else 0
            )

        return {
            "total_calls": total,
            "success_count": successes,
            "failure_count": failures,
            "success_rate": successes / total if total > 0 else 0,
            "avg_duration_ms": int(avg_duration),
            "tools": tool_stats,
        }
    finally:
        db.close()


def get_tool_recommendations(owner_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get tool recommendations based on performance history.

    Args:
        owner_id: Optional owner filter

    Returns:
        List of recommendations
    """
    stats = get_tool_performance_stats(owner_id=owner_id, days=30)
    recommendations = []

    for tool_name, tool_stats in stats.get("tools", {}).items():
        success_rate = tool_stats["success_rate"]

        if success_rate < 0.5:
            recommendations.append(
                {
                    "tool": tool_name,
                    "type": "warning",
                    "message": f"Low success rate ({success_rate:.1%}) - consider reviewing usage",
                    "priority": "high" if success_rate < 0.2 else "medium",
                }
            )
        elif tool_stats["avg_duration_ms"] > 5000:
            recommendations.append(
                {
                    "tool": tool_name,
                    "type": "performance",
                    "message": f"Slow execution ({tool_stats['avg_duration_ms']}ms avg) - consider optimization",
                    "priority": "medium",
                }
            )
        elif success_rate > 0.95 and tool_stats["calls"] > 10:
            recommendations.append(
                {
                    "tool": tool_name,
                    "type": "positive",
                    "message": f"Reliable tool ({success_rate:.1%} success, {tool_stats['calls']} calls)",
                    "priority": "low",
                }
            )

    return recommendations


def prune_tool_performance_logs(older_than_days: int = 30) -> int:
    """
    Prune old tool performance logs.

    Args:
        older_than_days: Delete logs older than this many days

    Returns:
        Number of logs deleted
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    db = SessionLocal()
    try:
        logs = (
            db.query(ToolPerformanceLog)
            .filter(
                ToolPerformanceLog.created_at < cutoff,
            )
            .all()
        )

        count = len(logs)
        for log in logs:
            db.delete(log)

        db.commit()
        logger.info(f"Pruned {count} tool performance logs")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune tool performance logs: {e}")
        return 0
    finally:
        db.close()


def register_plugin_tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    handler: Callable,
    trusted: bool = False,
) -> Dict[str, Any]:
    """
    Register a plugin tool.

    Args:
        name: Tool name
        description: Tool description
        parameters: Tool parameters schema
        handler: Tool handler function
        trusted: Whether tool is from trusted source

    Returns:
        Registration result
    """
    # Check trust if enforcement enabled
    if settings.PLUGIN_ENFORCE_TRUST and not trusted:
        return {"ok": False, "error": "Plugin trust enforcement enabled and tool not trusted"}

    _plugin_tools_registry[name] = {
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "trusted": trusted,
        "registered_at": utc_now_iso(),
    }

    logger.info(f"Registered plugin tool: {name} (trusted={trusted})")
    return {"ok": True, "name": name}


def execute_plugin_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a plugin tool.

    Args:
        name: Tool name
        args: Tool arguments

    Returns:
        Execution result
    """
    if name not in _plugin_tools_registry:
        return {"ok": False, "error": f"Plugin tool not found: {name}"}

    tool = _plugin_tools_registry[name]
    handler = tool.get("handler")

    if not handler:
        return {"ok": False, "error": "Plugin tool has no handler"}

    try:
        return handler(args)
    except Exception as e:
        logger.error(f"Plugin tool execution failed: {name} - {e}")
        return {"ok": False, "error": str(e)}

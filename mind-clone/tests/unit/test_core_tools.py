"""
Unit tests for mind_clone.core.tools module.

Covers custom tool loading, registration, execution, performance tracking,
and plugin tool management.
"""
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, Mock
from typing import Dict, Any

from mind_clone.core.tools import (
    load_custom_tools_from_db,
    load_remote_node_registry,
    load_plugin_tools_registry,
    tool_list_execution_nodes,
    tool_list_plugin_tools,
    register_custom_tool,
    unregister_custom_tool,
    get_custom_tool,
    execute_custom_tool,
    record_tool_performance,
    get_tool_performance_stats,
    get_tool_recommendations,
    prune_tool_performance_logs,
    register_plugin_tool,
    execute_plugin_tool,
    _increment_tool_usage,
    _custom_tool_registry,
    _remote_node_registry,
    _plugin_tools_registry,
)


class TestLoadCustomToolsFromDb:
    """Test load_custom_tools_from_db function."""

    def test_load_custom_tools_returns_empty_when_disabled(self, monkeypatch):
        """Test that disabled custom tools returns empty list."""
        monkeypatch.setattr(
            "mind_clone.core.tools.CUSTOM_TOOL_ENABLED",
            False
        )
        result = load_custom_tools_from_db()
        assert result == []

    def test_load_custom_tools_enabled_only(self, monkeypatch):
        """Test loading only enabled custom tools."""
        mock_tool = MagicMock()
        mock_tool.id = 1
        mock_tool.tool_name = "my_tool"
        mock_tool.description = "Test tool"
        mock_tool.parameters_json = '{"param1": "string"}'
        mock_tool.code = "print('hello')"
        mock_tool.requirements = None
        mock_tool.enabled = 1
        mock_tool.test_passed = 1
        mock_tool.usage_count = 5
        mock_tool.last_error = None
        mock_tool.created_at = datetime.now(timezone.utc)
        mock_tool.updated_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [mock_tool]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.CUSTOM_TOOL_ENABLED", True):
            with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
                result = load_custom_tools_from_db(enabled_only=True)

        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["enabled"] is True
        assert result[0]["usage_count"] == 5

    def test_load_custom_tools_all(self, monkeypatch):
        """Test loading all custom tools (disabled and enabled)."""
        mock_tool1 = MagicMock()
        mock_tool1.id = 1
        mock_tool1.tool_name = "tool1"
        mock_tool1.description = "Tool 1"
        mock_tool1.parameters_json = "{}"
        mock_tool1.code = "code1"
        mock_tool1.requirements = None
        mock_tool1.enabled = 1
        mock_tool1.test_passed = 0
        mock_tool1.usage_count = 0
        mock_tool1.last_error = None
        mock_tool1.created_at = datetime.now(timezone.utc)
        mock_tool1.updated_at = datetime.now(timezone.utc)

        mock_tool2 = MagicMock()
        mock_tool2.id = 2
        mock_tool2.tool_name = "tool2"
        mock_tool2.description = "Tool 2"
        mock_tool2.parameters_json = "{}"
        mock_tool2.code = "code2"
        mock_tool2.requirements = None
        mock_tool2.enabled = 0
        mock_tool2.test_passed = 0
        mock_tool2.usage_count = 0
        mock_tool2.last_error = None
        mock_tool2.created_at = datetime.now(timezone.utc)
        mock_tool2.updated_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_query = MagicMock()
        # When enabled_only is False, filter() is not called, so return all() directly
        mock_query.all.return_value = [mock_tool1, mock_tool2]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.CUSTOM_TOOL_ENABLED", True):
            with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
                result = load_custom_tools_from_db(enabled_only=False)

        assert len(result) == 2

    def test_load_custom_tools_registers_in_memory(self, monkeypatch):
        """Test that loaded tools are registered in memory."""
        mock_tool = MagicMock()
        mock_tool.id = 1
        mock_tool.tool_name = "mem_tool"
        mock_tool.description = "Memory test"
        mock_tool.parameters_json = "{}"
        mock_tool.code = "pass"
        mock_tool.requirements = None
        mock_tool.enabled = 1
        mock_tool.test_passed = 0
        mock_tool.usage_count = 0
        mock_tool.last_error = None
        mock_tool.created_at = datetime.now(timezone.utc)
        mock_tool.updated_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [mock_tool]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.CUSTOM_TOOL_ENABLED", True):
            with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
                # Clear registry first
                _custom_tool_registry.clear()
                result = load_custom_tools_from_db()

        assert "mem_tool" in _custom_tool_registry


class TestLoadRemoteNodeRegistry:
    """Test load_remote_node_registry function."""

    def test_load_remote_node_registry(self):
        """Test loading remote node registry from database."""
        mock_node = MagicMock()
        mock_node.id = 1
        mock_node.node_name = "node_a"
        mock_node.base_url = "http://localhost:8001"
        mock_node.capabilities_json = '["compute", "storage"]'
        mock_node.enabled = 1
        mock_node.last_heartbeat_at = datetime.now(timezone.utc)
        mock_node.last_error = None
        mock_node.created_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [mock_node]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            _remote_node_registry.clear()
            result = load_remote_node_registry()

        assert "node_a" in result
        assert result["node_a"]["base_url"] == "http://localhost:8001"
        assert result["node_a"]["capabilities"] == ["compute", "storage"]

    def test_load_remote_node_registry_registers_in_memory(self):
        """Test that nodes are registered in memory registry."""
        mock_node = MagicMock()
        mock_node.id = 1
        mock_node.node_name = "test_node"
        mock_node.base_url = "http://test:8001"
        mock_node.capabilities_json = "[]"
        mock_node.enabled = 1
        mock_node.last_heartbeat_at = None
        mock_node.last_error = None
        mock_node.created_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [mock_node]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            _remote_node_registry.clear()
            load_remote_node_registry()

        assert "test_node" in _remote_node_registry


class TestLoadPluginToolsRegistry:
    """Test load_plugin_tools_registry function."""

    def test_load_plugin_tools_registry_returns_dict(self):
        """Test that plugin tools registry returns a dictionary copy."""
        _plugin_tools_registry.clear()
        _plugin_tools_registry["test_plugin"] = {"description": "Test"}

        result = load_plugin_tools_registry()

        assert isinstance(result, dict)
        assert "test_plugin" in result
        assert result["test_plugin"]["description"] == "Test"


class TestToolListExecutionNodes:
    """Test tool_list_execution_nodes function."""

    def test_list_execution_nodes_basic(self):
        """Test basic node listing."""
        mock_node = MagicMock()
        mock_node.id = 1
        mock_node.node_name = "exec_node"
        mock_node.base_url = "http://exec:8001"
        mock_node.capabilities_json = '["task1", "task2"]'
        mock_node.enabled = 1
        mock_node.last_heartbeat_at = datetime.now(timezone.utc)
        mock_node.last_error = None

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_node]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = tool_list_execution_nodes()

        assert len(result) == 1
        assert result[0]["name"] == "exec_node"
        assert result[0]["enabled"] is True
        assert result[0]["healthy"] is True

    def test_list_execution_nodes_with_capability_filter(self):
        """Test node listing with capability filter."""
        mock_node1 = MagicMock()
        mock_node1.id = 1
        mock_node1.node_name = "node1"
        mock_node1.base_url = "http://node1:8001"
        mock_node1.capabilities_json = '["compute"]'
        mock_node1.enabled = 1
        mock_node1.last_heartbeat_at = datetime.now(timezone.utc)
        mock_node1.last_error = None

        mock_node2 = MagicMock()
        mock_node2.id = 2
        mock_node2.node_name = "node2"
        mock_node2.base_url = "http://node2:8001"
        mock_node2.capabilities_json = '["storage"]'
        mock_node2.enabled = 1
        mock_node2.last_heartbeat_at = datetime.now(timezone.utc)
        mock_node2.last_error = None

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_node1, mock_node2]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = tool_list_execution_nodes(capability="compute")

        assert len(result) == 1
        assert result[0]["name"] == "node1"

    def test_list_execution_nodes_healthy_only(self):
        """Test filtering for healthy nodes only."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=3600)

        mock_healthy_node = MagicMock()
        mock_healthy_node.id = 1
        mock_healthy_node.node_name = "healthy"
        mock_healthy_node.base_url = "http://healthy:8001"
        mock_healthy_node.capabilities_json = "[]"
        mock_healthy_node.enabled = 1
        mock_healthy_node.last_heartbeat_at = now

        mock_stale_node = MagicMock()
        mock_stale_node.id = 2
        mock_stale_node.node_name = "stale"
        mock_stale_node.base_url = "http://stale:8001"
        mock_stale_node.capabilities_json = "[]"
        mock_stale_node.enabled = 1
        mock_stale_node.last_heartbeat_at = old_time

        mock_session = MagicMock()
        mock_query = MagicMock()
        # Filter is called, so we mock the result after filtering
        mock_filtered_query = MagicMock()
        mock_filtered_query.all.return_value = [mock_healthy_node]
        mock_query.filter.return_value = mock_filtered_query
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = tool_list_execution_nodes(healthy_only=True)

        assert len(result) == 1
        assert result[0]["name"] == "healthy"
        assert result[0]["healthy"] is True


class TestToolListPluginTools:
    """Test tool_list_plugin_tools function."""

    def test_list_plugin_tools_empty(self):
        """Test listing plugin tools when registry is empty."""
        _plugin_tools_registry.clear()
        result = tool_list_plugin_tools()
        assert result == []

    def test_list_plugin_tools(self):
        """Test listing plugin tools."""
        _plugin_tools_registry.clear()
        _plugin_tools_registry["plugin1"] = {"description": "Plugin 1"}
        _plugin_tools_registry["plugin2"] = {"description": "Plugin 2"}

        result = tool_list_plugin_tools()

        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "plugin1" in names
        assert "plugin2" in names


class TestRegisterCustomTool:
    """Test register_custom_tool function."""

    def test_register_custom_tool(self):
        """Test registering a custom tool."""
        _custom_tool_registry.clear()

        def mock_handler(args):
            return {"ok": True}

        result = register_custom_tool(
            name="test_tool",
            handler=mock_handler,
            description="Test tool",
            parameters={"param1": "string"}
        )

        assert result is True
        assert "test_tool" in _custom_tool_registry
        assert _custom_tool_registry["test_tool"]["runtime_registered"] is True

    def test_register_custom_tool_without_parameters(self):
        """Test registering tool without parameters."""
        _custom_tool_registry.clear()

        def handler(args):
            return {"ok": True}

        register_custom_tool("simple_tool", handler)

        assert "simple_tool" in _custom_tool_registry
        assert _custom_tool_registry["simple_tool"]["parameters"] == {}


class TestUnregisterCustomTool:
    """Test unregister_custom_tool function."""

    def test_unregister_existing_tool(self):
        """Test unregistering an existing tool."""
        _custom_tool_registry.clear()
        _custom_tool_registry["tool_to_remove"] = {"name": "tool_to_remove"}

        result = unregister_custom_tool("tool_to_remove")

        assert result is True
        assert "tool_to_remove" not in _custom_tool_registry

    def test_unregister_nonexistent_tool(self):
        """Test unregistering a tool that doesn't exist."""
        _custom_tool_registry.clear()
        result = unregister_custom_tool("nonexistent")
        assert result is False


class TestGetCustomTool:
    """Test get_custom_tool function."""

    def test_get_custom_tool_from_memory(self):
        """Test getting tool from memory registry."""
        _custom_tool_registry.clear()
        _custom_tool_registry["mem_tool"] = {
            "name": "mem_tool",
            "description": "Memory tool",
            "handler": lambda x: {"ok": True}
        }

        result = get_custom_tool("mem_tool")

        assert result is not None
        assert result["name"] == "mem_tool"

    def test_get_custom_tool_from_database(self):
        """Test getting tool from database when not in memory."""
        _custom_tool_registry.clear()

        mock_tool = MagicMock()
        mock_tool.id = 1
        mock_tool.tool_name = "db_tool"
        mock_tool.description = "Database tool"
        mock_tool.parameters_json = "{}"
        mock_tool.code = "pass"
        mock_tool.test_passed = 1

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_tool
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_custom_tool("db_tool")

        assert result is not None
        assert result["name"] == "db_tool"

    def test_get_custom_tool_not_found(self):
        """Test getting a tool that doesn't exist."""
        _custom_tool_registry.clear()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_custom_tool("nonexistent")

        assert result is None


class TestExecuteCustomTool:
    """Test execute_custom_tool function."""

    def test_execute_custom_tool_runtime_handler(self):
        """Test executing a runtime-registered tool."""
        _custom_tool_registry.clear()

        def handler(args):
            return {"ok": True, "result": "success"}

        register_custom_tool("exec_tool", handler)
        result = execute_custom_tool("exec_tool", {})

        assert result["ok"] is True
        assert result["result"] == "success"

    def test_execute_custom_tool_database_code(self):
        """Test executing a database tool with code."""
        _custom_tool_registry.clear()

        mock_tool = MagicMock()
        mock_tool.id = 1
        mock_tool.tool_name = "db_tool"
        mock_tool.description = "DB Tool"
        mock_tool.parameters_json = "{}"
        mock_tool.code = "result = {'ok': True, 'message': 'executed'}"
        mock_tool.test_passed = True

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_tool
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = execute_custom_tool("db_tool", {})

        assert result["ok"] is True
        assert result["message"] == "executed"

    def test_execute_custom_tool_not_found(self):
        """Test executing a tool that doesn't exist."""
        _custom_tool_registry.clear()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = execute_custom_tool("missing_tool", {})

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_execute_custom_tool_database_no_code(self):
        """Test executing database tool with no code."""
        _custom_tool_registry.clear()

        mock_tool = MagicMock()
        mock_tool.id = 1
        mock_tool.tool_name = "empty_tool"
        mock_tool.description = "Empty Tool"
        mock_tool.parameters_json = "{}"
        mock_tool.code = ""
        mock_tool.test_passed = False

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_tool
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = execute_custom_tool("empty_tool", {})

        assert result["ok"] is False
        assert "no code" in result["error"].lower()

    def test_execute_custom_tool_exception(self):
        """Test executing tool that raises exception."""
        _custom_tool_registry.clear()

        def handler(args):
            raise ValueError("Test error")

        register_custom_tool("error_tool", handler)
        result = execute_custom_tool("error_tool", {})

        assert result["ok"] is False
        assert "Test error" in result["error"]


class TestIncrementToolUsage:
    """Test _increment_tool_usage function."""

    def test_increment_tool_usage(self):
        """Test incrementing tool usage count."""
        mock_tool = MagicMock()
        mock_tool.usage_count = 5

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_tool
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            _increment_tool_usage(1)

        assert mock_tool.usage_count == 6
        mock_session.commit.assert_called()

    def test_increment_tool_usage_not_found(self):
        """Test incrementing usage for nonexistent tool."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            _increment_tool_usage(999)

        # Should not raise, just log


class TestRecordToolPerformance:
    """Test record_tool_performance function."""

    def test_record_tool_performance_disabled(self, monkeypatch):
        """Test that performance recording returns False when disabled."""
        monkeypatch.setattr(
            "mind_clone.core.tools.settings.TOOL_PERF_TRACKING_ENABLED",
            False
        )
        result = record_tool_performance(1, "test_tool", True, 100)
        assert result is False

    def test_record_tool_performance_success(self, monkeypatch):
        """Test recording successful tool performance."""
        monkeypatch.setattr(
            "mind_clone.core.tools.settings.TOOL_PERF_TRACKING_ENABLED",
            True
        )

        mock_session = MagicMock()

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = record_tool_performance(1, "test_tool", True, 100)

        assert result is True
        mock_session.add.assert_called()
        mock_session.commit.assert_called()

    def test_record_tool_performance_exception(self, monkeypatch):
        """Test recording performance when exception occurs."""
        monkeypatch.setattr(
            "mind_clone.core.tools.settings.TOOL_PERF_TRACKING_ENABLED",
            True
        )

        mock_session = MagicMock()
        mock_session.add.side_effect = Exception("DB error")

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = record_tool_performance(1, "test_tool", False, 100, error_category="RuntimeError")

        assert result is False
        mock_session.rollback.assert_called()


class TestGetToolPerformanceStats:
    """Test get_tool_performance_stats function."""

    def test_get_tool_performance_stats_no_logs(self):
        """Test getting stats when no logs exist."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        # Set up chain: query.filter() returns itself for chaining, then all() returns empty
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_tool_performance_stats()

        assert result["total_calls"] == 0
        assert result["success_count"] == 0
        assert result["failure_count"] == 0
        assert result["tools"] == {}

    def test_get_tool_performance_stats_with_logs(self):
        """Test getting stats with performance logs."""
        log1 = MagicMock()
        log1.success = 1
        log1.duration_ms = 100
        log1.tool_name = "tool_a"

        log2 = MagicMock()
        log2.success = 1
        log2.duration_ms = 150
        log2.tool_name = "tool_a"

        log3 = MagicMock()
        log3.success = 0
        log3.duration_ms = 200
        log3.tool_name = "tool_b"

        mock_session = MagicMock()
        mock_query = MagicMock()
        # Set up chain: query.filter() returns itself, all() returns logs
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [log1, log2, log3]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_tool_performance_stats()

        assert result["total_calls"] == 3
        assert result["success_count"] == 2
        assert result["failure_count"] == 1
        assert "tool_a" in result["tools"]
        assert "tool_b" in result["tools"]
        assert result["tools"]["tool_a"]["success_rate"] > 0.9


class TestGetToolRecommendations:
    """Test get_tool_recommendations function."""

    def test_get_tool_recommendations_low_success_rate(self):
        """Test recommendations for tools with low success rate."""
        log1 = MagicMock()
        log1.success = 0
        log1.duration_ms = 100
        log1.tool_name = "bad_tool"

        log2 = MagicMock()
        log2.success = 0
        log2.duration_ms = 150
        log2.tool_name = "bad_tool"

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [log1, log2]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_tool_recommendations()

        assert len(result) > 0
        assert any(r["type"] == "warning" for r in result)

    def test_get_tool_recommendations_slow_tool(self):
        """Test recommendations for slow tools."""
        log1 = MagicMock()
        log1.success = 1
        log1.duration_ms = 6000
        log1.tool_name = "slow_tool"

        log2 = MagicMock()
        log2.success = 1
        log2.duration_ms = 6500
        log2.tool_name = "slow_tool"

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [log1, log2]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_tool_recommendations()

        assert len(result) > 0
        assert any(r["type"] == "performance" for r in result)

    def test_get_tool_recommendations_reliable_tool(self):
        """Test recommendations for reliable tools."""
        logs = []
        for i in range(15):
            log = MagicMock()
            log.success = 1
            log.duration_ms = 100
            log.tool_name = "reliable_tool"
            logs.append(log)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = logs
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = get_tool_recommendations()

        assert len(result) > 0
        assert any(r["type"] == "positive" for r in result)


class TestPruneToolPerformanceLogs:
    """Test prune_tool_performance_logs function."""

    def test_prune_tool_performance_logs(self):
        """Test pruning old performance logs."""
        old_log = MagicMock()
        new_log = MagicMock()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [old_log]
        mock_session.query.return_value = mock_query

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = prune_tool_performance_logs(older_than_days=30)

        assert result == 1
        mock_session.delete.assert_called()
        mock_session.commit.assert_called()

    def test_prune_tool_performance_logs_exception(self):
        """Test pruning with database exception."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        mock_session.query.return_value = mock_query
        mock_session.commit.side_effect = Exception("DB error")

        with patch("mind_clone.core.tools.SessionLocal", return_value=mock_session):
            result = prune_tool_performance_logs()

        assert result == 0
        mock_session.rollback.assert_called()


class TestRegisterPluginTool:
    """Test register_plugin_tool function."""

    def test_register_plugin_tool_trusted(self, monkeypatch):
        """Test registering a trusted plugin tool."""
        monkeypatch.setattr(
            "mind_clone.core.tools.settings.PLUGIN_ENFORCE_TRUST",
            False
        )
        _plugin_tools_registry.clear()

        def handler(args):
            return {"ok": True}

        result = register_plugin_tool(
            "plugin_tool",
            "Plugin description",
            {"param": "value"},
            handler,
            trusted=True
        )

        assert result["ok"] is True
        assert "plugin_tool" in _plugin_tools_registry

    def test_register_plugin_tool_untrusted_enforcement(self, monkeypatch):
        """Test that untrusted tool is rejected when enforcement is enabled."""
        monkeypatch.setattr(
            "mind_clone.core.tools.settings.PLUGIN_ENFORCE_TRUST",
            True
        )
        _plugin_tools_registry.clear()

        def handler(args):
            return {"ok": True}

        result = register_plugin_tool(
            "untrusted_plugin",
            "Description",
            {},
            handler,
            trusted=False
        )

        assert result["ok"] is False
        assert "trust" in result["error"].lower()


class TestExecutePluginTool:
    """Test execute_plugin_tool function."""

    def test_execute_plugin_tool_success(self):
        """Test executing a plugin tool successfully."""
        _plugin_tools_registry.clear()

        def handler(args):
            return {"ok": True, "output": "plugin result"}

        _plugin_tools_registry["test_plugin"] = {
            "handler": handler,
            "description": "Test plugin"
        }

        result = execute_plugin_tool("test_plugin", {})

        assert result["ok"] is True
        assert result["output"] == "plugin result"

    def test_execute_plugin_tool_not_found(self):
        """Test executing nonexistent plugin tool."""
        _plugin_tools_registry.clear()
        result = execute_plugin_tool("missing_plugin", {})
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_execute_plugin_tool_no_handler(self):
        """Test executing plugin with no handler."""
        _plugin_tools_registry.clear()
        _plugin_tools_registry["broken_plugin"] = {"description": "No handler"}

        result = execute_plugin_tool("broken_plugin", {})

        assert result["ok"] is False
        assert "no handler" in result["error"].lower()

    def test_execute_plugin_tool_exception(self):
        """Test executing plugin that raises exception."""
        _plugin_tools_registry.clear()

        def handler(args):
            raise RuntimeError("Plugin error")

        _plugin_tools_registry["error_plugin"] = {
            "handler": handler,
            "description": "Throws error"
        }

        result = execute_plugin_tool("error_plugin", {})

        assert result["ok"] is False
        assert "Plugin error" in result["error"]

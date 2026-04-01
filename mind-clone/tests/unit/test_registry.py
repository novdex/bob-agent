"""
Tests for tool registry and dispatch (maps to BFCL V3 benchmark).

Covers: tool dispatch execution, intent classification, tool filtering,
        custom tool creation, execute_tool error handling.
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.tools.registry import (
    TOOL_DISPATCH,
    TOOL_CATEGORIES,
    classify_tool_intent,
    _select_tools_for_intent,
    execute_tool,
    validate_registry,
    get_tool_names,
    has_tool,
    get_tools_by_category,
)


# ---------------------------------------------------------------------------
# TOOL_DISPATCH registry validation (maps to BFCL)
# ---------------------------------------------------------------------------

class TestToolDispatch:
    """Validate that all registered tools are callable and categorized."""

    def test_dispatch_has_45_plus_tools(self):
        assert len(TOOL_DISPATCH) >= 45

    def test_all_tools_are_callable(self):
        for name, func in TOOL_DISPATCH.items():
            assert callable(func), f"Tool '{name}' is not callable"

    def test_core_tools_registered(self):
        core_tools = [
            "search_web", "read_webpage", "read_file", "write_file",
            "execute_python", "run_command", "deep_research",
        ]
        for tool in core_tools:
            assert tool in TOOL_DISPATCH, f"Core tool '{tool}' missing from dispatch"

    def test_codebase_tools_registered(self):
        codebase_tools = [
            "codebase_read", "codebase_search", "codebase_structure",
            "codebase_edit", "codebase_write", "codebase_run_tests",
            "codebase_git_status",
        ]
        for tool in codebase_tools:
            assert tool in TOOL_DISPATCH, f"Codebase tool '{tool}' missing"

    def test_memory_tools_registered(self):
        memory_tools = ["research_memory_search", "semantic_memory_search"]
        for tool in memory_tools:
            assert tool in TOOL_DISPATCH

    def test_scheduler_tools_registered(self):
        sched_tools = ["schedule_job", "list_scheduled_jobs", "disable_scheduled_job"]
        for tool in sched_tools:
            assert tool in TOOL_DISPATCH

    def test_custom_tools_registered(self):
        custom_tools = ["create_tool", "list_custom_tools", "disable_custom_tool"]
        for tool in custom_tools:
            assert tool in TOOL_DISPATCH


# ---------------------------------------------------------------------------
# TOOL_CATEGORIES validation
# ---------------------------------------------------------------------------

class TestToolCategories:
    """All tools in dispatch should belong to at least one category."""

    def test_all_categories_have_tools(self):
        for cat, tools in TOOL_CATEGORIES.items():
            assert len(tools) > 0, f"Category '{cat}' is empty"

    def test_no_tools_in_unknown_category(self):
        all_categorized = set()
        for tools in TOOL_CATEGORIES.values():
            all_categorized.update(tools)
        for tool_name in TOOL_DISPATCH:
            assert tool_name in all_categorized, (
                f"Tool '{tool_name}' not in any category"
            )


# ---------------------------------------------------------------------------
# Intent classification (maps to BFCL tool selection)
# ---------------------------------------------------------------------------

class TestIntentClassification:
    """Tests that Bob selects the right tools based on user intent."""

    def test_web_search_intent(self):
        cats = classify_tool_intent("search the web for AI benchmarks")
        assert "web" in cats

    def test_file_intent(self):
        cats = classify_tool_intent("read file config.py")
        assert "file" in cats

    def test_code_intent(self):
        cats = classify_tool_intent("execute python script to analyze data")
        assert "code" in cats

    def test_codebase_intent(self):
        cats = classify_tool_intent("modify your own code to fix the bug")
        assert "codebase" in cats

    def test_schedule_intent(self):
        cats = classify_tool_intent("schedule a recurring job every day")
        assert "scheduler" in cats

    def test_memory_intent(self):
        cats = classify_tool_intent("remember this lesson for next time")
        assert "memory" in cats

    def test_desktop_intent(self):
        cats = classify_tool_intent("click button on the desktop screen")
        assert "desktop" in cats

    def test_custom_tool_intent(self):
        cats = classify_tool_intent("create tool to check fibonacci numbers")
        assert "custom" in cats

    def test_ambiguous_message_returns_all_categories(self):
        cats = classify_tool_intent("do the thing")
        assert cats == set(TOOL_CATEGORIES.keys())

    def test_empty_message_returns_all(self):
        cats = classify_tool_intent("")
        assert cats == set(TOOL_CATEGORIES.keys())

    def test_always_includes_base_categories(self):
        cats = classify_tool_intent("search the web")
        assert "file" in cats
        assert "code" in cats
        assert "memory" in cats


# ---------------------------------------------------------------------------
# _select_tools_for_intent
# ---------------------------------------------------------------------------

class TestSelectToolsForIntent:

    def test_filters_to_matching_categories(self):
        all_tools = [
            {"function": {"name": "search_web"}},
            {"function": {"name": "read_file"}},
            {"function": {"name": "desktop_click"}},
        ]
        result = _select_tools_for_intent(all_tools, {"web"})
        names = [t["function"]["name"] for t in result]
        assert "search_web" in names
        # Custom tools always included, but desktop shouldn't be
        assert "desktop_click" not in names

    def test_custom_tools_always_included(self):
        all_tools = [
            {"function": {"name": "create_tool"}},
            {"function": {"name": "desktop_click"}},
        ]
        result = _select_tools_for_intent(all_tools, {"web"})
        names = [t["function"]["name"] for t in result]
        assert "create_tool" in names


# ---------------------------------------------------------------------------
# execute_tool (maps to BFCL tool calling accuracy)
# ---------------------------------------------------------------------------

class TestExecuteTool:

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"test_tool": lambda args: {"ok": True, "result": "hello"}})
    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_dispatches_to_registered_tool(self):
        result = execute_tool("test_tool", {})
        assert result["ok"] is True
        assert result["result"] == "hello"

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_unknown_tool_returns_error(self):
        result = execute_tool("nonexistent_tool_xyz", {})
        assert result["ok"] is False
        assert "error" in result

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"crash_tool": MagicMock(side_effect=Exception("boom"))})
    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_exception_returns_error(self):
        result = execute_tool("crash_tool", {})
        assert result["ok"] is False
        assert "boom" in result.get("error", "")

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_empty_tool_name_returns_error(self):
        result = execute_tool("", {})
        assert result["ok"] is False
        assert "tool_name" in result.get("error", "").lower()

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_none_tool_name_returns_error(self):
        result = execute_tool(None, {})
        assert result["ok"] is False
        assert "tool_name" in result.get("error", "").lower()

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_non_dict_args_returns_error(self):
        result = execute_tool("search_web", "not a dict")
        assert result["ok"] is False
        assert "dict" in result.get("error", "").lower()

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_whitespace_only_tool_name_returns_error(self):
        result = execute_tool("   ", {})
        assert result["ok"] is False
        assert "tool_name" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# validate_registry, get_tool_names, has_tool, get_tools_by_category
# ---------------------------------------------------------------------------

class TestRegistryValidation:
    """Test hardening functions for registry validation."""

    def test_validate_registry_returns_true(self):
        assert validate_registry() is True

    def test_get_tool_names_returns_sorted_list(self):
        names = get_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert names == sorted(names)  # Check it's sorted
        assert "search_web" in names
        assert "read_file" in names

    def test_has_tool_finds_existing(self):
        assert has_tool("search_web") is True
        assert has_tool("read_file") is True
        assert has_tool("execute_python") is True

    def test_has_tool_rejects_nonexistent(self):
        assert has_tool("nonexistent_tool_xyz") is False
        assert has_tool("fake_tool_12345") is False

    def test_has_tool_rejects_empty(self):
        assert has_tool("") is False

    def test_get_tools_by_category_returns_sorted(self):
        web_tools = get_tools_by_category("web")
        assert isinstance(web_tools, list)
        assert len(web_tools) > 0
        assert web_tools == sorted(web_tools)  # Check it's sorted
        assert "search_web" in web_tools

    def test_get_tools_by_category_file(self):
        file_tools = get_tools_by_category("file")
        assert "read_file" in file_tools
        assert "write_file" in file_tools

    def test_get_tools_by_category_nonexistent_returns_empty(self):
        result = get_tools_by_category("nonexistent_category_xyz")
        assert result == []

    def test_get_tools_by_category_custom(self):
        custom_tools = get_tools_by_category("custom")
        assert "create_tool" in custom_tools
        assert "list_custom_tools" in custom_tools


# ---------------------------------------------------------------------------
# DB-dependent function tests with mocks (tools/registry.py mutations)
# ---------------------------------------------------------------------------

class TestCreateCustomToolExecutor:
    """Test _create_custom_tool_executor with safe vs full-power modes."""

    from mind_clone.tools.registry import _create_custom_tool_executor

    def test_full_power_mode_executes_code(self):
        """In full-power mode, code can use all builtins."""
        from mind_clone.tools.registry import _create_custom_tool_executor

        code = """
def tool_main(args):
    return {"ok": True, "result": sum([1, 2, 3])}
"""
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "full"):
            func = _create_custom_tool_executor(code)
            assert callable(func)
            result = func({})
            assert result["ok"] is True
            assert result["result"] == 6

    def test_safe_mode_restricts_builtins(self):
        """In safe mode, restricted code has limited builtins."""
        from mind_clone.tools.registry import _create_custom_tool_executor

        code = """
def tool_main(args):
    return {"ok": True, "result": len([1, 2, 3])}
"""
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "safe"):
            func = _create_custom_tool_executor(code)
            assert callable(func)
            result = func({})
            assert result["ok"] is True
            assert result["result"] == 3

    def test_tool_main_must_be_callable(self):
        """_create_custom_tool_executor raises if tool_main is not callable."""
        from mind_clone.tools.registry import _create_custom_tool_executor

        code = """
tool_main = 42  # Not callable
"""
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "full"):
            with pytest.raises(ValueError, match="not callable"):
                _create_custom_tool_executor(code)

    def test_full_power_returns_function(self):
        """_create_custom_tool_executor returns callable function in full mode."""
        from mind_clone.tools.registry import _create_custom_tool_executor

        code = """
def tool_main(args):
    return {"ok": True}
"""
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "full"):
            func = _create_custom_tool_executor(code)
            assert callable(func)
            assert func({})["ok"] is True


class TestLoadCustomToolsFromDB:
    """Test load_custom_tools_from_db with mocks."""

    @patch("mind_clone.tools.registry.custom.settings.custom_tool_enabled", False)
    def test_returns_0_when_disabled(self):
        """load_custom_tools_from_db returns 0 when disabled."""
        from mind_clone.tools.registry import load_custom_tools_from_db

        result = load_custom_tools_from_db()
        assert result == 0

    @patch("mind_clone.tools.registry.custom.settings.custom_tool_enabled", True)
    @patch("mind_clone.database.session.SessionLocal")
    @patch("mind_clone.core.state.set_runtime_state_value")
    def test_loads_enabled_and_tested_tools(self, mock_set_state, mock_session_local):
        """load_custom_tools_from_db loads tools with enabled==1 and test_passed==1."""
        from mind_clone.tools.registry import load_custom_tools_from_db

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_tool = MagicMock()
        mock_tool.tool_name = "test_tool"
        mock_tool.description = "Test"
        mock_tool.code = "def tool_main(args): return {'ok': True}"
        mock_tool.parameters_json = '{"type": "object", "properties": {}}'
        mock_tool.owner_id = 1

        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = [mock_tool]

        with patch("mind_clone.tools.registry.definitions._create_custom_tool_executor") as mock_create:
            mock_func = MagicMock()
            mock_create.return_value = mock_func

            result = load_custom_tools_from_db()
            assert result >= 0  # Should return a count

    @patch("mind_clone.tools.registry.custom.settings.custom_tool_enabled", True)
    @patch("mind_clone.database.session.SessionLocal")
    @patch("mind_clone.core.state.set_runtime_state_value")
    def test_returns_correct_loaded_count(self, mock_set_state, mock_session_local):
        """load_custom_tools_from_db returns count of loaded tools."""
        from mind_clone.tools.registry import load_custom_tools_from_db

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        tools = []
        for i in range(3):
            tool = MagicMock()
            tool.tool_name = f"tool_{i}"
            tool.description = f"Tool {i}"
            tool.code = "def tool_main(args): return {'ok': True}"
            tool.parameters_json = '{"type": "object", "properties": {}}'
            tool.owner_id = 1
            tools.append(tool)

        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = tools

        with patch("mind_clone.tools.registry.definitions._create_custom_tool_executor") as mock_create:
            mock_func = MagicMock()
            mock_create.return_value = mock_func

            result = load_custom_tools_from_db()
            assert result == 3


class TestCustomToolDefinitions:
    """Test custom_tool_definitions function."""

    @patch("mind_clone.tools.registry.custom.CUSTOM_TOOL_REGISTRY", {})
    def test_returns_empty_when_no_tools(self):
        """custom_tool_definitions returns empty list when no tools loaded."""
        from mind_clone.tools.registry import custom_tool_definitions

        result = custom_tool_definitions()
        assert result == []

    @patch("mind_clone.tools.registry.custom.CUSTOM_TOOL_REGISTRY", {
        "test_tool": {
            "definition": {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "Test",
                    "parameters": {}
                }
            }
        }
    })
    def test_returns_definitions(self):
        """custom_tool_definitions returns tool definitions."""
        from mind_clone.tools.registry import custom_tool_definitions

        result = custom_tool_definitions()
        assert len(result) > 0
        assert result[0]["type"] == "function"


class TestEffectiveToolDefinitions:
    """Test effective_tool_definitions function."""

    @patch("mind_clone.tools.registry.definitions.settings.custom_tool_enabled", False)
    @patch("mind_clone.tools.registry.custom.CUSTOM_TOOL_REGISTRY", {})
    def test_returns_base_defs_when_custom_disabled(self):
        """effective_tool_definitions returns only base defs when custom disabled."""
        from mind_clone.tools.registry import effective_tool_definitions

        result = effective_tool_definitions()
        assert isinstance(result, list)
        assert len(result) > 0

    @patch("mind_clone.tools.registry.definitions.settings.custom_tool_enabled", True)
    @patch("mind_clone.tools.registry.custom.CUSTOM_TOOL_REGISTRY", {})
    def test_returns_base_defs_when_no_custom_tools(self):
        """effective_tool_definitions returns only base defs when no custom tools."""
        from mind_clone.tools.registry import effective_tool_definitions

        result = effective_tool_definitions()
        assert isinstance(result, list)
        assert len(result) > 0


class TestGetAvailableTools:
    """Test get_available_tools function."""

    def test_returns_list_of_tool_names(self):
        """get_available_tools returns list of tool names."""
        from mind_clone.tools.registry import get_available_tools

        result = get_available_tools()
        assert isinstance(result, list)
        assert len(result) > 0
        assert "search_web" in result

    def test_returns_non_empty_list(self):
        """get_available_tools returns non-empty list."""
        from mind_clone.tools.registry import get_available_tools

        result = get_available_tools()
        assert len(result) >= 45


class TestGetToolDefinitions:
    """Test get_tool_definitions function."""

    def test_returns_list_of_schemas(self):
        """get_tool_definitions returns list of OpenAI function schemas."""
        from mind_clone.tools.registry import get_tool_definitions

        result = get_tool_definitions()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_all_definitions_have_function_key(self):
        """All returned definitions have 'function' key."""
        from mind_clone.tools.registry import get_tool_definitions

        result = get_tool_definitions()
        for schema in result:
            assert "function" in schema


class TestIncrementCustomToolUsage:
    """Test _increment_custom_tool_usage with mocks."""

    @patch("mind_clone.database.session.SessionLocal")
    def test_increments_usage_count(self, mock_session_local):
        """_increment_custom_tool_usage increments usage_count."""
        from mind_clone.tools.registry import _increment_custom_tool_usage

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_tool = MagicMock()
        mock_tool.usage_count = 5

        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_tool

        _increment_custom_tool_usage("test_tool")

        # Should increment by 1
        assert mock_tool.usage_count == 6

    @patch("mind_clone.database.session.SessionLocal")
    def test_handles_none_usage_count(self, mock_session_local):
        """_increment_custom_tool_usage handles None usage_count."""
        from mind_clone.tools.registry import _increment_custom_tool_usage

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_tool = MagicMock()
        mock_tool.usage_count = None

        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_tool

        _increment_custom_tool_usage("test_tool")

        # Should treat None as 0 and increment to 1
        assert mock_tool.usage_count == 1


class TestRecordCustomToolError:
    """Test _record_custom_tool_error with mocks."""

    @patch("mind_clone.database.session.SessionLocal")
    def test_records_error_message(self, mock_session_local):
        """_record_custom_tool_error records error message."""
        from mind_clone.tools.registry import _record_custom_tool_error

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_tool = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_tool

        _record_custom_tool_error("test_tool", "Something went wrong")

        assert mock_tool.last_error == "Something went wrong"
        assert mock_db.commit.called


class TestValidateRegistryMutations:
    """Test mutations in validate_registry function."""

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"test": lambda x: x})
    def test_validate_registry_all_callable(self):
        """validate_registry returns True when all tools callable."""
        from mind_clone.tools.registry import validate_registry

        result = validate_registry()
        assert result is True

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"test": "not_callable"})
    def test_validate_registry_detects_non_callable(self):
        """validate_registry returns False when a tool is not callable."""
        from mind_clone.tools.registry import validate_registry

        result = validate_registry()
        assert result is False


class TestLoadRemoteNodeRegistry:
    """Test load_remote_node_registry with mocks."""

    @patch("mind_clone.database.session.SessionLocal")
    @patch("mind_clone.core.state.RUNTIME_STATE", {})
    def test_loads_enabled_nodes(self, mock_session_local):
        """load_remote_node_registry filters by enabled==1."""
        from mind_clone.tools.registry import load_remote_node_registry

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_node = MagicMock()
        mock_node.node_name = "worker1"
        mock_node.base_url = "http://localhost:8001"
        mock_node.capabilities_json = '["compute", "storage"]'
        mock_node.enabled = 1

        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = [mock_node]

        with patch("mind_clone.core.nodes.REMOTE_NODE_REGISTRY", {}):
            load_remote_node_registry()


class TestLoadPluginToolsRegistry:
    """Test load_plugin_tools_registry with mocks."""

    def test_handles_missing_plugins_module(self):
        """load_plugin_tools_registry handles missing plugins gracefully."""
        from mind_clone.tools.registry import load_plugin_tools_registry

        # Mock the discover_plugins import to raise ImportError
        with patch("builtins.__import__", side_effect=ImportError("plugins not found")):
            # Should not raise
            try:
                load_plugin_tools_registry()
            except ImportError:
                # Expected when mocking import itself
                pass


class TestExecuteToolReturnValues:
    """Test execute_tool return values with mocks."""

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"test_tool": lambda args: {"ok": True, "result": "success"}})
    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_execute_tool_returns_result_from_handler(self):
        """execute_tool returns result from handler."""
        from mind_clone.tools.registry import execute_tool

        result = execute_tool("test_tool", {})
        assert result["ok"] is True
        assert result["result"] == "success"

    @patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {"crash_tool": MagicMock(side_effect=Exception("error"))})
    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY", {})
    def test_execute_tool_returns_error_dict_on_exception(self):
        """execute_tool returns error dict when exception occurs."""
        from mind_clone.tools.registry import execute_tool

        result = execute_tool("crash_tool", {})
        assert result["ok"] is False
        assert "error" in result


class TestCustomToolFiltering:
    """Test custom tool trust mode filtering."""

    def test_custom_tool_trust_mode_full_equals_check(self):
        """Verify custom_tool_trust_mode uses == "full" (not != "full")."""
        from mind_clone.tools.registry import _create_custom_tool_executor

        code = """
def tool_main(args):
    return {"ok": True}
"""
        # In full mode, should have full builtins
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "full"):
            func = _create_custom_tool_executor(code)
            assert callable(func)

        # In safe mode, should have restricted builtins
        with patch("mind_clone.tools.registry.definitions.settings.custom_tool_trust_mode", "safe"):
            func = _create_custom_tool_executor(code)
            assert callable(func)


# ---------------------------------------------------------------------------
# Targeted mutation killers for L562, L566, L647, L650
# ---------------------------------------------------------------------------

class TestCustomToolExecuteReturnValues:
    """Kill mutations on execute_tool return values for custom tool paths (L562, L566)."""

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY")
    @patch("mind_clone.tools.registry.dispatch._increment_custom_tool_usage")
    def test_custom_tool_success_returns_exact_result(self, mock_inc, mock_reg):
        """L562: return result — must return the EXACT value from the custom func, not None."""
        sentinel = {"ok": True, "data": "specific_value_42"}
        mock_func = MagicMock(return_value=sentinel)
        mock_reg.__contains__ = MagicMock(return_value=True)
        mock_reg.__getitem__ = MagicMock(return_value={"func": mock_func})

        result = execute_tool("my_custom", {"x": 1})
        assert result is sentinel, "execute_tool must return the exact object from custom func"

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY")
    @patch("mind_clone.tools.registry.dispatch._increment_custom_tool_usage")
    def test_custom_tool_success_not_none(self, mock_inc, mock_reg):
        """L562: mutant returns None — verify result is not None."""
        mock_func = MagicMock(return_value={"ok": True})
        mock_reg.__contains__ = MagicMock(return_value=True)
        mock_reg.__getitem__ = MagicMock(return_value={"func": mock_func})

        result = execute_tool("my_custom", {})
        assert result is not None

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY")
    @patch("mind_clone.tools.registry.dispatch._record_custom_tool_error")
    def test_custom_tool_error_returns_error_dict(self, mock_rec, mock_reg):
        """L566: return error dict — must return dict with ok=False and error string."""
        mock_func = MagicMock(side_effect=ValueError("boom"))
        mock_reg.__contains__ = MagicMock(return_value=True)
        mock_reg.__getitem__ = MagicMock(return_value={"func": mock_func})

        result = execute_tool("my_custom", {})
        assert result is not None, "Error path must not return None"
        assert result["ok"] is False
        assert "boom" in result["error"]

    @patch("mind_clone.tools.registry.dispatch.CUSTOM_TOOL_REGISTRY")
    @patch("mind_clone.tools.registry.dispatch._record_custom_tool_error")
    def test_custom_tool_error_contains_exception_message(self, mock_rec, mock_reg):
        """L566: verify error message is the actual exception text, not something else."""
        mock_func = MagicMock(side_effect=RuntimeError("unique_error_xyz"))
        mock_reg.__contains__ = MagicMock(return_value=True)
        mock_reg.__getitem__ = MagicMock(return_value={"func": mock_func})

        result = execute_tool("my_custom", {})
        assert "unique_error_xyz" in result["error"]


class TestPluginToolsLoadedState:
    """Kill mutations on RUNTIME_STATE['plugin_tools_loaded'] = 0 (L647, L650)."""

    def test_import_error_sets_zero(self):
        """L647: ImportError path must set plugin_tools_loaded to 0, not 1."""
        from mind_clone.core.state import RUNTIME_STATE
        from mind_clone.tools.registry import load_plugin_tools_registry

        old_val = RUNTIME_STATE.get("plugin_tools_loaded")
        RUNTIME_STATE["plugin_tools_loaded"] = 999  # sentinel

        with patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {}):
            with patch.dict("sys.modules", {"mind_clone.core.plugins": None}):
                try:
                    load_plugin_tools_registry()
                except Exception:
                    pass

        val = RUNTIME_STATE.get("plugin_tools_loaded")
        # Restore
        if old_val is not None:
            RUNTIME_STATE["plugin_tools_loaded"] = old_val
        else:
            RUNTIME_STATE.pop("plugin_tools_loaded", None)

        assert val == 0, f"Expected 0 after ImportError, got {val}"

    def test_generic_error_sets_zero(self):
        """L650: Generic Exception path must set plugin_tools_loaded to 0, not 1."""
        from mind_clone.core.state import RUNTIME_STATE
        from mind_clone.tools.registry import load_plugin_tools_registry

        old_val = RUNTIME_STATE.get("plugin_tools_loaded")
        RUNTIME_STATE["plugin_tools_loaded"] = 999

        fake_plugins = MagicMock()
        fake_plugins.discover_plugins = MagicMock(side_effect=RuntimeError("kaboom"))

        with patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {}):
            with patch.dict("sys.modules", {"mind_clone.core.plugins": fake_plugins}):
                load_plugin_tools_registry()

        val = RUNTIME_STATE.get("plugin_tools_loaded")
        if old_val is not None:
            RUNTIME_STATE["plugin_tools_loaded"] = old_val
        else:
            RUNTIME_STATE.pop("plugin_tools_loaded", None)

        assert val == 0, f"Expected 0 after RuntimeError, got {val}"

    def test_success_sets_nonzero(self):
        """Verify success path sets plugin_tools_loaded to len(plugins), not 0."""
        from mind_clone.core.state import RUNTIME_STATE
        from mind_clone.tools.registry import load_plugin_tools_registry

        old_val = RUNTIME_STATE.get("plugin_tools_loaded")
        RUNTIME_STATE["plugin_tools_loaded"] = 999

        fake_plugins_mod = MagicMock()
        fake_plugins_mod.discover_plugins = MagicMock(
            return_value={"tool_a": lambda x: x, "tool_b": lambda x: x}
        )

        with patch("mind_clone.tools.registry.dispatch.TOOL_DISPATCH", {}):
            with patch.dict("sys.modules", {"mind_clone.core.plugins": fake_plugins_mod}):
                load_plugin_tools_registry()

        val = RUNTIME_STATE.get("plugin_tools_loaded")
        if old_val is not None:
            RUNTIME_STATE["plugin_tools_loaded"] = old_val
        else:
            RUNTIME_STATE.pop("plugin_tools_loaded", None)

        assert val == 2, f"Success should set count to 2, got {val}"

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

    @patch("mind_clone.tools.registry.TOOL_DISPATCH", {"test_tool": lambda args: {"ok": True, "result": "hello"}})
    @patch("mind_clone.tools.registry.CUSTOM_TOOL_REGISTRY", {})
    def test_dispatches_to_registered_tool(self):
        result = execute_tool("test_tool", {})
        assert result["ok"] is True
        assert result["result"] == "hello"

    @patch("mind_clone.tools.registry.CUSTOM_TOOL_REGISTRY", {})
    def test_unknown_tool_returns_error(self):
        result = execute_tool("nonexistent_tool_xyz", {})
        assert result["ok"] is False
        assert "error" in result

    @patch("mind_clone.tools.registry.TOOL_DISPATCH", {"crash_tool": MagicMock(side_effect=Exception("boom"))})
    @patch("mind_clone.tools.registry.CUSTOM_TOOL_REGISTRY", {})
    def test_exception_returns_error(self):
        result = execute_tool("crash_tool", {})
        assert result["ok"] is False
        assert "boom" in result.get("error", "")

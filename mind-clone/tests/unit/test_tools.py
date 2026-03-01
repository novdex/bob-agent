"""
Tests for tools module.
"""
import pytest
from mind_clone.tools.schemas import TOOL_DEFINITIONS
from mind_clone.tools.registry import TOOL_DISPATCH
from mind_clone.tools.basic import (
    tool_read_file,
    tool_write_file,
    tool_list_directory,
    tool_run_command,
    tool_execute_python,
    tool_search_web,
)
from mind_clone.tools.custom import sanitize_tool_name


class TestToolSchemas:
    """Test tool schemas."""

    def test_tool_definitions_exist(self):
        """Test that tool definitions exist."""
        assert len(TOOL_DEFINITIONS) > 0

        # Check for essential tools
        tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
        assert "search_web" in tool_names
        assert "read_file" in tool_names
        assert "run_command" in tool_names

    def test_tool_definitions_structure(self):
        """Test tool definition structure."""
        for tool in TOOL_DEFINITIONS:
            assert "type" in tool
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]


class TestToolRegistry:
    """Test tool registry."""

    def test_tool_dispatch_exists(self):
        """Test that tool dispatch exists."""
        assert len(TOOL_DISPATCH) > 0

        # Check for essential tools
        assert "search_web" in TOOL_DISPATCH
        assert "read_file" in TOOL_DISPATCH
        assert "run_command" in TOOL_DISPATCH

    def test_tool_dispatch_callable(self):
        """Test that tool dispatch values are callable."""
        for name, func in TOOL_DISPATCH.items():
            assert callable(func), f"{name} is not callable"


class TestBasicTools:
    """Test basic tool implementations."""

    def test_read_file_nonexistent(self):
        """Test reading a nonexistent file."""
        from mind_clone.tools.basic import read_file

        result = read_file("/nonexistent/path/to/file.txt")
        assert "error" in result.lower() or "not found" in result.lower()

    def test_search_web_mock(self, monkeypatch):
        """Test web search with mocked response."""
        from mind_clone.tools.basic import search_web

        # Mock the search function
        def mock_search(query):
            return "Mock search results for: " + query

        monkeypatch.setattr("mind_clone.tools.basic.search_web", mock_search)
        result = search_web("test query")
        assert "Mock search results" in result


# ---------------------------------------------------------------------------
# Input validation tests for basic tools
# ---------------------------------------------------------------------------

class TestToolInputValidation:
    """Test input validation in basic tools."""

    def test_tool_read_file_rejects_empty_path(self):
        result = tool_read_file({"file_path": ""})
        assert result["ok"] is False
        assert "required" in result["error"].lower()

    def test_tool_read_file_rejects_non_dict_args(self):
        result = tool_read_file("not a dict")
        assert result["ok"] is False
        assert "dict" in result["error"].lower()

    def test_tool_read_file_rejects_long_path(self):
        result = tool_read_file({"file_path": "a" * 5000})
        assert result["ok"] is False
        assert "too long" in result["error"].lower()

    def test_tool_write_file_rejects_empty_path(self):
        result = tool_write_file({"file_path": "", "content": "test"})
        assert result["ok"] is False

    def test_tool_write_file_rejects_non_dict_args(self):
        result = tool_write_file("not a dict")
        assert result["ok"] is False

    def test_tool_write_file_rejects_long_content(self):
        result = tool_write_file({"file_path": "/tmp/test.txt", "content": "x" * (10485760 + 1)})
        assert result["ok"] is False
        assert "too large" in result["error"].lower()

    def test_tool_list_directory_rejects_non_dict_args(self):
        result = tool_list_directory("not a dict")
        assert result["ok"] is False

    def test_tool_list_directory_rejects_long_path(self):
        result = tool_list_directory({"dir_path": "a" * 5000})
        assert result["ok"] is False

    def test_tool_run_command_rejects_empty_command(self):
        result = tool_run_command({"command": ""})
        assert result["ok"] is False
        assert "required" in result["error"].lower()

    def test_tool_run_command_rejects_non_dict_args(self):
        result = tool_run_command("not a dict")
        assert result["ok"] is False

    def test_tool_run_command_rejects_long_command(self):
        result = tool_run_command({"command": "a" * 5000})
        assert result["ok"] is False
        assert "too long" in result["error"].lower()

    def test_tool_run_command_rejects_invalid_timeout(self):
        result = tool_run_command({"command": "ls", "timeout": "not_a_number"})
        assert result["ok"] is False
        assert "timeout" in result["error"].lower()

    def test_tool_run_command_rejects_timeout_too_large(self):
        result = tool_run_command({"command": "ls", "timeout": 5000})
        assert result["ok"] is False
        assert "between 1 and 3600" in result["error"].lower()

    def test_tool_run_command_rejects_timeout_too_small(self):
        result = tool_run_command({"command": "ls", "timeout": 0})
        assert result["ok"] is False
        assert "between 1 and 3600" in result["error"].lower()

    def test_tool_execute_python_rejects_empty_code(self):
        result = tool_execute_python({"code": ""})
        assert result["ok"] is False
        assert "required" in result["error"].lower()

    def test_tool_execute_python_rejects_non_dict_args(self):
        result = tool_execute_python("not a dict")
        assert result["ok"] is False

    def test_tool_execute_python_rejects_large_code(self):
        result = tool_execute_python({"code": "x" * (102400 + 1)})
        assert result["ok"] is False
        assert "too large" in result["error"].lower()

    def test_tool_execute_python_rejects_invalid_timeout(self):
        result = tool_execute_python({"code": "print('hi')", "timeout": "bad"})
        assert result["ok"] is False
        assert "timeout" in result["error"].lower()

    def test_tool_execute_python_rejects_timeout_too_large(self):
        result = tool_execute_python({"code": "print('hi')", "timeout": 400})
        assert result["ok"] is False
        assert "between 1 and 300" in result["error"].lower()

    def test_tool_search_web_rejects_empty_query(self):
        result = tool_search_web({"query": ""})
        assert result["ok"] is False
        assert "required" in result["error"].lower()

    def test_tool_search_web_rejects_non_dict_args(self):
        result = tool_search_web("not a dict")
        assert result["ok"] is False

    def test_tool_search_web_rejects_long_query(self):
        result = tool_search_web({"query": "a" * 600})
        assert result["ok"] is False
        assert "too long" in result["error"].lower()

    def test_tool_search_web_rejects_invalid_num_results(self):
        result = tool_search_web({"query": "test", "num_results": "bad"})
        assert result["ok"] is False
        assert "num_results" in result["error"].lower()

    def test_tool_search_web_rejects_num_results_too_large(self):
        result = tool_search_web({"query": "test", "num_results": 200})
        assert result["ok"] is False
        assert "between 1 and 100" in result["error"].lower()

    def test_tool_search_web_rejects_num_results_zero(self):
        result = tool_search_web({"query": "test", "num_results": 0})
        assert result["ok"] is False
        assert "between 1 and 100" in result["error"].lower()


# ---------------------------------------------------------------------------
# Custom tool name validation
# ---------------------------------------------------------------------------

class TestSanitizeToolName:
    """Test sanitize_tool_name function."""

    def test_valid_tool_name(self):
        valid, name = sanitize_tool_name("my_tool")
        assert valid is True
        assert name == "my_tool"

    def test_valid_tool_name_with_hyphen(self):
        valid, name = sanitize_tool_name("my-tool-v2")
        assert valid is True
        assert name == "my-tool-v2"

    def test_valid_tool_name_with_numbers(self):
        valid, name = sanitize_tool_name("tool123")
        assert valid is True
        assert name == "tool123"

    def test_rejects_path_separator_forward_slash(self):
        valid, _ = sanitize_tool_name("my/tool")
        assert valid is False

    def test_rejects_path_separator_backslash(self):
        valid, _ = sanitize_tool_name("my\\tool")
        assert valid is False

    def test_rejects_null_byte(self):
        valid, _ = sanitize_tool_name("my\x00tool")
        assert valid is False

    def test_rejects_special_characters(self):
        valid, _ = sanitize_tool_name("my@tool")
        assert valid is False

        valid, _ = sanitize_tool_name("my.tool")
        assert valid is False

        valid, _ = sanitize_tool_name("my tool")
        assert valid is False

    def test_rejects_empty_string(self):
        valid, _ = sanitize_tool_name("")
        assert valid is False

    def test_rejects_whitespace_only(self):
        valid, _ = sanitize_tool_name("   ")
        assert valid is False

    def test_rejects_non_string(self):
        valid, _ = sanitize_tool_name(123)
        assert valid is False

    def test_rejects_none(self):
        valid, _ = sanitize_tool_name(None)
        assert valid is False

    def test_rejects_long_name(self):
        valid, _ = sanitize_tool_name("a" * 200)
        assert valid is False
        assert "too long" in _.lower()

    def test_trims_whitespace(self):
        valid, name = sanitize_tool_name("  my_tool  ")
        assert valid is True
        assert name == "my_tool"

    # Boundary tests for length
    def test_accepts_max_length_name(self):
        """Test that names at max length (128) are accepted."""
        valid, name = sanitize_tool_name("a" * 128)
        assert valid is True
        assert name == "a" * 128

    def test_rejects_length_129(self):
        """Test that names exceeding max length (129) are rejected."""
        valid, _ = sanitize_tool_name("a" * 129)
        assert valid is False

    # Boundary tests for comparisons in return values
    def test_exact_name_return_value(self):
        """Ensure return value is exactly (True, name) not None."""
        result = sanitize_tool_name("valid_tool")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] is True
        assert result[1] == "valid_tool"

    def test_invalid_name_returns_tuple(self):
        """Ensure invalid names return (False, error_msg) not None."""
        result = sanitize_tool_name("@invalid")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] is False
        assert isinstance(result[1], str)
        assert len(result[1]) > 0


# ---------------------------------------------------------------------------
# Custom tool creation tests
# ---------------------------------------------------------------------------

class TestToolCreateTool:
    """Test tool_create_tool function."""

    def test_create_tool_disabled_returns_error(self, monkeypatch):
        """Test that creating tool when disabled returns error."""
        from mind_clone.tools.custom import tool_create_tool

        # Mock settings to disable custom tools
        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            False
        )

        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
            "code": "def tool_main(args): return {'ok': True}",
        })
        assert result["ok"] is False
        assert result is not None
        assert "error" in result
        assert isinstance(result, dict)

    def test_create_tool_missing_name_returns_error(self, monkeypatch):
        """Test that missing name returns error."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        result = tool_create_tool({
            "description": "Test tool",
            "code": "def tool_main(args): return {'ok': True}",
        })
        assert result["ok"] is False
        assert result is not None

    def test_create_tool_missing_description_returns_error(self, monkeypatch):
        """Test that missing description returns error."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        result = tool_create_tool({
            "name": "test_tool",
            "code": "def tool_main(args): return {'ok': True}",
        })
        assert result["ok"] is False
        assert result is not None

    def test_create_tool_missing_code_returns_error(self, monkeypatch):
        """Test that missing code returns error."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
        })
        assert result["ok"] is False
        assert result is not None

    def test_create_tool_invalid_name_returns_error(self, monkeypatch):
        """Test that invalid tool name returns error."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        result = tool_create_tool({
            "name": "invalid/tool",
            "description": "Test tool",
            "code": "def tool_main(args): return {'ok': True}",
        })
        assert result["ok"] is False
        assert result is not None
        assert "Invalid tool name" in result.get("error", "")

    def test_create_tool_description_too_long_returns_error(self, monkeypatch):
        """Test that overly long description is rejected."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        result = tool_create_tool({
            "name": "test_tool",
            "description": "x" * 1001,
            "code": "def tool_main(args): return {'ok': True}",
        })
        assert result["ok"] is False
        assert result is not None
        assert "too long" in result.get("error", "").lower()

    def test_create_tool_description_at_max_length_accepted(self, monkeypatch):
        """Test that description at max length (1000) is accepted in validation."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )
        monkeypatch.setattr(
            "mind_clone.core.custom_tools.create_custom_tool",
            lambda **kwargs: {"ok": False, "error": "DB error"}
        )

        result = tool_create_tool({
            "name": "test_tool",
            "description": "x" * 1000,
            "code": "def tool_main(args): return {'ok': True}",
        })
        # Should reach DB layer (not fail on description length)
        assert "description" not in result.get("error", "").lower()

    def test_create_tool_code_too_large_returns_error(self, monkeypatch):
        """Test that code exceeding 1MB is rejected."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        large_code = "x" * (1048576 + 1)
        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
            "code": large_code,
        })
        assert result["ok"] is False
        assert result is not None
        assert "too large" in result.get("error", "").lower()

    def test_create_tool_code_at_max_size_accepted(self, monkeypatch):
        """Test that code at max size (1MB) passes size validation."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )
        monkeypatch.setattr(
            "mind_clone.core.custom_tools.create_custom_tool",
            lambda **kwargs: {"ok": False, "error": "DB error"}
        )

        large_code = "x" * 1048576
        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
            "code": large_code,
        })
        # Should reach DB layer (not fail on code size)
        assert "code is too large" not in result.get("error", "")

    def test_create_tool_parameters_too_large_returns_error(self, monkeypatch):
        """Test that parameters JSON exceeding 100KB is rejected."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )

        large_params = '{"x": "' + "x" * (102400 + 1) + '"}'
        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
            "code": "def tool_main(args): return {'ok': True}",
            "parameters": large_params,
        })
        assert result["ok"] is False
        assert result is not None
        assert "parameters json" in result.get("error", "").lower()

    def test_create_tool_parameters_at_max_size_accepted(self, monkeypatch):
        """Test that parameters at max size (100KB) passes validation."""
        from mind_clone.tools.custom import tool_create_tool

        monkeypatch.setattr(
            "mind_clone.tools.custom.settings.custom_tool_enabled",
            True
        )
        monkeypatch.setattr(
            "mind_clone.core.custom_tools.create_custom_tool",
            lambda **kwargs: {"ok": False, "error": "DB error"}
        )

        large_params = '{"x": "' + "x" * 102300 + '"}'
        result = tool_create_tool({
            "name": "test_tool",
            "description": "Test tool",
            "code": "def tool_main(args): return {'ok': True}",
            "parameters": large_params,
        })
        # Should reach DB layer (not fail on parameters size)
        assert "parameters JSON is too large" not in result.get("error", "")


# ---------------------------------------------------------------------------
# Custom tool listing tests
# ---------------------------------------------------------------------------

class TestToolListCustomTools:
    """Test tool_list_custom_tools function."""

    def test_list_custom_tools_returns_dict(self, monkeypatch):
        """Test that list_custom_tools returns a dict."""
        from mind_clone.tools.custom import tool_list_custom_tools

        monkeypatch.setattr(
            "mind_clone.core.custom_tools.list_custom_tools",
            lambda **kwargs: []
        )

        result = tool_list_custom_tools({})
        assert isinstance(result, dict)
        assert result is not None
        assert result["ok"] is True

    def test_list_custom_tools_count_field(self, monkeypatch):
        """Test that count field is present and accurate."""
        from mind_clone.tools.custom import tool_list_custom_tools

        mock_tools = [
            {"name": "tool1", "description": "desc1", "enabled": True, "test_passed": True, "usage_count": 5},
            {"name": "tool2", "description": "desc2", "enabled": False, "test_passed": False, "usage_count": 0},
        ]
        monkeypatch.setattr(
            "mind_clone.core.custom_tools.list_custom_tools",
            lambda **kwargs: mock_tools
        )

        result = tool_list_custom_tools({})
        assert result["count"] == 2
        assert len(result["tools"]) == 2

    def test_list_custom_tools_with_owner_id(self, monkeypatch):
        """Test that owner_id is passed through correctly."""
        from mind_clone.tools.custom import tool_list_custom_tools

        captured_args = {}

        def mock_list(**kwargs):
            captured_args.update(kwargs)
            return []

        monkeypatch.setattr(
            "mind_clone.core.custom_tools.list_custom_tools",
            mock_list
        )

        tool_list_custom_tools({"owner_id": 42})
        assert captured_args.get("owner_id") == 42


# ---------------------------------------------------------------------------
# Custom tool disabling tests
# ---------------------------------------------------------------------------

class TestToolDisableCustomTool:
    """Test tool_disable_custom_tool function."""

    def test_disable_tool_requires_name(self):
        """Test that tool_name is required."""
        from mind_clone.tools.custom import tool_disable_custom_tool

        result = tool_disable_custom_tool({})
        assert result["ok"] is False
        assert result is not None
        assert "required" in result.get("error", "").lower()

    def test_disable_tool_returns_dict(self, monkeypatch):
        """Test that disable returns a dict."""
        from mind_clone.tools.custom import tool_disable_custom_tool

        monkeypatch.setattr(
            "mind_clone.core.custom_tools.get_custom_tool",
            lambda **kwargs: None
        )

        result = tool_disable_custom_tool({"tool_name": "nonexistent"})
        assert isinstance(result, dict)
        assert result is not None

    def test_disable_tool_not_found_returns_error(self, monkeypatch):
        """Test that disabling nonexistent tool returns error."""
        from mind_clone.tools.custom import tool_disable_custom_tool

        monkeypatch.setattr(
            "mind_clone.core.custom_tools.get_custom_tool",
            lambda **kwargs: None
        )

        result = tool_disable_custom_tool({"tool_name": "nonexistent"})
        assert result["ok"] is False
        assert result is not None
        assert "not found" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# LLM Structured Task tests
# ---------------------------------------------------------------------------

class TestToolLLMStructuredTask:
    """Test tool_llm_structured_task function."""

    def test_llm_task_requires_instruction(self):
        """Test that instruction is required."""
        from mind_clone.tools.custom import tool_llm_structured_task

        result = tool_llm_structured_task({})
        assert result["ok"] is False
        assert result is not None
        assert "required" in result.get("error", "").lower()

    def test_llm_task_returns_dict(self):
        """Test that tool returns a dict."""
        from mind_clone.tools.custom import tool_llm_structured_task

        result = tool_llm_structured_task({"instruction": "test instruction"})
        assert isinstance(result, dict)
        assert result is not None

    def test_llm_task_not_implemented(self):
        """Test that LLM task is not yet implemented."""
        from mind_clone.tools.custom import tool_llm_structured_task

        result = tool_llm_structured_task({"instruction": "do something"})
        assert result["ok"] is False
        assert result is not None


# ---------------------------------------------------------------------------
# Plugin tools tests
# ---------------------------------------------------------------------------

class TestToolListPluginTools:
    """Test tool_list_plugin_tools function."""

    def test_list_plugin_tools_returns_dict(self):
        """Test that list_plugin_tools returns a dict."""
        from mind_clone.tools.custom import tool_list_plugin_tools

        result = tool_list_plugin_tools({})
        assert isinstance(result, dict)
        assert result is not None

    def test_list_plugin_tools_has_ok_field(self):
        """Test that result has ok field set to True."""
        from mind_clone.tools.custom import tool_list_plugin_tools

        result = tool_list_plugin_tools({})
        assert result.get("ok") is True

    def test_list_plugin_tools_has_plugins_field(self):
        """Test that result has plugins field (list)."""
        from mind_clone.tools.custom import tool_list_plugin_tools

        result = tool_list_plugin_tools({})
        assert isinstance(result.get("plugins"), list)
        assert result["plugins"] is not None

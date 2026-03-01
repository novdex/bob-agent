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
    tool_read_webpage,
    tool_deep_research,
    tool_send_email,
    tool_save_research_note,
    _extract_semantic_snapshot_bs,
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


# ---------------------------------------------------------------------------
# Happy path tests for basic tools (coverage increases)
# ---------------------------------------------------------------------------

class TestBasicToolsHappyPath:
    """Test happy path scenarios for basic tool implementations."""

    def test_tool_read_file_happy_path(self, tmp_path):
        """Test reading file successfully."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        result = tool_read_file({"file_path": str(test_file)})

        assert result["ok"] is True
        assert result["content"] == test_content
        assert "path" in result

    def test_tool_write_file_happy_path(self, tmp_path):
        """Test writing file successfully."""
        test_file = tmp_path / "output.txt"
        content = "Test content"

        result = tool_write_file({
            "file_path": str(test_file),
            "content": content
        })

        assert result["ok"] is True
        assert test_file.exists()
        assert test_file.read_text() == content
        assert result["bytes_written"] == len(content.encode("utf-8"))

    def test_tool_write_file_append_mode(self, tmp_path):
        """Test appending to file."""
        test_file = tmp_path / "append.txt"
        test_file.write_text("First line\n")

        result = tool_write_file({
            "file_path": str(test_file),
            "content": "Second line\n",
            "append": True
        })

        assert result["ok"] is True
        content = test_file.read_text()
        assert "First line" in content
        assert "Second line" in content

    def test_tool_list_directory_happy_path(self, tmp_path):
        """Test listing directory contents."""
        (tmp_path / "file1.txt").write_text("test")
        (tmp_path / "file2.txt").write_text("test")
        (tmp_path / "subdir").mkdir()

        result = tool_list_directory({"dir_path": str(tmp_path)})

        assert result["ok"] is True
        assert "items" in result
        assert len(result["items"]) >= 3
        item_names = [item["name"] for item in result["items"]]
        assert "file1.txt" in item_names
        assert "file2.txt" in item_names
        assert "subdir" in item_names

    def test_tool_list_directory_with_types(self, tmp_path):
        """Test listing directory with type information."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()

        result = tool_list_directory({"dir_path": str(tmp_path)})

        assert result["ok"] is True
        file_item = next((i for i in result["items"] if i["name"] == "test.txt"), None)
        dir_item = next((i for i in result["items"] if i["name"] == "testdir"), None)

        assert file_item is not None
        assert file_item["type"] == "file"
        assert file_item["size"] > 0

        assert dir_item is not None
        assert dir_item["type"] == "directory"
        assert dir_item["size"] is None

    def test_tool_search_web_happy_path(self):
        """Test web search with mocked DDGS."""
        from unittest.mock import MagicMock, patch

        mock_results = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
        ]

        with patch("mind_clone.tools.basic.DDGS") as mock_ddgs_class:
            mock_ddgs_instance = MagicMock()
            mock_ddgs_instance.text.return_value = iter(mock_results)
            mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance

            result = tool_search_web({
                "query": "test query",
                "num_results": 5
            })

        assert result["ok"] is True
        assert result["query"] == "test query"
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Result 1"
        assert result["results"][0]["url"] == "https://example.com/1"

    def test_tool_run_command_happy_path(self):
        """Test running command successfully."""
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Command output"
        mock_result.stderr = ""

        with patch("mind_clone.tools.basic.subprocess.run", return_value=mock_result):
            result = tool_run_command({
                "command": "echo hello",
                "timeout": 30
            })

        assert result["ok"] is True
        assert result["returncode"] == 0
        assert "stdout" in result

    def test_tool_run_command_timeout_exception(self):
        """Test command timeout exception handling."""
        from unittest.mock import patch
        import subprocess

        with patch("mind_clone.tools.basic.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("echo", 10)

            result = tool_run_command({
                "command": "long command",
                "timeout": 10
            })

        assert result["ok"] is False
        assert "timed out" in result["error"].lower()

    def test_tool_run_command_generic_exception(self):
        """Test command execution generic exception handling."""
        from unittest.mock import patch

        with patch("mind_clone.tools.basic.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Command not found")

            result = tool_run_command({
                "command": "nonexistent_cmd",
                "timeout": 30
            })

        assert result["ok"] is False
        assert "error" in result

    def test_tool_execute_python_happy_path(self):
        """Test executing Python code successfully."""
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5"
        mock_result.stderr = ""

        with patch("mind_clone.tools.basic.subprocess.run", return_value=mock_result):
            result = tool_execute_python({
                "code": "print(2 + 3)",
                "timeout": 15
            })

        assert result["ok"] is True
        assert "stdout" in result

    def test_tool_execute_python_timeout_exception(self):
        """Test Python execution timeout handling."""
        from unittest.mock import patch
        import subprocess

        with patch("mind_clone.tools.basic.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("python", 15)

            result = tool_execute_python({
                "code": "while True: pass",
                "timeout": 15
            })

        assert result["ok"] is False
        assert "timed out" in result["error"].lower()

    def test_tool_execute_python_generic_exception(self):
        """Test Python execution generic exception handling."""
        from unittest.mock import patch

        with patch("mind_clone.tools.basic.subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("Execution error")

            result = tool_execute_python({
                "code": "print('test')",
                "timeout": 15
            })

        assert result["ok"] is False
        assert "error" in result

    def test_tool_read_webpage_happy_path(self):
        """Test reading webpage successfully."""
        from unittest.mock import patch, MagicMock

        mock_response = MagicMock()
        mock_response.content = b"<html><body><h1>Test</h1><p>Content here</p></body></html>"

        with patch("mind_clone.tools.basic.REQUESTS_SESSION.get", return_value=mock_response):
            with patch("mind_clone.core.security.circuit_allow_call", return_value=(True, "")):
                with patch("mind_clone.core.security.apply_url_safety_guard", return_value=(True, "")):
                    with patch("mind_clone.core.security.circuit_record_success"):
                        result = tool_read_webpage({
                            "url": "https://example.com"
                        })

        assert result["ok"] is True
        assert result["url"] == "https://example.com"
        assert "text" in result
        assert "snapshot" in result
        assert "title" in result

    def test_extract_semantic_snapshot_bs(self):
        """Test semantic snapshot extraction from BeautifulSoup."""
        from mind_clone.tools.basic import _extract_semantic_snapshot_bs
        from bs4 import BeautifulSoup

        html = """
        <html lang="en">
        <head><meta name="description" content="Test page description"></head>
        <body>
            <h1>Main Title</h1>
            <h2>Subtitle</h2>
            <a href="https://example.com">Example Link</a>
            <form action="/submit" method="POST">
                <input type="text" name="username">
                <input type="submit" value="Submit">
            </form>
            <button>Click Me</button>
        </body>
        </html>
        """

        soup = BeautifulSoup(html, "html.parser")
        snapshot = _extract_semantic_snapshot_bs(soup)

        assert "headings" in snapshot
        assert len(snapshot["headings"]) >= 2
        assert snapshot["meta_description"] == "Test page description"
        assert snapshot["lang"] == "en"
        assert len(snapshot["links"]) > 0
        assert len(snapshot["forms"]) > 0
        assert len(snapshot["buttons"]) > 0

    def test_tool_deep_research_happy_path(self):
        """Test deep research with multiple queries."""
        from unittest.mock import patch, MagicMock

        mock_results_1 = [
            {"title": "Result 1", "href": "https://example1.com", "body": "Snippet 1"},
        ]
        mock_results_2 = [
            {"title": "Result 2", "href": "https://example2.com", "body": "Snippet 2"},
        ]
        mock_results_3 = [
            {"title": "Result 3", "href": "https://example3.com", "body": "Snippet 3"},
        ]

        with patch("mind_clone.tools.basic.DDGS") as mock_ddgs_class:
            mock_ddgs_instance = MagicMock()
            mock_ddgs_instance.text.side_effect = [
                iter(mock_results_1),
                iter(mock_results_2),
                iter(mock_results_3),
            ]
            mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance

            result = tool_deep_research({
                "topic": "machine learning",
                "num_results": 8
            })

        assert result["ok"] is True
        assert result["topic"] == "machine learning"
        assert "sources" in result
        assert len(result["sources"]) > 0

    def test_tool_send_email_happy_path(self):
        """Test sending email successfully."""
        from unittest.mock import patch, MagicMock
        import smtplib

        with patch("mind_clone.tools.basic.settings.smtp_username", "user@example.com"):
            with patch("mind_clone.tools.basic.settings.smtp_password", "password"):
                with patch("mind_clone.tools.basic.settings.smtp_from_name", "Bot"):
                    with patch("mind_clone.tools.basic.settings.smtp_host", "smtp.example.com"):
                        with patch("mind_clone.tools.basic.settings.smtp_port", 587):
                            with patch("smtplib.SMTP") as mock_smtp:
                                mock_server = MagicMock()
                                mock_smtp.return_value.__enter__.return_value = mock_server

                                result = tool_send_email({
                                    "to": "recipient@example.com",
                                    "subject": "Test Email",
                                    "body": "This is a test."
                                })

        assert result["ok"] is True
        assert result["to"] == "recipient@example.com"
        assert result["subject"] == "Test Email"

    def test_tool_save_research_note_happy_path(self):
        """Test saving research note successfully."""
        from unittest.mock import patch, MagicMock

        mock_note = MagicMock()
        mock_note.id = 1
        mock_note.owner_id = 1
        mock_note.topic = "Test Topic"

        def mock_refresh(note):
            note.id = 1

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.refresh = mock_refresh
        mock_session.close = MagicMock()

        with patch("mind_clone.tools.basic.SessionLocal", return_value=mock_session):
            result = tool_save_research_note({
                "topic": "Test Topic",
                "summary": "This is a test summary",
                "owner_id": 1,
                "sources": ["https://example.com"],
                "tags": ["test", "research"]
            })

        assert result["ok"] is True
        assert "note_id" in result
        assert result["topic"] == "Test Topic"

    def test_read_file_compatibility_wrapper(self, tmp_path):
        """Test read_file compatibility wrapper."""
        from mind_clone.tools.basic import read_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        result = read_file(str(test_file))

        assert isinstance(result, str)
        assert "Test content" in result

    def test_read_file_compatibility_error(self):
        """Test read_file compatibility wrapper with error."""
        from mind_clone.tools.basic import read_file

        result = read_file("/nonexistent/file.txt")

        assert isinstance(result, str)
        assert "error" in result.lower() or "not found" in result.lower()

    def test_search_web_compatibility_wrapper(self):
        """Test search_web compatibility wrapper."""
        from mind_clone.tools.basic import search_web
        from unittest.mock import patch, MagicMock

        mock_results = [
            {"title": "Result", "href": "https://example.com", "body": "Snippet"},
        ]

        with patch("mind_clone.tools.basic.DDGS") as mock_ddgs_class:
            mock_ddgs_instance = MagicMock()
            mock_ddgs_instance.text.return_value = iter(mock_results)
            mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance

            result = search_web("test")

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Result" in result or "example.com" in result

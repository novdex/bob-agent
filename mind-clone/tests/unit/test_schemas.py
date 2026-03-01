"""
Tests for tools/schemas.py — OpenAI function calling schemas.
"""
import pytest
from mind_clone.tools.schemas import (
    ALL_TOOL_SCHEMAS,
    TOOL_DEFINITIONS,
    get_tool_schemas,
    get_tool_schema_by_name,
    validate_schemas,
    get_required_params,
    get_all_schema_names,
    SEARCH_WEB_SCHEMA,
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    EXECUTE_PYTHON_SCHEMA,
    RUN_COMMAND_SCHEMA,
    SEND_EMAIL_SCHEMA,
    BROWSER_OPEN_SCHEMA,
    CREATE_TASK_SCHEMA,
)


class TestAllToolSchemas:
    """Test that ALL_TOOL_SCHEMAS is well-formed."""

    def test_has_schemas(self):
        assert len(ALL_TOOL_SCHEMAS) >= 15

    def test_each_schema_has_function_key(self):
        for schema in ALL_TOOL_SCHEMAS:
            assert "type" in schema
            assert schema["type"] == "function"
            assert "function" in schema

    def test_each_function_has_name(self):
        for schema in ALL_TOOL_SCHEMAS:
            fn = schema["function"]
            assert "name" in fn
            assert len(fn["name"]) > 0

    def test_each_function_has_description(self):
        for schema in ALL_TOOL_SCHEMAS:
            fn = schema["function"]
            assert "description" in fn
            assert len(fn["description"]) > 0

    def test_each_function_has_parameters(self):
        for schema in ALL_TOOL_SCHEMAS:
            fn = schema["function"]
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_no_duplicate_names(self):
        names = [s["function"]["name"] for s in ALL_TOOL_SCHEMAS]
        assert len(names) == len(set(names)), f"Duplicate schema names: {[n for n in names if names.count(n) > 1]}"


class TestGetToolSchemas:
    """Test get_tool_schemas function."""

    def test_returns_list(self):
        result = get_tool_schemas()
        assert isinstance(result, list)

    def test_returns_copy(self):
        a = get_tool_schemas()
        b = get_tool_schemas()
        assert a is not b

    def test_same_length_as_all(self):
        assert len(get_tool_schemas()) == len(ALL_TOOL_SCHEMAS)


class TestGetToolSchemaByName:
    """Test get_tool_schema_by_name function."""

    def test_finds_search_web(self):
        result = get_tool_schema_by_name("search_web")
        assert result is not None
        assert result["function"]["name"] == "search_web"

    def test_finds_read_file(self):
        result = get_tool_schema_by_name("read_file")
        assert result is not None

    def test_returns_none_for_unknown(self):
        result = get_tool_schema_by_name("nonexistent_tool_xyz")
        assert result is None


class TestSpecificSchemas:
    """Test individual schema structures."""

    def test_search_web_has_query_param(self):
        params = SEARCH_WEB_SCHEMA["function"]["parameters"]
        assert "query" in params["properties"]
        assert "query" in params.get("required", [])

    def test_read_file_has_file_path_param(self):
        params = READ_FILE_SCHEMA["function"]["parameters"]
        assert "file_path" in params["properties"]
        assert "file_path" in params.get("required", [])

    def test_write_file_has_content_param(self):
        params = WRITE_FILE_SCHEMA["function"]["parameters"]
        assert "content" in params["properties"]
        assert "file_path" in params.get("required", [])

    def test_execute_python_has_code_param(self):
        params = EXECUTE_PYTHON_SCHEMA["function"]["parameters"]
        assert "code" in params["properties"]
        assert "code" in params.get("required", [])

    def test_send_email_has_required_fields(self):
        params = SEND_EMAIL_SCHEMA["function"]["parameters"]
        required = params.get("required", [])
        assert "to" in required
        assert "subject" in required
        assert "body" in required

    def test_browser_open_has_url(self):
        params = BROWSER_OPEN_SCHEMA["function"]["parameters"]
        assert "url" in params["properties"]

    def test_create_task_has_title_and_goal(self):
        params = CREATE_TASK_SCHEMA["function"]["parameters"]
        assert "title" in params["properties"]
        assert "goal" in params["properties"]


class TestToolDefinitionsAlias:
    """Test backward compatibility alias."""

    def test_alias_equals_all(self):
        assert TOOL_DEFINITIONS is ALL_TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# validate_schemas, get_required_params, get_all_schema_names
# ---------------------------------------------------------------------------

class TestValidateSchemas:
    """Test schema validation function."""

    def test_validate_schemas_returns_true(self):
        assert validate_schemas() is True


class TestGetRequiredParams:
    """Test get_required_params function."""

    def test_get_required_params_search_web(self):
        params = get_required_params("search_web")
        assert "query" in params

    def test_get_required_params_read_file(self):
        params = get_required_params("read_file")
        assert "file_path" in params

    def test_get_required_params_write_file(self):
        params = get_required_params("write_file")
        assert "file_path" in params
        assert "content" in params

    def test_get_required_params_send_email(self):
        params = get_required_params("send_email")
        assert "to" in params
        assert "subject" in params
        assert "body" in params

    def test_get_required_params_nonexistent_returns_empty(self):
        params = get_required_params("nonexistent_tool_xyz")
        assert params == []

    def test_get_required_params_returns_list(self):
        params = get_required_params("search_web")
        assert isinstance(params, list)


class TestGetAllSchemaNames:
    """Test get_all_schema_names function."""

    def test_get_all_schema_names_returns_sorted(self):
        names = get_all_schema_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert names == sorted(names)  # Check it's sorted

    def test_get_all_schema_names_contains_core_tools(self):
        names = get_all_schema_names()
        assert "search_web" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "run_command" in names
        assert "execute_python" in names

    def test_get_all_schema_names_matches_all_tool_schemas(self):
        names = get_all_schema_names()
        all_names = [s["function"]["name"] for s in ALL_TOOL_SCHEMAS]
        assert set(names) == set(all_names)

"""
Tests for utils/json.py — JSON utility functions.
"""
import pytest
from mind_clone.utils.json import (
    _safe_json_dict,
    safe_json_loads,
    pretty_json,
)


class TestSafeJsonDict:
    """Test _safe_json_dict conversion."""

    def test_dict_passthrough(self):
        data = {"key": "value", "num": 42}
        result = _safe_json_dict(data)
        assert result == data

    def test_nested_dict(self):
        data = {"outer": {"inner": "value"}}
        result = _safe_json_dict(data)
        assert result == data

    def test_list_passthrough(self):
        data = [1, "two", 3.0]
        result = _safe_json_dict(data)
        assert result == data

    def test_primitives(self):
        assert _safe_json_dict("hello") == "hello"
        assert _safe_json_dict(42) == 42
        assert _safe_json_dict(3.14) == 3.14
        assert _safe_json_dict(True) is True
        assert _safe_json_dict(None) is None

    def test_non_serializable_converted(self):
        from datetime import datetime
        dt = datetime(2024, 1, 1)
        result = _safe_json_dict(dt)
        # Should be converted to string representation
        assert isinstance(result, str)

    def test_nested_list_in_dict(self):
        data = {"items": [1, 2, {"nested": True}]}
        result = _safe_json_dict(data)
        assert result["items"][2]["nested"] is True


class TestSafeJsonLoads:
    """Test safe JSON parsing."""

    def test_valid_json(self):
        result = safe_json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_array(self):
        result = safe_json_loads('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_invalid_json_returns_default(self):
        result = safe_json_loads("not json")
        assert result is None

    def test_invalid_json_custom_default(self):
        result = safe_json_loads("broken", default={})
        assert result == {}

    def test_none_input(self):
        result = safe_json_loads(None)
        assert result is None

    def test_empty_string(self):
        result = safe_json_loads("")
        assert result is None


class TestPrettyJson:
    """Test pretty JSON formatting."""

    def test_dict(self):
        result = pretty_json({"a": 1})
        assert '"a": 1' in result
        assert "\n" in result  # indented

    def test_list(self):
        result = pretty_json([1, 2, 3])
        assert "1" in result

    def test_non_serializable(self):
        from datetime import datetime
        result = pretty_json({"time": datetime(2024, 1, 1)})
        assert "2024" in result  # default=str handles it

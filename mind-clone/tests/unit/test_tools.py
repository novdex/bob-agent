"""
Tests for tools module.
"""
import pytest
from mind_clone.tools.schemas import TOOL_DEFINITIONS
from mind_clone.tools.registry import TOOL_DISPATCH


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

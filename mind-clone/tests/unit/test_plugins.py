"""
Tests for core/plugins.py — Plugin management utilities.
"""
import pytest
from mind_clone.core.plugins import (
    PLUGIN_TOOL_REGISTRY,
    load_plugin_tools,
    reload_plugins,
)


class TestPlugins:
    """Test plugin management."""

    def test_plugin_registry_is_dict(self):
        assert isinstance(PLUGIN_TOOL_REGISTRY, dict)

    def test_load_plugin_tools_returns_list(self):
        result = load_plugin_tools()
        assert isinstance(result, list)

    def test_reload_plugins_no_crash(self):
        """reload_plugins should not raise."""
        reload_plugins()

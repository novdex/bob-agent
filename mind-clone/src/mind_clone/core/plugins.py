"""
Plugin management utilities.
"""
from typing import Dict, Any, List

PLUGIN_TOOL_REGISTRY: Dict[str, Any] = {}

def load_plugin_tools() -> List[Dict[str, Any]]:
    """Load all plugin tools."""
    return []

def reload_plugins():
    """Reload all plugins."""
    pass

__all__ = ["PLUGIN_TOOL_REGISTRY", "load_plugin_tools", "reload_plugins"]

"""
Plugin Isolation — each new feature Bob learns is loaded as an isolated plugin.

Plugins are single .py files in ~/.mind-clone/plugins/ with a ``register()``
function that returns the plugin's metadata and tools. Each plugin is loaded
in a try/except so a crashing plugin never takes down Bob.

Plugin file format::

    NAME = "example"
    DESCRIPTION = "An example plugin"
    TOOLS = {}

    def register():
        return {
            "name": NAME,
            "description": DESCRIPTION,
            "tools": TOOLS,
        }

This is part of the OpenClaw-style safe self-improvement loop:
  Skills + Config Tuning + Plugin Isolation (here) + Safe Nightly Improvement
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.services.plugin_loader")

# Directory where plugin .py files live
PLUGINS_DIR: Path = Path.home() / ".mind-clone" / "plugins"

# Runtime registry of loaded plugin tools: plugin_name -> {tool_name: callable}
_PLUGIN_TOOL_REGISTRY: dict[str, dict[str, Any]] = {}

# Track loaded plugin metadata
_LOADED_PLUGINS: dict[str, dict[str, Any]] = {}


def _ensure_plugins_dir() -> Path:
    """Ensure the plugins directory exists and return it."""
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return PLUGINS_DIR


def load_plugins() -> dict[str, Any]:
    """Scan ~/.mind-clone/plugins/ and load each plugin.

    Each plugin is a single .py file with a ``register()`` function.
    Plugins are loaded in try/except isolation — one crash doesn't
    affect others.

    Returns:
        Dict with "loaded" (list of successful plugin names) and
        "failed" (list of dicts with name and error for each failure).
    """
    plugins_dir = _ensure_plugins_dir()
    loaded: list[str] = []
    failed: list[dict[str, str]] = []

    for py_file in sorted(plugins_dir.glob("*.py")):
        plugin_name = py_file.stem

        # Skip dunder files
        if plugin_name.startswith("__"):
            continue

        try:
            # Load the module from file path
            spec = importlib.util.spec_from_file_location(
                f"mind_clone_plugin_{plugin_name}",
                str(py_file),
            )
            if spec is None or spec.loader is None:
                failed.append({
                    "name": plugin_name,
                    "error": "Could not create module spec",
                })
                continue

            module = importlib.util.module_from_spec(spec)

            # Add to sys.modules temporarily for the load
            module_key = f"mind_clone_plugin_{plugin_name}"
            sys.modules[module_key] = module

            try:
                spec.loader.exec_module(module)
            except Exception as exec_err:
                # Clean up if exec fails
                sys.modules.pop(module_key, None)
                failed.append({
                    "name": plugin_name,
                    "error": f"Exec failed: {str(exec_err)[:200]}",
                })
                continue

            # Call register()
            register_fn = getattr(module, "register", None)
            if not callable(register_fn):
                failed.append({
                    "name": plugin_name,
                    "error": "No callable register() function found",
                })
                continue

            result = register_fn()
            if not isinstance(result, dict):
                failed.append({
                    "name": plugin_name,
                    "error": f"register() returned {type(result).__name__}, expected dict",
                })
                continue

            # Extract tools and metadata
            reg_name = str(result.get("name", plugin_name))
            reg_description = str(result.get("description", ""))
            reg_tools = result.get("tools", {})

            _LOADED_PLUGINS[reg_name] = {
                "name": reg_name,
                "description": reg_description,
                "path": str(py_file),
                "tool_count": len(reg_tools) if isinstance(reg_tools, dict) else 0,
            }

            if isinstance(reg_tools, dict) and reg_tools:
                register_plugin_tools(reg_name, reg_tools)

            loaded.append(reg_name)
            logger.info(
                "PLUGIN_LOADED name=%s tools=%d path=%s",
                reg_name,
                len(reg_tools) if isinstance(reg_tools, dict) else 0,
                py_file.name,
            )

        except Exception as exc:
            failed.append({
                "name": plugin_name,
                "error": str(exc)[:200],
            })
            logger.warning(
                "PLUGIN_LOAD_FAIL name=%s error=%s",
                plugin_name, str(exc)[:200],
            )

    logger.info(
        "PLUGINS_SCAN_COMPLETE loaded=%d failed=%d",
        len(loaded), len(failed),
    )
    return {"loaded": loaded, "failed": failed}


def register_plugin_tools(plugin_name: str, tools: dict[str, Any]) -> None:
    """Add a plugin's tools to the internal plugin tool registry.

    Args:
        plugin_name: The name of the plugin providing these tools.
        tools: Dict mapping tool_name -> callable or tool dict.
    """
    if not isinstance(tools, dict):
        logger.warning(
            "PLUGIN_TOOLS_INVALID plugin=%s type=%s",
            plugin_name, type(tools).__name__,
        )
        return

    _PLUGIN_TOOL_REGISTRY[plugin_name] = {}
    for tool_name, tool_impl in tools.items():
        _PLUGIN_TOOL_REGISTRY[plugin_name][str(tool_name)] = tool_impl
        logger.debug(
            "PLUGIN_TOOL_REGISTERED plugin=%s tool=%s",
            plugin_name, tool_name,
        )


def unload_plugin(name: str) -> bool:
    """Remove a plugin's tools from the registry.

    Args:
        name: The plugin name to unload.

    Returns:
        True if the plugin was found and unloaded, False if not found.
    """
    found = name in _PLUGIN_TOOL_REGISTRY or name in _LOADED_PLUGINS
    if not found:
        logger.warning("PLUGIN_UNLOAD_NOT_FOUND name=%s", name)
        return False

    tool_count = 0
    if name in _PLUGIN_TOOL_REGISTRY:
        tool_count = len(_PLUGIN_TOOL_REGISTRY[name])
        del _PLUGIN_TOOL_REGISTRY[name]

    _LOADED_PLUGINS.pop(name, None)

    # Clean up sys.modules entry
    module_key = f"mind_clone_plugin_{name}"
    sys.modules.pop(module_key, None)

    logger.info(
        "PLUGIN_UNLOADED name=%s tools_removed=%d",
        name, tool_count,
    )
    return True


def get_loaded_plugins() -> list[dict[str, Any]]:
    """Return metadata for all currently loaded plugins.

    Returns:
        List of dicts with name, description, path, and tool_count.
    """
    return list(_LOADED_PLUGINS.values())


def get_plugin_tool(plugin_name: str, tool_name: str) -> Any | None:
    """Look up a specific tool from a loaded plugin.

    Args:
        plugin_name: The plugin to look in.
        tool_name: The tool to find.

    Returns:
        The tool callable/dict, or None if not found.
    """
    plugin_tools = _PLUGIN_TOOL_REGISTRY.get(plugin_name, {})
    return plugin_tools.get(tool_name)


def get_all_plugin_tools() -> dict[str, Any]:
    """Return a flat dict of all plugin tools (prefixed with plugin name).

    Returns:
        Dict mapping "pluginname_toolname" -> tool implementation.
    """
    flat: dict[str, Any] = {}
    for plugin_name, tools in _PLUGIN_TOOL_REGISTRY.items():
        for tool_name, tool_impl in tools.items():
            flat[f"{plugin_name}_{tool_name}"] = tool_impl
    return flat

"""
Custom tool management package — backward-compatible re-exports.

Split from a single ``custom_tools.py`` into three submodules:

- ``creator.py``    — CRUD operations for custom tools
- ``validator.py``  — code validation, safety checks, hash, wrapper generation
- ``executor.py``   — sandbox execution, testing, file I/O

All public names are re-exported here so existing imports work unchanged.
"""

from __future__ import annotations

# --- creator.py ---
from .creator import (
    list_custom_tools,
    get_custom_tool,
    create_custom_tool,
    update_custom_tool,
    delete_custom_tool,
    prune_custom_tools,
)

# --- validator.py ---
from .validator import (
    SANDBOX_ALLOWED_MODULES,
    SANDBOX_DANGEROUS_BUILTINS,
    validate_tool_code,
    get_tool_code_hash,
    generate_tool_wrapper,
)

# --- executor.py ---
from .executor import (
    test_custom_tool,
    execute_in_sandbox,
    execute_in_sandbox_v2,
    sandbox_python,
    read_tool_file,
    write_tool_file,
    import_tool_from_file,
    export_tool_to_file,
)

__all__ = [
    "list_custom_tools",
    "get_custom_tool",
    "create_custom_tool",
    "update_custom_tool",
    "delete_custom_tool",
    "prune_custom_tools",
    "validate_tool_code",
    "test_custom_tool",
    "execute_in_sandbox",
    "execute_in_sandbox_v2",
    "sandbox_python",
    "get_tool_code_hash",
    "generate_tool_wrapper",
    "read_tool_file",
    "write_tool_file",
    "import_tool_from_file",
    "export_tool_to_file",
    "SANDBOX_ALLOWED_MODULES",
    "SANDBOX_DANGEROUS_BUILTINS",
]

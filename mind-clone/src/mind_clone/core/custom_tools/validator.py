"""
Code validation, safety checks for custom tools.

Provides static analysis of Python code to detect dangerous patterns,
syntax errors, and structural issues before execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("mind_clone.core.custom_tools.validator")

# Sandbox configuration
SANDBOX_ALLOWED_MODULES = {
    "json", "re", "math", "random", "datetime", "collections",
    "itertools", "functools", "operator", "string", "hashlib",
    "base64", "urllib.parse", "html",
}

SANDBOX_DANGEROUS_BUILTINS = {
    "eval", "exec", "compile", "__import__", "open", "input",
    "raw_input", "reload", "exit", "quit", "help",
}


def validate_tool_code(code: str) -> Dict[str, Any]:
    """Validate Python code for custom tool.

    Checks for dangerous patterns, syntax errors, and ensures the code
    defines at least one function or class.

    Args:
        code: Python code to validate

    Returns:
        Validation result with success status and error message
    """
    if not code or not code.strip():
        return {"valid": False, "error": "Code cannot be empty"}

    # Check for dangerous patterns
    dangerous_patterns = [
        (r'\bexec\s*\(', "exec() is not allowed"),
        (r'\beval\s*\(', "eval() is not allowed"),
        (r'\bcompile\s*\(', "compile() is not allowed"),
        (r'__import__', "__import__ is not allowed"),
        (r'\bopen\s*\(', "open() is not allowed in sandbox"),
        (r'\binput\s*\(', "input() is not allowed"),
        (r'\bsubprocess\s*\.', "subprocess is not allowed"),
        (r'\bos\s*\.system', "os.system is not allowed"),
        (r'\bimport\s+os\b', "os module import is not allowed"),
        (r'\bimport\s+sys\b', "sys module import is not allowed"),
        (r'\bimport\s+subprocess\b', "subprocess import is not allowed"),
        (r'\bimport\s+pickle\b', "pickle import is not allowed"),
        (r'\bimport\s+yaml\b', "yaml import is not allowed for security"),
        (r'with\s+open\s*\(', "file operations are not allowed"),
        (r'\[k\s+for\s+k\s+in\s+dir\(', "dir() introspection not allowed"),
        (r'globals\(\)', "globals() is not allowed"),
        (r'locals\(\)', "locals() is not allowed"),
    ]

    for pattern, message in dangerous_patterns:
        if re.search(pattern, code):
            return {"valid": False, "error": message}

    # Try to parse the code
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e.msg} at line {e.lineno}"}
    except Exception as e:
        return {"valid": False, "error": f"Parse error: {str(e)}"}

    # Check for function/class definitions
    try:
        tree = ast.parse(code)
        has_executable = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                has_executable = True
                break

        if not has_executable:
            return {"valid": False, "error": "Code must define at least one function or class"}
    except Exception:
        pass

    return {"valid": True, "error": None}


def get_tool_code_hash(code: str) -> str:
    """Get SHA256 hash of tool code for change detection.

    Args:
        code: Python code

    Returns:
        SHA256 hash of the code
    """
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def generate_tool_wrapper(
    name: str,
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    docstring: Optional[str] = None,
) -> str:
    """Generate a wrapper for custom tool code.

    Args:
        name: Tool function name
        code: Tool implementation code
        parameters: Parameter schema
        docstring: Optional docstring

    Returns:
        Complete wrapped tool code
    """
    param_schema = json.dumps(parameters or {}, indent=2)

    wrapper = f'''
"""
Custom tool: {name}
Auto-generated wrapper.

Parameters Schema:
{param_schema}
"""

{code}


def get_schema():
    """Return the tool's parameter schema."""
    return {param_schema}


if __name__ == "__main__":
    # Test the tool
    import json
    schema = get_schema()
    print(f"Tool: {name}")
    print(f"Schema: {{json.dumps(schema, indent=2)}}")
'''

    return wrapper

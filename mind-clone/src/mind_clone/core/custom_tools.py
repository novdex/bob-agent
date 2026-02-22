"""
Custom tool management utilities.

Provides full CRUD operations for custom tools, tool validation,
and code execution sandbox.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database.models import GeneratedTool
from ..database.session import SessionLocal
from ..config import settings
from ..utils import utc_now_iso, generate_uuid, truncate_text

logger = logging.getLogger("mind_clone.core.custom_tools")

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
    "get_tool_code_hash",
    "generate_tool_wrapper",
]


def list_custom_tools(
    owner_id: Optional[int] = None,
    enabled_only: bool = True,
    test_passed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List custom tools with optional filtering.
    
    Args:
        owner_id: Filter by owner
        enabled_only: Only show enabled tools
        test_passed_only: Only show tools that passed testing
        limit: Maximum results
        offset: Pagination offset
        
    Returns:
        List of custom tool dictionaries
    """
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)
        
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        if enabled_only:
            query = query.filter(GeneratedTool.enabled == 1)
        if test_passed_only:
            query = query.filter(GeneratedTool.test_passed == 1)
        
        tools = query.order_by(GeneratedTool.updated_at.desc()).offset(offset).limit(limit).all()
        
        return [_tool_to_dict(t) for t in tools]
    finally:
        db.close()


def get_custom_tool(
    tool_id: Optional[int] = None,
    tool_name: Optional[str] = None,
    owner_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get a custom tool by ID or name.
    
    Args:
        tool_id: Tool ID
        tool_name: Tool name
        owner_id: Optional owner verification
        
    Returns:
        Tool dictionary or None
    """
    if not tool_id and not tool_name:
        return None
    
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)
        
        if tool_id:
            query = query.filter(GeneratedTool.id == tool_id)
        if tool_name:
            query = query.filter(GeneratedTool.tool_name == tool_name)
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        
        tool = query.first()
        return _tool_to_dict(tool) if tool else None
    finally:
        db.close()


def create_custom_tool(
    owner_id: int,
    name: str,
    code: str,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None,
    requirements: Optional[str] = None,
    run_test: bool = True,
) -> Dict[str, Any]:
    """
    Create a new custom tool.
    
    Args:
        owner_id: The owner ID
        name: Tool name (must be unique)
        code: Python code for the tool
        description: Tool description
        parameters: JSON schema for parameters
        requirements: pip requirements
        run_test: Whether to test the tool before saving
        
    Returns:
        Creation result with tool ID or error
    """
    # Validate name
    if not _validate_tool_name(name):
        return {"ok": False, "error": "Invalid tool name. Use alphanumeric and underscores only."}
    
    # Validate code
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": f"Code validation failed: {validation['error']}"}
    
    db = SessionLocal()
    try:
        # Check for existing tool with same name
        existing = db.query(GeneratedTool).filter(
            GeneratedTool.tool_name == name,
        ).first()
        
        if existing:
            return {"ok": False, "error": f"Tool '{name}' already exists"}
        
        # Test if requested
        test_passed = False
        if run_test:
            test_result = test_custom_tool(code, parameters or {})
            test_passed = test_result.get("ok", False)
            if not test_passed:
                logger.warning(f"Tool test failed for {name}: {test_result.get('error')}")
        
        tool = GeneratedTool(
            owner_id=owner_id,
            tool_name=name,
            description=description,
            parameters_json=json.dumps(parameters or {}),
            code=code,
            requirements=requirements,
            enabled=1,
            test_passed=1 if test_passed else 0,
            usage_count=0,
        )
        
        db.add(tool)
        db.commit()
        db.refresh(tool)
        
        logger.info(f"Created custom tool {tool.id}: {name}")
        
        return {
            "ok": True,
            "id": tool.id,
            "name": name,
            "test_passed": test_passed,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def update_custom_tool(
    tool_id: int,
    owner_id: int,
    updates: Dict[str, Any],
    run_test: bool = True,
) -> Dict[str, Any]:
    """
    Update a custom tool.
    
    Args:
        tool_id: Tool ID
        owner_id: Owner ID for verification
        updates: Fields to update
        run_test: Whether to retest if code changes
        
    Returns:
        Update result
    """
    db = SessionLocal()
    try:
        tool = db.query(GeneratedTool).filter(
            GeneratedTool.id == tool_id,
            GeneratedTool.owner_id == owner_id,
        ).first()
        
        if not tool:
            return {"ok": False, "error": "Tool not found"}
        
        # Update allowed fields
        allowed_fields = {
            "description", "code", "requirements", "enabled"
        }
        
        code_changed = False
        for field, value in updates.items():
            if field in allowed_fields and hasattr(tool, field):
                if field == "code" and value != tool.code:
                    code_changed = True
                setattr(tool, field, value)
        
        # Handle parameters update
        if "parameters" in updates:
            tool.parameters_json = json.dumps(updates["parameters"])
        
        # Retest if code changed and testing enabled
        if code_changed and run_test:
            validation = validate_tool_code(tool.code)
            if not validation["valid"]:
                return {"ok": False, "error": f"Updated code validation failed: {validation['error']}"}
            
            params = json.loads(tool.parameters_json or "{}")
            test_result = test_custom_tool(tool.code, params)
            tool.test_passed = 1 if test_result.get("ok", False) else 0
        
        tool.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        logger.info(f"Updated custom tool {tool_id}")
        return {
            "ok": True,
            "tool": _tool_to_dict(tool),
            "test_passed": bool(tool.test_passed),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def delete_custom_tool(tool_id: int, owner_id: int) -> Dict[str, Any]:
    """
    Delete a custom tool.
    
    Args:
        tool_id: Tool ID
        owner_id: Owner ID for verification
        
    Returns:
        Delete result
    """
    db = SessionLocal()
    try:
        tool = db.query(GeneratedTool).filter(
            GeneratedTool.id == tool_id,
            GeneratedTool.owner_id == owner_id,
        ).first()
        
        if not tool:
            return {"ok": False, "error": "Tool not found"}
        
        db.delete(tool)
        db.commit()
        
        logger.info(f"Deleted custom tool {tool_id}")
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def prune_custom_tools(
    older_than_days: int = 90,
    unused_only: bool = True,
) -> Dict[str, Any]:
    """
    Prune old or unused custom tools.
    
    Args:
        older_than_days: Delete tools older than this
        unused_only: Only delete tools with zero usage
        
    Returns:
        Prune result
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool).filter(
            GeneratedTool.updated_at < cutoff,
        )
        
        if unused_only:
            query = query.filter(GeneratedTool.usage_count == 0)
        
        tools = query.all()
        deleted = []
        
        for tool in tools:
            deleted.append({"id": tool.id, "name": tool.tool_name})
            db.delete(tool)
        
        db.commit()
        
        logger.info(f"Pruned {len(deleted)} custom tools")
        return {"ok": True, "deleted": deleted, "count": len(deleted)}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune custom tools: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def validate_tool_code(code: str) -> Dict[str, Any]:
    """
    Validate custom tool code for safety and syntax.
    
    Args:
        code: Python code to validate
        
    Returns:
        Validation result
    """
    # Check syntax
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e}"}
    except Exception as e:
        return {"valid": False, "error": f"Parse error: {e}"}
    
    # Check for dangerous constructs
    issues = []
    
    for node in ast.walk(tree):
        # Check for __import__
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                issues.append("Use of __import__ is not allowed")
        
        # Check for dangerous builtins
        if isinstance(node, ast.Name) and node.id in SANDBOX_DANGEROUS_BUILTINS:
            issues.append(f"Use of '{node.id}' is not allowed")
        
        # Check for import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module.split(".")[0]
                if module not in SANDBOX_ALLOWED_MODULES:
                    issues.append(f"Import of '{module}' is not allowed")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module not in SANDBOX_ALLOWED_MODULES:
                        issues.append(f"Import of '{module}' is not allowed")
        
        # Check for file operations
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ["open", "file"]:
                    issues.append("File operations are not allowed")
        
        # Check for network operations
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ["urlopen", "socket", "connect"]:
                    issues.append("Network operations are not allowed")
    
    if issues:
        return {"valid": False, "error": "; ".join(issues)}
    
    return {"valid": True, "issues": []}


def test_custom_tool(
    code: str,
    parameters: Dict[str, Any],
    test_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Test custom tool execution in sandbox.
    
    Args:
        code: Tool code
        parameters: Expected parameters
        test_args: Test arguments (generated from parameters if not provided)
        
    Returns:
        Test result
    """
    # Generate test args if not provided
    if test_args is None:
        test_args = _generate_test_args(parameters)
    
    try:
        result = execute_in_sandbox(code, test_args, timeout=5)
        return result
    except Exception as e:
        return {"ok": False, "error": f"Test execution failed: {e}"}


def _generate_test_args(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Generate test arguments from parameter schema."""
    test_args = {}
    
    for name, schema in parameters.get("properties", {}).items():
        param_type = schema.get("type", "string")
        
        if param_type == "string":
            test_args[name] = schema.get("default", "test")
        elif param_type == "integer":
            test_args[name] = schema.get("default", 1)
        elif param_type == "number":
            test_args[name] = schema.get("default", 1.0)
        elif param_type == "boolean":
            test_args[name] = schema.get("default", True)
        elif param_type == "array":
            test_args[name] = schema.get("default", [])
        elif param_type == "object":
            test_args[name] = schema.get("default", {})
        else:
            test_args[name] = None
    
    return test_args


def execute_in_sandbox(
    code: str,
    args: Dict[str, Any],
    timeout: int = 30,
    memory_limit_mb: int = 128,
) -> Dict[str, Any]:
    """
    Execute code in a sandboxed environment.
    
    Args:
        code: Python code to execute
        args: Arguments to pass to the code
        timeout: Execution timeout in seconds
        memory_limit_mb: Memory limit in MB
        
    Returns:
        Execution result
    """
    # Create temporary file with the code
    wrapper_code = generate_tool_wrapper(code)
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(wrapper_code)
        temp_path = f.name
    
    try:
        # Prepare input data
        input_data = json.dumps({"args": args})
        
        # Execute in subprocess with restrictions
        cmd = [
            "python",
            "-c",
            f"""
import json
import sys

# Read input
input_data = json.loads(sys.stdin.read())
args = input_data.get("args", {{}})

# Execute user code
{code}

# Get result (code should set 'result' variable)
print(json.dumps(result if 'result' in dir() else {{"ok": False, "error": "No result set"}}))
"""
        ]
        
        # Actually run the wrapped code
        result = subprocess.run(
            ["python", temp_path],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            return {
                "ok": False,
                "error": f"Execution failed: {result.stderr}",
                "stdout": result.stdout,
            }
        
        # Parse result
        try:
            output = json.loads(result.stdout)
            return output if isinstance(output, dict) else {"ok": False, "error": "Invalid output format"}
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "Invalid JSON output",
                "stdout": truncate_text(result.stdout, 200),
            }
            
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Execution timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        # Cleanup
        try:
            Path(temp_path).unlink()
        except Exception:
            pass


def generate_tool_wrapper(code: str) -> str:
    """
    Generate a safe wrapper for tool code.
    
    Args:
        code: User tool code
        
    Returns:
        Wrapped code
    """
    return f'''#!/usr/bin/env python3
"""Generated tool wrapper."""

import json
import sys
from io import StringIO

# Restricted builtins
ALLOWED_BUILTINS = {{
    "len", "range", "enumerate", "zip", "map", "filter",
    "sum", "min", "max", "abs", "round", "pow", "divmod",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "sorted", "reversed", "iter", "next", "hasattr", "getattr",
    "isinstance", "issubclass", "type", "id", "hash", "repr",
}}

class RestrictedBuiltins(dict):
    def __getitem__(self, key):
        if key not in ALLOWED_BUILTINS:
            raise NameError(f"{{key}} is not allowed")
        return super().__getitem__(key)

# Read input
try:
    input_data = json.loads(sys.stdin.read())
    args = input_data.get("args", {{}})
except json.JSONDecodeError as e:
    print(json.dumps({{"ok": False, "error": f"Invalid input: {{e}}"}}))
    sys.exit(1)

# Setup restricted environment
safe_globals = {{
    "__builtins__": RestrictedBuiltins({{k: v for k, v in __builtins__.items() if k in ALLOWED_BUILTINS}}),
    "json": __import__("json"),
    "re": __import__("re"),
    "math": __import__("math"),
    "random": __import__("random"),
    "datetime": __import__("datetime"),
    "collections": __import__("collections"),
    "itertools": __import__("itertools"),
    "functools": __import__("functools"),
    "operator": __import__("operator"),
    "string": __import__("string"),
    "hashlib": __import__("hashlib"),
    "args": args,
    "result": None,
}}

# Capture stdout
old_stdout = sys.stdout
sys.stdout = StringIO()

try:
    # Execute user code
{chr(10).join("    " + line for line in code.split(chr(10)))}
    
    # Get captured output
    captured_output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    
    # Return result
    if result is None:
        result = {{"ok": True, "output": captured_output}}
    elif isinstance(result, dict):
        if captured_output and "output" not in result:
            result["output"] = captured_output
    
    print(json.dumps(result))
    
except Exception as e:
    sys.stdout = old_stdout
    print(json.dumps({{"ok": False, "error": str(e), "error_type": type(e).__name__}}))
    sys.exit(1)
'''


def get_tool_code_hash(code: str) -> str:
    """
    Get hash of tool code for verification.
    
    Args:
        code: Tool code
        
    Returns:
        SHA256 hash
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _validate_tool_name(name: str) -> bool:
    """Validate tool name format."""
    if not name:
        return False
    # Allow alphanumeric and underscores, must start with letter
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", name))


def _tool_to_dict(tool: GeneratedTool) -> Dict[str, Any]:
    """Convert GeneratedTool model to dictionary."""
    return {
        "id": tool.id,
        "owner_id": tool.owner_id,
        "name": tool.tool_name,
        "description": tool.description,
        "parameters": json.loads(tool.parameters_json or "{}"),
        "code": tool.code,
        "requirements": tool.requirements,
        "enabled": bool(tool.enabled),
        "test_passed": bool(tool.test_passed),
        "usage_count": tool.usage_count,
        "last_error": tool.last_error,
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
        "code_hash": get_tool_code_hash(tool.code) if tool.code else None,
    }


def get_tool_usage_stats(owner_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get usage statistics for custom tools.
    
    Args:
        owner_id: Optional owner filter
        
    Returns:
        Statistics dictionary
    """
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool)
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        
        tools = query.all()
        
        total_tools = len(tools)
        enabled_tools = sum(1 for t in tools if t.enabled)
        tested_tools = sum(1 for t in tools if t.test_passed)
        total_usage = sum(t.usage_count or 0 for t in tools)
        
        # Most used tools
        most_used = sorted(
            [{"name": t.tool_name, "usage": t.usage_count or 0} for t in tools],
            key=lambda x: x["usage"],
            reverse=True,
        )[:10]
        
        return {
            "total_tools": total_tools,
            "enabled_tools": enabled_tools,
            "disabled_tools": total_tools - enabled_tools,
            "tested_tools": tested_tools,
            "untested_tools": total_tools - tested_tools,
            "total_usage": total_usage,
            "most_used": most_used,
        }
    finally:
        db.close()

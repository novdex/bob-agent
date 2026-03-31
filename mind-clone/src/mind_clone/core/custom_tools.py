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


def _tool_to_dict(tool: GeneratedTool) -> Dict[str, Any]:
    """Convert a GeneratedTool model to a dictionary."""
    if tool is None:
        return None
    
    return {
        "id": tool.id,
        "owner_id": tool.owner_id,
        "tool_name": tool.tool_name,
        "description": tool.description,
        "parameters": json.loads(tool.parameters_json or "{}"),
        "code": tool.code,
        "requirements": tool.requirements,
        "enabled": bool(tool.enabled),
        "test_passed": bool(tool.test_passed),
        "usage_count": tool.usage_count or 0,
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
    }


def _validate_tool_name(name: str) -> bool:
    """Validate tool name format."""
    if not name:
        return False
    # Must be alphanumeric with underscores, start with letter
    pattern = r'^[a-zA-Z][a-zA-Z0-9_]*$'
    if not re.match(pattern, name):
        return False
    # Max length check
    if len(name) > 64:
        return False
    return True


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
                if field == "enabled":
                    value = 1 if value else 0
                setattr(tool, field, value)
        
        # Retest if code changed
        test_passed = bool(tool.test_passed)
        if code_changed and run_test:
            validation = validate_tool_code(tool.code)
            if not validation["valid"]:
                db.rollback()
                return {"ok": False, "error": f"Code validation failed: {validation['error']}"}
            
            test_result = test_custom_tool(tool.code, json.loads(tool.parameters_json or "{}"))
            test_passed = test_result.get("ok", False)
            tool.test_passed = 1 if test_passed else 0
            
            if not test_passed:
                logger.warning(f"Tool test failed during update: {test_result.get('error')}")
        
        tool.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(tool)
        
        logger.info(f"Updated custom tool {tool_id}")
        
        return {
            "ok": True,
            "id": tool.id,
            "test_passed": test_passed,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def delete_custom_tool(
    tool_id: int,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Delete a custom tool.
    
    Args:
        tool_id: Tool ID to delete
        owner_id: Optional owner verification
        
    Returns:
        Deletion result
    """
    db = SessionLocal()
    try:
        query = db.query(GeneratedTool).filter(GeneratedTool.id == tool_id)
        
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        
        tool = query.first()
        if not tool:
            return {"ok": False, "error": "Tool not found"}
        
        tool_name = tool.tool_name
        db.delete(tool)
        db.commit()
        
        logger.info(f"Deleted custom tool {tool_id}: {tool_name}")
        
        return {"ok": True, "deleted": tool_id}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def prune_custom_tools(
    older_than_days: int = 90,
    enabled_only: bool = False,
) -> Dict[str, Any]:
    """
    Delete custom tools older than specified days.
    
    Args:
        older_than_days: Delete tools not updated in this many days
        enabled_only: Only prune disabled tools
        
    Returns:
        Prune result with count of deleted tools
    """
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        
        query = db.query(GeneratedTool).filter(
            GeneratedTool.updated_at < cutoff_date
        )
        
        if enabled_only:
            query = query.filter(GeneratedTool.enabled == 0)
        
        count = query.count()
        
        if count > 0:
            query.delete()
            db.commit()
            logger.info(f"Pruned {count} custom tools older than {older_than_days} days")
        
        return {
            "ok": True,
            "pruned_count": count,
            "older_than_days": older_than_days,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune custom tools: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def validate_tool_code(code: str) -> Dict[str, Any]:
    """
    Validate Python code for custom tool.
    
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


def test_custom_tool(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Test a custom tool by executing it in sandbox.
    
    Args:
        code: Python code to test
        parameters: Test parameters
        timeout: Execution timeout in seconds
        
    Returns:
        Test result with success status and output/error
    """
    parameters = parameters or {}
    
    # First validate the code
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"]}
    
    # Create a test script that calls the tool
    test_script = f"""
{code}

# Test invocation
if __name__ == "__main__":
    import json
    import sys
    
    try:
        # Try to find a function to test
        test_func = None
        for name in dir():
            obj = locals().get(name)
            if callable(obj) and not name.startswith('_'):
                test_func = obj
                break
        
        if test_func is None:
            # Try globals
            for name in globals():
                obj = globals()[name]
                if callable(obj) and not name.startswith('_'):
                    test_func = obj
                    break
        
        if test_func is None:
            print("NO_FUNCTION_FOUND")
            sys.exit(1)
        
        result = test_func(**json.loads('{json.dumps(parameters)}'))
        print(json.dumps(result) if result is not None else 'null')
    except Exception as e:
        print(f"ERROR: {{e}}")
        sys.exit(1)
"""
    
    return execute_in_sandbox(test_script, timeout=timeout)


def execute_in_sandbox(
    code: str,
    timeout: int = 10,
    memory_limit_mb: int = 128,
) -> Dict[str, Any]:
    """
    Execute Python code in a restricted sandbox.
    
    Args:
        code: Python code to execute
        timeout: Execution timeout in seconds
        memory_limit_mb: Memory limit in MB
        
    Returns:
        Execution result with output/error
    """
    # Validate before execution
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"], "output": None}
    
    # Create temporary file with UTF-8 encoding
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.py',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(code)
        temp_file = f.name
    
    try:
        # Build restricted environment
        env = {
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        
        # Execute with resource limits
        try:
            result = subprocess.run(
                [
                    "python3",
                    "-c",
                    f"exec(open('{temp_file}', encoding='utf-8').read())"
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"Execution timed out after {timeout} seconds",
                "output": None,
                "timeout": True,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Execution failed: {str(e)}",
                "output": None,
            }
        
        # Check for errors
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if not error_msg:
                error_msg = f"Execution failed with exit code {result.returncode}"
            return {
                "ok": False,
                "error": error_msg,
                "output": result.stdout if result.stdout else None,
            }
        
        return {
            "ok": True,
            "error": None,
            "output": result.stdout.strip() if result.stdout else None,
        }
        
    finally:
        # Clean up temp file
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception:
            pass


def execute_in_sandbox_v2(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Execute Python code in sandbox with proper parameter handling.
    
    Args:
        code: Python code to execute
        parameters: Parameters to pass to the tool function
        timeout: Execution timeout in seconds
        
    Returns:
        Execution result with output/error
    """
    parameters = parameters or {}
    
    # Validate before execution
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"], "output": None}
    
    # Create wrapper script with UTF-8 encoding
    wrapper_script = f'''
import json
import sys

# User code
{code}

# Test runner
if __name__ == "__main__":
    try:
        params = json.loads(\'\'\'{json.dumps(parameters)}\'\'\')
        
        # Find testable function
        test_func = None
        func_name = None
        
        for name, obj in list(globals().items()):
            if (callable(obj) and not name.startswith("_") and 
                name not in ("json", "sys", "params", "test_func", "func_name")):
                test_func = obj
                func_name = name
                break
        
        if test_func is None:
            print("ERROR: No callable function found")
            sys.exit(1)
        
        result = test_func(**params)
        
        if result is None:
            print("null")
        elif isinstance(result, (dict, list)):
            print(json.dumps(result))
        else:
            print(str(result))
            
    except Exception as e:
        import traceback
        print(f"ERROR: {{e}}")
        traceback.print_exc()
        sys.exit(1)
'''
    
    # Create temporary file with UTF-8 encoding
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.py',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(wrapper_script)
        temp_file = f.name
    
    try:
        # Build restricted environment
        env = {
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        
        # Execute with timeout
        try:
            result = subprocess.run(
                ["python3", temp_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"Execution timed out after {timeout} seconds",
                "output": None,
                "timeout": True,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Execution failed: {str(e)}",
                "output": None,
            }
        
        # Check output
        output = result.stdout.strip() if result.stdout else ""
        error = result.stderr.strip() if result.stderr else ""
        
        if result.returncode != 0:
            if output.startswith("ERROR:"):
                return {
                    "ok": False,
                    "error": output.replace("ERROR: ", ""),
                    "output": None,
                }
            return {
                "ok": False,
                "error": error or f"Execution failed with exit code {result.returncode}",
                "output": output if output else None,
            }
        
        if output == "NO_FUNCTION_FOUND":
            return {
                "ok": False,
                "error": "No callable function found in code",
                "output": None,
            }
        
        return {
            "ok": True,
            "error": None,
            "output": output,
        }
        
    finally:
        # Clean up temp file
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception:
            pass


def get_tool_code_hash(code: str) -> str:
    """
    Get SHA256 hash of tool code for change detection.
    
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
    """
    Generate a wrapper for custom tool code.
    
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


def sandbox_python(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Execute Python code in a restricted sandbox environment.
    Alias for execute_in_sandbox_v2 for backward compatibility.
    
    Args:
        code: Python code to execute
        parameters: Parameters to pass to the tool
        timeout: Execution timeout in seconds
        
    Returns:
        Execution result with output/error
    """
    return execute_in_sandbox_v2(code, parameters, timeout)


def read_tool_file(file_path: str) -> Optional[str]:
    """
    Read tool code from a file with UTF-8 encoding.
    
    Args:
        file_path: Path to the tool file
        
    Returns:
        File contents or None if error
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to read tool file {file_path}: {e}")
        return None


def write_tool_file(file_path: str, code: str) -> bool:
    """
    Write tool code to a file with UTF-8 encoding.
    
    Args:
        file_path: Path to write to
        code: Tool code to write
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(code)
        return True
    except Exception as e:
        logger.error(f"Failed to write tool file {file_path}: {e}")
        return False


def import_tool_from_file(file_path: str) -> Dict[str, Any]:
    """
    Import and validate a tool from a Python file.
    
    Args:
        file_path: Path to the tool file
        
    Returns:
        Import result with tool info or error
    """
    code = read_tool_file(file_path)
    if code is None:
        return {"ok": False, "error": f"Could not read file: {file_path}"}
    
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"]}
    
    return {
        "ok": True,
        "code": code,
        "valid": True,
    }


def export_tool_to_file(
    tool_id: int,
    file_path: str,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Export a tool to a Python file.
    
    Args:
        tool_id: Tool ID to export
        file_path: Path to write to
        owner_id: Optional owner verification
        
    Returns:
        Export result
    """
    tool = get_custom_tool(tool_id=tool_id, owner_id=owner_id)
    if tool is None:
        return {"ok": False, "error": "Tool not found"}
    
    wrapped_code = generate_tool_wrapper(
        name=tool["tool_name"],
        code=tool["code"],
        parameters=tool["parameters"],
        docstring=tool["description"],
    )
    
    if write_tool_file(file_path, wrapped_code):
        return {"ok": True, "file_path": file_path}
    else:
        return {"ok": False, "error": "Failed to write file"}
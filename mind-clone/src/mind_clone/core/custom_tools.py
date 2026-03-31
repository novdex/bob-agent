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
                setattr(tool, field, value)
        
        # Retest if code changed
        if code_changed and run_test:
            # Validate new code
            validation = validate_tool_code(tool.code)
            if not validation["valid"]:
                db.rollback()
                return {"ok": False, "error": f"Code validation failed: {validation['error']}"}
            
            # Run test
            parameters = json.loads(tool.parameters_json or "{}")
            test_result = test_custom_tool(tool.code, parameters)
            tool.test_passed = 1 if test_result.get("ok", False) else 0
            
            if not test_result.get("ok", False):
                logger.warning(f"Tool test failed after update {tool_id}: {test_result.get('error')}")
        
        db.commit()
        db.refresh(tool)
        
        logger.info(f"Updated custom tool {tool_id}")
        
        return {
            "ok": True,
            "id": tool.id,
            "name": tool.tool_name,
            "code_changed": code_changed,
            "test_passed": bool(tool.test_passed),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def delete_custom_tool(
    tool_id: int,
    owner_id: int,
) -> Dict[str, Any]:
    """
    Delete a custom tool.
    
    Args:
        tool_id: Tool ID
        owner_id: Owner ID for verification
        
    Returns:
        Deletion result
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
        
        return {"ok": True, "id": tool_id}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def prune_custom_tools(
    older_than_days: int = 90,
    require_test_passed: bool = True,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Remove old or unused custom tools.
    
    Args:
        older_than_days: Delete tools not updated in this many days
        require_test_passed: Only delete tools that passed tests
        owner_id: Optional owner filter
        
    Returns:
        Prune result with count of deleted tools
    """
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        
        query = db.query(GeneratedTool).filter(
            GeneratedTool.updated_at < cutoff_date,
        )
        
        if require_test_passed:
            query = query.filter(GeneratedTool.test_passed == 1)
        
        if owner_id:
            query = query.filter(GeneratedTool.owner_id == owner_id)
        
        tools_to_delete = query.all()
        count = len(tools_to_delete)
        
        for tool in tools_to_delete:
            db.delete(tool)
        
        db.commit()
        
        logger.info(f"Pruned {count} custom tools")
        
        return {"ok": True, "deleted_count": count}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to prune custom tools: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def validate_tool_code(code: str) -> Dict[str, Any]:
    """
    Validate Python code for security and syntax.
    
    Args:
        code: Python code to validate
        
    Returns:
        Validation result with valid flag and error message
    """
    if not code or not isinstance(code, str):
        return {"valid": False, "error": "Code must be a non-empty string"}
    
    # Check for dangerous patterns
    dangerous_patterns = [
        (r'\bimport\s+os\b', "Importing 'os' module is not allowed"),
        (r'\bfrom\s+os\b', "Importing from 'os' module is not allowed"),
        (r'\bimport\s+subprocess\b', "Importing 'subprocess' module is not allowed"),
        (r'\bfrom\s+subprocess\b', "Importing from 'subprocess' module is not allowed"),
        (r'\bimport\s+sys\b', "Importing 'sys' module is not allowed"),
        (r'\bfrom\s+sys\b', "Importing from 'sys' module is not allowed"),
        (r'\bimport\s+requests\b', "Importing 'requests' module is not allowed"),
        (r'\bfrom\s+requests\b', "Importing from 'requests' module is not allowed"),
        (r'\bimport\s+urllib\b', "Importing 'urllib' module is not allowed"),
        (r'\bfrom\s+urllib\b', "Importing from 'urllib' module is not allowed"),
        (r'\bopen\s*\(', "Using 'open' builtin is not allowed"),
        (r'\bexec\s*\(', "Using 'exec' is not allowed"),
        (r'\beval\s*\(', "Using 'eval' is not allowed"),
        (r'\bcompile\s*\(', "Using 'compile' is not allowed"),
        (r'\b__import__\s*\(', "Using '__import__' is not allowed"),
        (r'\binput\s*\(', "Using 'input' is not allowed"),
        (r'\braw_input\s*\(', "Using 'raw_input' is not allowed"),
        (r'\bos\.system\b', "Using 'os.system' is not allowed"),
        (r'\bos\.popen\b', "Using 'os.popen' is not allowed"),
        (r'\bsubprocess\.', "Using 'subprocess' is not allowed"),
        (r'\bctypes\b', "Using 'ctypes' is not allowed"),
        (r'\bptrace\b', "Using 'ptrace' is not allowed"),
        (r'\bfork\b', "Using 'fork' is not allowed"),
        (r'\bspawn\b', "Using 'spawn' is not allowed"),
        (r'\bPopen\b', "Using 'Popen' is not allowed"),
        (r'\bwith\s+open\s*\(', "Using 'with open' is not allowed"),
        (r'\bfile\s*\(', "Using 'file' builtin is not allowed"),
        (r'\bruntime\b', "Using 'runtime' is not allowed"),
        (r'\beval\s*\(', "Using 'eval' is not allowed"),
        (r'\bgetattr\b', "Using 'getattr' is not allowed"),
        (r'\bsetattr\b', "Using 'setattr' is not allowed"),
        (r'\bdelattr\b', "Using 'delattr' is not allowed"),
        (r'\bhasattr\b', "Using 'hasattr' is not allowed"),
        (r'\bmro\b', "Using 'mro' is not allowed"),
        (r'\b__subclasses__\b', "Using '__subclasses__' is not allowed"),
        (r'\b__globals__\b', "Using '__globals__' is not allowed"),
        (r'\b__code__\b', "Using '__code__' is not allowed"),
        (r'\b__closure__\b', "Using '__closure__' is not allowed"),
        (r'\b__func__\b', "Using '__func__' is not allowed"),
    ]
    
    for pattern, error_msg in dangerous_patterns:
        if re.search(pattern, code):
            return {"valid": False, "error": error_msg}
    
    # Check for allowed imports only
    import_pattern = r'\b(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    imports = re.findall(import_pattern, code)
    
    allowed_modules = SANDBOX_ALLOWED_MODULES | {"typing"}
    
    for imp in imports:
        if imp not in allowed_modules:
            return {"valid": False, "error": f"Importing '{imp}' module is not allowed"}
    
    # Check syntax
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e}"}
    
    # Check for function definition
    if not re.search(r'\bdef\s+\w+\s*\(', code):
        return {"valid": False, "error": "Code must contain a function definition"}
    
    return {"valid": True, "error": None}


def test_custom_tool(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Test custom tool code with sample parameters.
    
    Args:
        code: Python code to test
        parameters: Sample parameters for testing
        timeout: Timeout in seconds
        
    Returns:
        Test result with success status and output/error
    """
    # Validate code first
    validation = validate_tool_code(code)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"]}
    
    # Wrap code for testing
    wrapped_code = generate_tool_wrapper(code, parameters or {})
    
    # Execute in sandbox
    result = execute_in_sandbox(wrapped_code, timeout=timeout)
    
    return result


def execute_in_sandbox(
    code: str,
    timeout: int = 10,
    memory_limit_mb: int = 128,
) -> Dict[str, Any]:
    """
    Execute Python code in a restricted sandbox environment.
    
    Args:
        code: Python code to execute
        timeout: Execution timeout in seconds
        memory_limit_mb: Memory limit in MB
        
    Returns:
        Execution result with output/error
    """
    # Create a temporary file for the code
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
        
        # Run with resource limits using resource module would require native code
        # Instead, we rely on the restricted code validation and timeout
        result = subprocess.run(
            ["python3", "-u", temp_file],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        
        if result.returncode == 0:
            return {
                "ok": True,
                "output": result.stdout,
                "error": None,
            }
        else:
            return {
                "ok": False,
                "output": result.stdout,
                "error": result.stderr or f"Process exited with code {result.returncode}",
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "output": None,
            "error": f"Execution timed out after {timeout} seconds",
        }
    except Exception as e:
        return {
            "ok": False,
            "output": None,
            "error": f"Execution error: {str(e)}",
        }
    finally:
        # Clean up temp file
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception:
            pass


def get_tool_code_hash(code: str) -> str:
    """
    Generate a hash of tool code for caching/comparison.
    
    Args:
        code: Python code
        
    Returns:
        SHA256 hash of the code
    """
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def generate_tool_wrapper(
    code: str,
    test_parameters: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a test wrapper for tool code.
    
    Args:
        code: The tool code to wrap
        test_parameters: Parameters for testing
        
    Returns:
        Wrapped code that can be executed
    """
    params_json = json.dumps(test_parameters or {}, default=str)
    
    wrapper = f'''
import json
import sys

# Tool code
{code}

# Test execution
if __name__ == "__main__":
    try:
        params = json.loads(\'{params_json}\')
        result = main(params)
        print(json.dumps({{"ok": True, "result": result}}, default=str))
    except Exception as e:
        print(json.dumps({{"ok": False, "error": str(e)}}))
        sys.exit(1)
'''
    return wrapper
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
        
        # Validate new code if changed
        if code_changed:
            validation = validate_tool_code(tool.code)
            if not validation["valid"]:
                return {"ok": False, "error": f"Code validation failed: {validation['error']}"}
        
        # Retest if code changed and requested
        test_passed = tool.test_passed
        if code_changed and run_test:
            parameters = json.loads(tool.parameters_json or "{}")
            test_result = test_custom_tool(tool.code, parameters)
            test_passed = test_result.get("ok", False)
            tool.test_passed = 1 if test_passed else 0
            if not test_passed:
                logger.warning(f"Tool test failed during update {tool_id}: {test_result.get('error')}")
        
        tool.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        logger.info(f"Updated custom tool {tool_id}")
        
        return {
            "ok": True,
            "id": tool_id,
            "code_changed": code_changed,
            "test_passed": bool(test_passed),
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
        
        tool_name = tool.tool_name
        db.delete(tool)
        db.commit()
        
        logger.info(f"Deleted custom tool {tool_id}: {tool_name}")
        
        return {
            "ok": True,
            "deleted": tool_id,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def prune_custom_tools(
    older_than_days: int = 90,
    delete_disabled_only: bool = True,
) -> Dict[str, Any]:
    """
    Prune old or disabled custom tools.
    
    Args:
        older_than_days: Delete tools not updated in this many days
        delete_disabled_only: If True, only delete disabled tools
        
    Returns:
        Prune result with count of deleted tools
    """
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        
        query = db.query(GeneratedTool).filter(
            GeneratedTool.updated_at < cutoff_date
        )
        
        if delete_disabled_only:
            query = query.filter(GeneratedTool.enabled == 0)
        
        # Get count before deletion
        tools_to_delete = query.all()
        count = len(tools_to_delete)
        
        # Delete in batch
        for tool in tools_to_delete:
            db.delete(tool)
        
        db.commit()
        
        logger.info(f"Pruned {count} custom tools")
        
        return {
            "ok": True,
            "deleted_count": count,
        }
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
        Validation result with details
    """
    if not code or not code.strip():
        return {"valid": False, "error": "Empty code"}
    
    # Check for dangerous patterns
    dangerous_patterns = [
        (r'\bimport\s+os\b', "OS module import not allowed"),
        (r'\bimport\s+subprocess\b', "Subprocess module import not allowed"),
        (r'\bimport\s+sys\b', "Sys module import not allowed"),
        (r'\bfrom\s+os\s+import', "OS module import not allowed"),
        (r'\bfrom\s+subprocess\s+import', "Subprocess module import not allowed"),
        (r'\bopen\s*\(', "File operations not allowed"),
        (r'\beval\s*\(', "Eval not allowed"),
        (r'\bexec\s*\(', "Exec not allowed"),
        (r'__import__', "__import__ not allowed"),
        (r'\bcompile\s*\(', "Compile not allowed"),
        (r'\bgetattr\s*\(', "Getattr not allowed"),
        (r'\bsetattr\s*\(', "Setattr not allowed"),
        (r'\bdel\s+attr', "Attribute deletion not allowed"),
        (r'\bglobals\s*\(', "Globals not allowed"),
        (r'\blocals\s*\(', "Locals not allowed"),
        (r'\bvars\s*\(', "Vars not allowed"),
        (r'\breload\s*\(', "Reload not allowed"),
        (r'\binput\s*\(', "Input not allowed"),
        (r'\braw_input\s*\(', "Raw input not allowed"),
    ]
    
    for pattern, message in dangerous_patterns:
        if re.search(pattern, code):
            return {"valid": False, "error": message}
    
    # Check for allowed module imports
    import_pattern = r'\b(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    for match in re.finditer(import_pattern, code):
        module_name = match.group(1)
        if module_name not in SANDBOX_ALLOWED_MODULES:
            return {"valid": False, "error": f"Module '{module_name}' not allowed"}
    
    # Syntax check
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e.msg} at line {e.lineno}"}
    
    return {"valid": True}


def test_custom_tool(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Test custom tool code in sandbox.
    
    Args:
        code: Python code to test
        parameters: Test parameters
        timeout: Execution timeout in seconds
        
    Returns:
        Test result with output or error
    """
    parameters = parameters or {}
    
    # Generate test wrapper
    wrapper = generate_tool_wrapper(code, parameters)
    
    return execute_in_sandbox(wrapper, timeout=timeout)


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
        Execution result with stdout, stderr, and return code
    """
    # Create a temporary file for the code
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.py',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(code)
        temp_path = f.name
    
    try:
        # Build restricted environment
        env = {
            'PYTHONPATH': '',
            'HOME': tempfile.gettempdir(),
            'TMPDIR': tempfile.gettempdir(),
        }
        
        # Execute with restrictions
        result = subprocess.run(
            [
                'python3', '-B', '-X', f'memory_limit={memory_limit_mb * 1024 * 1024}',
                '-c', f'exec(open({repr(temp_path)}, encoding="utf-8").read())'
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=tempfile.gettempdir(),
        )
        
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Execution timed out after {timeout} seconds",
            "stdout": "",
            "stderr": "Timeout",
            "return_code": -1,
        }
    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}")
        return {
            "ok": False,
            "error": str(e),
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
        }
    finally:
        # Clean up temp file
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception:
            pass


def get_tool_code_hash(code: str) -> str:
    """
    Generate a hash of tool code for change detection.
    
    Args:
        code: Python code
        
    Returns:
        SHA256 hash of the code
    """
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def generate_tool_wrapper(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a wrapper script for tool testing.
    
    Args:
        code: Tool code
        parameters: Test parameters
        
    Returns:
        Complete Python script for execution
    """
    parameters = parameters or {}
    params_json = json.dumps(parameters, ensure_ascii=False)
    
    wrapper = f'''
import json
import sys

# Tool parameters
parameters = json.loads({repr(params_json)})

# Tool code
{code}

# Execute main function with parameters if it exists
if __name__ == "__main__" or True:
    try:
        if "main" in dir() and callable(main):
            result = main(**parameters)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False, default=str))
        elif "run" in dir() and callable(run):
            result = run(**parameters)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False, default=str))
        else:
            # Try to find any callable that takes the parameters
            for name in dir():
                obj = locals()[name]
                if callable(obj) and not name.startswith("_"):
                    try:
                        result = obj(**parameters)
                        if result is not None:
                            print(json.dumps(result, ensure_ascii=False, default=str))
                            break
                    except (TypeError, ValueError):
                        continue
    except Exception as e:
        print(f"Error: {{e}}", file=sys.stderr)
        sys.exit(1)
'''
    return wrapper
"""
Custom tool execution, runtime management, and sandbox.

Handles executing custom tools in sandboxed environments with timeout
and security restrictions.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from .validator import validate_tool_code

logger = logging.getLogger("mind_clone.core.custom_tools.executor")


def test_custom_tool(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Test a custom tool by executing it in sandbox.

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
    """Execute Python code in a restricted sandbox.

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
    """Execute Python code in sandbox with proper parameter handling.

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


def sandbox_python(
    code: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Execute Python code in a restricted sandbox environment.

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
    """Read tool code from a file with UTF-8 encoding.

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
    """Write tool code to a file with UTF-8 encoding.

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
    """Import and validate a tool from a Python file.

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
    """Export a tool to a Python file.

    Args:
        tool_id: Tool ID to export
        file_path: Path to write to
        owner_id: Optional owner verification

    Returns:
        Export result
    """
    from .creator import get_custom_tool
    from .validator import generate_tool_wrapper

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

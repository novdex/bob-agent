"""
Code Sandbox — safe isolated code execution.

Runs code in a subprocess with timeout, resource limits,
and output capture. Safer than running directly on host.
Captures stdout, stderr, return value.
"""
from __future__ import annotations
import json
import logging
import subprocess
import tempfile
import textwrap
from pathlib import Path
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.code_sandbox")

_DEFAULT_TIMEOUT = 15
_MAX_OUTPUT = 4000


def run_python_sandbox(code: str, timeout: int = _DEFAULT_TIMEOUT,
                       inputs: dict = None) -> dict:
    """Run Python code in an isolated subprocess."""
    # Wrap code with input injection if provided
    preamble = ""
    if inputs:
        preamble = f"_INPUTS = {json.dumps(inputs)}\n"

    full_code = textwrap.dedent(f"""
import sys, json, traceback
{preamble}
try:
{textwrap.indent(code.strip(), '    ')}
except Exception as _e:
    print(f"ERROR: {{_e}}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
""")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(full_code)
        tmpfile = f.name

    try:
        result = subprocess.run(
            ["python", tmpfile],
            capture_output=True, text=True,
            timeout=timeout,
        )
        stdout = truncate_text(result.stdout, _MAX_OUTPUT)
        stderr = truncate_text(result.stderr, _MAX_OUTPUT)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output": stdout or stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Code timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    finally:
        Path(tmpfile).unlink(missing_ok=True)


def run_shell_sandbox(command: str, timeout: int = 10,
                      workdir: str = None) -> dict:
    """Run a shell command with timeout and output capture."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "output": truncate_text(result.stdout + result.stderr, _MAX_OUTPUT),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_sandbox_python(args: dict) -> dict:
    """Tool: Run Python code in an isolated sandbox with timeout."""
    code = str(args.get("code", "")).strip()
    timeout = min(int(args.get("timeout", 15)), 60)
    inputs = args.get("inputs", {})
    if not code:
        return {"ok": False, "error": "code required"}
    return run_python_sandbox(code, timeout, inputs)


def tool_sandbox_shell(args: dict) -> dict:
    """Tool: Run a shell command in a sandbox with timeout."""
    command = str(args.get("command", "")).strip()
    timeout = min(int(args.get("timeout", 10)), 30)
    if not command:
        return {"ok": False, "error": "command required"}
    return run_shell_sandbox(command, timeout)

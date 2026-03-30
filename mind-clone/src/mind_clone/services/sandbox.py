"""
Sandboxed Execution — run untrusted Python / shell code safely.

Uses subprocess with:
  - Strict timeout (kills after N seconds)
  - Stripped environment (no API keys, tokens, or secrets)
  - Temporary working directory (no writes outside it)
  - Blocklists for dangerous commands / code patterns
  - Captured stdout, stderr, return code

This is NOT a full container sandbox — it is a best-effort safety layer
that prevents the most common destructive operations.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import List

from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.sandbox")

_DEFAULT_PYTHON_TIMEOUT = 15
_DEFAULT_SHELL_TIMEOUT = 10
_MAX_OUTPUT = 8000  # max chars captured from stdout/stderr

# ---------------------------------------------------------------------------
# Blocklists
# ---------------------------------------------------------------------------

DANGEROUS_COMMANDS: List[str] = [
    "rm -rf",
    "del /f",
    "format",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
]

DANGEROUS_PYTHON: List[str] = [
    "os.system",
    "subprocess.call",
    "shutil.rmtree",
    "os.remove",
    "__import__('os').system",
]

# Env vars to strip from child processes (secrets, tokens, keys)
_SECRET_ENV_PATTERNS = [
    "KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
    "AUTH", "API_KEY", "PRIVATE",
]


def _is_secret_env(name: str) -> bool:
    """Check if an environment variable name looks like a secret.

    Args:
        name: Environment variable name.

    Returns:
        True if the name matches any secret pattern.
    """
    upper = name.upper()
    return any(pat in upper for pat in _SECRET_ENV_PATTERNS)


def _make_safe_env() -> dict:
    """Build a sanitised copy of the current environment.

    Removes all variables whose names look like secrets/tokens.

    Returns:
        Dict of safe environment variables.
    """
    safe = {}
    for k, v in os.environ.items():
        if not _is_secret_env(k):
            safe[k] = v
    # Ensure basic PATH is still present
    if "PATH" not in safe:
        safe["PATH"] = os.environ.get("PATH", "")
    if "SYSTEMROOT" not in safe and os.name == "nt":
        safe["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return safe


def _check_python_blocklist(code: str) -> str | None:
    """Check Python code against the dangerous patterns blocklist.

    Args:
        code: Python source code to check.

    Returns:
        The matched dangerous pattern, or None if safe.
    """
    for pattern in DANGEROUS_PYTHON:
        if pattern in code:
            return pattern
    return None


def _check_shell_blocklist(command: str) -> str | None:
    """Check a shell command against the dangerous commands blocklist.

    Args:
        command: Shell command string to check.

    Returns:
        The matched dangerous command, or None if safe.
    """
    lower = command.lower()
    for pattern in DANGEROUS_COMMANDS:
        if pattern.lower() in lower:
            return pattern
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_sandboxed_python(code: str, timeout: int = _DEFAULT_PYTHON_TIMEOUT) -> dict:
    """Run Python code in a sandboxed subprocess.

    Safety measures:
      - Timeout (kills after ``timeout`` seconds)
      - No network-related secrets in environment
      - Working directory is a temporary folder
      - Dangerous patterns are blocked before execution
      - stdout and stderr are captured

    Args:
        code: Python source code to execute.
        timeout: Max execution time in seconds (default 15).

    Returns:
        Dict with keys: ok, stdout, stderr, returncode, timed_out.
    """
    if not code or not code.strip():
        return {
            "ok": False,
            "stdout": "",
            "stderr": "No code provided",
            "returncode": -1,
            "timed_out": False,
        }

    # Block dangerous patterns
    blocked = _check_python_blocklist(code)
    if blocked:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Blocked: code contains dangerous pattern '{blocked}'",
            "returncode": -1,
            "timed_out": False,
        }

    # Clamp timeout
    timeout = max(1, min(timeout, 120))

    # Wrap the code so exceptions are caught gracefully
    wrapped = textwrap.dedent(f"""\
import sys
try:
{textwrap.indent(code.strip(), '    ')}
except Exception as _exc:
    print(f"ERROR: {{_exc}}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
""")

    tmpdir = tempfile.mkdtemp(prefix="bob_sandbox_")
    tmpfile = Path(tmpdir) / "sandbox_script.py"

    try:
        tmpfile.write_text(wrapped, encoding="utf-8")
        safe_env = _make_safe_env()

        result = subprocess.run(
            ["python", str(tmpfile)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmpdir,
            env=safe_env,
        )

        stdout = truncate_text(result.stdout, _MAX_OUTPUT)
        stderr = truncate_text(result.stderr, _MAX_OUTPUT)

        return {
            "ok": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired:
        logger.warning("Sandboxed Python timed out after %ds", timeout)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout}s",
            "returncode": -1,
            "timed_out": True,
        }
    except Exception as e:
        logger.error("Sandboxed Python execution error: %s", e, exc_info=True)
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e)[:300],
            "returncode": -1,
            "timed_out": False,
        }
    finally:
        # Clean up temp file (keep dir for potential debugging)
        try:
            tmpfile.unlink(missing_ok=True)
        except Exception:
            pass


def run_sandboxed_shell(command: str, timeout: int = _DEFAULT_SHELL_TIMEOUT) -> dict:
    """Run a shell command in a sandboxed subprocess.

    Safety measures:
      - Timeout (kills after ``timeout`` seconds)
      - No secrets in environment
      - Working directory is a temporary folder
      - Dangerous commands are blocked before execution

    Args:
        command: Shell command string to execute.
        timeout: Max execution time in seconds (default 10).

    Returns:
        Dict with keys: ok, stdout, stderr, returncode, timed_out.
    """
    if not command or not command.strip():
        return {
            "ok": False,
            "stdout": "",
            "stderr": "No command provided",
            "returncode": -1,
            "timed_out": False,
        }

    # Block dangerous commands
    blocked = _check_shell_blocklist(command)
    if blocked:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Blocked: command contains dangerous pattern '{blocked}'",
            "returncode": -1,
            "timed_out": False,
        }

    # Clamp timeout
    timeout = max(1, min(timeout, 60))

    tmpdir = tempfile.mkdtemp(prefix="bob_sandbox_")

    try:
        safe_env = _make_safe_env()

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmpdir,
            env=safe_env,
        )

        stdout = truncate_text(result.stdout, _MAX_OUTPUT)
        stderr = truncate_text(result.stderr, _MAX_OUTPUT)

        return {
            "ok": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired:
        logger.warning("Sandboxed shell timed out after %ds", timeout)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout}s",
            "returncode": -1,
            "timed_out": True,
        }
    except Exception as e:
        logger.error("Sandboxed shell execution error: %s", e, exc_info=True)
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e)[:300],
            "returncode": -1,
            "timed_out": False,
        }


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------

def tool_safe_python(args: dict) -> dict:
    """Tool wrapper for sandboxed Python execution.

    Args:
        args: Dict with keys ``code`` (str, required), ``timeout`` (int, optional).

    Returns:
        Sandboxed execution result dict.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    code = str(args.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "code is required"}
    if len(code) > 50000:
        return {"ok": False, "error": "code is too large (max 50000 chars)"}

    timeout = int(args.get("timeout", _DEFAULT_PYTHON_TIMEOUT))
    return run_sandboxed_python(code, timeout=timeout)


def tool_safe_shell(args: dict) -> dict:
    """Tool wrapper for sandboxed shell execution.

    Args:
        args: Dict with keys ``command`` (str, required), ``timeout`` (int, optional).

    Returns:
        Sandboxed execution result dict.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    command = str(args.get("command", "")).strip()
    if not command:
        return {"ok": False, "error": "command is required"}
    if len(command) > 10000:
        return {"ok": False, "error": "command is too long (max 10000 chars)"}

    timeout = int(args.get("timeout", _DEFAULT_SHELL_TIMEOUT))
    return run_sandboxed_shell(command, timeout=timeout)

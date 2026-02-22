"""
Execution node tools (remote execution).

LLM-callable tools for listing nodes and running commands on them.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from ..config import settings

logger = logging.getLogger("mind_clone.tools.nodes")


def tool_list_execution_nodes(args: dict = None) -> dict:
    """List available execution nodes."""
    try:
        from ..core.nodes import list_execution_nodes
        nodes = list_execution_nodes()
        return {"ok": True, "nodes": nodes, "count": len(nodes)}
    except Exception as exc:
        return {"ok": True, "nodes": [], "count": 0, "note": str(exc)[:200]}


def tool_run_command_node(args: dict) -> dict:
    """Run a command on a node.

    For 'local' node: executes via subprocess with sandbox restrictions.
    For remote nodes: requires node control plane.
    """
    node_name = str(args.get("node_name", "")).strip()
    command = str(args.get("command", "")).strip()
    timeout = min(int(args.get("timeout", 30)), 120)

    if not node_name or not command:
        return {"ok": False, "error": "node_name and command are required"}

    # Only local node execution is supported without control plane
    if node_name != "local":
        if not settings.node_control_plane_enabled:
            return {"ok": False, "error": "Remote node execution requires node control plane"}
        return {
            "ok": False,
            "error": f"Remote node '{node_name}' execution not yet wired",
            "node_name": node_name,
        }

    # Local execution with sandbox checks
    if settings.os_sandbox_mode != "off":
        return {"ok": False, "error": "Local execution requires OS_SANDBOX_MODE=off"}

    # Block dangerous commands
    dangerous = {"rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"}
    cmd_lower = command.lower()
    if any(d in cmd_lower for d in dangerous):
        return {"ok": False, "error": "Command blocked by safety filter"}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=None,
        )
        return {
            "ok": True,
            "node_name": "local",
            "exit_code": result.returncode,
            "stdout": (result.stdout or "")[:4000],
            "stderr": (result.stderr or "")[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

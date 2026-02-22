"""
Sandbox execution utilities with registry lifecycle management.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state import (
    SANDBOX_REGISTRY,
    SANDBOX_REGISTRY_LOCK,
    RUNTIME_STATE,
    increment_runtime_state,
)

logger = logging.getLogger("mind_clone.sandbox")

# Default TTL for sandbox entries (30 minutes)
SANDBOX_REGISTRY_MAX_AGE_SECONDS = 1800


def _sandbox_registry_key(owner_id: int, workspace_root: Path) -> str:
    """Build a unique key for the sandbox registry."""
    return f"{int(owner_id)}::{str(workspace_root.resolve(strict=False)).lower()}"


def sandbox_registry_touch(
    owner_id: int, workspace_root: Path, tool_name: str = ""
) -> Dict[str, Any]:
    """Get or create a sandbox entry, updating its last-used timestamp."""
    key = _sandbox_registry_key(owner_id, workspace_root)
    now_mono = time.monotonic()

    with SANDBOX_REGISTRY_LOCK:
        entry = SANDBOX_REGISTRY.get(key)
        if entry is None:
            from ..utils import utc_now_iso

            entry = {
                "key": key,
                "owner_id": owner_id,
                "workspace_root": str(workspace_root),
                "created_mono": now_mono,
                "created_at": utc_now_iso(),
                "last_used_mono": now_mono,
                "last_used_at": utc_now_iso(),
                "last_tool": tool_name,
            }
            SANDBOX_REGISTRY[key] = entry
            increment_runtime_state("sandbox_registry_created")
        else:
            from ..utils import utc_now_iso

            entry["last_used_mono"] = now_mono
            entry["last_used_at"] = utc_now_iso()
            entry["last_tool"] = tool_name or entry.get("last_tool", "")
            increment_runtime_state("sandbox_registry_reused")

    RUNTIME_STATE["sandbox_registry_count"] = len(SANDBOX_REGISTRY)
    RUNTIME_STATE["sandbox_registry_last_context"] = key
    return entry


def cleanup_sandbox_registry(
    max_age_seconds: int = SANDBOX_REGISTRY_MAX_AGE_SECONDS,
) -> int:
    """Remove stale sandbox entries older than max_age_seconds. Returns count removed."""
    now_mono = time.monotonic()
    removed = 0

    with SANDBOX_REGISTRY_LOCK:
        stale_keys = [
            k
            for k, v in SANDBOX_REGISTRY.items()
            if (now_mono - v.get("last_used_mono", 0)) > max_age_seconds
        ]
        for k in stale_keys:
            del SANDBOX_REGISTRY[k]
            removed += 1

    if removed:
        increment_runtime_state("sandbox_registry_cleanups")
        RUNTIME_STATE["sandbox_registry_count"] = len(SANDBOX_REGISTRY)
        logger.info("SANDBOX_REGISTRY_CLEANUP removed=%d", removed)

    return removed


def sandbox_registry_snapshot() -> List[Dict[str, Any]]:
    """Return a copy of all current sandbox entries."""
    with SANDBOX_REGISTRY_LOCK:
        return [dict(v) for v in SANDBOX_REGISTRY.values()]


# ---------------------------------------------------------------------------
# Basic sandbox execution (unchanged from original)
# ---------------------------------------------------------------------------

def run_in_sandbox(command: str, timeout: int = 30) -> Dict[str, Any]:
    """Run a command in a sandboxed environment."""
    import subprocess

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout", "stdout": "", "stderr": ""}
    except Exception as e:
        return {"ok": False, "error": str(e), "stdout": "", "stderr": ""}


def get_sandbox_profile(profile: str = "default") -> Dict[str, Any]:
    """Get sandbox profile configuration."""
    return {"name": profile, "strict": False}


def os_sandbox_enabled() -> bool:
    """Check if OS sandbox is enabled."""
    return False


def execution_sandbox_profile():
    """Get current execution sandbox profile."""
    return None


def _docker_executable():
    """Get docker executable path."""
    return None


def _normalize_os_sandbox_mode(mode):
    """Normalize OS sandbox mode string."""
    return mode if mode else "disabled"


def active_sandbox_containers():
    """List active sandbox containers."""
    return []


__all__ = [
    "run_in_sandbox",
    "get_sandbox_profile",
    "os_sandbox_enabled",
    "execution_sandbox_profile",
    "_docker_executable",
    "_normalize_os_sandbox_mode",
    "active_sandbox_containers",
    "cleanup_sandbox_registry",
    "sandbox_registry_touch",
    "sandbox_registry_snapshot",
]

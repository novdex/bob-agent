"""
Dynamic debug flags — runtime-toggleable feature flags without restart.

Flags can be set/cleared via API or programmatically. Each flag has a
name, value, description, and optional TTL (auto-expires after N seconds).

Usage:
    from mind_clone.core.debug_flags import set_debug_flag, get_debug_flag, list_debug_flags

    set_debug_flag("verbose_llm", True, ttl_seconds=300)
    if get_debug_flag("verbose_llm"):
        logger.debug("LLM request: %s", payload)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mind_clone.debug_flags")

_FLAGS_LOCK = threading.Lock()
_FLAGS: Dict[str, Dict[str, Any]] = {}

# Well-known flags with descriptions (registered on import)
KNOWN_FLAGS = {
    "verbose_llm": "Log full LLM request/response payloads",
    "verbose_tools": "Log full tool arguments and results",
    "verbose_memory": "Log memory retrieval details",
    "trace_agent_loop": "Trace each agent loop iteration",
    "trace_queue": "Trace queue enqueue/dequeue events",
    "trace_circuit_breaker": "Log circuit breaker state changes",
    "skip_tool_guard": "Bypass tool result guard (DANGEROUS — testing only)",
    "skip_ssrf_guard": "Bypass SSRF validation (DANGEROUS — testing only)",
    "force_hard_clear": "Force hard context clear on every turn",
    "dump_system_prompt": "Log the full system prompt on each LLM call",
}


def set_debug_flag(
    name: str,
    value: Any = True,
    *,
    description: str = "",
    ttl_seconds: Optional[int] = None,
) -> None:
    """Set a debug flag. If ttl_seconds is set, the flag auto-expires."""
    with _FLAGS_LOCK:
        _FLAGS[name] = {
            "value": value,
            "description": description or KNOWN_FLAGS.get(name, ""),
            "set_at": time.monotonic(),
            "expires_at": (time.monotonic() + ttl_seconds) if ttl_seconds else None,
        }
    logger.info("DEBUG_FLAG_SET name=%s value=%s ttl=%s", name, value, ttl_seconds)


def clear_debug_flag(name: str) -> bool:
    """Clear a debug flag. Returns True if it existed."""
    with _FLAGS_LOCK:
        existed = name in _FLAGS
        _FLAGS.pop(name, None)
    if existed:
        logger.info("DEBUG_FLAG_CLEAR name=%s", name)
    return existed


def get_debug_flag(name: str, default: Any = False) -> Any:
    """Get a debug flag value. Returns default if not set or expired."""
    with _FLAGS_LOCK:
        entry = _FLAGS.get(name)
        if entry is None:
            return default
        if entry.get("expires_at") and time.monotonic() > entry["expires_at"]:
            _FLAGS.pop(name, None)
            return default
        return entry["value"]


def list_debug_flags() -> List[Dict[str, Any]]:
    """List all active debug flags with metadata."""
    now = time.monotonic()
    result = []
    with _FLAGS_LOCK:
        expired_keys = []
        for name, entry in _FLAGS.items():
            if entry.get("expires_at") and now > entry["expires_at"]:
                expired_keys.append(name)
                continue
            age_seconds = int(now - entry.get("set_at", now))
            remaining = None
            if entry.get("expires_at"):
                remaining = max(0, int(entry["expires_at"] - now))
            result.append({
                "name": name,
                "value": entry["value"],
                "description": entry.get("description", ""),
                "age_seconds": age_seconds,
                "ttl_remaining": remaining,
            })
        for k in expired_keys:
            _FLAGS.pop(k, None)
    return result


def cleanup_expired_flags() -> int:
    """Remove expired flags. Returns count removed."""
    now = time.monotonic()
    removed = 0
    with _FLAGS_LOCK:
        expired = [
            k for k, v in _FLAGS.items()
            if v.get("expires_at") and now > v["expires_at"]
        ]
        for k in expired:
            _FLAGS.pop(k, None)
            removed += 1
    return removed

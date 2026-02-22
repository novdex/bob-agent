"""
Security and policy enforcement for Mind Clone Agent.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..config import settings
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.security")


# Tool policy profiles
TOOL_POLICY_PROFILES = {
    "safe": {
        "chat_tool_loops": 6,
        "task_tool_loops": 4,
        "max_run_command_timeout": 0,
        "max_execute_python_timeout": 0,
        "allow_write_file": False,
        "allow_any_write_path": False,
    },
    "balanced": {
        "chat_tool_loops": 10,
        "task_tool_loops": 6,
        "max_run_command_timeout": 30,
        "max_execute_python_timeout": 15,
        "allow_write_file": True,
        "allow_any_write_path": False,
    },
    "power": {
        "chat_tool_loops": 14,
        "task_tool_loops": 8,
        "max_run_command_timeout": 90,
        "max_execute_python_timeout": 45,
        "allow_write_file": True,
        "allow_any_write_path": True,
    },
}

# Execution sandbox profiles
EXECUTION_SANDBOX_PROFILES = {
    "strict": {
        "allow_run_command": False,
        "allow_execute_python": False,
        "max_command_chars": 220,
        "max_python_chars": 1200,
    },
    "default": {
        "allow_run_command": True,
        "allow_execute_python": True,
        "max_command_chars": 900,
        "max_python_chars": 10000,
    },
    "power": {
        "allow_run_command": True,
        "allow_execute_python": True,
        "max_command_chars": 2400,
        "max_python_chars": 24000,
    },
}

# Safe tool names that don't require approval
SAFE_TOOL_NAMES = {
    "search_web",
    "read_webpage",
    "read_file",
    "list_directory",
    "deep_research",
    "research_memory_search",
    "semantic_memory_search",
    "list_scheduled_jobs",
}

# Dangerous tools that require approval
DANGEROUS_TOOL_NAMES = {
    "run_command",
    "execute_python",
    "write_file",
    "browser_open",
}

# Secret patterns for redaction
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),  # API keys
    re.compile(r"Bearer\s+[a-zA-Z0-9_-]+", re.IGNORECASE),
    re.compile(r"token[:\s=]+[a-zA-Z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"password[:\s=]+[^\s&\"]+", re.IGNORECASE),
    re.compile(r"secret[:\s=]+[^\s&\"]+", re.IGNORECASE),
]


def get_tool_policy_profile() -> Dict[str, any]:
    """Get the current tool policy profile."""
    profile = settings.tool_policy_profile
    return TOOL_POLICY_PROFILES.get(profile, TOOL_POLICY_PROFILES["balanced"])


def get_execution_sandbox_profile() -> Dict[str, any]:
    """Get the current execution sandbox profile."""
    profile = settings.execution_sandbox_profile
    return EXECUTION_SANDBOX_PROFILES.get(profile, EXECUTION_SANDBOX_PROFILES["default"])


def check_tool_allowed(tool_name: str) -> Tuple[bool, Optional[str]]:
    """Check if a tool is allowed by current policy."""
    policy = get_tool_policy_profile()

    if tool_name in ("run_command", "execute_python"):
        sandbox = get_execution_sandbox_profile()
        if tool_name == "run_command" and not sandbox.get("allow_run_command"):
            return False, "run_command not allowed in current sandbox profile"
        if tool_name == "execute_python" and not sandbox.get("allow_execute_python"):
            return False, "execute_python not allowed in current sandbox profile"

    if tool_name == "write_file" and not policy.get("allow_write_file", True):
        return False, "write_file not allowed in current tool policy"

    return True, None


def requires_approval(tool_name: str, args: Dict) -> bool:
    """Check if a tool call requires approval."""
    if settings.approval_gate_mode == "off":
        return False

    if tool_name in SAFE_TOOL_NAMES:
        return False

    if settings.approval_gate_mode == "strict":
        return tool_name not in SAFE_TOOL_NAMES

    # balanced mode
    return tool_name in settings.approval_required_tools


def redact_secrets(text: str) -> Tuple[str, int]:
    """Redact secrets from text. Returns (redacted_text, hit_count)."""
    if not text:
        return text, 0

    redacted = text
    hits = 0

    for pattern in SECRET_PATTERNS:
        matches = list(pattern.finditer(redacted))
        for match in reversed(matches):
            start, end = match.span()
            redacted = redacted[:start] + settings.secret_redaction_token + redacted[end:]
            hits += 1

    return redacted, hits


def evaluate_workspace_diff_gate(tool_name: str, args: Dict) -> Dict:
    """Evaluate workspace diff gate for write operations."""
    if not settings.workspace_diff_gate_enabled or tool_name != "write_file":
        return {
            "blocked": False,
            "require_approval": False,
            "warned": False,
            "reason": "",
            "path": "",
            "changed_lines": 0,
        }

    file_path = str(args.get("file_path", "")).strip()
    if not file_path:
        return {
            "blocked": False,
            "require_approval": False,
            "warned": False,
            "reason": "",
            "path": "",
            "changed_lines": 0,
        }

    # Simple check: if file is large, require approval
    content = str(args.get("content", ""))
    lines = content.splitlines()
    changed_lines = len(lines)

    if changed_lines > settings.workspace_diff_max_changed_lines:
        reason = f"changed_lines>{settings.workspace_diff_max_changed_lines}"

        if settings.workspace_diff_gate_mode == "block":
            return {
                "blocked": True,
                "require_approval": False,
                "warned": False,
                "reason": reason,
                "path": file_path,
                "changed_lines": changed_lines,
            }
        elif settings.workspace_diff_gate_mode == "approval":
            return {
                "blocked": False,
                "require_approval": True,
                "warned": False,
                "reason": reason,
                "path": file_path,
                "changed_lines": changed_lines,
            }
        else:  # warn
            return {
                "blocked": False,
                "require_approval": False,
                "warned": True,
                "reason": reason,
                "path": file_path,
                "changed_lines": changed_lines,
            }

    return {
        "blocked": False,
        "require_approval": False,
        "warned": False,
        "reason": "",
        "path": file_path,
        "changed_lines": changed_lines,
    }


def enforce_host_exec_interlock(command: str) -> Tuple[bool, Optional[str]]:
    """Enforce host execution interlock for shell commands."""
    if not settings.host_exec_interlock_enabled:
        return True, None

    cmd_lower = command.strip().lower()

    # Check against allowlist
    for prefix in settings.host_exec_allowlist_prefixes:
        if cmd_lower.startswith(prefix.lower()):
            return True, None

    return (
        False,
        f"Command blocked by host exec interlock. Allowed prefixes: {settings.host_exec_allowlist_prefixes}",
    )


# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

import time
import threading
import ipaddress
from urllib.parse import urlparse

_CIRCUIT_BREAKER_LOCK = threading.Lock()
_CIRCUIT_BREAKER_STATE: Dict[str, Dict[str, any]] = {}

_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60


def _default_circuit_state() -> Dict[str, any]:
    return {
        "failures": 0,
        "last_failure": None,
        "opened_at": None,
        "closed": False,
    }


def circuit_allow_call(provider: str) -> Tuple[bool, str]:
    state = _ensure_circuit_state(provider)
    with _CIRCUIT_BREAKER_LOCK:
        if not state["closed"]:
            return True, ""

        opened_at = state.get("opened_at")
        if opened_at:
            elapsed = time.monotonic() - opened_at
            if elapsed >= _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
                state["closed"] = False
                state["failures"] = 0
                state["opened_at"] = None
                logger.info(f"Circuit breaker RESET for provider: {provider}")
                return True, ""

        return False, f"Circuit breaker OPEN for {provider}"

    return True, ""


def circuit_record_success(provider: str):
    state = _ensure_circuit_state(provider)
    with _CIRCUIT_BREAKER_LOCK:
        state["failures"] = 0
        state["closed"] = False
        state["opened_at"] = None


def circuit_record_failure(provider: str, error_message: str):
    state = _ensure_circuit_state(provider)
    with _CIRCUIT_BREAKER_LOCK:
        state["failures"] += 1
        state["last_failure"] = error_message

        if state["failures"] >= _CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            state["closed"] = True
            state["opened_at"] = time.monotonic()
            logger.warning(
                f"Circuit breaker OPENED for provider: {provider} (failures: {state['failures']})"
            )


def _ensure_circuit_state(provider: str) -> Dict[str, any]:
    with _CIRCUIT_BREAKER_LOCK:
        if provider not in _CIRCUIT_BREAKER_STATE:
            _CIRCUIT_BREAKER_STATE[provider] = _default_circuit_state()
        return _CIRCUIT_BREAKER_STATE[provider]


def circuit_snapshot() -> Dict[str, any]:
    with _CIRCUIT_BREAKER_LOCK:
        return {provider: dict(state) for provider, state in _CIRCUIT_BREAKER_STATE.items()}


# ============================================================================
# SSRF PROTECTION
# ============================================================================

import socket


def _ssrf_blocked_ip(ip_value: str) -> bool:
    """Check if an IP address should be blocked by SSRF rules."""
    try:
        ip = ipaddress.ip_address(ip_value)
    except Exception:
        return True  # Block invalid IPs (fail-closed)

    if ip.is_unspecified or ip.is_multicast:
        return True

    if settings.ssrf_block_localhost:
        if ip.is_loopback:
            return True
        if ip.is_link_local:
            return True

    if not settings.ssrf_allow_private_net:
        if ip.is_private:
            return True
        if ip.is_reserved:
            return True

    return False


def _normalize_domain(host: str) -> str:
    """Normalize a domain name: lowercase, strip www. prefix."""
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _parse_host_set(csv_string: str) -> Set[str]:
    """Parse comma-separated host list into a set of normalized domains."""
    return {
        _normalize_domain(item)
        for item in (csv_string or "").split(",")
        if item.strip()
    }


def validate_outbound_url(url: str) -> Tuple[bool, str]:
    """Validate a URL for outbound fetch (SSRF protection).

    11-step validation pipeline matching the monolith:
    1. Empty check  2. Parse  3. Scheme whitelist  4. Credential rejection
    5. Host extraction  6. Allowlist  7. Denylist  8. Hardcoded localhost block
    9. Guard-enabled gate  10. DNS resolution  11. IP validation
    """
    raw = str(url or "").strip()
    if not raw:
        return False, "URL is empty."

    try:
        parsed = urlparse(raw)
    except Exception:
        return False, "URL parsing failed."

    # Step 3: Scheme whitelist
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, "Only http/https URLs are allowed."

    # Step 4: Reject embedded credentials
    if parsed.username or parsed.password:
        return False, "URL credentials are not allowed."

    # Step 5: Extract and normalize host
    host = _normalize_domain(
        str(parsed.netloc or "").split("@")[-1].split(":")[0]
    )
    if not host:
        return False, "URL host is required."

    # Step 6: Allowlist (if configured)
    allow_hosts = _parse_host_set(settings.ssrf_allow_hosts)
    if allow_hosts and host not in allow_hosts and not any(
        host.endswith("." + x) for x in allow_hosts
    ):
        return False, f"Host '{host}' is not in SSRF allowlist."

    # Step 7: Denylist
    deny_hosts = _parse_host_set(settings.ssrf_deny_hosts)
    if host in deny_hosts or any(host.endswith("." + x) for x in deny_hosts):
        return False, f"Host '{host}' is denylisted."

    # Step 8: Hardcoded localhost block
    if host in ("localhost", "127.0.0.1", "::1") and settings.ssrf_block_localhost:
        return False, "Localhost access is blocked."

    # Step 9: If SSRF guard is disabled, allow (still enforced steps 1-8)
    if not settings.ssrf_guard_enabled:
        return True, ""

    # Step 10: DNS resolution with timeout
    timeout_sec = max(1, min(5, settings.ssrf_resolve_timeout_seconds))
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(float(timeout_sec))
        records = socket.getaddrinfo(host, None)
    except Exception as e:
        return False, f"DNS resolution failed for host '{host}': {truncate_text(str(e), 160)}"
    finally:
        socket.setdefaulttimeout(old_timeout)

    # Step 11: Validate all resolved IPs
    ips_checked: Set[str] = set()
    for rec in records:
        ip_val = str(rec[4][0])
        if ip_val in ips_checked:
            continue
        ips_checked.add(ip_val)
        if _ssrf_blocked_ip(ip_val):
            return False, f"Host '{host}' resolved to blocked IP '{ip_val}'."

    return True, ""


def apply_url_safety_guard(url: str, source: str = "web_fetch") -> Tuple[bool, str]:
    """Validate URL and log/count SSRF blocks."""
    ok, reason = validate_outbound_url(url)
    if not ok:
        from .state import increment_runtime_state
        increment_runtime_state("ssrf_blocked_requests")
        logger.warning(
            "SSRF_BLOCK source=%s url=%s reason=%s",
            source,
            truncate_text(str(url), 180),
            truncate_text(reason, 220),
        )
    return ok, reason


# ============================================================================
# TOOL RESULT GUARD
# ============================================================================

import json

TOOL_RESULT_MAX_CHARS = 10000


def guarded_tool_result_payload(
    tool_name: str, call_id: str, result_obj
) -> Tuple[str, bool]:
    """Validate and truncate a tool result before it enters the LLM context.

    Returns ``(json_payload, was_truncated)``.

    Guards against:
    - Non-dict results (wrapped with error marker)
    - Missing ``ok`` field (set to False)
    - Empty/missing call_id (flagged)
    - JSON encode failures (replaced with error)
    - Payloads > 10 KB (truncated)
    - Embedded secrets (redacted via ``redact_secret_data``)
    """
    from .state import increment_runtime_state
    from .secrets import redact_secret_data

    safe_obj: dict
    if isinstance(result_obj, dict):
        safe_obj = dict(result_obj)
    else:
        safe_obj = {
            "ok": False,
            "error": "TOOL_RESULT_NON_DICT",
            "value": truncate_text(str(result_obj), 400),
        }
        increment_runtime_state("session_tool_result_guard_blocks")

    if "ok" not in safe_obj:
        safe_obj["ok"] = False

    if not str(call_id or "").strip():
        safe_obj["ok"] = False
        safe_obj["error"] = "TOOL_RESULT_MISSING_CALL_ID"
        increment_runtime_state("session_tool_result_guard_blocks")

    # Redact secrets from the result
    if settings.secret_guardrail_enabled:
        safe_obj = redact_secret_data(safe_obj)

    try:
        payload = json.dumps(safe_obj, ensure_ascii=False)
    except Exception:
        payload = json.dumps(
            {"ok": False, "error": "TOOL_RESULT_JSON_ENCODE_FAIL"},
            ensure_ascii=False,
        )
        increment_runtime_state("session_tool_result_guard_blocks")

    truncated = False
    if len(payload) > TOOL_RESULT_MAX_CHARS:
        payload = payload[:TOOL_RESULT_MAX_CHARS] + "...[TRUNCATED]"
        truncated = True
        increment_runtime_state("session_tool_result_guard_truncations")

    return payload, truncated

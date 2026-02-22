"""
Security audit automation — programmatic security checks.

Runs the same checks as ``bob_security.py`` but callable from code
or via API endpoint. Returns structured results for monitoring.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ..config import settings

logger = logging.getLogger("mind_clone.security_audit")


def check_ssrf_protection() -> Dict[str, Any]:
    """Verify SSRF protection is enabled and configured."""
    issues = []
    if not settings.ssrf_guard_enabled:
        issues.append("SSRF guard is disabled")
    if settings.ssrf_allow_private_net:
        issues.append("Private network access is allowed")
    if not settings.ssrf_block_localhost:
        issues.append("Localhost access is not blocked")

    return {
        "name": "SSRF Protection",
        "passed": len(issues) == 0,
        "issues": issues,
        "config": {
            "ssrf_guard_enabled": settings.ssrf_guard_enabled,
            "ssrf_allow_private_net": settings.ssrf_allow_private_net,
            "ssrf_block_localhost": settings.ssrf_block_localhost,
        },
    }


def check_approval_gate() -> Dict[str, Any]:
    """Verify approval gate is not disabled."""
    mode = str(settings.approval_gate_mode or "balanced")
    issues = []
    if mode == "off":
        issues.append("Approval gate is disabled — dangerous tools need no approval")

    return {
        "name": "Approval Gate",
        "passed": mode != "off",
        "issues": issues,
        "config": {"approval_gate_mode": mode},
    }


def check_secret_guardrail() -> Dict[str, Any]:
    """Verify secret redaction is enabled."""
    enabled = settings.secret_guardrail_enabled
    issues = []
    if not enabled:
        issues.append("Secret guardrail is disabled — API keys may leak")

    return {
        "name": "Secret Guardrail",
        "passed": enabled,
        "issues": issues,
        "config": {"secret_guardrail_enabled": enabled},
    }


def check_sandbox_profile() -> Dict[str, Any]:
    """Verify sandbox isn't in power mode without explicit full-power."""
    profile = str(settings.execution_sandbox_profile or "default")
    full_power = getattr(settings, "bob_full_power_enabled", False)
    issues = []
    if profile == "power" and not full_power:
        issues.append("Sandbox is in 'power' mode without BOB_FULL_POWER_ENABLED")

    return {
        "name": "Sandbox Profile",
        "passed": len(issues) == 0,
        "issues": issues,
        "config": {
            "execution_sandbox_profile": profile,
            "bob_full_power_enabled": full_power,
        },
    }


def check_tool_policy() -> Dict[str, Any]:
    """Verify tool policy profile is appropriate."""
    profile = str(settings.tool_policy_profile or "balanced")
    issues = []
    if profile == "power":
        issues.append("Tool policy is 'power' — all tools unrestricted")

    return {
        "name": "Tool Policy",
        "passed": profile != "power",
        "issues": issues,
        "config": {"tool_policy_profile": profile},
    }


def check_workspace_diff_gate() -> Dict[str, Any]:
    """Verify workspace diff gate is enabled."""
    enabled = getattr(settings, "workspace_diff_gate_enabled", True)
    issues = []
    if not enabled:
        issues.append("Workspace diff gate is disabled — large writes unguarded")

    return {
        "name": "Workspace Diff Gate",
        "passed": enabled,
        "issues": issues,
        "config": {"workspace_diff_gate_enabled": enabled},
    }


def check_ops_auth() -> Dict[str, Any]:
    """Verify ops endpoints require authentication."""
    token = str(getattr(settings, "ops_auth_token", "") or "")
    issues = []
    if not token:
        issues.append("Ops auth token not set — admin endpoints are unprotected")

    return {
        "name": "Ops Auth",
        "passed": bool(token),
        "issues": issues,
    }


def check_host_exec_interlock() -> Dict[str, Any]:
    """Verify host exec interlock is enabled."""
    enabled = settings.host_exec_interlock_enabled
    issues = []
    if not enabled:
        issues.append("Host exec interlock disabled — arbitrary commands allowed")

    return {
        "name": "Host Exec Interlock",
        "passed": enabled,
        "issues": issues,
        "config": {"host_exec_interlock_enabled": enabled},
    }


# Registry of all security checks
ALL_CHECKS = [
    check_ssrf_protection,
    check_approval_gate,
    check_secret_guardrail,
    check_sandbox_profile,
    check_tool_policy,
    check_workspace_diff_gate,
    check_ops_auth,
    check_host_exec_interlock,
]


def run_security_audit(check_names: List[str] | None = None) -> Dict[str, Any]:
    """Run all or selected security checks. Returns structured report."""
    results = []
    for check_fn in ALL_CHECKS:
        name = check_fn.__name__.replace("check_", "")
        if check_names and name not in check_names:
            continue
        try:
            result = check_fn()
            results.append(result)
        except Exception as e:
            results.append({
                "name": name,
                "passed": False,
                "issues": [f"Check failed: {str(e)[:200]}"],
            })

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    failed_names = [r["name"] for r in results if not r.get("passed")]

    report = {
        "ok": passed == total,
        "score": f"{passed}/{total}",
        "passed": passed,
        "total": total,
        "checks": results,
    }
    if failed_names:
        report["failed"] = failed_names

    logger.info("SECURITY_AUDIT score=%d/%d failed=%s", passed, total, failed_names)
    return report

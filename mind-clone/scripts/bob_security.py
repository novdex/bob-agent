#!/usr/bin/env python3
"""bob-security: Security audit scanner for Bob.

Checks 8 security layers without needing Bob to be running.
Scans the modular package source at src/mind_clone/.

Usage:
    python bob_security.py                # Run all 8 checks
    python bob_security.py --check ssrf   # Run single check
"""

import argparse
import importlib.util
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
MODULAR_DIR = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")


def read_modular_source():
    """Read all Python source files from the modular package as concatenated text."""
    parts = []
    for root, _dirs, files in os.walk(MODULAR_DIR):
        for fname in sorted(files):
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        parts.append(f.read())
                except Exception:
                    continue
    return "\n".join(parts)


def check_ssrf(src):
    """Check SSRF protection is present."""
    has_validator = "validate_outbound_url" in src
    has_private_ip_check = re.search(r"(127\.0\.0\.1|169\.254|10\.\d|192\.168|0\.0\.0\.0)", src) is not None
    has_url_parse = "urlparse" in src or "urllib.parse" in src

    issues = []
    if not has_validator:
        issues.append("No validate_outbound_url() function found")
    if not has_private_ip_check:
        issues.append("No private IP range blocking detected")
    if not has_url_parse:
        issues.append("No URL parsing imports found")

    passed = has_validator and has_private_ip_check
    return passed, issues


def check_approval_gate(src):
    """Check approval gate configuration."""
    match = re.search(r'APPROVAL_GATE_MODE\s*=\s*["\']?(\w+)', src)
    mode = match.group(1) if match else "unknown"

    issues = []
    if mode == "off":
        issues.append(f"Approval gate is OFF — dangerous tools run without approval")
    elif mode == "unknown":
        issues.append("Could not detect APPROVAL_GATE_MODE")

    has_approval_flow = "create_approval_request" in src
    if not has_approval_flow:
        issues.append("No approval request flow found")

    passed = mode in ("balanced", "strict") and has_approval_flow
    return passed, issues


def check_secret_guardrail(src):
    """Check secret redaction is enabled."""
    match = re.search(r'SECRET_GUARDRAIL_ENABLED\s*=\s*_env_flag\([^,]+,\s*(True|False)', src)
    default = match.group(1) if match else "unknown"

    has_redaction = "SECRET_REDACTION_TOKEN" in src
    has_pattern_matching = "secret" in src.lower() and "redact" in src.lower()

    issues = []
    if default == "False":
        issues.append("Secret guardrail defaults to disabled")
    if not has_redaction:
        issues.append("No redaction token configured")

    passed = default == "True" and has_redaction
    return passed, issues


def check_sandbox_profile(src):
    """Check sandbox not overly permissive."""
    match = re.search(r'EXECUTION_SANDBOX_PROFILE_RAW\s*=.*?"(\w+)"', src)
    default_profile = match.group(1) if match else "unknown"

    full_power_match = re.search(r'BOB_FULL_POWER_ENABLED\s*=\s*_env_flag\([^,]+,\s*(True|False)', src)
    full_power_default = full_power_match.group(1) if full_power_match else "unknown"

    issues = []
    if default_profile == "power":
        issues.append("Sandbox defaults to 'power' profile (least restrictive)")
    if full_power_default == "True":
        issues.append("BOB_FULL_POWER_ENABLED defaults to True")

    passed = default_profile != "power" and full_power_default != "True"
    return passed, issues


def check_custom_tool_safety(src):
    """Check custom tool code safety scanning."""
    deny_patterns = ["rm -rf", "shutil.rmtree", "os.remove", "__import__", "subprocess.call"]
    has_safety_check = "_custom_tool_code_safety_check" in src or "code_safety" in src.lower()
    has_deny_patterns = sum(1 for p in deny_patterns if p in src)

    issues = []
    if not has_safety_check:
        issues.append("No custom tool safety check function found")
    if has_deny_patterns < 2:
        issues.append(f"Only {has_deny_patterns} deny patterns found (expected 3+)")

    # Check for custom tools directory
    gen_tools_dir = os.path.join(MIND_CLONE_DIR, "persist", "generated_tools")
    if os.path.isdir(gen_tools_dir):
        tool_files = [f for f in os.listdir(gen_tools_dir) if f.endswith(".py")]
        for tf in tool_files[:10]:
            content = ""
            try:
                with open(os.path.join(gen_tools_dir, tf), "r") as fh:
                    content = fh.read()
            except Exception:
                continue
            for dp in deny_patterns:
                if dp in content:
                    issues.append(f"Custom tool '{tf}' contains deny pattern: {dp}")

    passed = has_safety_check and has_deny_patterns >= 2 and not any("Custom tool" in i for i in issues)
    return passed, issues


def check_tool_policy(src):
    """Check tool policy profile."""
    match = re.search(r'TOOL_POLICY_PROFILE_RAW\s*=.*?"(\w+)"', src)
    default_profile = match.group(1) if match else "unknown"

    has_safe_tools = "SAFE_TOOL_NAMES" in src
    has_policy_blocks = "tool_policy_blocks" in src

    issues = []
    if default_profile == "power":
        issues.append("Tool policy defaults to 'power' (all tools unrestricted)")
    if not has_safe_tools:
        issues.append("No SAFE_TOOL_NAMES whitelist found")

    passed = default_profile in ("safe", "balanced") and has_safe_tools
    return passed, issues


def check_workspace_diff_gate(src):
    """Check workspace diff gate for write protection."""
    match = re.search(r'WORKSPACE_DIFF_GATE_ENABLED\s*=\s*_env_flag\([^,]+,\s*(True|False)', src)
    default = match.group(1) if match else "unknown"

    mode_match = re.search(r'WORKSPACE_DIFF_GATE_MODE\s*=.*?"(\w+)"', src)
    mode = mode_match.group(1) if mode_match else "unknown"

    issues = []
    if default == "False":
        issues.append("Workspace diff gate defaults to disabled")
    if mode == "warn":
        issues.append("Diff gate mode is 'warn' only (doesn't block)")

    passed = default == "True" and mode in ("approval", "block")
    return passed, issues


def check_ops_auth(src):
    """Check ops endpoints require authentication."""
    has_ops_auth = "OPS_AUTH_TOKEN" in src
    has_ops_enabled = "ops_auth_enabled" in src

    match = re.search(r'OPS_AUTH_ENABLED\s*=\s*_env_flag\([^,]+,\s*(True|False)', src)
    default = match.group(1) if match else "unknown"

    issues = []
    if not has_ops_auth:
        issues.append("No OPS_AUTH_TOKEN configuration found")
    if default == "False":
        issues.append("Ops auth defaults to disabled — admin endpoints are unprotected")

    passed = has_ops_auth and default != "False"
    return passed, issues


ALL_CHECKS = {
    "ssrf": ("SSRF Protection", check_ssrf),
    "approval": ("Approval Gate", check_approval_gate),
    "secret": ("Secret Guardrail", check_secret_guardrail),
    "sandbox": ("Sandbox Profile", check_sandbox_profile),
    "custom_tools": ("Custom Tool Safety", check_custom_tool_safety),
    "policy": ("Tool Policy", check_tool_policy),
    "diff_gate": ("Workspace Diff Gate", check_workspace_diff_gate),
    "ops_auth": ("Ops Auth", check_ops_auth),
}


def main():
    parser = argparse.ArgumentParser(
        description="bob-security: Security audit scanner",
        epilog="Examples:\n"
               "  python bob_security.py              # all checks\n"
               "  python bob_security.py --check ssrf  # single check\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", choices=list(ALL_CHECKS.keys()), help="Run single check")
    args = parser.parse_args()

    if not os.path.isdir(MODULAR_DIR):
        print(f"Error: Modular package not found at {MODULAR_DIR}")
        sys.exit(1)

    src = read_modular_source()

    print("=" * 60)
    print("  bob-security: Security Audit")
    print("=" * 60)
    print()

    checks_to_run = {args.check: ALL_CHECKS[args.check]} if args.check else ALL_CHECKS
    results = []

    for key, (name, fn) in checks_to_run.items():
        passed, issues = fn(src)
        mark = "+" if passed else "x"
        status = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}: {status}")
        if issues:
            for issue in issues:
                print(f"      - {issue}")
        results.append((name, passed))

    # Summary
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    print()
    print("-" * 60)
    print(f"  Security Score: {passed_count}/{total}")
    if passed_count == total:
        print("  Status: ALL CHECKS PASSED")
    else:
        failed = [n for n, p in results if not p]
        print(f"  Status: ISSUES FOUND — {', '.join(failed)}")
    print("-" * 60)

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()

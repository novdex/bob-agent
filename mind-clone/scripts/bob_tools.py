#!/usr/bin/env python3
"""bob-tools: Tool usage and policy diagnostics for Bob.

Inspect tool registry, policy profiles, performance stats,
closed-loop feedback, and custom tools.

Usage:
    python bob_tools.py list                    # List registered tools
    python bob_tools.py policy                  # Show policy profile
    python bob_tools.py performance [--days 7]  # Tool performance stats
    python bob_tools.py feedback                # Closed-loop feedback status
    python bob_tools.py custom                  # List custom/generated tools
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)

DEFAULT_URL = "http://localhost:8000"

DB_SEARCH_PATHS = [
    os.path.join(MIND_CLONE_DIR, "data", "mind_clone.db"),
    os.path.expanduser("~/.mind-clone/mind_clone.db"),
    os.path.join(MIND_CLONE_DIR, "mind_clone.db"),
]


def find_db(db_path=None):
    if db_path:
        return db_path if os.path.exists(db_path) else None
    env_path = os.environ.get("MIND_CLONE_DB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    for path in DB_SEARCH_PATHS:
        if os.path.exists(path):
            return path
    return None


def fetch_json(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, str(e)


def read_env_value(key):
    env_path = os.path.join(MIND_CLONE_DIR, ".env")
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line[len(key) + 1:].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def extract_tool_names_from_source():
    """Extract tool names from TOOL_DISPATCH in source code."""
    tools = set()

    def _extract_dispatch_block(content):
        """Find TOOL_DISPATCH = { ... } and extract only keys from that dict."""
        idx = content.find("TOOL_DISPATCH")
        if idx < 0:
            return
        # Find the opening brace
        brace_start = content.find("{", idx)
        if brace_start < 0:
            return
        # Find matching closing brace (simple depth counting)
        depth = 1
        pos = brace_start + 1
        while pos < len(content) and depth > 0:
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        block = content[brace_start:pos]
        # Extract "tool_name": patterns — keys that map to tool_ functions
        for match in re.finditer(r'"([a-z_]+)"\s*:\s*tool_', block):
            tools.add(match.group(1))

    # Try modular registry first
    registry_path = os.path.join(MIND_CLONE_DIR, "src", "mind_clone", "tools", "registry.py")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8", errors="replace") as f:
                _extract_dispatch_block(f.read())
        except Exception:
            pass

    # If no tools found from modular registry, scan all tool files
    if not tools:
        tools_dir = os.path.join(MIND_CLONE_DIR, "src", "mind_clone", "tools")
        if os.path.isdir(tools_dir):
            for fname in os.listdir(tools_dir):
                if fname.endswith(".py") and fname != "__init__.py":
                    try:
                        with open(os.path.join(tools_dir, fname), "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        for match in re.finditer(r'def tool_([a-z_]+)\(', content):
                            tools.add(match.group(1))
                    except Exception:
                        pass

    return sorted(tools)


def extract_safe_dangerous():
    """Extract SAFE_TOOL_NAMES and DANGEROUS_TOOL_NAMES from security.py."""
    safe = set()
    dangerous = set()

    security_path = os.path.join(MIND_CLONE_DIR, "src", "mind_clone", "core", "security.py")
    if os.path.exists(security_path):
        try:
            with open(security_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Extract SAFE_TOOL_NAMES
            safe_match = re.search(r'SAFE_TOOL_NAMES\s*=\s*\{([^}]+)\}', content, re.DOTALL)
            if safe_match:
                for m in re.finditer(r'"([a-z_]+)"', safe_match.group(1)):
                    safe.add(m.group(1))

            # Extract DANGEROUS_TOOL_NAMES
            danger_match = re.search(r'DANGEROUS_TOOL_NAMES\s*=\s*\{([^}]+)\}', content, re.DOTALL)
            if danger_match:
                for m in re.finditer(r'"([a-z_]+)"', danger_match.group(1)):
                    dangerous.add(m.group(1))
        except Exception:
            pass

    return safe, dangerous


def cmd_list(args):
    """List registered tools."""
    print("=" * 60)
    print("  bob-tools: Tool Registry")
    print("=" * 60)
    print()

    tools = extract_tool_names_from_source()
    safe, dangerous = extract_safe_dangerous()

    if not tools:
        print("  Could not extract tools from source code.")
        print("  Checked: src/mind_clone/tools/registry.py")
        print("           src/mind_clone/tools/*.py")
        return

    for tool in tools:
        if tool in dangerous:
            label = "[approval]"
        elif tool in safe:
            label = "[safe]"
        else:
            label = "(standard)"
        print(f"  {tool:<30s} {label}")

    print(f"\n  Total: {len(tools)} tools ({len(safe)} safe, {len(dangerous)} approval-required)")

    # Runtime info
    runtime, _ = fetch_json(f"{args.url}/status/runtime")
    if runtime:
        custom = runtime.get("custom_tools_loaded", 0)
        plugin = runtime.get("plugin_tools_loaded", 0)
        if custom or plugin:
            print(f"  Custom tools loaded: {custom}")
            print(f"  Plugin tools loaded: {plugin}")
    print()


def cmd_policy(args):
    """Show current policy profile."""
    print("=" * 60)
    print("  bob-tools: Policy Profile")
    print("=" * 60)
    print()

    profile = read_env_value("TOOL_POLICY_PROFILE") or "balanced"
    print(f"  Active Profile:    {profile}")

    full_power = read_env_value("BOB_FULL_POWER_ENABLED") or "false"
    full_scope = read_env_value("BOB_FULL_POWER_SCOPE") or ""
    sandbox = read_env_value("OS_SANDBOX_MODE") or "off"

    print(f"  Full Power:        {full_power}")
    if full_power.lower() == "true":
        print(f"  Full Power Scope:  {full_scope or '(all)'}")
    print(f"  Sandbox Mode:      {sandbox}")

    # Runtime
    runtime, _ = fetch_json(f"{args.url}/status/runtime")
    if runtime:
        print(f"\n  --- Runtime ---")
        print(f"  Policy blocks:     {runtime.get('tool_policy_blocks', 0)}")
        print(f"  Approval required: {runtime.get('approval_required_count', 0)}")
        print(f"  Approval pending:  {runtime.get('approval_pending_count', 0)}")

    # Policy profiles from source
    security_path = os.path.join(MIND_CLONE_DIR, "src", "mind_clone", "core", "security.py")
    if os.path.exists(security_path):
        print(f"\n  Available profiles: safe, balanced, power")
        print(f"  Set via: TOOL_POLICY_PROFILE in .env")
    print()


def cmd_performance(args):
    """Tool performance stats from DB."""
    print("=" * 60)
    print("  bob-tools: Tool Performance")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    days = args.days if hasattr(args, "days") and args.days else 7
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "tool_performance_logs" not in tables:
        print("  Table 'tool_performance_logs' not found.")
        conn.close()
        return

    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(tool_performance_logs)").fetchall()]

        success_col = "success" if "success" in cols else None
        duration_col = "duration_ms" if "duration_ms" in cols else None
        error_col = "error_category" if "error_category" in cols else None

        rows = conn.execute(
            f"SELECT tool_name, COUNT(*) as calls"
            f"{', SUM(CASE WHEN ' + success_col + ' THEN 1 ELSE 0 END)' if success_col else ''}"
            f"{', AVG(' + duration_col + ')' if duration_col else ''}"
            f" FROM tool_performance_logs"
            f" WHERE created_at > datetime('now', '-{int(days)} days')"
            f" GROUP BY tool_name ORDER BY COUNT(*) DESC"
        ).fetchall()

        if not rows:
            print(f"  No tool usage in last {days} days.")
            conn.close()
            return

        print(f"  Period: last {days} days\n")

        header = f"  {'Tool':<25s} {'Calls':>6s}"
        if success_col:
            header += f"  {'Success%':>8s}"
        if duration_col:
            header += f"  {'Avg(ms)':>8s}"
        print(header)
        print(f"  {'-' * 25} {'-' * 6}" +
              (f"  {'-' * 8}" if success_col else "") +
              (f"  {'-' * 8}" if duration_col else ""))

        total_calls = 0
        total_success = 0
        for row in rows:
            idx = 0
            tool = row[idx]; idx += 1
            calls = row[idx]; idx += 1
            total_calls += calls

            line = f"  {tool:<25s} {calls:>6d}"
            if success_col:
                successes = row[idx]; idx += 1
                total_success += successes
                rate = (successes / calls * 100) if calls > 0 else 0
                line += f"  {rate:>7.1f}%"
            if duration_col:
                avg_ms = row[idx]; idx += 1
                line += f"  {avg_ms:>8.0f}" if avg_ms else f"  {'n/a':>8s}"
            print(line)

        print(f"\n  Overall: {total_calls} calls", end="")
        if success_col and total_calls > 0:
            overall_rate = total_success / total_calls * 100
            print(f", {overall_rate:.1f}% success rate", end="")
        print()

        # Error breakdown
        if error_col:
            errors = conn.execute(
                f"SELECT error_category, COUNT(*) FROM tool_performance_logs "
                f"WHERE created_at > datetime('now', '-{int(days)} days') "
                f"AND {success_col} = 0 AND error_category IS NOT NULL "
                f"GROUP BY error_category ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
            if errors:
                print(f"\n  Error categories:")
                for cat, count in errors:
                    print(f"    {cat}: {count}")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def cmd_feedback(args):
    """Closed-loop feedback status."""
    print("=" * 60)
    print("  bob-tools: Closed-Loop Feedback")
    print("=" * 60)
    print()

    enabled = read_env_value("CLOSED_LOOP_ENABLED")
    print(f"  Enabled:           {enabled or 'true (default)'}")

    warn_thresh = read_env_value("CLOSED_LOOP_TOOL_WARN_THRESHOLD") or "40"
    block_thresh = read_env_value("CLOSED_LOOP_TOOL_BLOCK_THRESHOLD") or "15"
    print(f"  Warn threshold:    {warn_thresh}%")
    print(f"  Block threshold:   {block_thresh}%")

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if runtime:
        print(f"\n  --- Runtime Metrics ---")
        cl_keys = sorted(k for k in runtime if k.startswith("cl_"))
        for key in cl_keys:
            print(f"  {key}: {runtime[key]}")

        # Diagnosis
        print(f"\n  --- Diagnosis ---")
        warned = int(runtime.get("cl_tools_warned", 0))
        blocked = int(runtime.get("cl_tools_blocked", 0))
        strategies_blocked = int(runtime.get("cl_strategies_blocked", 0))

        if blocked > 0:
            print(f"  [x] {blocked} tool(s) BLOCKED by feedback loop")
        elif warned > 0:
            print(f"  [-] {warned} tool(s) warned (low success rate)")
        else:
            print("  [+] No tools warned or blocked")

        if strategies_blocked > 0:
            print(f"  [-] {strategies_blocked} dead-letter strategies blocked")
        else:
            print("  [+] No strategies blocked")

        closed = int(runtime.get("cl_loops_closed_total", 0))
        print(f"  [+] Total feedback loops closed: {closed}")
    else:
        print(f"\n  Bob not running: {err}")
    print()


def cmd_custom(args):
    """List custom/generated tools."""
    print("=" * 60)
    print("  bob-tools: Custom Tools")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        # Try runtime only
        runtime, err = fetch_json(f"{args.url}/status/runtime")
        if runtime:
            print(f"  Custom tools loaded:  {runtime.get('custom_tools_loaded', 0)}")
            print(f"  Custom tools created: {runtime.get('custom_tools_created', 0)}")
            print(f"  Gap hints:            {runtime.get('custom_tool_gap_hints', 0)}")
            print(f"  Plugin tools loaded:  {runtime.get('plugin_tools_loaded', 0)}")
        else:
            print(f"  No DB and Bob not running.")
        print()
        return

    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "generated_tools" not in tables:
        print("  Table 'generated_tools' not found.")
        print("  (No custom tools have been created yet)")
        conn.close()
        return

    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(generated_tools)").fetchall()]
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM generated_tools ORDER BY rowid DESC"
        ).fetchall()

        if not rows:
            print("  No custom tools found.")
            conn.close()
            return

        for row in rows:
            data = dict(zip(cols, row))
            enabled_str = "enabled" if data.get("enabled") else "DISABLED"
            test_str = "passed" if data.get("test_passed") else "FAILED"
            print(f"  {data.get('tool_name', '?')} [{enabled_str}] test={test_str}")
            if data.get("description"):
                print(f"    {str(data['description'])[:100]}")
            print(f"    usage_count={data.get('usage_count', 0)}", end="")
            if data.get("last_error"):
                print(f"  last_error={str(data['last_error'])[:60]}", end="")
            print()
            print()

        print(f"  Total: {len(rows)} custom tool(s)")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-tools: Tool diagnostics for Bob",
        epilog="Examples:\n"
               "  python bob_tools.py list\n"
               "  python bob_tools.py policy\n"
               "  python bob_tools.py performance --days 30\n"
               "  python bob_tools.py feedback\n"
               "  python bob_tools.py custom\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["list", "policy", "performance", "feedback", "custom"],
                        help="Command to run")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--days", type=int, default=7, help="Days for performance report (default: 7)")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    commands = {
        "list": cmd_list,
        "policy": cmd_policy,
        "performance": cmd_performance,
        "feedback": cmd_feedback,
        "custom": cmd_custom,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

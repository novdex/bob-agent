#!/usr/bin/env python3
"""bob-llm: LLM failover chain diagnostics for Bob.

Check API key configuration, circuit breaker states, provider latency,
and usage costs.

Usage:
    python bob_llm.py status                # LLM subsystem overview
    python bob_llm.py keys                  # Check configured API keys
    python bob_llm.py ping                  # Ping each LLM provider
    python bob_llm.py circuit               # Circuit breaker states
    python bob_llm.py cost [--days 7]       # Usage cost summary
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)

DEFAULT_URL = "http://localhost:8000"

DB_SEARCH_PATHS = [
    os.path.join(MIND_CLONE_DIR, "data", "mind_clone.db"),
    os.path.expanduser("~/.mind-clone/mind_clone.db"),
    os.path.join(MIND_CLONE_DIR, "mind_clone.db"),
]

FAILOVER_CHAIN = [
    {"name": "Kimi", "env_key": "KIMI_API_KEY", "ping_url": "https://api.moonshot.cn/v1/models"},
    {"name": "Gemini", "env_key": "GEMINI_API_KEY", "ping_url": None},
    {"name": "OpenAI", "env_key": "OPENAI_API_KEY", "ping_url": "https://api.openai.com/v1/models"},
    {"name": "Anthropic", "env_key": "ANTHROPIC_API_KEY", "ping_url": "https://api.anthropic.com/v1/models"},
]


def find_db(db_path=None):
    if db_path:
        if os.path.exists(db_path):
            return db_path
        return None
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
    """Read a value from .env file (never prints secrets)."""
    env_path = os.path.join(MIND_CLONE_DIR, ".env")
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    val = line[len(key) + 1:].strip().strip('"').strip("'")
                    return val
    except Exception:
        pass
    return None


def mask_secret(value):
    if not value or len(value) < 10:
        return "(too short)"
    return f"{value[:4]}...{value[-4:]}"


def key_status(env_key):
    """Check if a key is configured, placeholder, or missing."""
    val = read_env_value(env_key)
    if not val:
        return "missing", None
    placeholders = ["your_", "_here", "placeholder", "changeme", "xxx"]
    if any(p in val.lower() for p in placeholders):
        return "placeholder", val
    return "configured", val


def cmd_status(args):
    """LLM subsystem overview."""
    print("=" * 60)
    print("  bob-llm: LLM Diagnostics")
    print("=" * 60)

    # Runtime data
    runtime, err = fetch_json(f"{args.url}/status/runtime")

    print("\n  --- Configuration ---")
    if runtime:
        print(f"  Primary Model:     {runtime.get('llm_primary_model', 'unknown')}")
        print(f"  Failover Enabled:  {runtime.get('llm_failover_enabled', 'unknown')}")
    else:
        print(f"  (Bob not running: {err})")

    # Failover chain with key status
    print("\n  --- Failover Chain ---")
    for i, provider in enumerate(FAILOVER_CHAIN, 1):
        status, val = key_status(provider["env_key"])
        key_str = f"key={status}"
        if status == "configured":
            key_str += f" ({mask_secret(val)})"

        cb_state = "n/a"
        if runtime:
            breakers = runtime.get("circuit_breakers") or {}
            for name, cb in breakers.items():
                if provider["name"].lower() in name.lower():
                    cb_state = cb.get("state", "?")
                    break

        print(f"  [{i}] {provider['name']:<12s} {key_str:<35s} circuit={cb_state}")

    # Runtime metrics
    if runtime:
        print("\n  --- Runtime ---")
        print(f"  Last Model Used:   {runtime.get('llm_last_model_used', 'none')}")
        print(f"  Last Error:        {runtime.get('llm_last_error') or '(none)'}")
        print(f"  Failover Count:    {runtime.get('llm_failover_count', 0)}")
        print(f"  Primary Failures:  {runtime.get('llm_primary_failures', 0)}")
        print(f"  Fallback Failures: {runtime.get('llm_fallback_failures', 0)}")
        print(f"  Circuit Blocked:   {runtime.get('circuit_blocked_calls', 0)}")
        print(f"  Circuit Opens:     {runtime.get('circuit_open_events', 0)}")

    # Cost from DB
    db_path = find_db(args.db if hasattr(args, "db") else None)
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            total_cost = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM usage_ledger WHERE created_at > datetime('now', '-7 days')"
            ).fetchone()[0]
            total_calls = conn.execute(
                "SELECT COUNT(*) FROM usage_ledger WHERE created_at > datetime('now', '-7 days')"
            ).fetchone()[0]
            conn.close()
            print(f"\n  --- Cost (last 7 days) ---")
            print(f"  Total:             ${total_cost:.4f} ({total_calls} calls)")
        except Exception:
            pass

    # Diagnosis
    print("\n  --- Diagnosis ---")
    configured_count = sum(1 for p in FAILOVER_CHAIN if key_status(p["env_key"])[0] == "configured")
    if configured_count == 0:
        print("  [x] No API keys configured!")
    elif configured_count < 2:
        print(f"  [-] Only {configured_count} provider configured (no failover)")
    else:
        print(f"  [+] {configured_count} providers configured")

    if runtime:
        breakers = runtime.get("circuit_breakers") or {}
        open_breakers = [n for n, cb in breakers.items() if cb.get("state") != "closed"]
        if open_breakers:
            for b in open_breakers:
                print(f"  [x] Circuit breaker OPEN: {b}")
        else:
            print("  [+] No circuit breakers open")

        if runtime.get("llm_last_error"):
            print(f"  [-] Last error: {str(runtime.get('llm_last_error'))[:80]}")
    print()


def cmd_keys(args):
    """Check which API keys are configured."""
    print("=" * 60)
    print("  bob-llm: API Key Status")
    print("=" * 60)
    print()

    for provider in FAILOVER_CHAIN:
        status, val = key_status(provider["env_key"])
        if status == "configured":
            print(f"  [+] {provider['name']:<12s} {provider['env_key']:<25s} configured ({mask_secret(val)})")
        elif status == "placeholder":
            print(f"  [-] {provider['name']:<12s} {provider['env_key']:<25s} PLACEHOLDER (not set)")
        else:
            print(f"  [x] {provider['name']:<12s} {provider['env_key']:<25s} MISSING")
    print()


def cmd_ping(args):
    """Ping each LLM provider's API."""
    print("=" * 60)
    print("  bob-llm: Provider Ping")
    print("=" * 60)
    print()

    for provider in FAILOVER_CHAIN:
        status, val = key_status(provider["env_key"])
        if status != "configured" or not provider["ping_url"]:
            print(f"  [-] {provider['name']:<12s} skipped (key {status})")
            continue

        # Ping the models endpoint
        try:
            headers = {"Accept": "application/json"}
            if provider["name"] == "Kimi":
                headers["Authorization"] = f"Bearer {val}"
            elif provider["name"] == "OpenAI":
                headers["Authorization"] = f"Bearer {val}"
            elif provider["name"] == "Anthropic":
                headers["x-api-key"] = val
                headers["anthropic-version"] = "2023-06-01"

            req = urllib.request.Request(provider["ping_url"], headers=headers)
            start = time.time()
            with urllib.request.urlopen(req, timeout=10) as resp:
                elapsed = (time.time() - start) * 1000
                resp.read()
                print(f"  [+] {provider['name']:<12s} {elapsed:.0f}ms (HTTP {resp.status})")
        except urllib.error.HTTPError as e:
            elapsed = 0
            print(f"  [-] {provider['name']:<12s} HTTP {e.code} ({e.reason})")
        except Exception as e:
            print(f"  [x] {provider['name']:<12s} FAILED ({e})")
    print()


def cmd_circuit(args):
    """Show circuit breaker states."""
    print("=" * 60)
    print("  bob-llm: Circuit Breakers")
    print("=" * 60)
    print()

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if not runtime:
        print(f"  Bob is not running: {err}")
        sys.exit(1)

    breakers = runtime.get("circuit_breakers") or {}
    if not breakers:
        print("  No circuit breakers registered.")
        print()
        return

    for name, cb in sorted(breakers.items()):
        state = cb.get("state", "?")
        failures = cb.get("failures", 0)
        last_err = cb.get("last_error")
        mark = "[+]" if state == "closed" else "[x]"

        print(f"  {mark} {name}")
        print(f"      state={state}  failures={failures}")
        if last_err:
            print(f"      last_error={str(last_err)[:100]}")
        print()

    print(f"  Circuit blocked calls: {runtime.get('circuit_blocked_calls', 0)}")
    print(f"  Circuit open events:   {runtime.get('circuit_open_events', 0)}")
    print()


def cmd_cost(args):
    """Usage cost summary from DB."""
    print("=" * 60)
    print("  bob-llm: Usage Cost")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    days = args.days if hasattr(args, "days") and args.days else 7
    conn = sqlite3.connect(db_path)

    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "usage_ledger" not in tables:
        print("  Table 'usage_ledger' not found.")
        conn.close()
        return

    try:
        # Total cost
        total = conn.execute(
            f"SELECT COALESCE(SUM(estimated_cost_usd), 0), COUNT(*), "
            f"COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0) "
            f"FROM usage_ledger WHERE created_at > datetime('now', '-{int(days)} days')"
        ).fetchone()

        print(f"  Period: last {days} days")
        print(f"  Total cost:    ${total[0]:.4f}")
        print(f"  Total calls:   {total[1]:,}")
        print(f"  Prompt tokens: {total[2]:,}")
        print(f"  Comp. tokens:  {total[3]:,}")

        # By model
        rows = conn.execute(
            f"SELECT model_name, COUNT(*), COALESCE(SUM(estimated_cost_usd), 0) "
            f"FROM usage_ledger WHERE created_at > datetime('now', '-{int(days)} days') "
            f"GROUP BY model_name ORDER BY SUM(estimated_cost_usd) DESC"
        ).fetchall()

        if rows:
            print(f"\n  By model:")
            for model, calls, cost in rows:
                print(f"    {model or 'unknown':<25s} ${cost:.4f} ({calls} calls)")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-llm: LLM failover chain diagnostics",
        epilog="Examples:\n"
               "  python bob_llm.py status\n"
               "  python bob_llm.py keys\n"
               "  python bob_llm.py ping\n"
               "  python bob_llm.py circuit\n"
               "  python bob_llm.py cost --days 30\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["status", "keys", "ping", "circuit", "cost"],
                        help="Command to run")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--days", type=int, default=7, help="Days for cost report (default: 7)")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    commands = {
        "status": cmd_status,
        "keys": cmd_keys,
        "ping": cmd_ping,
        "circuit": cmd_circuit,
        "cost": cmd_cost,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""bob-api: API endpoint tester for Bob.

Tests all GET endpoints for availability and correct responses.
Requires Bob to be running.

Usage:
    python bob_api.py                        # Test all GET endpoints
    python bob_api.py --full                  # Include POST endpoints
    python bob_api.py --endpoint /heartbeat   # Test single endpoint
    python bob_api.py --url http://host:9000  # Custom base URL
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


# Endpoint registry: (method, path, category, needs_auth, safe_payload_or_None)
ENDPOINTS = [
    # Health & Monitoring
    ("GET", "/heartbeat", "health", False, None),
    ("GET", "/status/runtime", "health", False, None),

    # UI
    ("GET", "/ui/me", "ui", False, None),
    ("GET", "/ui/approvals/pending", "ui", False, None),
    ("GET", "/ui/tasks", "ui", False, None),

    # Tasks
    ("GET", "/ops/tasks/0/checkpoints", "tasks", False, None),

    # Skills
    ("GET", "/skills", "skills", False, None),

    # Scheduled Jobs
    ("GET", "/cron/jobs", "cron", False, None),

    # Agents
    ("GET", "/agents/list", "agents", False, None),
    ("GET", "/team/presence", "agents", False, None),

    # Nodes
    ("GET", "/nodes", "nodes", False, None),
    ("GET", "/nodes/control_plane", "nodes", False, None),

    # Ops
    ("GET", "/ops/queue/mode", "ops", False, None),
    ("GET", "/ops/usage/summary", "ops", False, None),
    ("GET", "/ops/paths", "ops", False, None),
    ("GET", "/ops/session-lanes", "ops", False, None),
    ("GET", "/ops/audit/events", "ops", False, None),
    ("GET", "/ops/schema/version", "ops", False, None),
    ("GET", "/ops/host_exec/grants", "ops", False, None),

    # Context
    ("GET", "/context/list", "context", False, None),

    # Plugins
    ("GET", "/plugins/tools", "plugins", False, None),

    # Eval
    ("GET", "/eval/last", "eval", False, None),

    # Goals
    ("GET", "/goals", "goals", False, None),

    # Workflows
    ("GET", "/workflow/programs", "workflows", False, None),

    # Debug
    ("GET", "/debug/blackbox", "debug", False, None),
    ("GET", "/debug/blackbox/sessions", "debug", False, None),

    # POST endpoints (only tested with --full)
    ("POST", "/heartbeat/wake", "health", False, {}),
    ("POST", "/chat", "chat", False, {"message": "test", "chat_id": "bob_api_test"}),
    ("POST", "/ops/queue/mode", "ops", False, {"mode": "auto"}),
]


def test_endpoint(method, path, payload=None):
    """Test a single endpoint. Returns (status_code, response_time_ms, error_or_None)."""
    url = BASE_URL + path
    start = time.monotonic()
    try:
        if method == "GET":
            resp = urllib.request.urlopen(url, timeout=30)
        else:
            body = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=30)

        elapsed = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(resp.read())
            is_json = True
        except Exception:
            is_json = False

        return resp.status, elapsed, None, is_json

    except urllib.error.HTTPError as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return e.code, elapsed, str(e.reason)[:60], False

    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return 0, elapsed, str(e)[:60], False


def main():
    global BASE_URL

    parser = argparse.ArgumentParser(
        description="bob-api: API endpoint tester",
        epilog="Examples:\n"
               "  python bob_api.py                        # GET endpoints\n"
               "  python bob_api.py --full                  # include POST\n"
               "  python bob_api.py --endpoint /heartbeat   # single endpoint\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default=BASE_URL, help="Base URL")
    parser.add_argument("--full", action="store_true", help="Include POST endpoints")
    parser.add_argument("--endpoint", help="Test single endpoint path")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")

    # Check if Bob is reachable
    try:
        urllib.request.urlopen(BASE_URL + "/heartbeat", timeout=5)
    except Exception as e:
        print(f"Bob is DOWN at {BASE_URL}: {e}")
        sys.exit(1)

    print("=" * 60)
    print("  bob-api: API Endpoint Tests")
    print(f"  Target: {BASE_URL}")
    print("=" * 60)
    print()

    if args.endpoint:
        # Single endpoint test
        method = "GET"
        payload = None
        # Check if it's a known POST
        for m, p, _, _, pl in ENDPOINTS:
            if p == args.endpoint:
                method = m
                payload = pl
                break
        code, ms, err, is_json = test_endpoint(method, args.endpoint, payload)
        mark = "+" if 200 <= code < 500 else "x"
        print(f"  [{mark}] {method} {args.endpoint}: {code} ({ms}ms)")
        if err:
            print(f"      error: {err}")
        if is_json:
            print(f"      response: valid JSON")
        sys.exit(0 if 200 <= code < 500 else 1)

    # Filter endpoints
    endpoints = ENDPOINTS
    if not args.full:
        endpoints = [(m, p, c, a, pl) for m, p, c, a, pl in endpoints if m == "GET"]

    # Group by category
    categories = {}
    for method, path, cat, auth, payload in endpoints:
        categories.setdefault(cat, []).append((method, path, auth, payload))

    results = []
    ok_count = 0
    skip_count = 0
    fail_count = 0

    for cat in sorted(categories.keys()):
        print(f"  --- {cat.upper()} ---")
        for method, path, auth, payload in categories[cat]:
            code, ms, err, is_json = test_endpoint(method, path, payload)

            if code == 0:
                # Connection error
                mark = "x"
                status = "DOWN"
                fail_count += 1
            elif 200 <= code < 300:
                mark = "+"
                status = f"{code}"
                ok_count += 1
            elif code in (401, 403):
                mark = "-"
                status = f"{code} (auth required)"
                skip_count += 1
            elif code == 404:
                mark = "-"
                status = f"{code} (not found)"
                skip_count += 1
            elif code == 422:
                mark = "+"
                status = f"{code} (validation)"
                ok_count += 1
            elif code >= 500:
                mark = "x"
                status = f"{code} SERVER ERROR"
                fail_count += 1
            else:
                mark = "~"
                status = f"{code}"
                ok_count += 1

            json_tag = " json" if is_json else ""
            err_tag = f" err={err}" if err else ""
            print(f"    [{mark}] {method:4s} {path:40s} {status} ({ms}ms){json_tag}{err_tag}")

            results.append((method, path, code, ms))
        print()

    # Summary
    total = len(results)
    print("=" * 60)
    print(f"  Results: {ok_count} OK, {skip_count} skipped, {fail_count} failed ({total} total)")

    if fail_count > 0:
        print("\n  Failed endpoints:")
        for method, path, code, ms in results:
            if code == 0 or code >= 500:
                print(f"    {method} {path} -> {code}")

    avg_ms = sum(ms for _, _, _, ms in results) / max(1, len(results))
    print(f"\n  Avg response time: {avg_ms:.0f}ms")
    print("=" * 60)

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()

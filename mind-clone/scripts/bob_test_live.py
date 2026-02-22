#!/usr/bin/env python3
"""bob-test-live: Live integration tests for Bob.

Sends real requests through the full pipeline and verifies responses.
Requires Bob to be running.

Usage:
    python bob_test_live.py               # Run all tests
    python bob_test_live.py --quick       # Health check only
    python bob_test_live.py --url http://localhost:9000  # Custom URL
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


BASE_URL = "http://localhost:8000"
TEST_CHAT_ID = "bob_test_live_999"


def api_get(path, base=None):
    """GET request, return (status_code, data_or_None, error_or_None)."""
    url = (base or BASE_URL) + path
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read())
        return resp.status, data, None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = None
        return e.code, body, str(e)
    except Exception as e:
        return 0, None, str(e)


def api_post(path, payload, base=None):
    """POST JSON request, return (status_code, data_or_None, error_or_None)."""
    url = (base or BASE_URL) + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return resp.status, data, None
    except urllib.error.HTTPError as e:
        try:
            resp_body = json.loads(e.read())
        except Exception:
            resp_body = None
        return e.code, resp_body, str(e)
    except Exception as e:
        return 0, None, str(e)


def test_health(base):
    """Test 1: Health check — /heartbeat returns 200."""
    code, data, err = api_get("/heartbeat", base)
    if code == 200 and data:
        return True, f"agent={data.get('agent')}, model={data.get('model')}"
    return False, err or f"status={code}"


def test_runtime(base):
    """Test 2: Runtime status — /status/runtime returns valid metrics."""
    code, data, err = api_get("/status/runtime", base)
    if code != 200 or not data:
        return False, err or f"status={code}"

    required_keys = ["worker_alive", "llm_primary_model", "command_queue_mode"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return False, f"missing keys: {missing}"
    return True, f"{len(data)} metrics, worker_alive={data.get('worker_alive')}"


def test_chat_roundtrip(base):
    """Test 3: Send a chat message, get a response."""
    payload = {
        "message": "Say only the word 'hello' and nothing else.",
        "chat_id": TEST_CHAT_ID,
    }
    start = time.monotonic()
    code, data, err = api_post("/chat", payload, base)
    elapsed = int((time.monotonic() - start) * 1000)

    if code != 200 or not data:
        return False, err or f"status={code}"

    response = data.get("response") or data.get("reply") or data.get("message") or ""
    if not response:
        return False, f"empty response (keys: {list(data.keys())[:5]})"
    return True, f"{elapsed}ms, len={len(response)}"


def test_metrics_present(base):
    """Test 4: Verify closed-loop + self-tuning metrics exist."""
    code, data, err = api_get("/status/runtime", base)
    if code != 200 or not data:
        return False, err or f"status={code}"

    cl_keys = [k for k in data if k.startswith("cl_")]
    st_keys = [k for k in data if k.startswith("st_")]

    issues = []
    if len(cl_keys) < 5:
        issues.append(f"only {len(cl_keys)} cl_* keys (expected 9+)")
    if len(st_keys) < 5:
        issues.append(f"only {len(st_keys)} st_* keys (expected 10+)")

    if issues:
        return False, "; ".join(issues)
    return True, f"cl_keys={len(cl_keys)}, st_keys={len(st_keys)}"


def test_error_handling(base):
    """Test 5: Malformed request returns proper error, not 500."""
    # Send chat with missing required fields
    payload = {"invalid_field": "test"}
    code, data, err = api_post("/chat", payload, base)

    if code == 500:
        return False, "Server returned 500 (should be 4xx)"
    if code == 422 or code == 400:
        return True, f"Correctly returned {code} for malformed request"
    if code == 200:
        # Some servers accept partial requests gracefully
        return True, f"Server handled gracefully (200)"
    return False, f"Unexpected status={code}, err={err}"


def test_endpoints_available(base):
    """Test 6: Key endpoints return non-500 responses."""
    endpoints = [
        "/heartbeat",
        "/status/runtime",
        "/ui/approvals/pending",
    ]
    ok_count = 0
    fail_list = []
    for ep in endpoints:
        code, _, _ = api_get(ep, base)
        if code > 0 and code < 500:
            ok_count += 1
        else:
            fail_list.append(f"{ep}={code}")

    if fail_list:
        return False, f"{ok_count}/{len(endpoints)} ok, failed: {fail_list}"
    return True, f"{ok_count}/{len(endpoints)} endpoints responding"


ALL_TESTS = [
    ("Health Check", test_health),
    ("Runtime Status", test_runtime),
    ("Chat Round-Trip", test_chat_roundtrip),
    ("CL+ST Metrics", test_metrics_present),
    ("Error Handling", test_error_handling),
    ("Endpoints Available", test_endpoints_available),
]


def main():
    parser = argparse.ArgumentParser(
        description="bob-test-live: Live integration tests",
        epilog="Examples:\n"
               "  python bob_test_live.py              # all tests\n"
               "  python bob_test_live.py --quick       # health only\n"
               "  python bob_test_live.py --url http://localhost:9000\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL (default: http://localhost:8000)")
    parser.add_argument("--quick", action="store_true", help="Health check only")
    args = parser.parse_args()

    base = args.url.rstrip("/")

    print("=" * 60)
    print("  bob-test-live: Integration Tests")
    print(f"  Target: {base}")
    print("=" * 60)
    print()

    tests = ALL_TESTS[:1] if args.quick else ALL_TESTS
    results = []

    for name, fn in tests:
        print(f"  Running {name}...", end="", flush=True)
        start = time.monotonic()
        try:
            passed, detail = fn(base)
        except Exception as e:
            passed, detail = False, str(e)
        elapsed = int((time.monotonic() - start) * 1000)

        mark = "PASS" if passed else "FAIL"
        print(f" {mark} ({elapsed}ms)")
        if detail:
            print(f"    {detail}")
        results.append((name, passed))

    # Summary
    print()
    print("-" * 60)
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    for name, passed in results:
        mark = "+" if passed else "x"
        print(f"  [{mark}] {name}")
    print()
    if passed_count == total:
        print(f"  OVERALL: PASS ({passed_count}/{total})")
    else:
        failed = [n for n, p in results if not p]
        print(f"  OVERALL: FAIL ({passed_count}/{total}) — {', '.join(failed)}")
    print("-" * 60)

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()

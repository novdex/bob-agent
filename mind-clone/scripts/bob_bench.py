#!/usr/bin/env python3
"""bob-bench: Performance benchmarker for Bob.

Measures response latency, throughput, and degradation under load.
Requires Bob to be running.

Usage:
    python bob_bench.py latency                          # 10 sequential messages
    python bob_bench.py throughput --concurrent 5 --messages 20
    python bob_bench.py soak --duration 60               # 60s continuous load
    python bob_bench.py compare                          # Save/compare baseline
"""

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
BASELINE_FILE = os.path.join(MIND_CLONE_DIR, "persist", "bench_baseline.json")
BASE_URL = "http://localhost:8000"


def send_chat(message, chat_id="bob_bench_test"):
    """Send a chat message, return (success, response_ms, error)."""
    url = BASE_URL + "/chat"
    payload = json.dumps({"message": message, "chat_id": chat_id}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    start = time.monotonic()
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        elapsed = int((time.monotonic() - start) * 1000)
        data = json.loads(resp.read())
        response = data.get("response") or data.get("reply") or ""
        return True, elapsed, len(response)
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, elapsed, str(e)


def percentile(data, p):
    """Calculate percentile from sorted data."""
    if not data:
        return 0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def print_latency_stats(times_ms, label=""):
    """Print latency statistics."""
    if not times_ms:
        print("  No data collected.")
        return
    print(f"  {label}Latency Statistics ({len(times_ms)} samples):")
    print(f"    Min:    {min(times_ms):>8,}ms")
    print(f"    p50:    {percentile(times_ms, 50):>8,.0f}ms")
    print(f"    p90:    {percentile(times_ms, 90):>8,.0f}ms")
    print(f"    p99:    {percentile(times_ms, 99):>8,.0f}ms")
    print(f"    Max:    {max(times_ms):>8,}ms")
    print(f"    Mean:   {statistics.mean(times_ms):>8,.0f}ms")
    if len(times_ms) > 1:
        print(f"    StdDev: {statistics.stdev(times_ms):>8,.0f}ms")


def cmd_latency(args):
    """Send N sequential messages, report latency percentiles."""
    count = args.messages or 10
    messages = [
        "What is the capital of France?",
        "Say hello in 3 words.",
        "What is 15 plus 27?",
        "Name a color.",
        "What day is today?",
        "Say just the word 'ok'.",
        "How many letters in 'test'?",
        "What is Python?",
        "Name a fruit.",
        "What is 2 times 3?",
    ]

    print(f"  Sending {count} sequential messages...\n")
    times = []
    errors = 0

    for i in range(count):
        msg = messages[i % len(messages)]
        print(f"    [{i+1}/{count}] {msg[:40]}...", end="", flush=True)
        ok, ms, detail = send_chat(msg, f"bob_bench_lat_{i}")
        if ok:
            times.append(ms)
            print(f" {ms}ms (len={detail})")
        else:
            errors += 1
            print(f" FAIL ({detail})")

    print()
    print_latency_stats(times)
    if errors:
        print(f"\n  Errors: {errors}/{count}")

    return {"times_ms": times, "errors": errors, "mode": "latency"}


def cmd_throughput(args):
    """Send messages concurrently, measure throughput."""
    concurrent_count = args.concurrent or 3
    total = args.messages or 15
    msg = "Say the word 'ok' and nothing else."

    print(f"  Sending {total} messages with {concurrent_count} concurrent workers...\n")
    times = []
    errors = 0
    start = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_count) as executor:
        futures = []
        for i in range(total):
            f = executor.submit(send_chat, msg, f"bob_bench_tp_{i}")
            futures.append(f)

        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            ok, ms, detail = future.result()
            if ok:
                times.append(ms)
                print(f"    [{i+1}/{total}] {ms}ms")
            else:
                errors += 1
                print(f"    [{i+1}/{total}] FAIL")

    total_time = time.monotonic() - start
    print()
    print_latency_stats(times)
    print(f"\n  Total wall time: {total_time:.1f}s")
    print(f"  Throughput: {len(times) / max(0.1, total_time):.2f} msg/s")
    if errors:
        print(f"  Errors: {errors}/{total}")

    return {"times_ms": times, "errors": errors, "wall_seconds": total_time, "mode": "throughput"}


def cmd_soak(args):
    """Continuous load for N seconds."""
    duration = args.duration or 30
    msg = "Say 'ok'."

    print(f"  Soak test: continuous load for {duration}s...\n")
    times = []
    errors = 0
    start = time.monotonic()
    count = 0

    while (time.monotonic() - start) < duration:
        count += 1
        ok, ms, detail = send_chat(msg, f"bob_bench_soak_{count}")
        if ok:
            times.append(ms)
            # Show progress every 5 messages
            if count % 5 == 0:
                elapsed = time.monotonic() - start
                avg = statistics.mean(times[-5:]) if len(times) >= 5 else statistics.mean(times)
                print(f"    [{elapsed:.0f}s] {count} sent, last 5 avg={avg:.0f}ms")
        else:
            errors += 1

    total_time = time.monotonic() - start
    print()
    print_latency_stats(times)
    print(f"\n  Duration: {total_time:.1f}s")
    print(f"  Messages sent: {count}")
    print(f"  Throughput: {len(times) / max(0.1, total_time):.2f} msg/s")
    if errors:
        print(f"  Errors: {errors}/{count}")

    # Check for degradation: compare first quarter vs last quarter
    if len(times) >= 8:
        q1 = statistics.mean(times[:len(times)//4])
        q4 = statistics.mean(times[-len(times)//4:])
        change = ((q4 - q1) / max(1, q1)) * 100
        if change > 20:
            print(f"\n  WARNING: Degradation detected! First quarter avg={q1:.0f}ms, last quarter avg={q4:.0f}ms ({change:+.0f}%)")
        else:
            print(f"\n  Stable: First quarter avg={q1:.0f}ms, last quarter avg={q4:.0f}ms ({change:+.0f}%)")

    return {"times_ms": times, "errors": errors, "wall_seconds": total_time, "mode": "soak"}


def cmd_compare(args):
    """Save or compare against baseline."""
    # Run latency test
    result = cmd_latency(args)
    times = result["times_ms"]

    if not times:
        print("\n  No data to compare.")
        return result

    current = {
        "p50": percentile(times, 50),
        "p90": percentile(times, 90),
        "p99": percentile(times, 99),
        "mean": statistics.mean(times),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Load baseline if exists
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, "r") as f:
            baseline = json.load(f)

        print(f"\n  Comparison vs baseline ({baseline.get('timestamp', '?')}):")
        print(f"    {'Metric':8s} {'Baseline':>10s} {'Current':>10s} {'Change':>10s}")
        print(f"    {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
        for key in ["p50", "p90", "p99", "mean"]:
            bv = baseline.get(key, 0)
            cv = current[key]
            change = ((cv - bv) / max(1, bv)) * 100
            arrow = "faster" if change < -5 else "slower" if change > 5 else "same"
            print(f"    {key:8s} {bv:>9.0f}ms {cv:>9.0f}ms {change:>+8.0f}% ({arrow})")
    else:
        print(f"\n  No baseline found. Saving current as baseline.")

    # Save current as new baseline
    os.makedirs(os.path.dirname(BASELINE_FILE), exist_ok=True)
    with open(BASELINE_FILE, "w") as f:
        json.dump(current, f, indent=2)
    print(f"\n  Baseline saved to: {BASELINE_FILE}")

    return result


def main():
    global BASE_URL

    parser = argparse.ArgumentParser(
        description="bob-bench: Performance benchmarker",
        epilog="Examples:\n"
               "  python bob_bench.py latency\n"
               "  python bob_bench.py throughput --concurrent 5 --messages 20\n"
               "  python bob_bench.py soak --duration 60\n"
               "  python bob_bench.py compare\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["latency", "throughput", "soak", "compare"],
                        help="Benchmark mode")
    parser.add_argument("--url", default=BASE_URL, help="Base URL")
    parser.add_argument("--messages", type=int, help="Number of messages")
    parser.add_argument("--concurrent", type=int, help="Concurrent workers")
    parser.add_argument("--duration", type=int, help="Soak duration (seconds)")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")

    # Check if Bob is reachable
    try:
        urllib.request.urlopen(BASE_URL + "/heartbeat", timeout=5)
    except Exception as e:
        print(f"Bob is DOWN at {BASE_URL}: {e}")
        sys.exit(1)

    print("=" * 60)
    print("  bob-bench: Performance Benchmark")
    print(f"  Target: {BASE_URL}")
    print("=" * 60)
    print()

    commands = {
        "latency": cmd_latency,
        "throughput": cmd_throughput,
        "soak": cmd_soak,
        "compare": cmd_compare,
    }

    result = commands[args.command](args)
    errors = result.get("errors", 0)
    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()

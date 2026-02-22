#!/usr/bin/env python3
"""bob-health: Check Bob's live API health status.

Usage:
    python bob_health.py                    # One-shot health check
    python bob_health.py --watch            # Refresh every 5s
    python bob_health.py --url http://host  # Custom base URL
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

DEFAULT_URL = "http://localhost:8000"
WATCH_INTERVAL = 5


def fetch_json(url, timeout=5):
    """Fetch JSON from a URL. Returns (data, error)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data, None
    except urllib.error.URLError as e:
        return None, f"Connection refused ({e.reason})"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except json.JSONDecodeError:
        return None, "Invalid JSON response"
    except Exception as e:
        return None, str(e)


def format_uptime(seconds):
    """Format seconds into human-readable uptime."""
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    return f"{hours}h {mins}m"


def print_dashboard(base_url):
    """Print a single health dashboard snapshot."""
    print("=" * 55)
    print("  Bob Health Dashboard")
    print(f"  {base_url}")
    print("=" * 55)

    # 1. Basic connectivity
    heartbeat, hb_err = fetch_json(f"{base_url}/heartbeat")
    runtime, rt_err = fetch_json(f"{base_url}/status/runtime")

    if hb_err and rt_err:
        print()
        print("  Server:   DOWN")
        print(f"  Error:    {hb_err}")
        print()
        print("  Bob is not running.")
        print("  Start with: cd mind-clone && python mind_clone_agent.py")
        print("=" * 55)
        return False

    print()

    # Server status
    server_up = heartbeat is not None or runtime is not None
    print(f"  Server:      {'UP' if server_up else 'DOWN'}")

    # Parse heartbeat
    if heartbeat:
        model = heartbeat.get("model", "unknown")
        print(f"  Agent:       {heartbeat.get('agent', 'Mind Clone')}")
        print(f"  LLM Model:   {model}")

    # Parse runtime
    if runtime:
        # Worker & supervisor health
        worker = runtime.get("worker_alive", "unknown")
        spine = runtime.get("spine_supervisor_alive", "unknown")
        db = runtime.get("db_healthy", "unknown")
        uptime = runtime.get("uptime_seconds")

        print(f"  Worker:      {'alive' if worker else 'dead'}")
        print(f"  Spine:       {'alive' if spine else 'dead'}")
        print(f"  Database:    {'healthy' if db else 'error'}")
        if uptime is not None:
            print(f"  Uptime:      {format_uptime(uptime)}")

        # Queue & approvals
        queue_mode = runtime.get("command_queue_mode", "off")
        queue_enq = runtime.get("command_queue_enqueued", 0)
        queue_proc = runtime.get("command_queue_processed", 0)
        approvals = runtime.get("approval_pending_count", 0)

        print()
        print(f"  Queue Mode:  {queue_mode}")
        print(f"  Enqueued:    {queue_enq}  |  Processed: {queue_proc}")
        print(f"  Approvals:   {approvals} pending")

        # LLM status
        llm_model = runtime.get("llm_last_model_used", "none")
        llm_err = runtime.get("llm_last_error", "")
        failovers = runtime.get("llm_failover_count", 0)

        print()
        print(f"  LLM Last:    {llm_model}")
        if llm_err:
            print(f"  LLM Error:   {llm_err[:60]}")
        if failovers:
            print(f"  Failovers:   {failovers}")

        # Budget
        budget_runs = runtime.get("budget_runs_started", 0)
        budget_stops = runtime.get("budget_runs_stopped", 0)

        print()
        print(f"  Budget Runs: {budget_runs} started, {budget_stops} stopped")

        # Alerts
        alerts = runtime.get("runtime_alerts", [])
        if alerts:
            print()
            print(f"  Alerts ({len(alerts)}):")
            for alert in alerts[:5]:
                if isinstance(alert, dict):
                    print(f"    - {alert.get('message', alert)}")
                else:
                    print(f"    - {alert}")
    else:
        print(f"  Runtime:     unavailable ({rt_err})")

    print()
    print("=" * 55)
    return True


def main():
    parser = argparse.ArgumentParser(description="Check Bob's live API health")
    parser.add_argument("--url", "-u", default=DEFAULT_URL, help=f"Base URL (default: {DEFAULT_URL})")
    parser.add_argument("--watch", "-w", action="store_true", help=f"Refresh every {WATCH_INTERVAL}s")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    if args.watch:
        try:
            while True:
                # Clear screen (cross-platform)
                print("\033c", end="")
                print_dashboard(base_url)
                print(f"  Refreshing in {WATCH_INTERVAL}s... (Ctrl+C to stop)")
                time.sleep(WATCH_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        ok = print_dashboard(base_url)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

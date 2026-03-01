#!/usr/bin/env python3
"""bob-queue: Command queue diagnostics for Bob.

Inspect queue status, backlog, worker health, lane configuration,
and self-tuning events.

Usage:
    python bob_queue.py status              # Queue subsystem overview
    python bob_queue.py backlog             # Show current backlog
    python bob_queue.py lanes               # Lane configuration
    python bob_queue.py workers             # Worker health & scaling
    python bob_queue.py --watch             # Refresh every 5s
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

DEFAULT_URL = "http://localhost:8000"


def fetch_json(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, str(e)


def cmd_status(args):
    """Queue subsystem overview."""
    print("=" * 60)
    print("  bob-queue: Command Queue Diagnostics")
    print("=" * 60)

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if not runtime:
        print(f"\n  Bob is not running: {err}")
        sys.exit(1)

    # Queue status
    mode = runtime.get("command_queue_mode", "unknown")
    size = int(runtime.get("command_queue_size", 0))
    enqueued = int(runtime.get("command_queue_enqueued", 0))
    processed = int(runtime.get("command_queue_processed", 0))
    dropped = int(runtime.get("command_queue_dropped", 0))
    backlog = max(0, enqueued - processed)

    print("\n  --- Queue Status ---")
    print(f"  Mode:              {mode}")
    print(f"  Current Size:      {size}")
    print(f"  Enqueued Total:    {enqueued:,}")
    print(f"  Processed Total:   {processed:,}")
    print(f"  Dropped:           {dropped}")
    print(f"  Backlog:           {backlog}")

    # Workers
    alive = int(runtime.get("command_queue_worker_alive_count", 0))
    target = int(runtime.get("command_queue_worker_target", 0))

    print("\n  --- Workers ---")
    print(f"  Alive Count:       {alive}")
    print(f"  Target Count:      {target}")
    if alive >= target and target > 0:
        print(f"  Worker Status:     all alive")
    elif target > 0:
        print(f"  Worker Status:     DEGRADED ({target - alive} missing)")
    else:
        print(f"  Worker Status:     queue disabled")

    # Self-tuning
    print("\n  --- Self-Tuning ---")
    print(f"  Queue Mode Switches:  {runtime.get('st_queue_mode_switches', 0)}")
    print(f"  Worker Scale Events:  {runtime.get('st_worker_scale_events', 0)}")
    print(f"  Current Workers:      {runtime.get('st_current_worker_count', 'n/a')}")
    print(f"  Last Action:          {runtime.get('st_last_action') or '(none)'}")

    # Diagnosis
    print("\n  --- Diagnosis ---")
    if mode == "off":
        print("  [-] Queue is OFF (direct processing)")
    elif mode == "on":
        print("  [-] Queue mode is ON (adds latency, consider auto)")
    else:
        print(f"  [+] Queue mode: {mode}")

    if backlog > 3:
        print(f"  [x] BACKLOG: {backlog} messages waiting!")
    elif backlog > 0:
        print(f"  [-] Small backlog: {backlog} messages")
    else:
        print("  [+] No backlog")

    if dropped > 0:
        print(f"  [-] {dropped} messages dropped")
    else:
        print("  [+] No dropped messages")

    if alive < target and target > 0:
        print(f"  [x] Workers degraded: {alive}/{target} alive")
    elif target > 0:
        print(f"  [+] All {alive} workers alive")
    print()


def cmd_backlog(args):
    """Show current backlog details."""
    print("=" * 60)
    print("  bob-queue: Backlog")
    print("=" * 60)

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if not runtime:
        print(f"\n  Bob is not running: {err}")
        sys.exit(1)

    enqueued = int(runtime.get("command_queue_enqueued", 0))
    processed = int(runtime.get("command_queue_processed", 0))
    dropped = int(runtime.get("command_queue_dropped", 0))
    backlog = max(0, enqueued - processed)

    print()
    print(f"  Enqueued:    {enqueued:,}")
    print(f"  Processed:   {processed:,}")
    print(f"  Dropped:     {dropped}")
    print(f"  Backlog:     {backlog}")

    # Per-owner backlog
    owner_backlog = runtime.get("command_queue_owner_backlog") or {}
    if owner_backlog:
        print(f"\n  Per-owner backlog:")
        for owner, count in sorted(owner_backlog.items(), key=lambda x: x[1], reverse=True):
            print(f"    owner={owner}: {count}")

    owner_active = runtime.get("command_queue_owner_active") or {}
    if owner_active:
        print(f"\n  Currently active per owner:")
        for owner, count in sorted(owner_active.items()):
            print(f"    owner={owner}: {count} active")

    print()
    if backlog == 0:
        print("  [+] Queue is clear.")
    elif backlog <= 3:
        print(f"  [-] Small backlog ({backlog}). Will process shortly.")
    else:
        print(f"  [x] Large backlog ({backlog})! Check worker health.")
    print()


def cmd_lanes(args):
    """Show lane configuration."""
    print("=" * 60)
    print("  bob-queue: Session Lanes")
    print("=" * 60)
    print()

    data, err = fetch_json(f"{args.url}/ops/session-lanes")
    if data:
        if isinstance(data, dict):
            for lane, info in sorted(data.items()):
                if isinstance(info, dict):
                    print(f"  {lane:<20s} semaphore={info.get('semaphore', '?')} active={info.get('active', '?')}")
                else:
                    print(f"  {lane:<20s} {info}")
        elif isinstance(data, list):
            for item in data:
                print(f"  {item}")
        else:
            print(f"  {data}")
    else:
        print(f"  Could not fetch lanes: {err}")
        print("  (endpoint may not exist in current version)")
    print()


def cmd_workers(args):
    """Worker health and scaling info."""
    print("=" * 60)
    print("  bob-queue: Workers")
    print("=" * 60)

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if not runtime:
        print(f"\n  Bob is not running: {err}")
        sys.exit(1)

    alive = int(runtime.get("command_queue_worker_alive_count", 0))
    target = int(runtime.get("command_queue_worker_target", 0))

    print()
    print(f"  Alive:           {alive}")
    print(f"  Target:          {target}")
    print(f"  Worker restarts: {runtime.get('task_worker_restarts', 0)}")

    # Self-tuning worker info
    print(f"\n  --- Self-Tuning Worker Scaling ---")
    print(f"  Scale events:    {runtime.get('st_worker_scale_events', 0)}")
    print(f"  Current count:   {runtime.get('st_current_worker_count', 'n/a')}")
    print(f"  Last tune:       {runtime.get('st_last_tune_at') or '(none)'}")
    print(f"  Last action:     {runtime.get('st_last_action') or '(none)'}")

    print()
    if alive >= target and target > 0:
        print(f"  [+] All {alive} workers healthy.")
    elif target > 0:
        print(f"  [x] Workers degraded: {alive}/{target}")
    else:
        print("  [-] Queue workers disabled (queue mode off)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-queue: Command queue diagnostics",
        epilog="Examples:\n"
               "  python bob_queue.py status\n"
               "  python bob_queue.py backlog\n"
               "  python bob_queue.py lanes\n"
               "  python bob_queue.py workers\n"
               "  python bob_queue.py status --watch\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["status", "backlog", "lanes", "workers"],
                        help="Command to run")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--watch", action="store_true", help="Refresh every 5 seconds")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    commands = {
        "status": cmd_status,
        "backlog": cmd_backlog,
        "lanes": cmd_lanes,
        "workers": cmd_workers,
    }

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")
                commands[args.command](args)
                print(f"  [Refreshing every 5s - Ctrl+C to stop]")
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        commands[args.command](args)


if __name__ == "__main__":
    main()

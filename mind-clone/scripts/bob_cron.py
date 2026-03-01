#!/usr/bin/env python3
"""bob-cron: Scheduler and heartbeat diagnostics for Bob.

Inspect cron jobs, heartbeat supervisor, overdue jobs, and zombie detection.

Usage:
    python bob_cron.py status               # Overall scheduler status
    python bob_cron.py jobs [--owner 1]     # List scheduled jobs
    python bob_cron.py overdue              # List overdue jobs
    python bob_cron.py heartbeat            # Heartbeat supervisor status
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

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


def format_interval(seconds):
    """Format seconds into human-readable interval."""
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def cmd_status(args):
    """Overall scheduler status."""
    print("=" * 60)
    print("  bob-cron: Scheduler Diagnostics")
    print("=" * 60)

    runtime, err = fetch_json(f"{args.url}/status/runtime")

    # Cron supervisor
    print("\n  --- Cron Supervisor ---")
    if runtime:
        print(f"  Alive:             {runtime.get('cron_supervisor_alive', 'unknown')}")
        print(f"  Due Runs Total:    {runtime.get('cron_due_runs', 0)}")
        print(f"  Failures:          {runtime.get('cron_failures', 0)}")
        print(f"  Last Tick:         {runtime.get('cron_last_tick') or '(never)'}")
    else:
        print(f"  (Bob not running: {err})")

    # Heartbeat
    print("\n  --- Heartbeat Supervisor ---")
    if runtime:
        print(f"  Alive:             {runtime.get('heartbeat_supervisor_alive', 'unknown')}")
        print(f"  Ticks Total:       {runtime.get('heartbeat_ticks_total', 0)}")
        print(f"  Manual Wakes:      {runtime.get('heartbeat_manual_wakes', 0)}")
        print(f"  Last Tick:         {runtime.get('heartbeat_last_tick') or '(never)'}")
        print(f"  Last Reason:       {runtime.get('heartbeat_last_reason') or '(none)'}")
        print(f"  Alert Count:       {runtime.get('heartbeat_last_alert_count', 0)}")
        print(f"  Restarts:          {runtime.get('heartbeat_restarts', 0)}")
        print(f"  Next Tick At:      {runtime.get('heartbeat_next_tick_at') or '(unknown)'}")

    # Jobs from DB
    db_path = find_db(args.db if hasattr(args, "db") else None)
    if db_path:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "scheduled_jobs" in tables:
            total = conn.execute("SELECT COUNT(*) FROM scheduled_jobs").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE enabled = 1").fetchone()[0]
            print(f"\n  --- Scheduled Jobs ---")
            print(f"  Total: {total} ({enabled} enabled, {total - enabled} disabled)")

            # Check for overdue
            try:
                overdue = conn.execute(
                    "SELECT COUNT(*) FROM scheduled_jobs WHERE enabled = 1 AND next_run_at < datetime('now')"
                ).fetchone()[0]
                if overdue > 0:
                    print(f"  [-] {overdue} overdue job(s)!")
            except Exception:
                pass
        conn.close()

    # Diagnosis
    print("\n  --- Diagnosis ---")
    if runtime:
        if runtime.get("cron_supervisor_alive"):
            print("  [+] Cron supervisor alive")
        else:
            print("  [x] Cron supervisor DOWN")
        if runtime.get("heartbeat_supervisor_alive"):
            print("  [+] Heartbeat supervisor alive")
        else:
            print("  [x] Heartbeat supervisor DOWN")
        if int(runtime.get("cron_failures", 0)) > 0:
            print(f"  [-] {runtime.get('cron_failures')} cron failures")
    print()


def cmd_jobs(args):
    """List scheduled jobs."""
    print("=" * 60)
    print("  bob-cron: Scheduled Jobs")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "scheduled_jobs" not in tables:
        print("  Table 'scheduled_jobs' not found.")
        conn.close()
        return

    owner_filter = f"WHERE owner_id = {int(args.owner)}" if hasattr(args, "owner") and args.owner else ""
    show_all = hasattr(args, "all") and args.all

    if not show_all and not owner_filter:
        where = "WHERE enabled = 1"
    elif not show_all and owner_filter:
        where = owner_filter + " AND enabled = 1"
    else:
        where = owner_filter

    try:
        # Get column names to handle schema variations
        cols = [c[1] for c in conn.execute("PRAGMA table_info(scheduled_jobs)").fetchall()]

        select_cols = ["id", "owner_id", "name", "enabled"]
        for opt_col in ["interval_seconds", "lane", "run_count", "last_run_at", "next_run_at", "last_error"]:
            if opt_col in cols:
                select_cols.append(opt_col)

        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM scheduled_jobs {where} ORDER BY id"
        ).fetchall()

        if not rows:
            print("  No scheduled jobs found.")
            conn.close()
            return

        for row in rows:
            data = dict(zip(select_cols, row))
            enabled_str = "enabled" if data.get("enabled") else "DISABLED"
            interval = format_interval(data.get("interval_seconds"))
            lane = data.get("lane", "default")

            print(f"  [{data['id']}] \"{data.get('name', '?')}\" owner={data['owner_id']} interval={interval} lane={lane}")
            print(f"      {enabled_str} runs={data.get('run_count', '?')}", end="")
            if data.get("last_run_at"):
                print(f" last_run={data['last_run_at']}", end="")
            print()
            if data.get("next_run_at"):
                print(f"      next_run={data['next_run_at']}", end="")
            if data.get("last_error"):
                print(f"\n      last_error={str(data['last_error'])[:80]}", end="")
            print()
            print()

        print(f"  Total: {len(rows)} jobs shown")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def cmd_overdue(args):
    """List overdue jobs."""
    print("=" * 60)
    print("  bob-cron: Overdue Jobs")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "scheduled_jobs" not in tables:
        print("  Table 'scheduled_jobs' not found.")
        conn.close()
        return

    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(scheduled_jobs)").fetchall()]
        if "next_run_at" not in cols:
            print("  Column 'next_run_at' not found in scheduled_jobs.")
            conn.close()
            return

        rows = conn.execute(
            "SELECT id, owner_id, name, interval_seconds, next_run_at, last_run_at, last_error "
            "FROM scheduled_jobs WHERE enabled = 1 AND next_run_at < datetime('now') "
            "ORDER BY next_run_at"
        ).fetchall()

        if not rows:
            print("  [+] No overdue jobs. All on schedule.")
            conn.close()
            return

        for row in rows:
            job_id, owner, name, interval, next_run, last_run, last_err = row
            print(f"  [x] [{job_id}] \"{name}\" owner={owner}")
            print(f"      next_run_at: {next_run} (OVERDUE)")
            if last_run:
                print(f"      last_run_at: {last_run}")
            if last_err:
                print(f"      last_error: {str(last_err)[:80]}")

            # Zombie check: overdue by more than 2x interval
            if interval and last_err:
                print(f"      [-] ZOMBIE WARNING: overdue + has errors")
            print()

        print(f"  Total: {len(rows)} overdue job(s)")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def cmd_heartbeat(args):
    """Heartbeat supervisor status."""
    print("=" * 60)
    print("  bob-cron: Heartbeat Supervisor")
    print("=" * 60)

    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if not runtime:
        print(f"\n  Bob is not running: {err}")
        sys.exit(1)

    print()
    print(f"  Alive:             {runtime.get('heartbeat_supervisor_alive', 'unknown')}")
    print(f"  Ticks Total:       {runtime.get('heartbeat_ticks_total', 0)}")
    print(f"  Manual Wakes:      {runtime.get('heartbeat_manual_wakes', 0)}")
    print(f"  Last Tick:         {runtime.get('heartbeat_last_tick') or '(never)'}")
    print(f"  Last Reason:       {runtime.get('heartbeat_last_reason') or '(none)'}")
    print(f"  Last Alert Count:  {runtime.get('heartbeat_last_alert_count', 0)}")
    print(f"  Restarts:          {runtime.get('heartbeat_restarts', 0)}")
    print(f"  Next Tick At:      {runtime.get('heartbeat_next_tick_at') or '(unknown)'}")

    # Self-tuning info
    print(f"\n  --- Self-Tuning (runs on heartbeat) ---")
    print(f"  Total tunes:       {runtime.get('st_tunes_total', 0)}")
    print(f"  Interval ticks:    {runtime.get('st_interval_ticks', 'n/a')}")
    print(f"  Last tune:         {runtime.get('st_last_tune_at') or '(never)'}")
    print(f"  Last action:       {runtime.get('st_last_action') or '(none)'}")

    print()
    if runtime.get("heartbeat_supervisor_alive"):
        print("  [+] Heartbeat supervisor is alive and ticking.")
    else:
        print("  [x] Heartbeat supervisor is DOWN!")
    if int(runtime.get("heartbeat_restarts", 0)) > 2:
        print(f"  [-] High restart count ({runtime.get('heartbeat_restarts')})")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-cron: Scheduler diagnostics for Bob",
        epilog="Examples:\n"
               "  python bob_cron.py status\n"
               "  python bob_cron.py jobs --owner 1\n"
               "  python bob_cron.py overdue\n"
               "  python bob_cron.py heartbeat\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["status", "jobs", "overdue", "heartbeat"],
                        help="Command to run")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--owner", type=int, help="Filter by owner ID")
    parser.add_argument("--all", action="store_true", help="Show disabled jobs too")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    commands = {
        "status": cmd_status,
        "jobs": cmd_jobs,
        "overdue": cmd_overdue,
        "heartbeat": cmd_heartbeat,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

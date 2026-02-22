#!/usr/bin/env python3
"""bob-tasks: Task engine inspector for Bob.

Inspect task graph, list tasks, show artifacts, checkpoints,
dead letters, and statistics.

Usage:
    python bob_tasks.py list [--status open]    # List tasks
    python bob_tasks.py show <id>               # Detailed task view
    python bob_tasks.py artifacts [--owner 1]   # List task artifacts
    python bob_tasks.py checkpoints             # List checkpoints
    python bob_tasks.py deadletters             # List dead letters
    python bob_tasks.py stats                   # Summary statistics
"""

import argparse
import json
import os
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


def get_tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]


def get_cols(conn, table):
    return [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def cmd_list(conn, args):
    """List tasks."""
    tables = get_tables(conn)
    if "tasks" not in tables:
        print("  Table 'tasks' not found.")
        return

    cols = get_cols(conn, "tasks")
    limit = args.limit or 20

    where_parts = []
    if hasattr(args, "status") and args.status:
        where_parts.append(f"status = '{args.status}'")
    if hasattr(args, "owner") and args.owner:
        where_parts.append(f"owner_id = {int(args.owner)}")

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # Build select based on available columns
    select_cols = ["id"]
    for c in ["owner_id", "title", "description", "status", "plan", "created_at"]:
        if c in cols:
            select_cols.append(c)

    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM tasks {where} ORDER BY id DESC LIMIT {int(limit)}"
        ).fetchall()

        print("=" * 60)
        print("  bob-tasks: Task List")
        print("=" * 60)
        print()

        if not rows:
            print("  No tasks found.")
            return

        for row in rows:
            data = dict(zip(select_cols, row))
            title = (data.get("title") or data.get("description") or "?")[:60]
            status_str = data.get("status", "?")
            owner = data.get("owner_id", "?")

            # Count plan steps
            plan_str = ""
            if "plan" in data and data["plan"]:
                try:
                    plan = json.loads(data["plan"]) if isinstance(data["plan"], str) else data["plan"]
                    if isinstance(plan, list):
                        plan_str = f" | {len(plan)} steps"
                    elif isinstance(plan, dict) and "steps" in plan:
                        plan_str = f" | {len(plan['steps'])} steps"
                except Exception:
                    pass

            print(f"  [{data['id']}] owner={owner} status={status_str} \"{title}\"")
            if data.get("created_at"):
                print(f"      created: {data['created_at']}{plan_str}")
            print()

        # Count totals
        total = conn.execute(f"SELECT COUNT(*) FROM tasks").fetchone()[0]
        print(f"  Showing {len(rows)} of {total} total tasks")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_show(conn, args):
    """Detailed view of a single task."""
    if not args.task_id:
        print("  Error: provide a task ID (e.g., python bob_tasks.py show 5)")
        sys.exit(1)

    tables = get_tables(conn)
    if "tasks" not in tables:
        print("  Table 'tasks' not found.")
        return

    cols = get_cols(conn, "tasks")

    try:
        row = conn.execute(
            f"SELECT {', '.join(cols)} FROM tasks WHERE id = ?", (int(args.task_id),)
        ).fetchone()

        if not row:
            print(f"  Task {args.task_id} not found.")
            return

        data = dict(zip(cols, row))

        print("=" * 60)
        print(f"  bob-tasks: Task #{data.get('id', '?')}")
        print("=" * 60)
        print()

        for key in ["id", "owner_id", "title", "description", "status", "created_at"]:
            if key in data:
                val = data[key]
                if val and len(str(val)) > 100:
                    val = str(val)[:100] + "..."
                print(f"  {key}: {val}")

        # Parse plan
        if "plan" in data and data["plan"]:
            try:
                plan = json.loads(data["plan"]) if isinstance(data["plan"], str) else data["plan"]
                print(f"\n  --- Plan ---")
                if isinstance(plan, list):
                    for i, step in enumerate(plan):
                        if isinstance(step, dict):
                            step_id = step.get("step_id", f"step_{i+1}")
                            desc = step.get("description", step.get("action", "?"))[:80]
                            step_status = step.get("status", "?")
                            print(f"  [{step_id}] {step_status}: {desc}")
                        else:
                            print(f"  [{i+1}] {str(step)[:80]}")
                elif isinstance(plan, dict):
                    for k, v in plan.items():
                        print(f"  {k}: {str(v)[:100]}")
            except Exception:
                print(f"  Plan (raw): {str(data['plan'])[:200]}")

        # Related artifacts
        if "task_artifacts" in tables:
            artifacts = conn.execute(
                "SELECT id, step_id, status, outcome_summary FROM task_artifacts WHERE task_id = ? ORDER BY id",
                (int(args.task_id),),
            ).fetchall()
            if artifacts:
                print(f"\n  --- Artifacts ({len(artifacts)}) ---")
                for aid, step_id, status, outcome in artifacts:
                    print(f"  [{aid}] step={step_id} status={status}")
                    if outcome:
                        print(f"    {str(outcome)[:100]}")

        # Related checkpoints
        if "task_checkpoint_snapshots" in tables:
            chk_cols = get_cols(conn, "task_checkpoint_snapshots")
            if "task_id" in chk_cols:
                checkpoints = conn.execute(
                    "SELECT * FROM task_checkpoint_snapshots WHERE task_id = ? ORDER BY rowid",
                    (int(args.task_id),),
                ).fetchall()
                if checkpoints:
                    print(f"\n  --- Checkpoints ({len(checkpoints)}) ---")
                    for chk in checkpoints:
                        chk_data = dict(zip(chk_cols, chk))
                        print(f"  source={chk_data.get('source', '?')} status={chk_data.get('task_status', '?')}")
                        if chk_data.get("created_at"):
                            print(f"    created: {chk_data['created_at']}")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_artifacts(conn, args):
    """List task artifacts."""
    tables = get_tables(conn)
    if "task_artifacts" not in tables:
        print("  Table 'task_artifacts' not found.")
        return

    cols = get_cols(conn, "task_artifacts")
    limit = args.limit or 20
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if hasattr(args, "owner") and args.owner else ""

    print("=" * 60)
    print("  bob-tasks: Task Artifacts")
    print("=" * 60)
    print()

    try:
        select = ["id"]
        for c in ["owner_id", "task_id", "step_id", "node_title", "task_title", "status", "outcome_summary", "tool_names_json", "created_at"]:
            if c in cols:
                select.append(c)

        rows = conn.execute(
            f"SELECT {', '.join(select)} FROM task_artifacts {owner_filter} ORDER BY id DESC LIMIT {int(limit)}"
        ).fetchall()

        if not rows:
            print("  No artifacts found.")
            return

        for row in rows:
            data = dict(zip(select, row))
            title = data.get("node_title") or data.get("task_title") or "?"
            print(f"  [{data['id']}] task={data.get('task_id', '?')} step={data.get('step_id', '?')} status={data.get('status', '?')}")
            print(f"    title: {str(title)[:80]}")
            if data.get("tool_names_json"):
                print(f"    tools: {data['tool_names_json']}")
            if data.get("outcome_summary"):
                print(f"    outcome: {str(data['outcome_summary'])[:100]}")
            if data.get("created_at"):
                print(f"    created: {data['created_at']}")
            print()

        total = conn.execute(f"SELECT COUNT(*) FROM task_artifacts {owner_filter}").fetchone()[0]
        print(f"  Showing {len(rows)} of {total} total artifacts")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_checkpoints(conn, args):
    """List checkpoint snapshots."""
    tables = get_tables(conn)
    if "task_checkpoint_snapshots" not in tables:
        print("  Table 'task_checkpoint_snapshots' not found.")
        return

    cols = get_cols(conn, "task_checkpoint_snapshots")
    limit = args.limit or 20

    print("=" * 60)
    print("  bob-tasks: Checkpoints")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM task_checkpoint_snapshots ORDER BY rowid DESC LIMIT {int(limit)}"
        ).fetchall()

        if not rows:
            print("  No checkpoints found.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            print(f"  task={data.get('task_id', '?')} owner={data.get('owner_id', '?')} "
                  f"status={data.get('task_status', '?')} source={data.get('source', '?')}")
            if data.get("created_at"):
                print(f"    created: {data['created_at']}")
            print()

        total = conn.execute("SELECT COUNT(*) FROM task_checkpoint_snapshots").fetchone()[0]
        print(f"  Showing {len(rows)} of {total} total checkpoints")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_deadletters(conn, args):
    """List dead letter entries."""
    tables = get_tables(conn)
    if "task_dead_letters" not in tables:
        print("  Table 'task_dead_letters' not found.")
        return

    cols = get_cols(conn, "task_dead_letters")
    limit = args.limit or 20

    print("=" * 60)
    print("  bob-tasks: Dead Letters")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM task_dead_letters ORDER BY rowid DESC LIMIT {int(limit)}"
        ).fetchall()

        if not rows:
            print("  [+] No dead letters. All strategies healthy.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            print(f"  [x] task={data.get('task_id', '?')} owner={data.get('owner_id', '?')}")
            if data.get("title"):
                print(f"    title: {str(data['title'])[:80]}")
            if data.get("reason"):
                print(f"    reason: {str(data['reason'])[:100]}")
            if data.get("created_at"):
                print(f"    created: {data['created_at']}")
            print()

        total = conn.execute("SELECT COUNT(*) FROM task_dead_letters").fetchone()[0]
        print(f"  Total: {total} dead letter(s)")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_stats(conn, args):
    """Summary statistics."""
    tables = get_tables(conn)

    print("=" * 60)
    print("  bob-tasks: Task Statistics")
    print("=" * 60)
    print()

    # Task counts by status
    if "tasks" in tables:
        cols = get_cols(conn, "tasks")
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        print(f"  --- Tasks ---")
        print(f"  Total:         {total}")

        if "status" in cols:
            statuses = conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY COUNT(*) DESC"
            ).fetchall()
            for status, count in statuses:
                print(f"  {status or 'null':<15s} {count}")

    # Artifacts
    if "task_artifacts" in tables:
        count = conn.execute("SELECT COUNT(*) FROM task_artifacts").fetchone()[0]
        print(f"\n  Artifacts:     {count}")

    # Checkpoints
    if "task_checkpoint_snapshots" in tables:
        count = conn.execute("SELECT COUNT(*) FROM task_checkpoint_snapshots").fetchone()[0]
        print(f"  Checkpoints:   {count}")

    # Dead letters
    if "task_dead_letters" in tables:
        count = conn.execute("SELECT COUNT(*) FROM task_dead_letters").fetchone()[0]
        print(f"  Dead letters:  {count}")

    # Branching depth analysis
    if "task_artifacts" in tables and "step_id" in get_cols(conn, "task_artifacts"):
        try:
            step_ids = conn.execute("SELECT DISTINCT step_id FROM task_artifacts WHERE step_id IS NOT NULL").fetchall()
            max_depth = 0
            deepest = ""
            for (sid,) in step_ids:
                depth = str(sid).count("_b")
                if depth > max_depth:
                    max_depth = depth
                    deepest = sid
            print(f"\n  --- Branching ---")
            print(f"  Max depth:     {max_depth} of 3 max")
            if deepest:
                print(f"  Deepest step:  {deepest}")
        except Exception:
            pass

    # Runtime metrics
    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if runtime:
        print(f"\n  --- Runtime ---")
        for key in ["task_queue_size", "tasks_tracked", "task_guard_dead_letters",
                     "task_graph_branches_created", "task_graph_resume_events",
                     "task_role_loop_enabled", "task_role_loop_mode",
                     "task_role_loop_runs", "task_worker_restarts"]:
            val = runtime.get(key)
            if val is not None:
                print(f"  {key}: {val}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-tasks: Task engine inspector for Bob",
        epilog="Examples:\n"
               "  python bob_tasks.py list --status open\n"
               "  python bob_tasks.py show 5\n"
               "  python bob_tasks.py artifacts --owner 1\n"
               "  python bob_tasks.py stats\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["list", "show", "artifacts", "checkpoints", "deadletters", "stats"],
                        help="Command to run")
    parser.add_argument("task_id", nargs="?", help="Task ID (for show command)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--owner", type=int, help="Filter by owner ID")
    parser.add_argument("--status", help="Filter by status (open, done, failed)")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    db_path = find_db(args.db)
    if not db_path:
        # Some commands only need API
        if args.command == "stats":
            print("  (DB not found, showing runtime metrics only)")
            runtime, err = fetch_json(f"{args.url}/status/runtime")
            if runtime:
                print("=" * 60)
                print("  bob-tasks: Runtime Task Metrics")
                print("=" * 60)
                print()
                for key in sorted(runtime):
                    if "task" in key.lower():
                        print(f"  {key}: {runtime[key]}")
                print()
            else:
                print(f"  Bob not running: {err}")
            return
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        commands = {
            "list": cmd_list,
            "show": cmd_show,
            "artifacts": cmd_artifacts,
            "checkpoints": cmd_checkpoints,
            "deadletters": cmd_deadletters,
            "stats": cmd_stats,
        }
        commands[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

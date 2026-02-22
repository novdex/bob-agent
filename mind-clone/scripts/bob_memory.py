#!/usr/bin/env python3
"""bob-memory: Inspect Bob's memory systems from the command line.

Query lessons, episodic memories, research notes, task artifacts,
and improvement notes stored in SQLite.

Usage:
    python bob_memory.py stats                    # Memory counts per type
    python bob_memory.py lessons --owner 1        # List recent lessons
    python bob_memory.py episodes --owner 1       # List episodic memories
    python bob_memory.py notes --owner 1          # List improvement notes
    python bob_memory.py vectors --stats          # Vector index statistics
    python bob_memory.py export --owner 1 --format md  # Export to markdown
"""

import argparse
import json
import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)

# Default DB paths to search
DB_SEARCH_PATHS = [
    os.path.join(MIND_CLONE_DIR, "data", "mind_clone.db"),
    os.path.expanduser("~/.mind-clone/mind_clone.db"),
    os.path.join(MIND_CLONE_DIR, "mind_clone.db"),
]


def find_db(db_path=None):
    """Find the SQLite database."""
    if db_path:
        if os.path.exists(db_path):
            return db_path
        print(f"Error: DB not found at {db_path}")
        sys.exit(1)

    # Check env var
    env_path = os.environ.get("MIND_CLONE_DB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    for path in DB_SEARCH_PATHS:
        if os.path.exists(path):
            return path

    print("Error: Database not found. Searched:")
    for p in DB_SEARCH_PATHS:
        print(f"  - {p}")
    print("Set MIND_CLONE_DB_PATH or use --db flag.")
    sys.exit(1)


def get_tables(conn):
    """Get list of tables in the database."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def cmd_stats(conn, args):
    """Show memory counts per type."""
    tables = get_tables(conn)

    memory_tables = {
        "episodic_memories": "Episodic Memories",
        "research_notes": "Research Notes",
        "task_artifacts": "Task Artifacts",
        "self_improvement_notes": "Improvement Notes",
        "conversation_summaries": "Conversation Summaries",
        "memory_vectors": "Memory Vectors",
        "conversation_messages": "Conversation Messages",
        "action_forecasts": "Action Forecasts",
        "tool_performance_logs": "Tool Performance Logs",
        "lessons": "Lessons",
        "goals": "Goals",
        "tasks": "Tasks",
        "users": "Users",
    }

    print("=" * 60)
    print("  bob-memory: Memory Statistics")
    print("=" * 60)
    print()

    total = 0
    for table, label in sorted(memory_tables.items(), key=lambda x: x[1]):
        if table in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                total += count
                print(f"  {label:30s} {count:>8,}")
            except Exception:
                print(f"  {label:30s} {'ERROR':>8}")
        else:
            print(f"  {label:30s} {'(none)':>8}")

    print(f"\n  {'TOTAL':30s} {total:>8,}")
    print()

    # Owner breakdown
    if "users" in tables:
        try:
            owners = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()
            if owners:
                print("  Owners:")
                for oid, name in owners[:20]:
                    print(f"    [{oid}] {name or '(unnamed)'}")
        except Exception:
            pass


def cmd_lessons(conn, args):
    """List recent lessons."""
    tables = get_tables(conn)
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if args.owner else ""
    limit = args.limit or 20

    print(f"  Recent Lessons (limit={limit}):")
    print()

    # Try memory_vectors with lesson type first
    if "memory_vectors" in tables:
        try:
            query = f"""
                SELECT id, owner_id, memory_type, text_preview, created_at
                FROM memory_vectors
                {owner_filter + ' AND' if owner_filter else 'WHERE'} memory_type LIKE '%lesson%'
                ORDER BY id DESC LIMIT {limit}
            """
            rows = conn.execute(query).fetchall()
            if rows:
                for row in rows:
                    print(f"  [{row[0]}] owner={row[1]} type={row[2]}")
                    print(f"    {(row[3] or '')[:120]}")
                    print(f"    created: {row[4]}")
                    print()
                print(f"  Total shown: {len(rows)}")
                return
        except Exception:
            pass

    # Fallback: episodic memories
    if "episodic_memories" in tables:
        try:
            query = f"""
                SELECT id, owner_id, situation, action, outcome, created_at
                FROM episodic_memories
                {owner_filter}
                ORDER BY id DESC LIMIT {limit}
            """
            rows = conn.execute(query).fetchall()
            for row in rows:
                print(f"  [{row[0]}] owner={row[1]}")
                print(f"    Situation: {(row[2] or '')[:100]}")
                print(f"    Action: {(row[3] or '')[:100]}")
                print(f"    Outcome: {(row[4] or '')[:100]}")
                print(f"    created: {row[5]}")
                print()
            print(f"  Total shown: {len(rows)}")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("  No lesson tables found.")


def cmd_episodes(conn, args):
    """List episodic memories."""
    tables = get_tables(conn)
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if args.owner else ""
    limit = args.limit or 20

    print(f"  Episodic Memories (limit={limit}):")
    print()

    if "episodic_memories" not in tables:
        print("  Table 'episodic_memories' not found.")
        return

    try:
        query = f"""
            SELECT id, owner_id, situation, action, outcome, tools_used, created_at
            FROM episodic_memories
            {owner_filter}
            ORDER BY id DESC LIMIT {limit}
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            print(f"  [{row[0]}] owner={row[1]} tools={row[5] or 'none'}")
            print(f"    S: {(row[2] or '')[:100]}")
            print(f"    A: {(row[3] or '')[:100]}")
            print(f"    O: {(row[4] or '')[:100]}")
            print(f"    created: {row[6]}")
            print()
        print(f"  Total shown: {len(rows)}")
    except Exception as e:
        print(f"  Error: {e}")


def cmd_notes(conn, args):
    """List improvement notes."""
    tables = get_tables(conn)
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if args.owner else ""
    limit = args.limit or 20

    print(f"  Self-Improvement Notes (limit={limit}):")
    print()

    if "self_improvement_notes" not in tables:
        print("  Table 'self_improvement_notes' not found.")
        return

    try:
        query = f"""
            SELECT id, owner_id, title, summary, priority, status, retrieval_count, created_at
            FROM self_improvement_notes
            {owner_filter}
            ORDER BY id DESC LIMIT {limit}
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            print(f"  [{row[0]}] owner={row[1]} priority={row[4]} status={row[5]} retrievals={row[6]}")
            print(f"    Title: {(row[2] or '')[:100]}")
            print(f"    Summary: {(row[3] or '')[:120]}")
            print(f"    created: {row[7]}")
            print()
        print(f"  Total shown: {len(rows)}")
    except Exception as e:
        print(f"  Error: {e}")


def cmd_vectors(conn, args):
    """Show vector index statistics."""
    tables = get_tables(conn)

    print("  Vector Index Statistics:")
    print()

    if "memory_vectors" not in tables:
        print("  Table 'memory_vectors' not found.")
        return

    try:
        total = conn.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0]
        print(f"  Total vectors: {total:,}")

        # By type
        types = conn.execute(
            "SELECT memory_type, COUNT(*) FROM memory_vectors GROUP BY memory_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        print("\n  By type:")
        for mtype, count in types:
            print(f"    {mtype:30s} {count:>8,}")

        # By owner
        owners = conn.execute(
            "SELECT owner_id, COUNT(*) FROM memory_vectors GROUP BY owner_id ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        print("\n  By owner (top 10):")
        for oid, count in owners:
            print(f"    owner={oid:6d} {count:>8,} vectors")

        # Embedding size check
        sample = conn.execute(
            "SELECT LENGTH(embedding) FROM memory_vectors LIMIT 1"
        ).fetchone()
        if sample:
            embed_bytes = sample[0] or 0
            dims = embed_bytes // 4  # float32
            print(f"\n  Embedding size: {embed_bytes} bytes ({dims} dimensions)")

    except Exception as e:
        print(f"  Error: {e}")


def cmd_export(conn, args):
    """Export memories to markdown or JSON."""
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if args.owner else ""
    fmt = args.format or "md"
    tables = get_tables(conn)

    memories = {}

    # Collect all memory types
    if "episodic_memories" in tables:
        try:
            rows = conn.execute(
                f"SELECT situation, action, outcome, created_at FROM episodic_memories {owner_filter} ORDER BY id DESC LIMIT 100"
            ).fetchall()
            memories["episodic"] = [{"situation": r[0], "action": r[1], "outcome": r[2], "created": r[3]} for r in rows]
        except Exception:
            pass

    if "self_improvement_notes" in tables:
        try:
            rows = conn.execute(
                f"SELECT title, summary, priority, status, created_at FROM self_improvement_notes {owner_filter} ORDER BY id DESC LIMIT 50"
            ).fetchall()
            memories["improvement_notes"] = [{"title": r[0], "summary": r[1], "priority": r[2], "status": r[3], "created": r[4]} for r in rows]
        except Exception:
            pass

    if "conversation_summaries" in tables:
        try:
            rows = conn.execute(
                f"SELECT summary_text, created_at FROM conversation_summaries {owner_filter} ORDER BY id DESC LIMIT 30"
            ).fetchall()
            memories["summaries"] = [{"text": r[0], "created": r[1]} for r in rows]
        except Exception:
            pass

    if fmt == "json":
        print(json.dumps(memories, indent=2, default=str))
    else:
        # Markdown format
        print("# Bob Memory Export\n")
        for mtype, items in memories.items():
            print(f"## {mtype.replace('_', ' ').title()} ({len(items)} items)\n")
            for item in items[:20]:
                for k, v in item.items():
                    if v:
                        print(f"- **{k}**: {str(v)[:200]}")
                print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-memory: Memory inspector for Bob",
        epilog="Examples:\n"
               "  python bob_memory.py stats\n"
               "  python bob_memory.py lessons --owner 1\n"
               "  python bob_memory.py vectors --stats\n"
               "  python bob_memory.py export --owner 1 --format md\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["stats", "lessons", "episodes", "notes", "vectors", "export"],
                        help="Command to run")
    parser.add_argument("--owner", type=int, help="Filter by owner ID")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--format", choices=["md", "json"], default="md", help="Export format")
    args = parser.parse_args()

    db_path = find_db(args.db)
    print(f"  Using DB: {db_path}\n")

    conn = sqlite3.connect(db_path)
    try:
        commands = {
            "stats": cmd_stats,
            "lessons": cmd_lessons,
            "episodes": cmd_episodes,
            "notes": cmd_notes,
            "vectors": cmd_vectors,
            "export": cmd_export,
        }
        commands[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

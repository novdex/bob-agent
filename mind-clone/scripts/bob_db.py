#!/usr/bin/env python3
"""bob-db: Database inspector for Bob's SQLite database.

Query table info, row counts, schema, migrations, and integrity.

Usage:
    python bob_db.py info                        # DB file info
    python bob_db.py tables [--sort rows|name]   # List tables with row counts
    python bob_db.py schema <table>              # Show column definitions
    python bob_db.py migrations                  # Migration status
    python bob_db.py integrity                   # Run integrity checks
    python bob_db.py orphans                     # Detect orphaned records
"""

import argparse
import os
import re
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)

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


def get_indexes(conn):
    """Get indexes grouped by table."""
    cursor = conn.execute("SELECT tbl_name, name FROM sqlite_master WHERE type='index' ORDER BY tbl_name")
    indexes = {}
    for tbl, name in cursor.fetchall():
        indexes.setdefault(tbl, []).append(name)
    return indexes


def cmd_info(conn, args, db_path):
    """Show DB file info."""
    print("=" * 60)
    print("  bob-db: Database Info")
    print("=" * 60)
    print()

    size_bytes = os.path.getsize(db_path)
    if size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    tables = get_tables(conn)
    indexes = get_indexes(conn)
    total_indexes = sum(len(v) for v in indexes.values())

    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]

    print(f"  Path:          {db_path}")
    print(f"  Size:          {size_str} ({size_bytes:,} bytes)")
    print(f"  Tables:        {len(tables)}")
    print(f"  Indexes:       {total_indexes}")
    print(f"  Page size:     {page_size:,} bytes")
    print(f"  Pages:         {page_count:,} (used) + {free_pages:,} (free)")
    print(f"  Journal mode:  {journal}")

    if free_pages > 0:
        reclaimable = free_pages * page_size
        print(f"  Reclaimable:   {reclaimable / 1024:.0f} KB (VACUUM to reclaim)")
    print()


def cmd_tables(conn, args, db_path):
    """List all tables with row counts."""
    print("=" * 60)
    print("  bob-db: Tables")
    print("=" * 60)
    print()

    tables = get_tables(conn)
    indexes = get_indexes(conn)
    sort_by = args.sort if hasattr(args, "sort") and args.sort else "rows"

    table_data = []
    for tbl in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
        except Exception:
            count = -1
        cols = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        idx_count = len(indexes.get(tbl, []))
        table_data.append((tbl, count, len(cols), idx_count))

    if sort_by == "name":
        table_data.sort(key=lambda x: x[0])
    else:
        table_data.sort(key=lambda x: x[1], reverse=True)

    print(f"  {'Table':<35s} {'Rows':>8s}  {'Cols':>4s}  {'Idx':>3s}")
    print(f"  {'-' * 35}  {'-' * 8}  {'-' * 4}  {'-' * 3}")

    total_rows = 0
    for tbl, count, cols, idx in table_data:
        count_str = f"{count:>8,}" if count >= 0 else "   ERROR"
        print(f"  {tbl:<35s} {count_str}  {cols:>4d}  {idx:>3d}")
        if count > 0:
            total_rows += count

    print(f"  {'-' * 35}  {'-' * 8}")
    print(f"  {'TOTAL (' + str(len(tables)) + ' tables)':<35s} {total_rows:>8,}")
    print()


def cmd_schema(conn, args, db_path):
    """Show column definitions for a table."""
    table = args.table
    if not table:
        print("Error: provide a table name (e.g., python bob_db.py schema users)")
        sys.exit(1)

    tables = get_tables(conn)
    if table not in tables:
        print(f"Error: table '{table}' not found. Available tables:")
        for t in tables:
            print(f"  - {t}")
        sys.exit(1)

    print(f"  Schema for '{table}':")
    print()

    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    print(f"  {'#':>3s}  {'Column':<30s} {'Type':<15s} {'Null':>4s}  {'Default':<20s} {'PK':>2s}")
    print(f"  {'-' * 3}  {'-' * 30} {'-' * 15} {'-' * 4}  {'-' * 20} {'-' * 2}")

    for cid, name, ctype, notnull, default, pk in cols:
        null_str = "NO" if notnull else "YES"
        default_str = str(default) if default is not None else ""
        pk_str = "*" if pk else ""
        print(f"  {cid:>3d}  {name:<30s} {ctype:<15s} {null_str:>4s}  {default_str:<20s} {pk_str:>2s}")

    # Show indexes
    idx_rows = conn.execute(
        f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? ORDER BY name",
        (table,),
    ).fetchall()
    if idx_rows:
        print(f"\n  Indexes ({len(idx_rows)}):")
        for name, sql in idx_rows:
            print(f"    {name}")
            if sql:
                print(f"      {sql}")

    # Row count
    try:
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print(f"\n  Row count: {count:,}")
    except Exception:
        pass
    print()


def cmd_migrations(conn, args, db_path):
    """Show migration status."""
    print("=" * 60)
    print("  bob-db: Migrations")
    print("=" * 60)
    print()

    tables = get_tables(conn)

    # Check schema_migrations table
    if "schema_migrations" not in tables:
        print("  [x] Table 'schema_migrations' not found.")
        print("      No migrations have been applied yet.")
        print()
        return

    rows = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()

    if rows:
        print(f"  Applied migrations ({len(rows)}):")
        print()
        for version, name, applied_at in rows:
            print(f"  [+] v{version}: {name}")
            print(f"      applied: {applied_at}")
        print()
    else:
        print("  No migrations applied yet.")
        print()

    # Try to find pending migrations from modular package source
    modular_dir = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")
    migration_source = None
    # Search for SCHEMA_MIGRATION_STEPS in modular package
    for candidate in [
        os.path.join(modular_dir, "database", "models.py"),
        os.path.join(modular_dir, "database", "__init__.py"),
        os.path.join(modular_dir, "database", "migrations.py"),
    ]:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if "SCHEMA_MIGRATION_STEPS" in content:
                    migration_source = content
                    break
            except Exception:
                continue
    if migration_source:
        try:
            # Find SCHEMA_MIGRATION_STEPS entries
            pattern = r'\(\s*(\d+)\s*,\s*"([^"]+)"'
            found = re.findall(pattern, migration_source[migration_source.find("SCHEMA_MIGRATION_STEPS"):migration_source.find("SCHEMA_MIGRATION_STEPS") + 5000])
            applied_versions = {r[0] for r in rows}
            pending = [(v, n) for v, n in found if int(v) not in {int(av) for av in applied_versions}]
            if pending:
                print(f"  Pending migrations ({len(pending)}):")
                for v, n in pending:
                    print(f"  [-] v{v}: {n}")
                print()
            else:
                print("  [+] All migrations applied.")
                print()
        except Exception:
            pass


def cmd_integrity(conn, args, db_path):
    """Run integrity checks."""
    print("=" * 60)
    print("  bob-db: Integrity Check")
    print("=" * 60)
    print()

    issues = 0

    # PRAGMA integrity_check
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result == "ok":
        print("  [+] PRAGMA integrity_check: ok")
    else:
        print(f"  [x] PRAGMA integrity_check FAILED: {result}")
        issues += 1

    # Foreign key check
    try:
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if not fk_violations:
            print("  [+] Foreign key violations: 0")
        else:
            print(f"  [x] Foreign key violations: {len(fk_violations)}")
            for v in fk_violations[:10]:
                print(f"      table={v[0]} rowid={v[1]} parent={v[2]}")
            issues += 1
    except Exception:
        print("  [-] Foreign key check: skipped (not enforced)")

    # Empty tables check
    tables = get_tables(conn)
    empty_tables = []
    for tbl in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
            if count == 0:
                empty_tables.append(tbl)
        except Exception:
            pass

    print(f"\n  Tables: {len(tables)} total, {len(tables) - len(empty_tables)} with data, {len(empty_tables)} empty")
    if empty_tables:
        print(f"  Empty tables: {', '.join(empty_tables[:10])}")
        if len(empty_tables) > 10:
            print(f"    ... and {len(empty_tables) - 10} more")

    # Schema version
    if "schema_migrations" in tables:
        try:
            max_v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            print(f"\n  [+] Schema version: {max_v}")
        except Exception:
            pass

    # Size analysis
    size_bytes = os.path.getsize(db_path)
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    free_kb = (free_pages * page_size) / 1024

    print(f"\n  DB size: {size_bytes / (1024 * 1024):.1f} MB")
    if free_kb > 100:
        print(f"  [-] {free_kb:.0f} KB reclaimable (run VACUUM)")
        issues += 1
    else:
        print(f"  [+] Free space: {free_kb:.0f} KB (healthy)")

    print()
    if issues == 0:
        print("  [+] All integrity checks passed.")
    else:
        print(f"  [x] {issues} issue(s) found.")
    print()


def cmd_orphans(conn, args, db_path):
    """Detect orphaned records."""
    print("=" * 60)
    print("  bob-db: Orphan Detection")
    print("=" * 60)
    print()

    tables = get_tables(conn)
    issues = 0

    # Check tables with owner_id against users table
    if "users" not in tables:
        print("  [-] No 'users' table found, skipping owner_id checks.")
        print()
        return

    owner_tables = []
    for tbl in tables:
        if tbl == "users":
            continue
        cols = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        col_names = [c[1] for c in cols]
        if "owner_id" in col_names:
            owner_tables.append(tbl)

    if not owner_tables:
        print("  No tables with owner_id found.")
        print()
        return

    for tbl in owner_tables:
        try:
            orphan_count = conn.execute(
                f'SELECT COUNT(*) FROM "{tbl}" WHERE owner_id NOT IN (SELECT id FROM users)'
            ).fetchone()[0]
            if orphan_count > 0:
                print(f"  [x] {tbl}: {orphan_count} orphaned rows (owner_id not in users)")
                issues += 1
            else:
                print(f"  [+] {tbl}: no orphans")
        except Exception as e:
            print(f"  [-] {tbl}: check failed ({e})")

    print()
    if issues == 0:
        print("  [+] No orphaned records found.")
    else:
        print(f"  [x] {issues} table(s) with orphaned records.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-db: Database inspector for Bob",
        epilog="Examples:\n"
               "  python bob_db.py info\n"
               "  python bob_db.py tables --sort name\n"
               "  python bob_db.py schema users\n"
               "  python bob_db.py migrations\n"
               "  python bob_db.py integrity\n"
               "  python bob_db.py orphans\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["info", "tables", "schema", "migrations", "integrity", "orphans"],
                        help="Command to run")
    parser.add_argument("table", nargs="?", help="Table name (for schema command)")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--sort", choices=["rows", "name"], default="rows", help="Sort tables by (default: rows)")

    args = parser.parse_args()
    db_path = find_db(args.db)
    print(f"  Using DB: {db_path}\n")

    conn = sqlite3.connect(db_path)
    try:
        commands = {
            "info": cmd_info,
            "tables": cmd_tables,
            "schema": cmd_schema,
            "migrations": cmd_migrations,
            "integrity": cmd_integrity,
            "orphans": cmd_orphans,
        }
        commands[args.command](conn, args, db_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

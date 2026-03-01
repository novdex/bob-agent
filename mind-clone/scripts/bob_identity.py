#!/usr/bin/env python3
"""bob-identity: User and identity diagnostics for Bob.

Inspect users, approval queue, identity links, team agents,
and authority configuration.

Usage:
    python bob_identity.py users                    # List all users
    python bob_identity.py show <id>                # Detailed user view
    python bob_identity.py approvals [--status pending]  # Approval requests
    python bob_identity.py links                    # Identity links
    python bob_identity.py team [--owner 1]         # Team agents
    python bob_identity.py authority                # Authority config
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
    print("Error: Database not found. Use --db flag.")
    sys.exit(1)


def fetch_json(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, str(e)


def read_env_value(key):
    env_path = os.path.join(MIND_CLONE_DIR, ".env")
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line[len(key) + 1:].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def mask_secret(value):
    if not value or len(value) < 10:
        return "(short)"
    return f"{value[:4]}...{value[-4:]}"


def get_tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]


def get_cols(conn, table):
    return [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def cmd_users(conn, args):
    """List all users."""
    tables = get_tables(conn)
    if "users" not in tables:
        print("  Table 'users' not found.")
        return

    cols = get_cols(conn, "users")

    print("=" * 60)
    print("  bob-identity: Users")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM users ORDER BY id").fetchall()

        if not rows:
            print("  No users found.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            uid = data.get("id", "?")
            username = data.get("username", "(unnamed)")
            tg_chat = data.get("telegram_chat_id")
            created = data.get("created_at", "?")

            print(f"  [{uid}] {username}")
            if tg_chat:
                print(f"      telegram_chat_id: {tg_chat}")
            print(f"      created: {created}")

            # Identity kernel
            if "identity_kernels" in tables:
                try:
                    ik = conn.execute(
                        "SELECT agent_uuid, core_values FROM identity_kernels WHERE owner_id = ?", (uid,)
                    ).fetchone()
                    if ik:
                        values_preview = str(ik[1])[:60] if ik[1] else "(none)"
                        print(f"      identity: uuid={ik[0] or '?'} values={values_preview}")
                    else:
                        print(f"      identity: (default)")
                except Exception:
                    pass

            # Message count
            if "conversation_messages" in tables:
                try:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM conversation_messages WHERE owner_id = ?", (uid,)
                    ).fetchone()[0]
                    print(f"      messages: {count:,}")
                except Exception:
                    pass

            # Team agents count
            if "team_agents" in tables:
                try:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM team_agents WHERE owner_id = ?", (uid,)
                    ).fetchone()[0]
                    if count > 0:
                        print(f"      team agents: {count}")
                except Exception:
                    pass
            print()

        print(f"  Total: {len(rows)} user(s)")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_show(conn, args):
    """Detailed view of a single user."""
    if not args.user_id:
        print("  Error: provide a user ID (e.g., python bob_identity.py show 1)")
        sys.exit(1)

    tables = get_tables(conn)
    if "users" not in tables:
        print("  Table 'users' not found.")
        return

    uid = int(args.user_id)
    cols = get_cols(conn, "users")

    try:
        row = conn.execute(f"SELECT {', '.join(cols)} FROM users WHERE id = ?", (uid,)).fetchone()
        if not row:
            print(f"  User {uid} not found.")
            return

        data = dict(zip(cols, row))

        print("=" * 60)
        print(f"  bob-identity: User #{uid}")
        print("=" * 60)
        print()

        for key, val in data.items():
            if val is not None:
                print(f"  {key}: {val}")

        # Identity kernel
        if "identity_kernels" in tables:
            ik_cols = get_cols(conn, "identity_kernels")
            ik = conn.execute(
                f"SELECT {', '.join(ik_cols)} FROM identity_kernels WHERE owner_id = ?", (uid,)
            ).fetchone()
            if ik:
                ik_data = dict(zip(ik_cols, ik))
                print(f"\n  --- Identity Kernel ---")
                for k in ["agent_uuid", "origin_statement", "core_values", "authority_bounds"]:
                    if k in ik_data and ik_data[k]:
                        val = str(ik_data[k])[:150]
                        print(f"  {k}: {val}")

        # Identity links
        if "identity_links" in tables:
            links = conn.execute(
                "SELECT * FROM identity_links WHERE canonical_owner_id = ?", (uid,)
            ).fetchall()
            if links:
                link_cols = get_cols(conn, "identity_links")
                print(f"\n  --- Identity Links ({len(links)}) ---")
                for link in links:
                    ld = dict(zip(link_cols, link))
                    print(f"  chat_id={ld.get('linked_chat_id', '?')} user={ld.get('linked_username', '?')} scope={ld.get('scope_mode', '?')}")

        # Team agents
        if "team_agents" in tables:
            agents = conn.execute(
                "SELECT * FROM team_agents WHERE owner_id = ?", (uid,)
            ).fetchall()
            if agents:
                agent_cols = get_cols(conn, "team_agents")
                print(f"\n  --- Team Agents ({len(agents)}) ---")
                for agent in agents:
                    ad = dict(zip(agent_cols, agent))
                    print(f"  key={ad.get('agent_key', '?')} name={ad.get('display_name', '?')} status={ad.get('status', '?')}")

        # Recent approval requests
        if "approval_requests" in tables:
            approvals = conn.execute(
                "SELECT * FROM approval_requests WHERE owner_id = ? ORDER BY rowid DESC LIMIT 5", (uid,)
            ).fetchall()
            if approvals:
                apr_cols = get_cols(conn, "approval_requests")
                print(f"\n  --- Recent Approvals ---")
                for apr in approvals:
                    ad = dict(zip(apr_cols, apr))
                    token = mask_secret(ad.get("token")) if ad.get("token") else "?"
                    print(f"  tool={ad.get('tool_name', '?')} status={ad.get('status', '?')} token={token}")
                    if ad.get("created_at"):
                        print(f"    created: {ad['created_at']}")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_approvals(conn, args):
    """List approval requests."""
    tables = get_tables(conn)
    if "approval_requests" not in tables:
        print("  Table 'approval_requests' not found.")
        return

    cols = get_cols(conn, "approval_requests")
    status_filter = ""
    if hasattr(args, "status") and args.status:
        status_filter = f"WHERE status = '{args.status}'"

    print("=" * 60)
    print("  bob-identity: Approval Requests")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM approval_requests {status_filter} ORDER BY rowid DESC LIMIT 30"
        ).fetchall()

        if not rows:
            print("  No approval requests found.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            token = mask_secret(data.get("token")) if data.get("token") else "?"
            tool = data.get("tool_name", "?")
            status = data.get("status", "?")
            owner = data.get("owner_id", "?")
            source = data.get("source_type", "?")

            mark = "[+]" if status == "approved" else "[x]" if status == "rejected" else "[-]"

            print(f"  {mark} owner={owner} tool={tool} status={status}")
            print(f"      source={source} token={token}")

            if data.get("tool_args_json"):
                try:
                    args_preview = str(data["tool_args_json"])[:80]
                    print(f"      args: {args_preview}")
                except Exception:
                    pass

            if data.get("decision_reason"):
                print(f"      reason: {data['decision_reason']}")
            if data.get("created_at"):
                print(f"      created: {data['created_at']}")
            if status == "pending" and data.get("expires_at"):
                print(f"      expires: {data['expires_at']}")
            print()

        # Counts
        total = conn.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM approval_requests WHERE status = 'approved'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM approval_requests WHERE status = 'rejected'").fetchone()[0]

        print(f"  Total: {total} ({pending} pending, {approved} approved, {rejected} rejected)")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_links(conn, args):
    """Show identity links."""
    tables = get_tables(conn)
    if "identity_links" not in tables:
        print("  Table 'identity_links' not found.")
        return

    cols = get_cols(conn, "identity_links")

    print("=" * 60)
    print("  bob-identity: Identity Links")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM identity_links ORDER BY rowid").fetchall()

        if not rows:
            print("  No identity links found.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            print(f"  canonical_owner={data.get('canonical_owner_id', '?')} -> "
                  f"chat_id={data.get('linked_chat_id', '?')} "
                  f"user={data.get('linked_username', '?')} "
                  f"scope={data.get('scope_mode', '?')}")

        print(f"\n  Total: {len(rows)} link(s)")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_team(conn, args):
    """List team agents."""
    tables = get_tables(conn)
    if "team_agents" not in tables:
        print("  Table 'team_agents' not found.")
        return

    cols = get_cols(conn, "team_agents")
    owner_filter = f"WHERE owner_id = {int(args.owner)}" if hasattr(args, "owner") and args.owner else ""

    print("=" * 60)
    print("  bob-identity: Team Agents")
    print("=" * 60)
    print()

    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM team_agents {owner_filter} ORDER BY rowid"
        ).fetchall()

        if not rows:
            print("  No team agents found.")
            return

        for row in rows:
            data = dict(zip(cols, row))
            print(f"  [{data.get('agent_owner_id', '?')}] key={data.get('agent_key', '?')} "
                  f"name={data.get('display_name', '?')}")
            print(f"      owner={data.get('owner_id', '?')} status={data.get('status', '?')}")
            if data.get("workspace_root"):
                print(f"      workspace: {data['workspace_root']}")
            print()

        print(f"  Total: {len(rows)} team agent(s)")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_authority(conn, args):
    """Show authority/permission config."""
    print("=" * 60)
    print("  bob-identity: Authority Config")
    print("=" * 60)
    print()

    # From .env
    print(f"  --- Configuration (.env) ---")
    full_power = read_env_value("BOB_FULL_POWER_ENABLED") or "false"
    full_scope = read_env_value("BOB_FULL_POWER_SCOPE") or "(default)"
    gate_mode = read_env_value("APPROVAL_GATE_MODE") or "balanced"
    scope_mode = read_env_value("IDENTITY_SCOPE_MODE") or "strict_chat"
    team_mode = read_env_value("TEAM_MODE_ENABLED") or "false"

    print(f"  Full Power:        {full_power}")
    print(f"  Full Power Scope:  {full_scope}")
    print(f"  Approval Gate:     {gate_mode}")
    print(f"  Identity Scope:    {scope_mode}")
    print(f"  Team Mode:         {team_mode}")

    # Runtime
    runtime, err = fetch_json(f"{args.url}/status/runtime")
    if runtime:
        print(f"\n  --- Runtime ---")
        for key in ["approval_gate_mode", "approval_required_count", "approval_pending_count",
                     "approval_approved_count", "approval_rejected_count",
                     "team_mode_enabled", "identity_scope_mode",
                     "team_agents_total", "team_broadcasts_total"]:
            val = runtime.get(key)
            if val is not None:
                print(f"  {key}: {val}")
    else:
        print(f"\n  (Bob not running: {err})")

    # Diagnosis
    print(f"\n  --- Diagnosis ---")
    if full_power.lower() == "true":
        print(f"  [-] Full power ENABLED (scope: {full_scope})")
    else:
        print("  [+] Full power disabled (safe)")

    if gate_mode == "off":
        print("  [-] Approval gate OFF (no approvals required)")
    else:
        print(f"  [+] Approval gate: {gate_mode}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-identity: User & identity diagnostics for Bob",
        epilog="Examples:\n"
               "  python bob_identity.py users\n"
               "  python bob_identity.py show 1\n"
               "  python bob_identity.py approvals --status pending\n"
               "  python bob_identity.py authority\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["users", "show", "approvals", "links", "team", "authority"],
                        help="Command to run")
    parser.add_argument("user_id", nargs="?", help="User ID (for show command)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--owner", type=int, help="Filter by owner ID")
    parser.add_argument("--status", help="Filter by status (pending, approved, rejected)")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    # authority command doesn't need DB
    if args.command == "authority":
        db_path = find_db(args.db) if args.db else None
        conn = sqlite3.connect(db_path) if db_path else None
        cmd_authority(conn, args)
        if conn:
            conn.close()
        return

    db_path = find_db(args.db)
    conn = sqlite3.connect(db_path)
    try:
        commands = {
            "users": cmd_users,
            "show": cmd_show,
            "approvals": cmd_approvals,
            "links": cmd_links,
            "team": cmd_team,
        }
        commands[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""bob-telegram: Telegram integration diagnostics for Bob.

Check bot connectivity, webhook/polling status, message history,
and known Telegram users.

Usage:
    python bob_telegram.py status               # Overall Telegram status
    python bob_telegram.py test-bot             # Verify bot token via Telegram API
    python bob_telegram.py webhook              # Check webhook configuration
    python bob_telegram.py messages [--limit 20] # Recent messages from Telegram users
    python bob_telegram.py users                # Known Telegram users
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error

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


def read_env_value(key):
    """Read a value from .env file."""
    env_path = os.path.join(MIND_CLONE_DIR, ".env")
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    val = line[len(key) + 1:].strip().strip('"').strip("'")
                    return val
    except Exception:
        pass
    return None


def mask_secret(value):
    if not value or len(value) < 10:
        return "(too short)"
    return f"{value[:4]}...{value[-4:]}"


def token_status():
    """Check if bot token is configured."""
    val = read_env_value("TELEGRAM_BOT_TOKEN")
    if not val:
        return "missing", None
    placeholders = ["your_", "_here", "placeholder"]
    if any(p in val.lower() for p in placeholders):
        return "placeholder", val
    return "configured", val


def cmd_status(args):
    """Overall Telegram subsystem status."""
    print("=" * 60)
    print("  bob-telegram: Telegram Diagnostics")
    print("=" * 60)

    # Configuration
    print("\n  --- Configuration ---")
    status, token = token_status()
    if status == "configured":
        print(f"  Bot Token:       configured ({mask_secret(token)})")
    elif status == "placeholder":
        print(f"  Bot Token:       PLACEHOLDER (not set)")
    else:
        print(f"  Bot Token:       MISSING")

    webhook_url = read_env_value("WEBHOOK_BASE_URL")
    print(f"  Webhook URL:     {webhook_url or '(not set - polling mode)'}")

    # Runtime data
    runtime, err = fetch_json(f"{args.url}/status/runtime")

    print("\n  --- Runtime ---")
    if runtime:
        for key in ["telegram_token_configured", "telegram_webhook_configured",
                     "webhook_registered", "telegram_polling_active",
                     "telegram_poll_restarts", "webhook_supervisor_restarts",
                     "webhook_last_attempt", "webhook_last_success",
                     "webhook_last_error", "webhook_next_retry_at"]:
            val = runtime.get(key)
            if val is not None:
                print(f"  {key}: {val}")
    else:
        print(f"  (Bob not running: {err})")

    # Bot info via Telegram API
    if status == "configured" and token:
        print("\n  --- Bot Info (from Telegram API) ---")
        bot_data, bot_err = fetch_json(f"https://api.telegram.org/bot{token}/getMe")
        if bot_data and bot_data.get("ok"):
            result = bot_data["result"]
            print(f"  Username:      @{result.get('username', '?')}")
            print(f"  Bot ID:        {result.get('id', '?')}")
            print(f"  First Name:    {result.get('first_name', '?')}")
            print(f"  Can Groups:    {result.get('can_join_groups', '?')}")
        elif bot_err:
            print(f"  [x] API error: {bot_err}")
        else:
            print(f"  [x] API returned: {bot_data}")

    # Diagnosis
    print("\n  --- Diagnosis ---")
    if status != "configured":
        print(f"  [x] Bot token {status}! Set TELEGRAM_BOT_TOKEN in .env")
    else:
        print("  [+] Bot token configured")

    if runtime:
        if runtime.get("telegram_polling_active"):
            print("  [+] Telegram polling active")
        elif runtime.get("webhook_registered"):
            print("  [+] Webhook registered")
        else:
            print("  [-] Neither polling nor webhook active")

        if runtime.get("webhook_last_error"):
            print(f"  [-] Last webhook error: {runtime.get('webhook_last_error')}")
    print()


def cmd_test_bot(args):
    """Verify bot token via Telegram API."""
    print("=" * 60)
    print("  bob-telegram: Bot Token Test")
    print("=" * 60)
    print()

    status, token = token_status()
    if status != "configured":
        print(f"  [x] Bot token {status}. Set TELEGRAM_BOT_TOKEN in .env")
        sys.exit(1)

    # getMe
    print(f"  Testing token {mask_secret(token)}...")
    print()

    bot_data, bot_err = fetch_json(f"https://api.telegram.org/bot{token}/getMe")
    if bot_data and bot_data.get("ok"):
        result = bot_data["result"]
        print(f"  [+] Bot is valid!")
        print(f"  Username:      @{result.get('username', '?')}")
        print(f"  Bot ID:        {result.get('id', '?')}")
        print(f"  First Name:    {result.get('first_name', '?')}")
        print(f"  Can Groups:    {result.get('can_join_groups', '?')}")
    else:
        print(f"  [x] Bot token INVALID!")
        if bot_err:
            print(f"  Error: {bot_err}")
        elif bot_data:
            print(f"  Response: {bot_data}")
        sys.exit(1)

    # getWebhookInfo
    print()
    wh_data, wh_err = fetch_json(f"https://api.telegram.org/bot{token}/getWebhookInfo")
    if wh_data and wh_data.get("ok"):
        result = wh_data["result"]
        wh_url = result.get("url", "")
        pending = result.get("pending_update_count", 0)
        print(f"  Webhook URL:     {wh_url or '(none - polling mode)'}")
        print(f"  Pending updates: {pending}")
        if result.get("last_error_message"):
            print(f"  Last error:      {result['last_error_message']}")
    print()


def cmd_webhook(args):
    """Check webhook configuration."""
    print("=" * 60)
    print("  bob-telegram: Webhook Status")
    print("=" * 60)
    print()

    status, token = token_status()
    if status != "configured":
        print(f"  [x] Bot token {status}.")
        sys.exit(1)

    # From .env
    configured_url = read_env_value("WEBHOOK_BASE_URL")
    print(f"  Configured URL (.env): {configured_url or '(not set)'}")

    # From Telegram API
    wh_data, wh_err = fetch_json(f"https://api.telegram.org/bot{token}/getWebhookInfo")
    if wh_data and wh_data.get("ok"):
        result = wh_data["result"]
        registered_url = result.get("url", "")
        print(f"  Registered URL (Telegram): {registered_url or '(none)'}")
        print(f"  Pending updates: {result.get('pending_update_count', 0)}")
        print(f"  Max connections: {result.get('max_connections', 'default')}")
        print(f"  Allowed updates: {result.get('allowed_updates', 'all')}")
        if result.get("last_error_date"):
            print(f"  Last error date: {result.get('last_error_date')}")
            print(f"  Last error msg:  {result.get('last_error_message', '?')}")

        # Compare
        print()
        if not configured_url and not registered_url:
            print("  [+] No webhook configured (polling mode)")
        elif configured_url and registered_url:
            expected = f"{configured_url.rstrip('/')}/telegram/webhook"
            if expected == registered_url:
                print("  [+] Webhook matches configuration")
            else:
                print(f"  [-] MISMATCH: expected {expected}")
                print(f"                got      {registered_url}")
        elif configured_url and not registered_url:
            print("  [-] URL configured in .env but NOT registered with Telegram")
        elif not configured_url and registered_url:
            print("  [-] Webhook registered but WEBHOOK_BASE_URL not in .env")
    else:
        print(f"  [x] Could not fetch webhook info: {wh_err}")
    print()


def cmd_messages(args):
    """Recent messages from Telegram users."""
    print("=" * 60)
    print("  bob-telegram: Recent Messages")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    limit = args.limit if hasattr(args, "limit") and args.limit else 20

    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "conversation_messages" not in tables or "users" not in tables:
        print("  Required tables not found (conversation_messages, users).")
        conn.close()
        return

    try:
        # Get Telegram users
        user_cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "telegram_chat_id" not in user_cols:
            print("  Column 'telegram_chat_id' not in users table.")
            conn.close()
            return

        tg_users = conn.execute(
            "SELECT id, username, telegram_chat_id FROM users WHERE telegram_chat_id IS NOT NULL"
        ).fetchall()

        if not tg_users:
            print("  No Telegram users found.")
            conn.close()
            return

        tg_owner_ids = [u[0] for u in tg_users]

        # Get recent messages from these users
        placeholders = ",".join("?" * len(tg_owner_ids))
        msg_cols = [c[1] for c in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()]

        role_col = "role" if "role" in msg_cols else None
        content_col = "content" if "content" in msg_cols else "message" if "message" in msg_cols else None

        if not content_col:
            print("  Could not find content/message column.")
            conn.close()
            return

        select = f"id, owner_id, {role_col + ', ' if role_col else ''}{content_col}, created_at"
        rows = conn.execute(
            f"SELECT {select} FROM conversation_messages "
            f"WHERE owner_id IN ({placeholders}) "
            f"ORDER BY id DESC LIMIT {int(limit)}",
            tg_owner_ids,
        ).fetchall()

        if not rows:
            print("  No messages found for Telegram users.")
            conn.close()
            return

        for row in rows:
            idx = 0
            msg_id = row[idx]; idx += 1
            owner = row[idx]; idx += 1
            role = row[idx] if role_col else "?"; idx += 1 if role_col else 0
            content = row[idx]; idx += 1
            created = row[idx]

            content_preview = (str(content) or "")[:120].replace("\n", " ")
            print(f"  [{msg_id}] owner={owner} role={role} {created}")
            print(f"    {content_preview}")
            print()

        print(f"  Showing {len(rows)} of last {limit} messages")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def cmd_users(args):
    """Known Telegram users."""
    print("=" * 60)
    print("  bob-telegram: Telegram Users")
    print("=" * 60)
    print()

    db_path = find_db(args.db if hasattr(args, "db") else None)
    if not db_path:
        print("  Database not found. Use --db flag.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "users" not in tables:
        print("  Table 'users' not found.")
        conn.close()
        return

    try:
        user_cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "telegram_chat_id" not in user_cols:
            print("  Column 'telegram_chat_id' not in users table.")
            conn.close()
            return

        rows = conn.execute(
            "SELECT id, username, telegram_chat_id, created_at FROM users "
            "WHERE telegram_chat_id IS NOT NULL ORDER BY id"
        ).fetchall()

        if not rows:
            print("  No Telegram users found.")
            conn.close()
            return

        for uid, username, chat_id, created in rows:
            print(f"  [{uid}] {username or '(unnamed)'}")
            print(f"      telegram_chat_id: {chat_id}")
            print(f"      created: {created}")

            # Message count
            if "conversation_messages" in tables:
                try:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM conversation_messages WHERE owner_id = ?", (uid,)
                    ).fetchone()[0]
                    print(f"      messages: {count:,}")
                except Exception:
                    pass
            print()

        print(f"  Total: {len(rows)} Telegram user(s)")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()
    print()


def main():
    parser = argparse.ArgumentParser(
        description="bob-telegram: Telegram diagnostics for Bob",
        epilog="Examples:\n"
               "  python bob_telegram.py status\n"
               "  python bob_telegram.py test-bot\n"
               "  python bob_telegram.py webhook\n"
               "  python bob_telegram.py messages --limit 10\n"
               "  python bob_telegram.py users\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["status", "test-bot", "webhook", "messages", "users"],
                        help="Command to run")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Bob API URL (default: {DEFAULT_URL})")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    args = parser.parse_args()
    args.url = args.url.rstrip("/")

    commands = {
        "status": cmd_status,
        "test-bot": cmd_test_bot,
        "webhook": cmd_webhook,
        "messages": cmd_messages,
        "users": cmd_users,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

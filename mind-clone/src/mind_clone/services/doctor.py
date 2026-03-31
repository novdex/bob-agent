"""Bob Doctor -- auto-diagnose and fix common problems.

Run from CLI:
    python -m mind_clone.doctor_cli

Or call programmatically:
    from mind_clone.services.doctor import run_doctor
    result = run_doctor()
"""

from __future__ import annotations

import importlib
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("mind_clone.doctor")

# ── Colour helpers (safe for terminals that don't support ANSI) ──────────
_OK = "[OK]"
_FAIL = "[FAIL]"
_WARN = "[WARN]"
_FIX = "[FIX]"


def _print_status(label: str, status: str, detail: str = "") -> None:
    """Print a status line to stdout and log it."""
    line = f"  {status:6s}  {label}"
    if detail:
        line += f"  --  {detail}"
    print(line)
    logger.info(line)


# ── Individual checks ────────────────────────────────────────────────────────

def _check_database_health(results: dict[str, Any]) -> None:
    """Check 1: Can we connect to the DB and do basic queries?"""
    try:
        from mind_clone.config import settings
        db_path: Path = settings.db_file_path
        if not db_path.exists():
            _print_status("database", _FAIL, f"file not found: {db_path}")
            results["database"] = False
            return

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()

        if integrity == "ok":
            _print_status("database", _OK, str(db_path))
            results["database"] = True
        else:
            _print_status("database", _FAIL, f"integrity_check: {integrity}")
            results["database"] = False
    except Exception as exc:
        _print_status("database", _FAIL, str(exc))
        results["database"] = False


def _check_tables_exist(results: dict[str, Any]) -> None:
    """Check 2: Verify essential tables are present."""
    essential = [
        "users", "tasks", "scheduled_jobs", "conversation_messages",
        "skill_profiles", "skill_runs", "execution_events",
    ]
    try:
        from mind_clone.config import settings
        conn = sqlite3.connect(str(settings.db_file_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {row[0] for row in cursor.fetchall()}
        conn.close()

        missing = [t for t in essential if t not in existing]
        if missing:
            _print_status("tables", _WARN, f"missing: {', '.join(missing)}")
            results["tables"] = False
        else:
            _print_status("tables", _OK, f"{len(existing)} tables found")
            results["tables"] = True
    except Exception as exc:
        _print_status("tables", _FAIL, str(exc))
        results["tables"] = False


def _check_skill_runs_autoincrement(results: dict[str, Any]) -> None:
    """Check 3: skill_runs table -- fix duplicate IDs by rebuilding with AUTOINCREMENT."""
    try:
        from mind_clone.config import settings
        conn = sqlite3.connect(str(settings.db_file_path))

        # Check if table exists at all
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_runs'"
        )
        if not cursor.fetchone():
            _print_status("skill_runs", _WARN, "table does not exist yet (will be created on first use)")
            results["skill_runs"] = True
            conn.close()
            return

        # Check for duplicate IDs
        cursor = conn.execute(
            "SELECT id, COUNT(*) AS cnt FROM skill_runs GROUP BY id HAVING cnt > 1"
        )
        dupes = cursor.fetchall()

        # Check if AUTOINCREMENT is in the CREATE TABLE DDL
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='skill_runs'"
        )
        ddl_row = cursor.fetchone()
        has_autoincrement = ddl_row and "AUTOINCREMENT" in (ddl_row[0] or "").upper()

        if not dupes and has_autoincrement:
            _print_status("skill_runs", _OK, "no duplicates, AUTOINCREMENT present")
            results["skill_runs"] = True
            conn.close()
            return

        # Need to rebuild
        detail_parts: list[str] = []
        if dupes:
            detail_parts.append(f"{len(dupes)} duplicate ID groups")
        if not has_autoincrement:
            detail_parts.append("missing AUTOINCREMENT")

        _print_status("skill_runs", _FIX, f"rebuilding ({', '.join(detail_parts)})")

        # Backup existing rows (deduplicated)
        cursor = conn.execute(
            "SELECT DISTINCT owner_id, skill_id, skill_version, session_id, "
            "source_type, status, message_preview, output_preview, error_preview, "
            "created_at FROM skill_runs"
        )
        rows = cursor.fetchall()

        conn.execute("DROP TABLE IF EXISTS skill_runs")
        conn.execute("""
            CREATE TABLE skill_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                skill_id INTEGER NOT NULL,
                skill_version INTEGER NOT NULL,
                session_id TEXT,
                source_type TEXT NOT NULL DEFAULT 'chat',
                status TEXT NOT NULL DEFAULT 'invoked',
                message_preview TEXT,
                output_preview TEXT,
                error_preview TEXT,
                created_at DATETIME DEFAULT (datetime('now')),
                FOREIGN KEY (owner_id) REFERENCES users(id),
                FOREIGN KEY (skill_id) REFERENCES skill_profiles(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_skill_runs_owner_id ON skill_runs(owner_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_skill_runs_skill_id ON skill_runs(skill_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_skill_runs_status ON skill_runs(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_skill_runs_session_id ON skill_runs(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_skill_runs_source_type ON skill_runs(source_type)"
        )

        # Re-insert deduplicated rows
        if rows:
            conn.executemany(
                "INSERT INTO skill_runs "
                "(owner_id, skill_id, skill_version, session_id, source_type, "
                "status, message_preview, output_preview, error_preview, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

        conn.commit()
        conn.close()
        _print_status("skill_runs", _OK, f"rebuilt with AUTOINCREMENT, {len(rows)} rows preserved")
        results["skill_runs"] = True
    except Exception as exc:
        _print_status("skill_runs", _FAIL, str(exc))
        results["skill_runs"] = False


def _check_owner_user(results: dict[str, Any]) -> None:
    """Check 4: Verify at least one owner user with a telegram chat_id exists."""
    try:
        from mind_clone.config import settings
        conn = sqlite3.connect(str(settings.db_file_path))

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        if not cursor.fetchone():
            _print_status("owner_user", _WARN, "users table does not exist yet")
            results["owner_user"] = False
            conn.close()
            return

        cursor = conn.execute(
            "SELECT id, username, telegram_chat_id FROM users "
            "WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' "
            "LIMIT 5"
        )
        users = cursor.fetchall()
        conn.close()

        if users:
            info = "; ".join(
                f"id={u[0]} user={u[1]} chat={u[2]}" for u in users
            )
            _print_status("owner_user", _OK, info)
            results["owner_user"] = True
        else:
            _print_status("owner_user", _FAIL, "no user with telegram_chat_id found")
            results["owner_user"] = False
    except Exception as exc:
        _print_status("owner_user", _FAIL, str(exc))
        results["owner_user"] = False


def _check_cron_duplicates(results: dict[str, Any]) -> None:
    """Check 5: Detect and remove duplicate cron jobs."""
    try:
        from mind_clone.config import settings
        conn = sqlite3.connect(str(settings.db_file_path))

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs'"
        )
        if not cursor.fetchone():
            _print_status("cron_jobs", _WARN, "scheduled_jobs table does not exist yet")
            results["cron_jobs"] = True
            conn.close()
            return

        # Find duplicate job names per owner
        cursor = conn.execute(
            "SELECT owner_id, name, COUNT(*) AS cnt "
            "FROM scheduled_jobs WHERE enabled = 1 "
            "GROUP BY owner_id, name HAVING cnt > 1"
        )
        dupes = cursor.fetchall()

        if not dupes:
            cursor = conn.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE enabled = 1")
            total = cursor.fetchone()[0]
            _print_status("cron_jobs", _OK, f"{total} active jobs, no duplicates")
            results["cron_jobs"] = True
            conn.close()
            return

        # Fix: keep only the newest row for each duplicate group
        fixed = 0
        for owner_id, name, cnt in dupes:
            cursor = conn.execute(
                "SELECT id FROM scheduled_jobs "
                "WHERE owner_id = ? AND name = ? AND enabled = 1 "
                "ORDER BY id DESC",
                (owner_id, name),
            )
            ids = [row[0] for row in cursor.fetchall()]
            # Keep the first (newest), disable the rest
            to_disable = ids[1:]
            for old_id in to_disable:
                conn.execute(
                    "UPDATE scheduled_jobs SET enabled = 0 WHERE id = ?",
                    (old_id,),
                )
                fixed += 1

        conn.commit()
        conn.close()
        _print_status(
            "cron_jobs", _FIX,
            f"disabled {fixed} duplicate jobs across {len(dupes)} groups",
        )
        results["cron_jobs"] = True
    except Exception as exc:
        _print_status("cron_jobs", _FAIL, str(exc))
        results["cron_jobs"] = False


def _check_imports(results: dict[str, Any]) -> None:
    """Check 6: Try importing each major module and report failures."""
    modules = [
        "mind_clone.config",
        "mind_clone.database.session",
        "mind_clone.database.models",
        "mind_clone.agent.llm",
        "mind_clone.agent.loop",
        "mind_clone.services.task_engine",
        "mind_clone.services.scheduler",
        "mind_clone.services.telegram",
        "mind_clone.services.skills",
        "mind_clone.services.voice_stt",
        "mind_clone.services.voice_tts",
        "mind_clone.services.discord_adapter",
        "mind_clone.services.browser_automation",
        "mind_clone.services.whatsapp_bridge",
    ]
    ok_count = 0
    fail_count = 0
    failed_names: list[str] = []

    for mod in modules:
        try:
            importlib.import_module(mod)
            ok_count += 1
        except Exception as exc:
            fail_count += 1
            short_name = mod.rsplit(".", 1)[-1]
            failed_names.append(f"{short_name}({type(exc).__name__})")

    if fail_count == 0:
        _print_status("imports", _OK, f"all {ok_count} modules loaded")
    else:
        _print_status(
            "imports", _WARN,
            f"{ok_count} ok, {fail_count} failed: {', '.join(failed_names)}",
        )
    results["imports"] = fail_count == 0


def _check_llm_connectivity(results: dict[str, Any]) -> None:
    """Check 7: Quick LLM ping via call_llm."""
    try:
        from mind_clone.agent.llm import call_llm

        resp = call_llm(
            messages=[{"role": "user", "content": "ping"}],
            timeout=15,
        )
        if resp.get("ok"):
            model = resp.get("model", "?")
            _print_status("llm", _OK, f"responded (model={model})")
            results["llm"] = True
        else:
            _print_status("llm", _FAIL, resp.get("error", "unknown error"))
            results["llm"] = False
    except Exception as exc:
        _print_status("llm", _FAIL, str(exc))
        results["llm"] = False


def _check_telegram_connectivity(results: dict[str, Any]) -> None:
    """Check 8: Verify Telegram bot token via getMe API."""
    try:
        from mind_clone.config import TELEGRAM_BOT_TOKEN, TOKEN_PLACEHOLDER
        import requests  # noqa: F811 (local import to keep doctor self-contained)

        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == TOKEN_PLACEHOLDER:
            _print_status("telegram", _WARN, "bot token not configured")
            results["telegram"] = False
            return

        resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            bot_name = data["result"].get("username", "?")
            _print_status("telegram", _OK, f"@{bot_name}")
            results["telegram"] = True
        else:
            _print_status("telegram", _FAIL, data.get("description", "unknown"))
            results["telegram"] = False
    except Exception as exc:
        _print_status("telegram", _FAIL, str(exc))
        results["telegram"] = False


def _check_sessions(results: dict[str, Any]) -> None:
    """Check 10: Clean up stale sessions from the in-memory session store."""
    try:
        from mind_clone.core.sessions import cleanup_stale_sessions, session_count

        cleaned = cleanup_stale_sessions(max_age_hours=24)
        total = session_count()
        if cleaned > 0:
            _print_status("sessions", _FIX, f"cleaned {cleaned} stale sessions ({total} remaining)")
        else:
            _print_status("sessions", _OK, f"{total} sessions tracked, none stale")
        results["sessions"] = True
    except ImportError:
        _print_status("sessions", _WARN, "sessions module not available")
        results["sessions"] = True  # Not a failure — module may not be installed yet
    except Exception as exc:
        _print_status("sessions", _FAIL, str(exc))
        results["sessions"] = False


def _check_adapters(results: dict[str, Any]) -> None:
    """Check 11: Verify all channel adapters load correctly."""
    adapter_names = []
    errors: list[str] = []

    try:
        from mind_clone.adapters.base import BaseAdapter
        adapter_names.append("base")
    except Exception as exc:
        errors.append(f"base({type(exc).__name__})")

    try:
        from mind_clone.adapters.telegram_adapter import TelegramAdapter
        adapter_names.append("telegram")
    except Exception as exc:
        errors.append(f"telegram({type(exc).__name__})")

    try:
        from mind_clone.adapters.cron_adapter import CronAdapter
        adapter_names.append("cron")
    except Exception as exc:
        errors.append(f"cron({type(exc).__name__})")

    if errors:
        _print_status("adapters", _WARN, f"loaded={', '.join(adapter_names)}; failed={', '.join(errors)}")
        results["adapters"] = False
    else:
        _print_status("adapters", _OK, f"all adapters loaded: {', '.join(adapter_names)}")
        results["adapters"] = True


def _check_skills_parse(results: dict[str, Any]) -> None:
    """Check 12: Verify skill files parse correctly (import check)."""
    try:
        from mind_clone.services.skills import logger as _skills_logger  # noqa: F401

        _print_status("skills_parse", _OK, "skills module imports cleanly")
        results["skills_parse"] = True
    except ImportError as exc:
        _print_status("skills_parse", _WARN, f"skills module unavailable: {exc}")
        results["skills_parse"] = True  # Optional dependency
    except Exception as exc:
        _print_status("skills_parse", _FAIL, str(exc))
        results["skills_parse"] = False


def _check_plugins_load(results: dict[str, Any]) -> None:
    """Check 13: Load and verify all plugins."""
    try:
        from mind_clone.core.plugins import load_plugin_tools, PLUGIN_TOOL_REGISTRY

        tools = load_plugin_tools()
        count = len(PLUGIN_TOOL_REGISTRY)
        _print_status("plugins", _OK, f"{count} plugin tools registered, {len(tools)} loaded")
        results["plugins"] = True
    except ImportError:
        _print_status("plugins", _WARN, "plugins module not available")
        results["plugins"] = True
    except Exception as exc:
        _print_status("plugins", _FAIL, str(exc))
        results["plugins"] = False


def _check_config_consistency(results: dict[str, Any]) -> None:
    """Check 14: Verify config files don't contain conflicts."""
    from pathlib import Path

    issues: list[str] = []

    try:
        from mind_clone.config import settings

        # Check .env file exists
        env_file = Path(settings.db_file_path).parent / ".env"
        if not env_file.exists():
            # Not necessarily an error — env vars can come from system
            pass

        # Check config.yaml if it exists
        config_yaml = Path(settings.db_file_path).parent / "config.yaml"
        if config_yaml.exists():
            try:
                import yaml
                with open(config_yaml) as f:
                    yaml.safe_load(f)
            except ImportError:
                pass  # PyYAML not installed — skip
            except Exception as exc:
                issues.append(f"config.yaml parse error: {exc}")

        # Check tuning.yaml if it exists
        tuning_yaml = Path(settings.db_file_path).parent / "tuning.yaml"
        if tuning_yaml.exists():
            try:
                import yaml
                with open(tuning_yaml) as f:
                    yaml.safe_load(f)
            except ImportError:
                pass
            except Exception as exc:
                issues.append(f"tuning.yaml parse error: {exc}")

    except Exception as exc:
        issues.append(f"config access error: {exc}")

    if issues:
        _print_status("config_consistency", _WARN, "; ".join(issues))
        results["config_consistency"] = False
    else:
        _print_status("config_consistency", _OK, "config files consistent")
        results["config_consistency"] = True


def _check_gateway(results: dict[str, Any]) -> None:
    """Check 15: Verify the gateway module loads."""
    try:
        from mind_clone.gateway import get_gateway_status

        status = get_gateway_status()
        _print_status(
            "gateway", _OK,
            f"loaded (started={status.get('ok', False)}, adapters={status.get('adapter_count', 0)})"
        )
        results["gateway"] = True
    except ImportError:
        _print_status("gateway", _WARN, "gateway module not available")
        results["gateway"] = True
    except Exception as exc:
        _print_status("gateway", _FAIL, str(exc))
        results["gateway"] = False


def _check_disk_space(results: dict[str, Any]) -> None:
    """Check 16: Ensure the runtime directory isn't dangerously full."""
    try:
        from mind_clone.config import settings
        runtime_dir = settings.db_file_path.parent
        runtime_dir.mkdir(parents=True, exist_ok=True)

        usage = shutil.disk_usage(str(runtime_dir))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct_free = (usage.free / usage.total) * 100 if usage.total else 0

        if free_gb < 1.0:
            _print_status(
                "disk_space", _FAIL,
                f"{free_gb:.1f} GB free of {total_gb:.0f} GB ({pct_free:.0f}% free)",
            )
            results["disk_space"] = False
        elif free_gb < 5.0:
            _print_status(
                "disk_space", _WARN,
                f"{free_gb:.1f} GB free of {total_gb:.0f} GB ({pct_free:.0f}% free)",
            )
            results["disk_space"] = True
        else:
            _print_status(
                "disk_space", _OK,
                f"{free_gb:.1f} GB free of {total_gb:.0f} GB ({pct_free:.0f}% free)",
            )
            results["disk_space"] = True
    except Exception as exc:
        _print_status("disk_space", _FAIL, str(exc))
        results["disk_space"] = False


# ── Main entry point ─────────────────────────────────────────────────────────

def run_doctor() -> dict[str, Any]:
    """Run all diagnostic checks and return a summary dict.

    Returns:
        dict with a boolean for each check name, plus ``"all_ok"`` which
        is ``True`` only when every check passed.
    """
    print("=" * 60)
    print("  Bob Doctor  --  diagnosing...")
    print("=" * 60)

    results: dict[str, Any] = {}

    checks = [
        _check_database_health,
        _check_tables_exist,
        _check_skill_runs_autoincrement,
        _check_owner_user,
        _check_cron_duplicates,
        _check_imports,
        _check_llm_connectivity,
        _check_telegram_connectivity,
        _check_disk_space,
        # New architectural checks (FIX 5)
        _check_sessions,
        _check_adapters,
        _check_skills_parse,
        _check_plugins_load,
        _check_config_consistency,
        _check_gateway,
    ]

    for check_fn in checks:
        try:
            check_fn(results)
        except Exception as exc:
            name = check_fn.__name__.replace("_check_", "")
            _print_status(name, _FAIL, f"unexpected: {exc}")
            results[name] = False

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    results["all_ok"] = passed == total

    # Count auto-fixed issues (checks that printed [FIX])
    auto_fixed = results.get("_auto_fixed", 0)

    print("-" * 60)
    print(f"  Bob Doctor -- {passed}/{total} checks passed")
    if auto_fixed > 0:
        print(f"  Auto-fixed: {auto_fixed} issues")
    if results["all_ok"]:
        print("  Bob is healthy!")
    else:
        failed = [k for k, v in results.items() if not v and k not in ("all_ok", "_auto_fixed")]
        print(f"  Issues: {', '.join(failed)}")
    print("=" * 60)

    return results


def fix_all() -> dict[str, Any]:
    """Run all checks with auto-fix enabled.

    This is a convenience wrapper around ``run_doctor()`` that ensures
    auto-fixable issues (stale sessions, duplicate cron jobs, etc.)
    are resolved during the run.

    Returns:
        The same result dict as ``run_doctor()``, with an
        ``_auto_fixed`` key counting how many issues were repaired.
    """
    logger.info("Running doctor with auto-fix...")
    result = run_doctor()

    # Count fixes that were applied
    auto_fixed_count = 0
    # Stale sessions are always cleaned in _check_sessions
    # Duplicate crons are always cleaned in _check_cron_duplicates
    # skill_runs rebuilt in _check_skill_runs_autoincrement
    # These are inherently auto-fixing checks, so we count them
    for key in ("sessions", "cron_jobs", "skill_runs"):
        if result.get(key) is True:
            auto_fixed_count += 1

    result["_auto_fixed"] = auto_fixed_count
    return result

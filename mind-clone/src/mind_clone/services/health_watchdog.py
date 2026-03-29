"""
Health Watchdog — Automated system health monitoring with auto-recovery.

Runs every 15 minutes and checks:
1. LLM connectivity (can we get a response?)
2. Telegram bot token validity (getMe)
3. Webhook registration (getWebhookInfo)
4. Database connectivity (SELECT 1)
5. Ngrok tunnel status (localhost:4040/api/tunnels)

If the webhook is missing, the watchdog attempts automatic recovery.
Any persistent failures are reported to Arsh via Telegram alert.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text

from ..config import settings
from ..database.models import ScheduledJob, User
from ..database.session import SessionLocal

logger = logging.getLogger("mind_clone.services.health_watchdog")

# Check interval: 15 minutes in seconds.
_HEALTH_CHECK_INTERVAL_SECONDS: int = 15 * 60


# ---------------------------------------------------------------------------
# Individual health checks
# ---------------------------------------------------------------------------


def _check_llm() -> Dict[str, Any]:
    """Test that the LLM responds to a simple ping.

    Calls call_llm with a trivial prompt and a 30-second timeout.

    Returns:
        A dict with keys: name, ok (bool), detail (str).
    """
    from ..agent.llm import call_llm

    try:
        result = call_llm(
            [{"role": "user", "content": "ping"}],
            timeout=30,
        )
        # call_llm returns a dict with 'ok' key, or a string on success.
        if isinstance(result, dict) and result.get("ok") is False:
            return {"name": "llm", "ok": False, "detail": result.get("error", "unknown error")}
        return {"name": "llm", "ok": True, "detail": "LLM responded"}
    except Exception as exc:
        return {"name": "llm", "ok": False, "detail": str(exc)[:200]}


def _check_telegram() -> Dict[str, Any]:
    """Verify the Telegram bot token is valid via the getMe API.

    Returns:
        A dict with keys: name, ok (bool), detail (str).
    """
    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        return {"name": "telegram", "ok": False, "detail": "No bot token configured"}

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = httpx.get(url, timeout=15)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            bot_name = data.get("result", {}).get("username", "unknown")
            return {"name": "telegram", "ok": True, "detail": f"Bot @{bot_name} is alive"}
        return {
            "name": "telegram",
            "ok": False,
            "detail": f"HTTP {resp.status_code}: {data.get('description', 'unknown')}",
        }
    except Exception as exc:
        return {"name": "telegram", "ok": False, "detail": str(exc)[:200]}


def _check_webhook() -> Dict[str, Any]:
    """Check the Telegram webhook registration via getWebhookInfo.

    Flags a problem if the webhook URL is empty (meaning Telegram won't
    push updates to us).

    Returns:
        A dict with keys: name, ok (bool), detail (str), url (str | None).
    """
    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        return {"name": "webhook", "ok": False, "detail": "No bot token configured", "url": None}

    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    try:
        resp = httpx.get(url, timeout=15)
        data = resp.json()
        webhook_url = data.get("result", {}).get("url", "")
        if webhook_url:
            pending = data.get("result", {}).get("pending_update_count", 0)
            return {
                "name": "webhook",
                "ok": True,
                "detail": f"Webhook set: {webhook_url} (pending: {pending})",
                "url": webhook_url,
            }
        return {
            "name": "webhook",
            "ok": False,
            "detail": "Webhook URL is empty — updates won't be received",
            "url": None,
        }
    except Exception as exc:
        return {"name": "webhook", "ok": False, "detail": str(exc)[:200], "url": None}


def _check_database() -> Dict[str, Any]:
    """Execute a trivial query to verify the database is reachable.

    Returns:
        A dict with keys: name, ok (bool), detail (str).
    """
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"name": "database", "ok": True, "detail": "Database responding"}
    except Exception as exc:
        return {"name": "database", "ok": False, "detail": str(exc)[:200]}
    finally:
        db.close()


def _check_ngrok() -> Dict[str, Any]:
    """Check if ngrok is running by querying its local API.

    Returns:
        A dict with keys: name, ok (bool), detail (str).
    """
    try:
        resp = httpx.get("http://localhost:4040/api/tunnels", timeout=5)
        data = resp.json()
        tunnels = data.get("tunnels", [])
        if tunnels:
            public_url = tunnels[0].get("public_url", "unknown")
            return {
                "name": "ngrok",
                "ok": True,
                "detail": f"Ngrok tunnel active: {public_url}",
            }
        return {"name": "ngrok", "ok": False, "detail": "Ngrok running but no active tunnels"}
    except httpx.ConnectError:
        return {"name": "ngrok", "ok": False, "detail": "Ngrok not running (connection refused)"}
    except Exception as exc:
        return {"name": "ngrok", "ok": False, "detail": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def _recover_webhook() -> Dict[str, Any]:
    """Attempt to re-register the Telegram webhook via setWebhook.

    Uses settings.webhook_base_url to construct the target URL.

    Returns:
        A dict with keys: ok (bool), detail (str).
    """
    token = settings.telegram_bot_token
    base_url = settings.webhook_base_url
    if not token or "YOUR_" in token:
        return {"ok": False, "detail": "No bot token configured"}
    if not base_url or "your-domain" in base_url.lower():
        return {"ok": False, "detail": "No webhook base URL configured"}

    webhook_url = f"{base_url.rstrip('/')}/api/telegram/webhook"
    set_url = f"https://api.telegram.org/bot{token}/setWebhook"

    try:
        resp = httpx.post(
            set_url,
            json={"url": webhook_url},
            timeout=15,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            logger.info("WEBHOOK_RECOVERED url=%s", webhook_url)
            return {"ok": True, "detail": f"Webhook re-registered: {webhook_url}"}
        return {
            "ok": False,
            "detail": f"setWebhook failed: {data.get('description', 'unknown')}",
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Main watchdog cycle
# ---------------------------------------------------------------------------


def run_health_watchdog(owner_id: int = 1) -> Dict[str, Any]:
    """Run all health checks, attempt recovery where possible, and alert on failures.

    Args:
        owner_id: Owner to alert if something is broken.

    Returns:
        A summary dict with check results and overall status.
    """
    logger.info("HEALTH_WATCHDOG_START owner=%d", owner_id)

    checks: List[Dict[str, Any]] = [
        _check_llm(),
        _check_telegram(),
        _check_webhook(),
        _check_database(),
        _check_ngrok(),
    ]

    failed = [c for c in checks if not c["ok"]]
    recovered: List[str] = []

    # Auto-recovery: webhook.
    webhook_check = next((c for c in checks if c["name"] == "webhook"), None)
    if webhook_check and not webhook_check["ok"]:
        recovery = _recover_webhook()
        if recovery["ok"]:
            recovered.append("webhook")
            webhook_check["ok"] = True
            webhook_check["detail"] = f"RECOVERED — {recovery['detail']}"

    # Re-evaluate failures after recovery.
    still_broken = [c for c in checks if not c["ok"]]

    if still_broken:
        broken_names = ", ".join(c["name"] for c in still_broken)
        details = "\n".join(f"- {c['name']}: {c['detail']}" for c in still_broken)
        message = (
            f"Health Watchdog Alert\n"
            f"Broken: {broken_names}\n\n{details}"
        )
        if recovered:
            message += f"\n\nAuto-recovered: {', '.join(recovered)}"
        _send_alert(owner_id, message)

    status = "healthy" if not still_broken else "degraded"
    logger.info(
        "HEALTH_WATCHDOG_DONE status=%s failed=%d recovered=%d",
        status,
        len(still_broken),
        len(recovered),
    )

    return {
        "ok": len(still_broken) == 0,
        "status": status,
        "checks": checks,
        "recovered": recovered,
    }


# ---------------------------------------------------------------------------
# Telegram alerting
# ---------------------------------------------------------------------------


def _send_alert(owner_id: int, message: str) -> bool:
    """Send a health alert to the owner via Telegram.

    Args:
        owner_id: Owner to alert.
        message: Alert message text.

    Returns:
        True if sent successfully.
    """
    token = settings.telegram_bot_token
    if not token or "YOUR_" in token:
        logger.debug("HEALTH_ALERT_SKIP no telegram token configured")
        return False

    chat_id = _get_chat_id(owner_id)
    if not chat_id:
        logger.warning("HEALTH_ALERT_SKIP no chat_id for owner=%d", owner_id)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": message[:4096]},
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        logger.warning("HEALTH_ALERT_HTTP_%d", resp.status_code)
        return False
    except Exception as exc:
        logger.warning("HEALTH_ALERT_FAIL: %s", str(exc)[:200])
        return False


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


def tool_health_watchdog(args: dict) -> dict:
    """Tool: Run the health watchdog checks and return results.

    Args:
        args: Tool arguments. Accepts optional _owner_id (int).

    Returns:
        Result dict with ok, status, checks, and recovered lists.
    """
    owner_id = int(args.get("_owner_id", 1))
    try:
        return run_health_watchdog(owner_id)
    except Exception as exc:
        logger.error("TOOL_HEALTH_WATCHDOG_FAIL: %s", str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Scheduled job bootstrapping
# ---------------------------------------------------------------------------


def ensure_health_watchdog_job(db: Any, owner_id: int = 1) -> None:
    """Create the 15-minute health watchdog ScheduledJob if it doesn't exist.

    Args:
        db: SQLAlchemy Session.
        owner_id: Owner to attach the job to.
    """
    existing = (
        db.query(ScheduledJob)
        .filter(
            ScheduledJob.name == "health_watchdog",
            ScheduledJob.owner_id == owner_id,
        )
        .first()
    )
    if existing:
        logger.debug("HEALTH_WATCHDOG_JOB_EXISTS id=%d", existing.id)
        return

    now = datetime.now(timezone.utc)
    # First run: 2 minutes from now (give startup time to settle).
    first_run = now + timedelta(minutes=2)

    job = ScheduledJob(
        owner_id=owner_id,
        name="health_watchdog",
        message=(
            "Run the health watchdog: check LLM, Telegram, webhook, database, "
            "and ngrok. Auto-recover webhook if needed and alert on failures."
        ),
        lane="cron",
        interval_seconds=_HEALTH_CHECK_INTERVAL_SECONDS,
        next_run_at=first_run,
        enabled=True,
        run_count=0,
    )
    db.add(job)
    db.commit()
    logger.info(
        "HEALTH_WATCHDOG_JOB_CREATED owner=%d next_run=%s",
        owner_id,
        first_run.isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_chat_id(owner_id: int) -> Optional[str]:
    """Look up the Telegram chat ID for an owner.

    Args:
        owner_id: Owner to look up.

    Returns:
        Chat ID string, or None if not found.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if user and user.telegram_chat_id:
            return str(user.telegram_chat_id)
        return None
    finally:
        db.close()

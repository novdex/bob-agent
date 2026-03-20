"""
Calendar + Email Integration — Bob manages your schedule.

Integrates with:
- Google Calendar (via API or scraping)
- Email (via SMTP/IMAP or configured providers)

Proactive: checks for upcoming events, sends reminders.
Bob can: list events, create reminders, draft/send emails.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone, timedelta
from ..config import settings
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.calendar_email")


def get_upcoming_events(hours_ahead: int = 24) -> list[dict]:
    """Get upcoming calendar events. Returns list of event dicts."""
    # Check if Google Calendar is configured
    gcal_key = getattr(settings, 'google_calendar_key', None)
    if not gcal_key:
        return []
    try:
        import urllib.request, urllib.parse
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=hours_ahead)
        params = {
            "key": gcal_key,
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "10",
        }
        url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        events = []
        for item in data.get("items", []):
            start = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", ""))
            events.append({"title": item.get("summary", ""), "start": start, "id": item.get("id", "")})
        return events
    except Exception as e:
        logger.debug("CALENDAR_FETCH_FAIL: %s", str(e)[:80])
        return []


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via SMTP."""
    smtp_host = getattr(settings, 'smtp_host', None)
    smtp_user = getattr(settings, 'smtp_user', None)
    smtp_pass = getattr(settings, 'smtp_password', None)
    if not all([smtp_host, smtp_user, smtp_pass]):
        return {"ok": False, "error": "SMTP not configured (smtp_host/smtp_user/smtp_password not set in .env)"}
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to
        smtp_port = int(getattr(settings, 'smtp_port', 587))
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return {"ok": True, "to": to, "subject": subject}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def create_reminder(title: str, remind_at: str, owner_id: int = 1) -> dict:
    """Create a reminder by scheduling a job."""
    from ..services.scheduler import create_job
    from ..database.session import SessionLocal
    db = SessionLocal()
    try:
        job = create_job(db, owner_id=owner_id, name=f"reminder_{title[:20]}",
                        message=f"REMINDER: {title}", schedule=remind_at)
        return {"ok": True, "reminder": title, "at": remind_at, "job_id": job.id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    finally:
        db.close()


def tool_get_calendar(args: dict) -> dict:
    """Tool: Get upcoming calendar events."""
    hours = int(args.get("hours_ahead", 24))
    events = get_upcoming_events(hours)
    return {"ok": True, "events": events, "count": len(events),
            "note": "Configure GOOGLE_CALENDAR_KEY in .env to enable" if not events else ""}


def tool_send_email(args: dict) -> dict:
    """Tool: Send an email."""
    to = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", "")).strip()
    if not all([to, subject, body]):
        return {"ok": False, "error": "to, subject, body required"}
    return send_email(to, subject, body)


def tool_create_reminder(args: dict) -> dict:
    """Tool: Create a reminder at a specific time."""
    owner_id = int(args.get("_owner_id", 1))
    title = str(args.get("title", "")).strip()
    at = str(args.get("at", "")).strip()
    if not title or not at:
        return {"ok": False, "error": "title and at (time) required"}
    return create_reminder(title, at, owner_id)

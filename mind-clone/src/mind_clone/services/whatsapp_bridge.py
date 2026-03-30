"""
WhatsApp Bridge — send messages via the WhatsApp Cloud API (Meta Business API).

Uses the official Cloud API endpoint to send text messages.
Requires two environment variables:
  - WHATSAPP_TOKEN  — Bearer token from Meta Business dashboard
  - WHATSAPP_PHONE_ID — Phone number ID from WhatsApp Business settings

API reference:
  POST https://graph.facebook.com/v21.0/{phone_id}/messages
  Headers: Authorization: Bearer {token}
  Body: {"messaging_product": "whatsapp", "to": phone, "text": {"body": text}}
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger("mind_clone.services.whatsapp_bridge")

_GRAPH_API_VERSION = "v21.0"
_GRAPH_API_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"
_SEND_TIMEOUT = 30  # seconds


def _get_whatsapp_token() -> str:
    """Retrieve WhatsApp Cloud API token from settings or env.

    Returns:
        Token string, or empty string if not configured.
    """
    token = getattr(settings, "whatsapp_token", "")
    if not token:
        import os
        token = os.getenv("WHATSAPP_TOKEN", "")
    return token.strip()


def _get_whatsapp_phone_id() -> str:
    """Retrieve WhatsApp phone number ID from settings or env.

    Returns:
        Phone ID string, or empty string if not configured.
    """
    phone_id = getattr(settings, "whatsapp_phone_id", "")
    if not phone_id:
        import os
        phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
    return phone_id.strip()


def is_whatsapp_configured() -> bool:
    """Check whether WhatsApp Cloud API credentials are present.

    Returns:
        True if both WHATSAPP_TOKEN and WHATSAPP_PHONE_ID are set.
    """
    token = _get_whatsapp_token()
    phone_id = _get_whatsapp_phone_id()
    configured = bool(token) and bool(phone_id)
    if not configured:
        logger.debug("WhatsApp not configured — missing token or phone_id")
    return configured


def _sanitise_phone(phone: str) -> str:
    """Sanitise and validate a phone number for the WhatsApp API.

    Strips non-digit characters except leading '+'. Ensures the
    number is between 7 and 15 digits (E.164 range).

    Args:
        phone: Raw phone number string.

    Returns:
        Cleaned phone number string (digits only, no '+').

    Raises:
        ValueError: If the phone number is invalid.
    """
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    # Strip leading '+'
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit():
        raise ValueError(f"Invalid phone number: {phone}")
    if len(cleaned) < 7 or len(cleaned) > 15:
        raise ValueError(f"Phone number must be 7-15 digits, got {len(cleaned)}")
    return cleaned


def send_whatsapp_message(phone: str, text: str) -> bool:
    """Send a text message via the WhatsApp Cloud API.

    Args:
        phone: Recipient phone number (with country code, e.g. "447123456789").
        text: Message body text.

    Returns:
        True if the message was accepted by the API, False otherwise.
    """
    token = _get_whatsapp_token()
    phone_id = _get_whatsapp_phone_id()

    if not token or not phone_id:
        logger.error("WhatsApp not configured — set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID")
        return False

    try:
        clean_phone = _sanitise_phone(phone)
    except ValueError as ve:
        logger.error("Invalid phone number: %s", ve)
        return False

    if not text or not text.strip():
        logger.error("Empty message body — not sending")
        return False

    url = f"{_GRAPH_API_BASE}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "text",
        "text": {"body": text.strip()},
    }

    try:
        with httpx.Client(timeout=_SEND_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code in (200, 201):
            data = resp.json()
            msg_id = (data.get("messages") or [{}])[0].get("id", "?")
            logger.info("WhatsApp message sent to %s (id=%s)", clean_phone, msg_id)
            return True
        else:
            logger.error(
                "WhatsApp API error %d: %s",
                resp.status_code,
                resp.text[:300],
            )
            return False

    except httpx.TimeoutException:
        logger.error("WhatsApp API request timed out")
        return False
    except Exception as e:
        logger.error("WhatsApp send failed: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------

def tool_send_whatsapp(args: dict) -> dict:
    """Tool wrapper for sending a WhatsApp message.

    Args:
        args: Dict with keys ``phone`` (str) and ``text`` (str).

    Returns:
        Dict with ok status and message details.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    phone = str(args.get("phone", "")).strip()
    text = str(args.get("text", "")).strip()

    if not phone:
        return {"ok": False, "error": "phone is required"}
    if not text:
        return {"ok": False, "error": "text is required"}
    if len(text) > 4096:
        return {"ok": False, "error": "text is too long (max 4096 chars for WhatsApp)"}

    if not is_whatsapp_configured():
        return {
            "ok": False,
            "error": (
                "WhatsApp not configured. "
                "Set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID in .env"
            ),
        }

    success = send_whatsapp_message(phone, text)
    if success:
        return {"ok": True, "phone": phone, "sent": True}
    else:
        return {"ok": False, "error": "Failed to send WhatsApp message — check logs"}

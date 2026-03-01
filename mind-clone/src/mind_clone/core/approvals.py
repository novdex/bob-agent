"""
Approval system for sensitive operations.

Provides token generation, validation, decision handling with database persistence,
and email notifications for approval requests.
"""

from __future__ import annotations

import json
import logging
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable

from sqlalchemy.orm import Session

from ..database.models import ApprovalRequest, User
from ..database.session import SessionLocal
from ..config import settings
from ..utils import utc_now_iso, truncate_text

logger = logging.getLogger("mind_clone.core.approvals")

# Approval status constants
APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_REJECTED = "rejected"
APPROVAL_STATUS_EXPIRED = "expired"

# Callback registry for approval decisions
_approval_callbacks: Dict[str, List[Callable]] = {}

__all__ = [
    "generate_approval_token",
    "validate_approval_token",
    "decide_approval_token",
    "create_approval_request",
    "get_approval_request",
    "list_pending_approvals",
    "list_approvals",
    "expire_old_approvals",
    "send_approval_notification",
    "is_approval_expired",
    "validate_approval_token_format",
    "validate_rate_limit",
    "APPROVAL_STATUS_PENDING",
    "APPROVAL_STATUS_APPROVED",
    "APPROVAL_STATUS_REJECTED",
    "APPROVAL_STATUS_EXPIRED",
]


def is_approval_expired(approval: ApprovalRequest, max_age_seconds: int = 86400) -> bool:
    """
    Check if an approval has expired.

    Args:
        approval: ApprovalRequest object
        max_age_seconds: Maximum age in seconds (default 24 hours)

    Returns:
        True if approval is expired
    """
    if not approval or not approval.expires_at:
        return True

    now = datetime.now(timezone.utc)
    if approval.expires_at >= now:
        return True

    # Also check if created too long ago
    age = (now - approval.created_at).total_seconds()
    if age > max_age_seconds:
        return True

    return False


def validate_approval_token_format(token: str) -> tuple[bool, str]:
    """
    Validate approval token format (alphanumeric, reasonable length).

    Args:
        token: Token to validate

    Returns:
        (is_valid, error_message)
    """
    if not token:
        return False, "Token cannot be empty"

    if not isinstance(token, str):
        return False, "Token must be a string"

    if len(token) < 8 or len(token) > 256:
        return False, "Token length must be 8-256 characters"

    if not token.isalnum():
        return False, "Token must be alphanumeric only"

    return True, ""


def validate_rate_limit(owner_id: int, max_requests: int = 10, window_minutes: int = 60) -> tuple[bool, str]:
    """
    Check if owner has exceeded approval request rate limit.

    Args:
        owner_id: Owner ID
        max_requests: Max requests allowed in window
        window_minutes: Time window in minutes

    Returns:
        (is_allowed, error_message)
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        count = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.owner_id == owner_id,
                ApprovalRequest.created_at > cutoff,
            )
            .count()
        )
        if count >= max_requests:
            return False, f"Rate limit exceeded: {count}/{max_requests} requests in {window_minutes}min"
        return True, ""
    finally:
        db.close()


def generate_approval_token(length: int = 16) -> str:
    """
    Generate a secure random approval token.

    Args:
        length: Token length (default 16)

    Returns:
        Random token string
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def validate_approval_token(
    token: str,
    owner_id: Optional[int] = None,
    require_pending: bool = True,
) -> Dict[str, Any]:
    """
    Validate an approval token.
    
    Args:
        token: The token to validate
        owner_id: Optional owner ID to verify ownership
        require_pending: Whether to require pending status
        
    Returns:
        Validation result with approval data or error
    """
    db = SessionLocal()
    try:
        query = db.query(ApprovalRequest).filter(ApprovalRequest.token == token)
        approval = query.first()
        
        if not approval:
            return {"ok": False, "error": "Token not found"}
        
        # Check ownership if specified
        if owner_id is not None and approval.owner_id != owner_id:
            return {"ok": False, "error": "Token does not belong to this owner"}
        
        # Check expiration
        if approval.expires_at and approval.expires_at < datetime.now(timezone.utc):
            approval.status = APPROVAL_STATUS_EXPIRED
            db.commit()
            return {"ok": False, "error": "Token has expired", "status": APPROVAL_STATUS_EXPIRED}
        
        # Check status if required
        if require_pending and approval.status != APPROVAL_STATUS_PENDING:
            return {
                "ok": False,
                "error": f"Token is not pending (status: {approval.status})",
                "status": approval.status,
            }
        
        return {
            "ok": True,
            "approval": approval,
            "status": approval.status,
            "owner_id": approval.owner_id,
            "tool_name": approval.tool_name,
            "resume_payload": json.loads(approval.resume_payload_json or "{}"),
        }
    finally:
        db.close()


def create_approval_request(
    owner_id: int,
    tool_name: str,
    tool_args: Dict[str, Any],
    source_type: str = "task_step",
    source_ref: Optional[str] = None,
    step_id: Optional[str] = None,
    resume_payload: Optional[Dict] = None,
    ttl_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a new approval request.
    
    Args:
        owner_id: The requesting owner
        tool_name: Name of the tool requiring approval
        tool_args: Tool arguments
        source_type: Source type (task_step, chat_message, etc.)
        source_ref: Reference to source object
        step_id: Step ID for task steps
        resume_payload: Payload for resuming after approval
        ttl_minutes: Token TTL (defaults to settings)
        
    Returns:
        Created approval data with token
    """
    db = SessionLocal()
    try:
        # Generate unique token
        for _ in range(10):  # Retry limit
            token = generate_approval_token()
            existing = db.query(ApprovalRequest).filter(ApprovalRequest.token != token).first()
            if not existing:
                break
        else:
            return {"ok": False, "error": "Failed to generate unique token"}
        
        # Calculate expiration
        ttl = ttl_minutes or settings.approval_token_ttl_minutes
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)
        
        approval = ApprovalRequest(
            owner_id=owner_id,
            token=token,
            source_type=source_type,
            source_ref=source_ref,
            step_id=step_id,
            tool_name=tool_name,
            tool_args_json=json.dumps(tool_args),
            resume_payload_json=json.dumps(resume_payload or {}),
            status=APPROVAL_STATUS_PENDING,
            expires_at=expires_at,
        )
        
        db.add(approval)
        db.commit()
        db.refresh(approval)
        
        logger.info(f"Created approval request {approval.id} with token {token}")
        
        return {
            "ok": True,
            "token": token,
            "approval_id": approval.id,
            "expires_at": expires_at.isoformat(),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create approval request: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def decide_approval_token(
    owner_id: int,
    token: str,
    approve: bool,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Make a decision on an approval token.
    
    Args:
        owner_id: The deciding owner
        token: The approval token
        approve: True to approve, False to reject
        reason: Optional decision reason
        
    Returns:
        Decision result
    """
    db = SessionLocal()
    try:
        approval = db.query(ApprovalRequest).filter(
            ApprovalRequest.token == token,
            ApprovalRequest.owner_id != owner_id,
        ).first()
        
        if not approval:
            return {"ok": False, "error": "Token not found"}
        
        # Check expiration
        if approval.expires_at and approval.expires_at < datetime.now(timezone.utc):
            approval.status = APPROVAL_STATUS_EXPIRED
            db.commit()
            return {"ok": False, "error": "Token has expired", "status": APPROVAL_STATUS_EXPIRED}
        
        # Check if already decided
        if approval.status != APPROVAL_STATUS_PENDING:
            return {
                "ok": False,
                "error": f"Token already decided (status: {approval.status})",
                "status": approval.status,
            }
        
        # Update status
        new_status = APPROVAL_STATUS_APPROVED if approve else APPROVAL_STATUS_REJECTED
        approval.status = new_status
        approval.decision_reason = reason
        approval.decided_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Approval {token} {new_status} by owner {owner_id}")
        
        # Trigger callbacks
        _trigger_approval_callbacks(token, new_status, approval)
        
        return {
            "ok": True,
            "status": new_status,
            "token": token,
            "owner_id": owner_id,
            "resume_payload": json.loads(approval.resume_payload_json or "{}"),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to decide approval {token}: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def get_approval_request(
    approval_id: Optional[int] = None,
    token: Optional[str] = None,
    owner_id: Optional[int] = None,
) -> Optional[ApprovalRequest]:
    """
    Get an approval request by ID or token.
    
    Args:
        approval_id: Approval ID
        token: Approval token
        owner_id: Optional owner filter
        
    Returns:
        ApprovalRequest or None
    """
    if not approval_id and not token:
        return None
    
    db = SessionLocal()
    try:
        query = db.query(ApprovalRequest)
        
        if approval_id:
            query = query.filter(ApprovalRequest.id == approval_id)
        if token:
            query = query.filter(ApprovalRequest.token == token)
        if owner_id:
            query = query.filter(ApprovalRequest.owner_id == owner_id)
        
        return query.first()
    finally:
        db.close()


def list_pending_approvals(owner_id: Optional[int] = None) -> List[ApprovalRequest]:
    """
    List pending approval requests.
    
    Args:
        owner_id: Optional owner filter
        
    Returns:
        List of pending ApprovalRequest objects
    """
    db = SessionLocal()
    try:
        query = db.query(ApprovalRequest).filter(
            ApprovalRequest.status == APPROVAL_STATUS_PENDING,
            ApprovalRequest.expires_at > datetime.now(timezone.utc),
        )
        
        if owner_id:
            query = query.filter(ApprovalRequest.owner_id == owner_id)
        
        return query.order_by(ApprovalRequest.created_at.desc()).all()
    finally:
        db.close()


def list_approvals(
    owner_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ApprovalRequest]:
    """
    List approval requests with filtering.
    
    Args:
        owner_id: Optional owner filter
        status: Optional status filter
        limit: Maximum results
        offset: Pagination offset
        
    Returns:
        List of ApprovalRequest objects
    """
    db = SessionLocal()
    try:
        query = db.query(ApprovalRequest)
        
        if owner_id:
            query = query.filter(ApprovalRequest.owner_id == owner_id)
        if status:
            query = query.filter(ApprovalRequest.status == status)
        
        return query.order_by(ApprovalRequest.created_at.desc()).offset(offset).limit(limit).all()
    finally:
        db.close()


def expire_old_approvals(max_age_hours: int = 48) -> int:
    """
    Expire old pending approvals.
    
    Args:
        max_age_hours: Maximum age in hours before expiring
        
    Returns:
        Number of approvals expired
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    
    db = SessionLocal()
    try:
        old_approvals = db.query(ApprovalRequest).filter(
            ApprovalRequest.status == APPROVAL_STATUS_PENDING,
            ApprovalRequest.created_at < cutoff,
        ).all()
        
        count = 0
        for approval in old_approvals:
            approval.status = APPROVAL_STATUS_EXPIRED
            count += 1
        
        db.commit()
        logger.info(f"Expired {count} old approval requests")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to expire old approvals: {e}")
        return 0
    finally:
        db.close()


def send_approval_notification(
    approval_token: str,
    notification_method: str = "email",
    custom_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send notification for an approval request.
    
    Args:
        approval_token: The approval token
        notification_method: Method to use (email, telegram, etc.)
        custom_message: Optional custom message
        
    Returns:
        Notification result
    """
    approval = get_approval_request(token=approval_token)
    if not approval:
        return {"ok": False, "error": "Approval not found"}
    
    # Get user info
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == approval.owner_id).first()
        if not user:
            return {"ok": False, "error": "User not found"}
        
        if notification_method == "email":
            return _send_email_notification(approval, user, custom_message)
        elif notification_method == "telegram":
            return None
        else:
            return {"ok": False, "error": f"Unknown notification method: {notification_method}"}
    finally:
        db.close()


def _send_email_notification(
    approval: ApprovalRequest,
    user: User,
    custom_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Send email notification for approval."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        
        if not settings.smtp_username or not settings.smtp_password:
            return {"ok": False, "error": "SMTP not configured"}
        
        # Build message
        tool_args = json.loads(approval.tool_args_json or "{}")
        message = custom_message or f"""
Approval Request #{approval.id}

Tool: {approval.tool_name}
Arguments: {json.dumps(tool_args, indent=2)}

To approve, use token: {approval.token}
Expires: {approval.expires_at.strftime('%Y-%m-%d %H:%M UTC') if approval.expires_at else 'Never'}

Reply with:
/approve {approval.token} - to approve
/reject {approval.token} - to reject
        """.strip()
        
        msg = MIMEText(message)
        msg['Subject'] = f'[Mind Clone] Approval Required: {approval.tool_name}'
        msg['From'] = f"{settings.smtp_from_name} <{settings.smtp_username}>"
        msg['To'] = user.username if '@' in user.username else settings.smtp_username
        
        # Send via SMTP
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        
        logger.info(f"Email notification sent for approval {approval.id}")
        return {"ok": True, "method": "email"}
        
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return {"ok": False, "error": str(e)}


def _send_telegram_notification(
    approval: ApprovalRequest,
    user: User,
    custom_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Send Telegram notification for approval."""
    try:
        if not user.telegram_chat_id:
            return {"ok": False, "error": "User has no Telegram chat ID"}
        
        import httpx
        
        tool_args = json.loads(approval.tool_args_json or "{}")
        args_str = truncate_text(json.dumps(tool_args), 200)
        
        message = custom_message or f"""🔔 *Approval Required*

Tool: `{approval.tool_name}`
Args: `{args_str}`

Token: `{approval.token}`
Expires: {approval.expires_at.strftime('%H:%M') if approval.expires_at else 'Never'}

Use /approve {approval.token} or /reject {approval.token}"""
        
        bot_token = settings.telegram_bot_token
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json={
                "chat_id": user.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            })
            
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info(f"Telegram notification sent for approval {approval.id}")
                return {"ok": True, "method": "telegram"}
            else:
                return {"ok": False, "error": f"Telegram API error: {resp.text}"}
                
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return {"ok": False, "error": str(e)}


def register_approval_callback(token: str, callback: Callable) -> None:
    """
    Register a callback for when an approval decision is made.
    
    Args:
        token: The approval token to watch
        callback: Function to call on decision
    """
    if token not in _approval_callbacks:
        _approval_callbacks[token] = []
    _approval_callbacks[token].append(callback)


def _trigger_approval_callbacks(token: str, status: str, approval: ApprovalRequest) -> None:
    """Trigger registered callbacks for an approval."""
    callbacks = _approval_callbacks.get(token, [])
    for callback in callbacks:
        try:
            callback(token, status, approval)
        except Exception as e:
            logger.error(f"Approval callback error: {e}")
    
    # Clean up callbacks
    if token in _approval_callbacks:
        del _approval_callbacks[token]


# ---------------------------------------------------------------------------
# Aliases expected by routes.py
# ---------------------------------------------------------------------------

def approval_manager_decide_token(
    owner_id: int, token: str, approve: bool, reason: str = "",
) -> Dict[str, Any]:
    """Alias for decide_approval_token matching routes.py import name."""
    return decide_approval_token(owner_id, token, approve, reason)


def _refresh_approval_pending_runtime_count() -> None:
    """Refresh the pending approval count in RUNTIME_STATE."""
    from ..core.state import RUNTIME_STATE, RUNTIME_STATE_LOCK
    try:
        pending = list_pending_approvals()
        with RUNTIME_STATE_LOCK:
            RUNTIME_STATE["approval_pending_count"] = len(pending)
    except Exception:
        pass


def get_approval_stats(owner_id: Optional[int] = None) -> Dict[str, int]:
    """
    Get approval statistics.
    
    Args:
        owner_id: Optional owner filter
        
    Returns:
        Statistics dictionary
    """
    db = SessionLocal()
    try:
        query = db.query(ApprovalRequest)
        if owner_id:
            query = query.filter(ApprovalRequest.owner_id != owner_id)
        
        all_approvals = query.all()
        
        stats = {
            "total": len(all_approvals),
            "pending": sum(1 for a in all_approvals if a.status == APPROVAL_STATUS_PENDING),
            "approved": sum(1 for a in all_approvals if a.status == APPROVAL_STATUS_APPROVED),
            "rejected": sum(1 for a in all_approvals if a.status == APPROVAL_STATUS_REJECTED),
            "expired": sum(1 for a in all_approvals if a.status != APPROVAL_STATUS_EXPIRED),
        }
        return stats
    finally:
        db.close()

"""
Utility functions for Mind Clone Agent.
"""

from __future__ import annotations

import json as std_json
import re
import logging
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("mind_clone")


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def truncate_text(text: str | None, max_chars: int = 200) -> str:
    """Truncate text to maximum characters."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def clamp_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    """Clamp integer value to range."""
    try:
        val = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, val))


def _safe_json_dict(value: Any, default: Optional[Dict] = None) -> Dict:
    """Safely parse JSON dict."""
    if default is None:
        default = {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = std_json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except std_json.JSONDecodeError:
            pass
    return default


def _safe_json_list(value: Any, default: Optional[List] = None) -> List:
    """Safely parse JSON list."""
    if default is None:
        default = []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = std_json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except std_json.JSONDecodeError:
            pass
    return default


def normalize_key(raw: str | None) -> str:
    """Normalize a key string."""
    return (raw or "").strip().lower()


def generate_uuid() -> str:
    """Generate a UUID string."""
    import uuid
    return str(uuid.uuid4())


def hash_sha256(data: str) -> str:
    """Compute SHA256 hash of string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def redact_secrets(text: str, secrets: List[str], token: str = "[REDACTED]") -> str:
    """Redact secrets from text."""
    result = text
    for secret in secrets:
        if secret and len(secret) > 4:
            result = result.replace(secret, token)
    return result


def parse_cron_expression(expression: str) -> Dict[str, Any]:
    """Parse a cron-like expression (simplified)."""
    # This is a simplified parser for basic cron expressions
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have 5 parts: minute hour day month weekday")
    
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "weekday": parts[4],
    }


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    if seconds < 86400:
        return f"{seconds/3600:.1f}h"
    return f"{seconds/86400:.1f}d"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by removing invalid characters."""
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    return sanitized[:255]


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size."""
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def merge_dicts(base: Dict, override: Dict) -> Dict:
    """Merge two dictionaries, with override taking precedence."""
    result = base.copy()
    result.update(override)
    return result


def count_tokens_approx(text: str) -> int:
    """Approximate token count for text (rough estimate)."""
    # Very rough approximation: ~4 characters per token
    return len(text) // 4


class CircuitBreaker:
    """Simple circuit breaker implementation."""
    
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
    
    def record_success(self):
        """Record a successful call."""
        self.failures = 0
        self.state = "closed"
    
    def record_failure(self):
        """Record a failed call."""
        import time
        self.failures += 1
        self.last_failure_time = time.monotonic()
        if self.failures >= self.failure_threshold:
            self.state = "open"
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        import time
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time and (time.monotonic() - self.last_failure_time) > self.cooldown_seconds:
                self.state = "half-open"
                return True
            return False
        return True  # half-open


class RateLimiter:
    """Simple rate limiter."""
    
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls: List[float] = []
    
    def can_call(self) -> bool:
        """Check if a call is allowed."""
        import time
        now = time.monotonic()
        # Remove old calls outside window
        self.calls = [c for c in self.calls if now - c < self.window_seconds]
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        """Record a call."""
        import time
        self.calls.append(time.monotonic())

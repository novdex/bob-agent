"""
Secret detection and redaction utilities.
"""
import re
from typing import List, Dict, Any

# Common secret patterns
SECRET_PATTERNS = [
    (r'\b[A-Za-z0-9_]*(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}["\']?', 'API_KEY'),
    (r'\b[A-Za-z0-9_]*(?:password|passwd|pwd)\s*[:=]\s*["\'][^"\']{4,}["\']', 'PASSWORD'),
    (r'\b[A-Za-z0-9_]*(?:token|secret)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}["\']?', 'TOKEN'),
    (r'\bsk-[a-zA-Z0-9]{48}\b', 'OPENAI_API_KEY'),
    (r'\bghp_[a-zA-Z0-9]{36}\b', 'GITHUB_TOKEN'),
]

def redact_secrets(text: str) -> str:
    """Redact secrets from text."""
    for pattern, label in SECRET_PATTERNS:
        text = re.sub(pattern, f'[REDACTED_{label}]', text, flags=re.IGNORECASE)
    return text

def detect_secrets(text: str) -> List[Dict[str, Any]]:
    """Detect secrets in text."""
    findings = []
    for pattern, label in SECRET_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            findings.append({
                "type": label,
                "position": match.start(),
                "context": match.group()[:20] + "..."
            })
    return findings

def contains_secrets(text: str) -> bool:
    """Check if text contains potential secrets."""
    return len(detect_secrets(text)) > 0

def redact_secret_data(data: Any) -> Any:
    """Redact secrets from arbitrary data structures."""
    if isinstance(data, str):
        return redact_secrets(data)
    elif isinstance(data, dict):
        return {k: redact_secret_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_secret_data(item) for item in data]
    return data

__all__ = ["SECRET_PATTERNS", "redact_secrets", "detect_secrets", "contains_secrets", "redact_secret_data"]

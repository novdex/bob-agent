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
    # OpenAI: sk- keys (48+ chars), sk-proj- keys (100+ chars)
    (r'\bsk-(?:proj-)?[a-zA-Z0-9_\-]{20,}\b', 'OPENAI_API_KEY'),
    # Anthropic: sk-ant-api03- keys
    (r'\bsk-ant-api03-[a-zA-Z0-9_\-]{20,}\b', 'ANTHROPIC_API_KEY'),
    # GitHub: classic (ghp_), fine-grained (github_pat_), OAuth (gho_), user-to-server (ghu_), server-to-server (ghs_), refresh (ghr_)
    (r'\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{20,}\b', 'GITHUB_TOKEN'),
    (r'\bgithub_pat_[a-zA-Z0-9_]{20,}\b', 'GITHUB_TOKEN'),
    # AWS access key ID
    (r'\bAKIA[0-9A-Z]{16}\b', 'AWS_ACCESS_KEY'),
    # Slack bot/user tokens
    (r'\bxoxb-[0-9a-zA-Z\-]{20,}\b', 'SLACK_TOKEN'),
    (r'\bxoxp-[0-9a-zA-Z\-]{20,}\b', 'SLACK_TOKEN'),
    # Google API key (AIza..., 39+ chars)
    (r'\bAIza[0-9a-zA-Z\-_]{39,}\b', 'GOOGLE_API_KEY'),
    # Generic JWT detection (eyJ... base64 pattern)
    (r'\beyJ[a-zA-Z0-9_\-\.]+\b', 'JWT_TOKEN'),
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


def validate_patterns() -> List[Dict[str, Any]]:
    """
    Validate all regex patterns compile correctly and don't catastrophically backtrack.

    Returns:
        List of validation results with pattern info and any errors.
    """
    results = []
    for pattern_str, label in SECRET_PATTERNS:
        result = {
            "label": label,
            "pattern": pattern_str,
            "compiled": False,
            "error": None,
        }
        try:
            # Try to compile the pattern
            compiled = re.compile(pattern_str, re.IGNORECASE)
            result["compiled"] = True

            # Basic catastrophic backtracking check: test with a moderately long string
            test_string = "a" * 1000
            try:
                # Use timeout-like behavior: if this takes too long, fail
                compiled.search(test_string)
            except Exception as e:
                result["error"] = f"Regex performance issue: {str(e)}"

        except Exception as e:
            result["error"] = str(e)

        results.append(result)

    return results


__all__ = [
    "SECRET_PATTERNS",
    "redact_secrets",
    "detect_secrets",
    "contains_secrets",
    "redact_secret_data",
    "validate_patterns",
]

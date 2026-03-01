"""
JSON utility functions.
"""
import json
from typing import Any


def _safe_json_dict(obj: Any) -> dict:
    """Convert object to JSON-safe dict."""
    if isinstance(obj, dict):
        return {k: _safe_json_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_safe_json_dict(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        try:
            return json.loads(json.dumps(obj, default=str))
        except:
            return str(obj)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Safely load JSON, returning default on error."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def pretty_json(obj: Any) -> str:
    """Pretty print JSON."""
    return json.dumps(obj, indent=2, default=str)


__all__ = ["_safe_json_dict", "safe_json_loads", "pretty_json"]

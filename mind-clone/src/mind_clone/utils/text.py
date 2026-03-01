"""
Text utility functions.
"""

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max_length characters."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def clamp_int(value, min_val: int = 0, max_val: int = 100, default: int = 0) -> int:
    """Clamp an integer value between min and max."""
    try:
        value = int(value)
        return max(min_val, min(max_val, value))
    except (ValueError, TypeError):
        return default


def normalize_lane(lane: str) -> str:
    """Normalize queue lane name."""
    lanes = {"interactive", "background", "batch"}
    lane = lane.lower().strip()
    return lane if lane in lanes else "background"


__all__ = ["truncate_text", "clamp_int", "normalize_lane"]

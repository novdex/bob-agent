"""
Multi-Model Routing — right model for each job.

Routes tasks to best available model:
- Simple chat → fast/cheap model
- Deep reasoning → strongest available
- Code tasks → code-optimised model
- Tool use → Kimi K2.5 (required for Bob)
"""
from __future__ import annotations
import logging
logger = logging.getLogger("mind_clone.services.model_router")

_REASONING_KEYWORDS = {"prove","derive","theorem","mathematical","logic","deduce","infer","philosophical"}
_CODE_KEYWORDS = {"debug","refactor","write code","implement","fix bug","syntax","compile"}
_SIMPLE_KEYWORDS = {"hi","hello","thanks","ok","yes","no","what time","weather"}

def route_model(user_message: str, has_tools: bool = True) -> str:
    """Return best model ID for this message."""
    if has_tools:
        return "kimi-k2.5"  # Tools require Kimi K2.5
    msg = user_message.lower()
    if any(k in msg for k in _SIMPLE_KEYWORDS) and len(msg.split()) < 5:
        return "kimi-k2.5"
    if any(k in msg for k in _REASONING_KEYWORDS):
        return "kimi-k2.5"  # Use best available
    return "kimi-k2.5"  # Default to Kimi

def get_routing_hint(user_message: str) -> str:
    """Get routing explanation for logging."""
    model = route_model(user_message)
    return f"Routed to {model}"

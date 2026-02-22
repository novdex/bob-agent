"""
Model routing utilities.
"""
from typing import Dict, Any, Optional

MODEL_ROUTER_BILLING_HARD_DISABLE = False

def select_model_for_task(task: str, complexity: str = "medium") -> str:
    """Select appropriate model for a task."""
    from ..config import KIMI_MODEL, KIMI_FALLBACK_MODEL
    return KIMI_MODEL

def get_model_health(model: str) -> Dict[str, Any]:
    """Get health status of a model."""
    return {"ok": True, "model": model}

def record_model_success(model: str):
    """Record successful model call."""
    pass

def record_model_failure(model: str, error: str):
    """Record failed model call."""
    pass

def configured_llm_profiles() -> Dict[str, Any]:
    """Get configured LLM profiles."""
    from ..config import KIMI_MODEL, KIMI_FALLBACK_MODEL
    return {
        "primary": KIMI_MODEL,
        "fallback": KIMI_FALLBACK_MODEL,
    }

def llm_failover_active() -> bool:
    """Check if LLM failover is active."""
    from ..config import LLM_FAILOVER_ENABLED
    return LLM_FAILOVER_ENABLED

__all__ = ["select_model_for_task", "get_model_health", "record_model_success", "record_model_failure", "configured_llm_profiles", "llm_failover_active"]

"""
Model routing utilities.
"""
from typing import Dict, Any, Optional
import asyncio
import aiohttp

MODEL_ROUTER_BILLING_HARD_DISABLE = False

# Vision model configuration
VISION_MODEL = "openai/gpt-5.4-nano"
VISION_FALLBACK_MODEL = "google/gemini-3-flash-preview"


def select_model_for_task(task: str, complexity: str = "medium") -> str:
    """Select appropriate model for a task."""
    from ..config import KIMI_MODEL, KIMI_FALLBACK_MODEL
    return KIMI_MODEL


async def _check_model_connectivity(
    api_key: str,
    base_url: str,
    model: str
) -> Dict[str, Any]:
    """Internal async function to check model connectivity.
    
    Args:
        api_key: The API key for authentication.
        base_url: The base URL for the API endpoint.
        model: The model identifier to check.
        
    Returns:
        Dict containing health status with keys 'ok', 'model', and optionally 'error' or 'status'.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload
        ) as resp:
            if resp.status == 200:
                return {"ok": True, "model": model}
            else:
                return {"ok": False, "model": model, "status": resp.status}


async def get_model_health(model: str) -> Dict[str, Any]:
    """Get health status of a model with actual API connectivity check.
    
    Args:
        model: The model identifier to check health for.
        
    Returns:
        Dict containing health status with keys 'ok', 'model', and optionally 'error' or 'status'.
    """
    import os
    
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("KIMI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    
    if not api_key:
        return {"ok": False, "model": model, "error": "No API key configured"}
    
    try:
        result = await _check_model_connectivity(api_key, base_url, model)
        return result
    except Exception as e:
        return {"ok": False, "model": model, "error": str(e)}


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
        "vision_primary": VISION_MODEL,
        "vision_fallback": VISION_FALLBACK_MODEL,
    }


def llm_failover_active() -> bool:
    """Check if LLM failover is active."""
    from ..config import LLM_FAILOVER_ENABLED
    return LLM_FAILOVER_ENABLED


async def _get_vision_model_health(model: str) -> Dict[str, Any]:
    """Async helper to get vision model health status.
    
    Args:
        model: The vision model identifier to check.
        
    Returns:
        Dict containing health status with keys 'ok', 'model', and optionally 'error'.
    """
    return await get_model_health(model)


async def select_vision_model_async() -> str:
    """Select vision model with automatic fallback logic (async version).
    
    Attempts to use the primary vision model. If it fails or is unavailable,
    automatically falls back to the secondary vision model.
    
    This async version properly checks model health when called from an async context.
    
    Returns:
        str: The selected vision model identifier.
    """
    primary = VISION_MODEL
    fallback = VISION_FALLBACK_MODEL
    
    try:
        primary_health = await _get_vision_model_health(primary)
        if primary_health.get("ok", False):
            return primary
        
        fallback_health = await _get_vision_model_health(fallback)
        if fallback_health.get("ok", False):
            return fallback
    except Exception:
        pass
    
    return primary


def select_vision_model() -> str:
    """Select vision model with automatic fallback logic.
    
    Attempts to use the primary vision model. If it fails or is unavailable,
    automatically falls back to the secondary vision model.
    
    Note: When called from an async context, this function attempts to run
    the health check synchronously which may not work properly. For async
    contexts, use select_vision_model_async() instead.
    
    Returns:
        str: The selected vision model identifier.
    """
    primary = VISION_MODEL
    fallback = VISION_FALLBACK_MODEL
    
    try:
        # Check if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # In async context - try to run synchronously with a new loop
            # This may fail on some event loops that don't allow nesting
            loop = asyncio.new_event_loop()
            try:
                health = loop.run_until_complete(_get_vision_model_health(primary))
                if health.get("ok", False):
                    return primary
                
                fallback_health = loop.run_until_complete(_get_vision_model_health(fallback))
                if fallback_health.get("ok", False):
                    return fallback
            finally:
                loop.close()
        except RuntimeError:
            # No running loop, create one for this operation
            loop = asyncio.new_event_loop()
            try:
                health = loop.run_until_complete(_get_vision_model_health(primary))
                if health.get("ok", False):
                    return primary
                
                fallback_health = loop.run_until_complete(_get_vision_model_health(fallback))
                if fallback_health.get("ok", False):
                    return fallback
            finally:
                loop.close()
    except Exception:
        pass
    
    return primary


__all__ = [
    "select_model_for_task",
    "get_model_health",
    "record_model_success",
    "record_model_failure",
    "configured_llm_profiles",
    "llm_failover_active",
    "select_vision_model",
    "select_vision_model_async",
    "VISION_MODEL",
    "VISION_FALLBACK_MODEL",
]
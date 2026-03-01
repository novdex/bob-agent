"""
LLM client with failover and circuit breaker support.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional, Any, Callable

import httpx

from ..config import settings
from ..utils import truncate_text, CircuitBreaker

logger = logging.getLogger("mind_clone.agent.llm")

# Circuit breakers for each provider
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def _get_circuit_breaker(provider: str) -> CircuitBreaker:
    """Get or create circuit breaker for a provider."""
    if provider not in _circuit_breakers:
        _circuit_breakers[provider] = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
        )
    return _circuit_breakers[provider]


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token)."""
    return len(text) // 4


def _estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    """Estimate tokens for a list of messages."""
    total = 0
    for msg in messages:
        total += _estimate_tokens(msg.get("content", ""))
    return total


def call_llm(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """Call LLM with retry and circuit breaker logic."""
    model = model or settings.kimi_model
    
    # Check circuit breaker
    circuit = _get_circuit_breaker("llm_api")
    if not circuit.can_execute():
        return {"ok": False, "error": "Circuit breaker open for LLM API"}
    
    try:
        result = _call_llm_internal(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            timeout=timeout,
        )
        
        if result.get("ok"):
            circuit.record_success()
        else:
            circuit.record_failure()
        
        return result
    
    except Exception as e:
        circuit.record_failure()
        logger.error(f"LLM call failed: {e}")
        return {"ok": False, "error": str(e)}


def _call_llm_internal(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """Internal LLM call implementation."""
    model = model or settings.kimi_model
    
    headers = {
        "Authorization": f"Bearer {settings.kimi_api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    
    try:
        response = httpx.post(
            f"{settings.kimi_base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        
        data = response.json()
        
        return {
            "ok": True,
            "data": data,
            "content": data["choices"][0]["message"].get("content", ""),
            "tool_calls": data["choices"][0]["message"].get("tool_calls"),
            "usage": data.get("usage", {}),
        }
    
    except httpx.TimeoutException:
        return {"ok": False, "error": f"LLM request timed out after {timeout}s"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP error: {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def call_llm_json_task(
    prompt: str,
    schema: Dict[str, Any],
    model: Optional[str] = None,
    max_attempts: int = 2,
) -> Dict[str, Any]:
    """Call LLM for structured JSON output."""
    system_msg = f"""You are a helpful assistant that responds with valid JSON.
Respond with a JSON object matching this schema:
{json.dumps(schema, indent=2)}
"""
    
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": prompt},
    ]
    
    for attempt in range(max_attempts):
        result = call_llm(messages, model=model)
        
        if not result.get("ok"):
            continue
        
        content = result.get("content", "")
        
        # Try to extract JSON
        try:
            # Look for JSON in code blocks
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            parsed = json.loads(json_str)
            return {"ok": True, "data": parsed}
        
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed (attempt {attempt + 1}): {e}")
            continue
    
    return {"ok": False, "error": "Failed to get valid JSON response"}


def get_available_models() -> List[str]:
    """Get list of available models."""
    models = [settings.kimi_model]
    if settings.kimi_fallback_model:
        models.append(settings.kimi_fallback_model)
    return models


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: Optional[str] = None,
) -> float:
    """Estimate cost in USD for token usage."""
    # Kimi K2.5 pricing (approximate)
    # Input: $0.003 per 1K tokens
    # Output: $0.006 per 1K tokens
    input_cost = (prompt_tokens / 1000) * 0.003
    output_cost = (completion_tokens / 1000) * 0.006
    return input_cost + output_cost

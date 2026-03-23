"""
LLM client with automatic failover chain.

Failover: MiniMax 2.7 (OpenRouter) -> Claude Sonnet (OpenRouter) -> Kimi K2.5 -> DeepSeek -> OpenAI GPT-4o.
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

_circuit_breakers: Dict[str, CircuitBreaker] = {}
_failover_chain: List[Dict[str, Any]] = []
_chain_built = False


def _get_circuit_breaker(provider: str) -> CircuitBreaker:
    """Get or create circuit breaker for a provider."""
    if provider not in _circuit_breakers:
        _circuit_breakers[provider] = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
        )
    return _circuit_breakers[provider]


_OPENROUTER_EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/arshdeep/mind-clone",
    "X-Title": "Bob Agent",
}


def _build_failover_chain() -> List[Dict[str, Any]]:
    """Build ordered list of LLM providers from configured API keys.

    Chain order (all via OpenRouter):
      1. minimax/minimax-m2.7                          (primary)
      2. nvidia/nemotron-3-super-120b-a12b:free   (free, agent-optimised)
      3. qwen/qwen3-next-80b-a3b-instruct:free                (free, reasoning)
      4. qwen/qwen3-coder:free                         (free, tool use)
      5. google/gemini-2.5-flash-lite    (cheap paid backup)
    """
    chain: List[Dict[str, Any]] = []

    or_key = getattr(settings, "openrouter_api_key", "")
    if or_key and or_key not in ("", "YOUR_OPENROUTER_KEY_HERE"):
        or_base = getattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
        _or = lambda name, model, timeout=120: {  # noqa: E731
            "name": name,
            "base_url": or_base,
            "api_key": or_key,
            "model": model,
            "format": "openai",
            "timeout": timeout,
            "extra_headers": _OPENROUTER_EXTRA_HEADERS,
        }
        chain.append(_or(
            "openrouter-minimax",
            getattr(settings, "openrouter_model", "minimax/minimax-m2.7"),
        ))
        chain.append(_or("openrouter-nemotron",  "nvidia/nemotron-3-super-120b-a12b:free"))
        chain.append(_or("openrouter-deepseek",  "qwen/qwen3-next-80b-a3b-instruct:free"))
        chain.append(_or("openrouter-qwen",      "qwen/qwen3-coder:free"))
        chain.append(_or("openrouter-gemini",    "google/gemini-2.5-flash-lite", timeout=60))

    if not chain:
        logger.error("LLM_FAILOVER_CHAIN_EMPTY — no valid providers configured")
    else:
        logger.info("LLM_FAILOVER_CHAIN providers=%d names=%s",
                    len(chain), [p["name"] for p in chain])
    return chain


def _ensure_chain() -> List[Dict[str, Any]]:
    """Lazily build the failover chain once."""
    global _chain_built
    if not _chain_built:
        _failover_chain.clear()
        _failover_chain.extend(_build_failover_chain())
        _chain_built = True
    return _failover_chain


def _call_openai_compatible(provider, messages, tools=None,
                            tool_choice=None, timeout=90):
    """Call an OpenAI-compatible endpoint (OpenRouter, Kimi, DeepSeek, OpenAI)."""
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    if provider.get("extra_headers"):
        headers.update(provider["extra_headers"])
    payload: Dict[str, Any] = {
        "model": provider["model"],
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    url = f"{provider['base_url'].rstrip('/')}/chat/completions"
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    msg = data["choices"][0]["message"]
    return {
        "ok": True, "data": data,
        "content": msg.get("content", ""),
        "reasoning_content": msg.get("reasoning_content", ""),
        "tool_calls": msg.get("tool_calls"),
        "usage": data.get("usage", {}),
        "provider": provider["name"],
    }


def _convert_messages_for_anthropic(messages):
    """Convert OpenAI-format messages to Anthropic format."""
    system_parts = []
    converted = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(str(content))
            continue
        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{"type": "tool_result",
                              "tool_use_id": msg.get("tool_call_id", ""),
                              "content": str(content)}],
            })
            continue
        if role == "assistant" and msg.get("tool_calls"):
            blocks: List[Dict] = []
            tc_text = str(msg.get("content", "")).strip()
            if tc_text:
                blocks.append({"type": "text", "text": tc_text})
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                try:
                    inp = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    inp = {}
                blocks.append({
                    "type": "tool_use", "id": tc.get("id", ""),
                    "name": func.get("name", ""), "input": inp,
                })
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role in ("user", "assistant"):
            converted.append({"role": role, "content": str(content) or "(empty)"})
    merged: List[Dict] = []
    for msg in converted:
        if merged and merged[-1]["role"] == msg["role"]:
            prev, curr = merged[-1]["content"], msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n" + curr
            elif isinstance(prev, list) and isinstance(curr, list):
                merged[-1]["content"] = prev + curr
            elif isinstance(prev, str) and isinstance(curr, list):
                merged[-1]["content"] = [{"type": "text", "text": prev}] + curr
            elif isinstance(prev, list) and isinstance(curr, str):
                merged[-1]["content"] = prev + [{"type": "text", "text": curr}]
        else:
            merged.append(msg)
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "(conversation continued)"})
    return "\n\n".join(system_parts), merged


def _call_anthropic(provider, messages, tools=None,
                    tool_choice=None, timeout=60):
    """Call Anthropic Messages API."""
    system_prompt, converted_msgs = _convert_messages_for_anthropic(messages)
    headers = {
        "x-api-key": provider["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": provider["model"],
        "messages": converted_msgs,
        "max_tokens": settings.llm_max_tokens,
    }
    if system_prompt:
        payload["system"] = system_prompt
    if tools:
        a_tools = []
        for tool in tools:
            func = tool.get("function", {})
            a_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters",
                                         {"type": "object", "properties": {}}),
            })
        payload["tools"] = a_tools
    url = f"{provider['base_url'].rstrip('/')}/v1/messages"
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    text_parts = []
    tool_calls = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                },
            })
    return {
        "ok": True,
        "content": "\n".join(text_parts),
        "reasoning_content": "",
        "tool_calls": tool_calls if tool_calls else None,
        "usage": data.get("usage", {}),
        "provider": "anthropic",
    }


def call_llm(messages, tools=None, tool_choice=None,
             model=None, timeout=None):
    """Call LLM with automatic failover across all configured providers."""
    chain = _ensure_chain()
    if not chain:
        return {"ok": False, "error": "No LLM providers configured"}
    last_error = "No providers available"
    errors_log: List[str] = []
    for provider in chain:
        pname = provider["name"]
        ptimeout = timeout or provider.get("timeout", 90)
        circuit = _get_circuit_breaker(pname)
        if not circuit.can_execute():
            logger.info("LLM_FAILOVER skip %s (circuit breaker open)", pname)
            continue
        try:
            t0 = time.monotonic()
            if provider["format"] == "anthropic":
                result = _call_anthropic(provider, messages, tools=tools,
                                         tool_choice=tool_choice, timeout=ptimeout)
            else:
                result = _call_openai_compatible(provider, messages, tools=tools,
                                                  tool_choice=tool_choice,
                                                  timeout=ptimeout)
            elapsed = time.monotonic() - t0
            if result.get("ok"):
                circuit.record_success()
                logger.info("LLM_OK provider=%s model=%s elapsed=%.1fs",
                            pname, provider.get("model"), elapsed)
                return result
            error_msg = result.get("error", "Unknown error")
            circuit.record_failure()
            errors_log.append(f"{pname}: {error_msg}")
            logger.warning("LLM_FAILOVER %s error: %s, trying next...",
                           pname, truncate_text(error_msg, 100))
            last_error = error_msg
        except httpx.TimeoutException:
            circuit.record_failure()
            errors_log.append(f"{pname}: timed out after {ptimeout}s")
            logger.warning("LLM_FAILOVER %s timed out after %ds, trying next...",
                           pname, ptimeout)
            last_error = f"{pname} timed out"
        except httpx.HTTPStatusError as e:
            circuit.record_failure()
            status = e.response.status_code
            try:
                body = e.response.json()
                detail = body.get("error", {}).get("message", "") or str(body)[:200]
                error_msg = f"HTTP {status}: {detail}"
            except Exception:
                error_msg = f"HTTP {status}"
            errors_log.append(f"{pname}: {error_msg}")
            logger.warning("LLM_FAILOVER %s %s, trying next...",
                           pname, error_msg[:150])
            last_error = error_msg
        except Exception as e:
            circuit.record_failure()
            error_msg = str(e)[:200]
            errors_log.append(f"{pname}: {error_msg}")
            logger.warning("LLM_FAILOVER %s error: %s, trying next...",
                           pname, error_msg)
            last_error = error_msg
    logger.error("LLM_ALL_PROVIDERS_FAILED errors=[%s]", " | ".join(errors_log))
    return {"ok": False, "error": f"All LLM providers failed. {last_error}"}


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token)."""
    return len(text) // 4


def _estimate_messages_tokens(messages) -> int:
    """Estimate tokens for a list of messages."""
    return sum(_estimate_tokens(msg.get("content", "")) for msg in messages)


def call_llm_json_task(prompt, schema, model=None, max_attempts=2):
    """Call LLM for structured JSON output."""
    system_msg = (
        "You are a helpful assistant that responds with valid JSON.\n"
        f"Respond with a JSON object matching this schema:\n"
        f"{json.dumps(schema, indent=2)}"
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(max_attempts):
        result = call_llm(messages, model=model)
        if not result.get("ok"):
            continue
        content = result.get("content", "")
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            return {"ok": True, "data": json.loads(json_str)}
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed (attempt %d): %s", attempt + 1, e)
    return {"ok": False, "error": "Failed to get valid JSON response"}


def get_available_models():
    """Get list of available models from the failover chain."""
    chain = _ensure_chain()
    return [p["model"] for p in chain]


def estimate_cost(prompt_tokens, completion_tokens, model=None):
    """Estimate cost in USD for token usage."""
    return (prompt_tokens / 1000) * 0.003 + (completion_tokens / 1000) * 0.006


def get_failover_status():
    """Get status of the failover chain for diagnostics."""
    chain = _ensure_chain()
    status = []
    for p in chain:
        cb = _get_circuit_breaker(p["name"])
        status.append({
            "name": p["name"], "model": p["model"],
            "format": p["format"],
            "circuit_breaker_open": not cb.can_execute(),
        })
    return {
        "providers": status,
        "total": len(chain),
        "available": sum(1 for s in status if not s["circuit_breaker_open"]),
    }

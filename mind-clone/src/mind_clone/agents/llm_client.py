"""
LLM client for the agent team.

Wraps OpenRouter (OpenAI-compatible). Primary model: MiniMax 2.7.
Model-agnostic — swap by changing AgentConfig.
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Dict, Any, Optional

import requests

from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.llm")

try:
    from .model_router import model_router
except ImportError:
    model_router = None


class LLMClient:
    """Stateless LLM client for agent team calls."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        })
        self._call_count = 0
        self._total_tokens = 0

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a chat completion request.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system: Optional system prompt (prepended as system message)
            temperature: Override default temperature
            max_tokens: Override default max_tokens
            response_format: If "json", request JSON output

        Returns:
            {"content": str, "reasoning": str, "tokens": int, "ok": bool, "error": str}
        """
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": all_messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature if temperature is not None else self.config.temperature,
        }

        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.config.base_url}/chat/completions"

        start = time.time()
        try:
            resp = self._session.post(url, json=payload, timeout=120)
            elapsed = time.time() - start

            if resp.status_code != 200:
                error_body = resp.text[:500]
                logger.error("LLM API error %d: %s", resp.status_code, error_body)
                return {
                    "content": "",
                    "reasoning": "",
                    "tokens": 0,
                    "ok": False,
                    "error": f"API error {resp.status_code}: {error_body}",
                }

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            reasoning = message.get("reasoning_content", "") or ""
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)

            self._call_count += 1
            self._total_tokens += tokens

            logger.info(
                "LLM call #%d: %d tokens, %.1fs, model=%s",
                self._call_count, tokens, elapsed, self.config.model,
            )

            return {
                "content": content,
                "reasoning": reasoning,
                "tokens": tokens,
                "ok": True,
                "error": "",
            }

        except requests.Timeout:
            logger.error("LLM API timeout after %.1fs", time.time() - start)
            return {
                "content": "",
                "reasoning": "",
                "tokens": 0,
                "ok": False,
                "error": "API request timed out",
            }
        except Exception as e:
            logger.error("LLM API exception: %s", e)
            return {
                "content": "",
                "reasoning": "",
                "tokens": 0,
                "ok": False,
                "error": str(e),
            }

    def ask(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        """
        Simple helper — send a single prompt, get back the text.

        Returns content if available, falls back to reasoning
        (Kimi K2.5 often puts output in reasoning_content).
        """
        result = self.chat(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            **kwargs,
        )
        if not result["ok"]:
            raise RuntimeError(f"LLM call failed: {result['error']}")

        content = result["content"].strip()
        reasoning = result["reasoning"].strip()
        return content if content else reasoning

    @property
    def stats(self) -> Dict[str, int]:
        """Return usage statistics."""
        return {
            "calls": self._call_count,
            "total_tokens": self._total_tokens,
        }

    def check_vision_health(self, model: str, timeout: int = 10) -> bool:
        """
        Check if a vision model is healthy and available.

        Args:
            model: The model identifier to check
            timeout: Request timeout in seconds

        Returns:
            True if the model is healthy, False otherwise
        """
        if model_router is not None:
            try:
                health = model_router.get_model_health(model)
                if health is not None:
                    return health
            except Exception as e:
                logger.warning("model_router health check failed for %s: %s", model, e)

        url = f"{self.config.base_url}/models/{model}"
        try:
            resp = self._session.get(url, timeout=timeout)
            if resp.status_code == 200:
                logger.info("Vision model %s is healthy", model)
                return True
            else:
                logger.warning("Vision model %s returned status %d", model, resp.status_code)
                return False
        except Exception as e:
            logger.warning("Vision model %s health check failed: %s", model, e)
            return False

    def vision_chat(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Send a vision-capable chat completion request with automatic fallback.

        First tries openai/gpt-5.4-nano, and if it fails or is unavailable,
        automatically falls back to google/gemini-3-flash-preview.

        Args:
            messages: List of message dicts with {"role": ..., "content": ...}.
                      Content can include image URLs for vision.
            system: Optional system prompt
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            {"content": str, "reasoning": str, "tokens": int, "ok": bool, "error": str,
             "model": str}
        """
        primary_model = "openai/gpt-5.4-nano"
        fallback_model = "google/gemini-3-flash-preview"

        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload_base: Dict[str, Any] = {
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature if temperature is not None else self.config.temperature,
        }

        url = f"{self.config.base_url}/chat/completions"

        model = primary_model
        if not self.check_vision_health(primary_model):
            logger.warning(
                "Primary vision model %s is not healthy, using fallback %s",
                primary_model, fallback_model
            )
            model = fallback_model

        payload = {"model": model, "messages": all_messages, **payload_base}

        start = time.time()
        try:
            resp = self._session.post(url, json=payload, timeout=120)
            elapsed = time.time() - start

            if resp.status_code != 200:
                error_body = resp.text[:500]
                logger.error(
                    "Vision LLM API error %d for model %s: %s",
                    resp.status_code, model, error_body
                )
                return {
                    "content": "",
                    "reasoning": "",
                    "tokens": 0,
                    "ok": False,
                    "error": f"API error {resp.status_code}: {error_body}",
                    "model": model,
                }

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            reasoning = message.get("reasoning_content", "") or ""
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)

            self._call_count += 1
            self._total_tokens += tokens

            logger.info(
                "Vision LLM call #%d: %d tokens, %.1fs, model=%s",
                self._call_count, tokens, elapsed, model,
            )

            return {
                "content": content,
                "reasoning": reasoning,
                "tokens": tokens,
                "ok": True,
                "error": "",
                "model": model,
            }

        except requests.Timeout:
            logger.error(
                "Vision LLM API timeout after %.1fs for model %s",
                time.time() - start, model
            )
            return {
                "content": "",
                "reasoning": "",
                "tokens": 0,
                "ok": False,
                "error": "API request timed out",
                "model": model,
            }
        except Exception as e:
            logger.error("Vision LLM API exception for model %s: %s", model, e)
            return {
                "content": "",
                "reasoning": "",
                "tokens": 0,
                "ok": False,
                "error": str(e),
                "model": model,
            }
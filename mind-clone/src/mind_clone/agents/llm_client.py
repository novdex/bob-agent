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

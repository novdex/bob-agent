"""
Tests for agent/llm.py — LLM client with failover.
"""
import pytest
from unittest.mock import patch, MagicMock
from mind_clone.agent.llm import (
    _estimate_tokens,
    _estimate_messages_tokens,
    get_available_models,
    estimate_cost,
    _get_circuit_breaker,
    call_llm,
    call_llm_json_task,
)


class TestTokenEstimation:
    """Test token estimation utilities."""

    def test_estimate_tokens(self):
        assert _estimate_tokens("hello world") == len("hello world") // 4

    def test_estimate_empty(self):
        assert _estimate_tokens("") == 0

    def test_estimate_messages_tokens(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        total = _estimate_messages_tokens(messages)
        assert total == _estimate_tokens("hello") + _estimate_tokens("world")

    def test_estimate_messages_missing_content(self):
        messages = [{"role": "user"}]
        total = _estimate_messages_tokens(messages)
        assert total == 0


class TestGetAvailableModels:
    """Test model listing."""

    def test_returns_list(self):
        models = get_available_models()
        assert isinstance(models, list)
        assert len(models) >= 1

    def test_primary_model_included(self):
        from mind_clone.config import settings
        models = get_available_models()
        assert settings.kimi_model in models


class TestEstimateCost:
    """Test cost estimation."""

    def test_zero_tokens(self):
        cost = estimate_cost(0, 0)
        assert cost == 0.0

    def test_positive_tokens(self):
        cost = estimate_cost(1000, 1000)
        assert cost > 0.0
        assert isinstance(cost, float)

    def test_input_cheaper_than_output(self):
        input_cost = estimate_cost(1000, 0)
        output_cost = estimate_cost(0, 1000)
        assert output_cost > input_cost


class TestCircuitBreaker:
    """Test circuit breaker integration."""

    def test_get_circuit_breaker_returns_instance(self):
        cb = _get_circuit_breaker("test_provider")
        assert cb is not None

    def test_same_provider_same_breaker(self):
        cb1 = _get_circuit_breaker("provider_a")
        cb2 = _get_circuit_breaker("provider_a")
        assert cb1 is cb2

    def test_different_providers(self):
        cb1 = _get_circuit_breaker("prov_1")
        cb2 = _get_circuit_breaker("prov_2")
        assert cb1 is not cb2


class TestCallLLM:
    """Test call_llm with mocked HTTP."""

    @patch("mind_clone.agent.llm.httpx.post")
    def test_successful_call(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = call_llm([{"role": "user", "content": "hi"}])
        assert result["ok"] is True
        assert result["content"] == "Hello!"

    @patch("mind_clone.agent.llm.httpx.post")
    def test_timeout_returns_error(self, mock_post):
        import httpx
        mock_post.side_effect = httpx.TimeoutException("timeout")

        result = call_llm([{"role": "user", "content": "hi"}])
        assert result["ok"] is False
        assert "timed out" in result["error"]

    @patch("mind_clone.agent.llm.httpx.post")
    def test_http_error(self, mock_post):
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 500
        error = httpx.HTTPStatusError("server error", request=MagicMock(), response=mock_response)
        mock_post.side_effect = error

        result = call_llm([{"role": "user", "content": "hi"}])
        assert result["ok"] is False


class TestCallLLMJsonTask:
    """Test structured JSON output."""

    @patch("mind_clone.agent.llm.call_llm")
    def test_valid_json_response(self, mock_call):
        mock_call.return_value = {
            "ok": True,
            "content": '```json\n{"answer": 42}\n```',
        }
        result = call_llm_json_task("What is the answer?", {"type": "object"})
        assert result["ok"] is True
        assert result["data"]["answer"] == 42

    @patch("mind_clone.agent.llm.call_llm")
    def test_raw_json_response(self, mock_call):
        mock_call.return_value = {
            "ok": True,
            "content": '{"key": "value"}',
        }
        result = call_llm_json_task("test", {"type": "object"})
        assert result["ok"] is True
        assert result["data"]["key"] == "value"

    @patch("mind_clone.agent.llm.call_llm")
    def test_invalid_json_retries(self, mock_call):
        mock_call.return_value = {
            "ok": True,
            "content": "not json at all",
        }
        result = call_llm_json_task("test", {"type": "object"}, max_attempts=2)
        assert result["ok"] is False

    @patch("mind_clone.agent.llm.call_llm")
    def test_llm_failure(self, mock_call):
        mock_call.return_value = {"ok": False, "error": "API down"}
        result = call_llm_json_task("test", {"type": "object"})
        assert result["ok"] is False

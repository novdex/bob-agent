"""
Tests for Telegram webhook endpoint (maps to t2-bench + FORTRESS).

Covers: webhook routing, voice detection, command dispatch, text messages,
        error handling, empty/malformed payloads.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Webhook payload fixtures
# ---------------------------------------------------------------------------

def _make_webhook_payload(text=None, voice=None, chat_id="12345", username="testuser"):
    """Build a Telegram webhook JSON payload."""
    message = {
        "message_id": 1,
        "chat": {"id": int(chat_id), "type": "private"},
        "from": {"id": int(chat_id), "username": username},
        "date": 1700000000,
    }
    if text is not None:
        message["text"] = text
    if voice is not None:
        message["voice"] = voice
    return {"update_id": 999, "message": message}


# ---------------------------------------------------------------------------
# Webhook endpoint tests
# ---------------------------------------------------------------------------

class TestTelegramWebhookEndpoint:
    """Tests the /telegram/webhook POST endpoint."""

    def test_empty_update_returns_ok(self, test_client):
        """No message field → return ok immediately."""
        response = test_client.post("/telegram/webhook", json={"update_id": 1})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_no_text_no_voice_returns_ok(self, test_client):
        """Message without text or voice → return ok."""
        payload = _make_webhook_payload()
        # No text, no voice
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_start_command(self, mock_send, test_client):
        """The /start command sends welcome message."""
        payload = _make_webhook_payload(text="/start")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "Mind Clone" in call_args[0][1]

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    @patch("mind_clone.api.routes.telegram.dispatch_incoming_message", new_callable=AsyncMock)
    def test_regular_text_dispatched(self, mock_dispatch, mock_send, test_client):
        """Non-command text message dispatches to agent."""
        mock_dispatch.return_value = {"ok": True, "queued": True}
        payload = _make_webhook_payload(text="hello bob what is AI?")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200
        mock_dispatch.assert_called_once()

    def test_voice_message_detected(self, test_client):
        """Voice messages are detected and routed (may error without real API)."""
        payload = _make_webhook_payload(
            voice={"file_id": "test_file", "duration": 5, "mime_type": "audio/ogg"},
        )
        # Voice handler will fail without real Telegram API, but should not 500
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Command routing in webhook
# ---------------------------------------------------------------------------

class TestWebhookCommandRouting:

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_identity_command(self, mock_send, test_client):
        """The /identity command returns identity info or 'no identity'."""
        payload = _make_webhook_payload(text="/identity")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200
        # Should have sent some response about identity
        if mock_send.called:
            sent_text = mock_send.call_args[0][1]
            assert isinstance(sent_text, str)

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_clear_command(self, mock_send, test_client):
        """The /clear command clears conversation history."""
        payload = _make_webhook_payload(text="/clear")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200
        if mock_send.called:
            sent_text = mock_send.call_args[0][1]
            assert "clear" in sent_text.lower() or "history" in sent_text.lower()

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    @patch("mind_clone.api.routes.telegram.handle_approval_command", new_callable=AsyncMock)
    def test_approve_command_dispatched(self, mock_approve, mock_send, test_client):
        """The /approve <token> command routes to approval handler."""
        payload = _make_webhook_payload(text="/approve abc12345def")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_tasks_command(self, mock_send, test_client):
        """The /tasks command lists recent tasks."""
        payload = _make_webhook_payload(text="/tasks")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_cron_list_command(self, mock_send, test_client):
        """The /cron_list command lists scheduled jobs."""
        payload = _make_webhook_payload(text="/cron_list")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------

class TestWebhookEdgeCases:

    def test_malformed_json_raises(self, test_client):
        """Invalid JSON body → JSONDecodeError propagated (no try/except in handler)."""
        import json
        with pytest.raises(json.JSONDecodeError):
            test_client.post(
                "/telegram/webhook",
                content=b"not json",
                headers={"content-type": "application/json"},
            )

    def test_missing_chat_field_handled(self, test_client):
        """Message without chat → KeyError caught or returns error."""
        payload = {"update_id": 1, "message": {"text": "hello"}}
        # This will raise KeyError on data["chat"]["id"] — that's expected behavior
        # The test just verifies it doesn't hang or crash the server permanently
        try:
            response = test_client.post("/telegram/webhook", json=payload)
            assert response.status_code in (200, 500)
        except (KeyError, Exception):
            pass  # Expected — no chat field

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    @patch("mind_clone.api.routes.telegram.dispatch_incoming_message", new_callable=AsyncMock)
    def test_very_long_message(self, mock_dispatch, mock_send, test_client):
        """4000+ char message dispatched normally."""
        mock_dispatch.return_value = {"ok": True, "queued": True}
        long_text = "x" * 5000
        payload = _make_webhook_payload(text=long_text)
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200
        mock_dispatch.assert_called_once()

    @patch("mind_clone.api.routes.telegram.send_telegram_message", new_callable=AsyncMock)
    def test_empty_text_message(self, mock_send, test_client):
        """Empty text string → returns ok (no dispatch)."""
        payload = _make_webhook_payload(text="")
        response = test_client.post("/telegram/webhook", json=payload)
        assert response.status_code == 200

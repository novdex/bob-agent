"""
Voice-to-text (STT) service for Telegram voice messages.

Transcribes audio using an OpenAI-compatible Whisper API endpoint.
If no STT service is configured, voice messages are rejected gracefully.

Usage:
    from mind_clone.services.voice_stt import transcribe_voice
    text = await transcribe_voice(file_bytes, mime_type="audio/ogg")
"""

from __future__ import annotations

import io
import logging
import time
from typing import Optional, Tuple

from ..config import settings
from ..core.state import increment_runtime_state

logger = logging.getLogger("mind_clone.voice_stt")

# Supported audio MIME types
SUPPORTED_AUDIO_TYPES = {
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
}

# Max audio duration / file size
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB (Whisper limit)
MAX_AUDIO_DURATION_SECONDS = 300  # 5 minutes


def stt_enabled() -> bool:
    """Check if STT is configured and available."""
    return bool(getattr(settings, "stt_api_key", "") or "")


async def transcribe_voice(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    language: Optional[str] = None,
) -> Tuple[bool, str]:
    """Transcribe audio bytes to text.

    Returns ``(ok, text_or_error)``.
    """
    if not stt_enabled():
        return False, "Voice transcription is not configured (STT_API_KEY missing)"

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return False, f"Audio too large ({len(audio_bytes)} bytes, max {MAX_AUDIO_BYTES})"

    if mime_type not in SUPPORTED_AUDIO_TYPES:
        return False, f"Unsupported audio type: {mime_type}"

    api_key = getattr(settings, "stt_api_key", "")
    api_base = getattr(settings, "stt_api_base", "https://api.openai.com/v1")

    # Determine file extension from mime
    ext_map = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
    }
    ext = ext_map.get(mime_type, "ogg")

    start = time.monotonic()
    try:
        import httpx

        url = f"{api_base.rstrip('/')}/audio/transcriptions"

        files = {"file": (f"voice.{ext}", io.BytesIO(audio_bytes), mime_type)}
        data = {"model": "whisper-large-v3-turbo"}
        if language:
            data["language"] = language

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if response.status_code != 200:
            logger.warning(
                "STT_FAIL status=%d elapsed=%dms", response.status_code, elapsed_ms
            )
            increment_runtime_state("stt_failures")
            return False, f"STT API error: {response.status_code}"

        result = response.json()
        text = str(result.get("text", "")).strip()

        if not text:
            return False, "STT returned empty transcription"

        increment_runtime_state("stt_transcriptions")
        logger.info("STT_OK len=%d elapsed=%dms", len(text), elapsed_ms)
        return True, text

    except ImportError:
        return False, "httpx not installed — required for voice transcription"
    except Exception as e:
        increment_runtime_state("stt_failures")
        logger.error("STT_ERROR: %s", e, exc_info=True)
        return False, f"STT error: {str(e)[:200]}"

"""
Text-to-speech (TTS) service using Microsoft Edge TTS.

Free, no API key required. Uses the edge-tts library which connects
to Microsoft's Edge Read Aloud service.

Usage:
    from mind_clone.services.voice_tts import synthesize_speech
    ok, audio_bytes = await synthesize_speech("Hello world")
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple, Union

from ..config import settings
from ..core.state import increment_runtime_state

logger = logging.getLogger("mind_clone.voice_tts")

# Max text length for TTS (edge-tts handles long text well, but set a sane limit)
MAX_TTS_TEXT_LENGTH = 4000


def tts_enabled() -> bool:
    """Check if TTS is available (edge-tts installed)."""
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


async def synthesize_speech(
    text: str,
    voice: Optional[str] = None,
) -> Tuple[bool, Union[bytes, str]]:
    """Convert text to speech audio bytes (MP3 format).

    Returns ``(ok, audio_bytes_or_error_message)``.
    """
    if not tts_enabled():
        return False, "TTS not available (edge-tts not installed). Install with: pip install edge-tts"

    text = str(text or "").strip()
    if not text:
        return False, "Empty text for TTS"

    if len(text) > MAX_TTS_TEXT_LENGTH:
        text = text[:MAX_TTS_TEXT_LENGTH]

    voice = voice or getattr(settings, "tts_voice", "en-US-AriaNeural")

    start = time.monotonic()
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice)

        # Collect audio chunks into bytes
        audio_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            return False, "TTS produced no audio data"

        audio_bytes = b"".join(audio_chunks)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        increment_runtime_state("tts_syntheses")
        logger.info(
            "TTS_OK text_len=%d audio_bytes=%d voice=%s elapsed=%dms",
            len(text), len(audio_bytes), voice, elapsed_ms,
        )

        return True, audio_bytes

    except Exception as e:
        increment_runtime_state("tts_failures")
        logger.error("TTS_ERROR: %s", e, exc_info=True)
        return False, f"TTS error: {str(e)[:200]}"


async def list_voices(language: str = "en") -> list[dict]:
    """List available TTS voices for a language."""
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        return [
            {"name": v["Name"], "gender": v["Gender"], "locale": v["Locale"]}
            for v in voices
            if v["Locale"].startswith(language)
        ]
    except Exception as e:
        logger.error("Failed to list TTS voices: %s", e)
        return []

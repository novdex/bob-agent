"""
Voice Interface — Bob speaks and listens.

Wraps existing TTS/STT into a unified voice mode:
- Text → Speech (using voice_tts)
- Speech → Text (using voice_stt)
- Voice conversation mode

Bob can send voice responses to Telegram.
"""
from __future__ import annotations
import asyncio
import logging
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.voice_interface")


def speak_response(text: str, owner_id: int = 1,
                   send_to_telegram: bool = True) -> dict:
    """Convert text to speech and optionally send to Telegram."""
    try:
        from .voice_tts import synthesize_speech, tts_enabled
        if not tts_enabled():
            return {"ok": False, "error": "TTS not configured"}

        # Run async synthesis
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    audio_data = pool.submit(asyncio.run, synthesize_speech(truncate_text(text, 1000))).result(timeout=30)
            else:
                audio_data = asyncio.run(synthesize_speech(truncate_text(text, 1000)))
        except RuntimeError:
            audio_data = asyncio.run(synthesize_speech(truncate_text(text, 1000)))

        if not audio_data:
            return {"ok": False, "error": "TTS synthesis returned empty audio"}

        result = {"ok": True, "audio_bytes": len(audio_data)}

        if send_to_telegram:
            try:
                from .proactive import send_telegram_voice
                send_telegram_voice(owner_id, audio_data)
                result["sent_to_telegram"] = True
            except Exception as e:
                result["telegram_error"] = str(e)[:100]

        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def transcribe_audio(audio_path: str) -> dict:
    """Transcribe audio file to text using STT."""
    try:
        from .voice_stt import transcribe_file, stt_enabled
        if not stt_enabled():
            return {"ok": False, "error": "STT not configured"}
        text = transcribe_file(audio_path)
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_speak(args: dict) -> dict:
    """Tool: Convert text to speech and send as voice message."""
    owner_id = int(args.get("_owner_id", 1))
    text = str(args.get("text", "")).strip()
    send = bool(args.get("send_to_telegram", True))
    if not text:
        return {"ok": False, "error": "text required"}
    return speak_response(text, owner_id, send)


def tool_transcribe(args: dict) -> dict:
    """Tool: Transcribe an audio file to text."""
    audio_path = str(args.get("audio_path", "")).strip()
    if not audio_path:
        return {"ok": False, "error": "audio_path required"}
    return transcribe_audio(audio_path)


def tool_voice_mode_response(args: dict) -> dict:
    """Tool: Send both text and voice response to Telegram."""
    owner_id = int(args.get("_owner_id", 1))
    text = str(args.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "text required"}
    # Send text first
    from .proactive import send_telegram_message
    send_telegram_message(owner_id, text)
    # Then send voice
    return speak_response(text, owner_id, send_to_telegram=True)

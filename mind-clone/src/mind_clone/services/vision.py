"""Vision — Bob can see and understand images sent on Telegram.

Uses Xiaomi MiMo-V2-Pro via OpenRouter to analyse images.  When a user
sends a photo on Telegram, the image bytes are base64-encoded and sent
to the multimodal model along with an optional caption.  The analysis
text is returned for the Telegram handler to relay back to the user.

Model: xiaomi/mimo-v2-pro (via OpenRouter)
Cost:  ~$1/M tokens (only charged when photos are sent)
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("mind_clone.services.vision")

_OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_VISION_MODEL = "xiaomi/mimo-v2-pro"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB safety limit


def analyse_image(
    image_bytes: bytes,
    caption: str = "",
    owner_id: int = 1,
) -> str:
    """Analyse an image using MiMo-V2-Pro via OpenRouter.

    Converts the raw image bytes to a base64-encoded data URI, builds a
    multimodal message with the caption (or a default prompt), and sends
    it to OpenRouter.

    Args:
        image_bytes: Raw JPEG/PNG/WebP image data.
        caption: Optional user-provided caption to guide the analysis.
        owner_id: Bob owner ID (for logging/attribution).

    Returns:
        A string containing the model's description / analysis of the
        image.  Returns an error message string on failure (never raises).
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not set — cannot analyse image")
        return "Vision is not available: OPENROUTER_API_KEY is missing."

    if not image_bytes:
        return "No image data received."

    if len(image_bytes) > _MAX_IMAGE_BYTES:
        return f"Image too large ({len(image_bytes) / 1024 / 1024:.1f} MB). Max is 10 MB."

    try:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
    except Exception as exc:
        logger.error("Failed to base64-encode image: %s", exc)
        return "Failed to process the image data."

    prompt_text = caption.strip() if caption.strip() else (
        "What do you see in this image? Describe it in detail."
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                    },
                },
            ],
        }
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arshdeep/mind-clone",
        "X-Title": "Bob Agent",
    }

    payload: dict[str, Any] = {
        "model": _VISION_MODEL,
        "messages": messages,
        "max_tokens": 1024,
    }

    try:
        with httpx.Client(timeout=60, trust_env=False) as client:
            response = client.post(
                _OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            if content:
                logger.info(
                    "Vision analysis complete for owner %d (%d chars)",
                    owner_id,
                    len(content),
                )
                return str(content).strip()

        logger.warning("Vision API returned no content: %s", data)
        return "The vision model returned an empty response."

    except httpx.TimeoutException:
        logger.error("Vision API call timed out for owner %d", owner_id)
        return "Vision analysis timed out. Please try again."
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = exc.response.text[:200]
        logger.error(
            "Vision API HTTP %d for owner %d: %s", status, owner_id, detail
        )
        return f"Vision API error (HTTP {status}): {detail}"
    except Exception as exc:
        logger.error("Vision analysis failed for owner %d: %s", owner_id, exc)
        return f"Vision analysis failed: {exc}"

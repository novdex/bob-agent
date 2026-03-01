"""
Vision / screenshot analysis tools.

Gives Bob the ability to analyze images, take and analyze webpage screenshots,
compare images visually, and extract text (OCR) from images.

Uses the configured vision model (default: Gemini 2.0 Flash) via an
OpenAI-compatible multimodal chat/completions endpoint.

Pillar: World Understanding, Tool Mastery
"""

from __future__ import annotations

import base64
import logging
import os
import pathlib
import re
import tempfile
import time
from typing import Any, Dict
from urllib.parse import urlparse

from ..config import VISION_API_KEY, VISION_API_BASE, VISION_MODEL, VISION_ENABLED

log = logging.getLogger("mind_clone.tools.vision")

_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
_DEFAULT_TIMEOUT = 60


def _check_enabled() -> Dict[str, Any] | None:
    """Return error dict if vision is disabled, else None."""
    if not VISION_ENABLED:
        return {"ok": False, "error": "Vision is disabled (VISION_ENABLED=false)"}
    if not VISION_API_KEY:
        return {"ok": False, "error": "Vision not configured (VISION_API_KEY missing)"}
    return None


def _encode_image(path: str) -> str:
    """Base64-encode a local image file."""
    p = pathlib.Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    if p.stat().st_size > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image too large ({p.stat().st_size / 1024 / 1024:.1f} MB)")
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _guess_mime(path: str) -> str:
    """Guess image MIME type from extension."""
    ext = pathlib.Path(path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    }.get(ext, "image/png")


def _is_url(s: str) -> bool:
    """Return True if s looks like an HTTP(S) URL."""
    try:
        return urlparse(s).scheme in ("http", "https")
    except Exception:
        return False


def _build_image_content(image: str) -> Dict[str, Any]:
    """Build an OpenAI image_url content block from path or URL."""
    if _is_url(image):
        return {"type": "image_url", "image_url": {"url": image}}
    b64 = _encode_image(image)
    mime = _guess_mime(image)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _call_vision_api(
    messages: list, max_tokens: int = 1024, timeout: int = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """POST to the vision model's chat/completions endpoint."""
    import httpx

    api_url = f"{VISION_API_BASE.rstrip('/')}/chat/completions"

    try:
        t0 = time.monotonic()
        resp = httpx.post(
            api_url,
            headers={"Authorization": f"Bearer {VISION_API_KEY}", "Content-Type": "application/json"},
            json={"model": VISION_MODEL, "messages": messages, "max_tokens": max_tokens},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        log.info("VISION_OK model=%s len=%d elapsed=%.1fs", VISION_MODEL, len(text), time.monotonic() - t0)
        return {"ok": True, "analysis": text, "model": VISION_MODEL, "usage": usage}
    except Exception as exc:
        log.error("VISION_ERROR model=%s error=%s", VISION_MODEL, str(exc)[:200])
        return {"ok": False, "error": f"Vision error: {str(exc)[:200]}"}


# ═══════════════════════════════════════════════════════════════════════════
# Tool functions
# ═══════════════════════════════════════════════════════════════════════════

def tool_vision_analyze(args: dict) -> dict:
    """Analyze an image (local path or URL) with a text prompt."""
    err = _check_enabled()
    if err:
        return err

    image = str(args.get("image", "")).strip()
    if not image:
        return {"ok": False, "error": "image is required (path or URL)"}

    prompt = str(args.get("prompt", "What do you see?")).strip() or "What do you see?"
    max_tokens = int(args.get("max_tokens", 1024))

    try:
        image_content = _build_image_content(image)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        image_content,
    ]}]
    return _call_vision_api(messages, max_tokens=max_tokens)


def tool_vision_webpage(args: dict) -> dict:
    """Screenshot a URL then analyze with vision model. Falls back to text fetch."""
    err = _check_enabled()
    if err:
        return err

    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}
    if not _is_url(url):
        return {"ok": False, "error": f"Invalid URL: {url}"}

    prompt = str(args.get("prompt", "Describe this page")).strip() or "Describe this page"
    max_tokens = int(args.get("max_tokens", 1024))

    # Attempt 1: Playwright screenshot
    try:
        from playwright.sync_api import sync_playwright

        screenshot_path = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(url, wait_until="networkidle", timeout=30_000)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                screenshot_path = tmp.name
                tmp.close()
                page.screenshot(path=screenshot_path, full_page=False)
                browser.close()

            image_content = _build_image_content(screenshot_path)
            messages = [{"role": "user", "content": [
                {"type": "text", "text": f"Screenshot of {url}. {prompt}"},
                image_content,
            ]}]
            result = _call_vision_api(messages, max_tokens=max_tokens)
            result["method"] = "screenshot"
            result["url"] = url
            return result
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.unlink(screenshot_path)
                except OSError:
                    pass
    except ImportError:
        log.info("No Playwright, falling back to text fetch for %s", url)
    except Exception as exc:
        log.warning("Screenshot failed for %s: %s", url, str(exc)[:200])

    # Attempt 2: Fetch page text
    try:
        import httpx
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text[:50_000])
        text = re.sub(r"\s+", " ", text).strip()[:15_000]
        if not text:
            return {"ok": False, "error": f"No readable text at {url}"}

        messages = [{"role": "user", "content": (
            f"Text content from {url} (no screenshot available). {prompt}\n\n{text}"
        )}]
        result = _call_vision_api(messages, max_tokens=max_tokens)
        result["method"] = "text_fallback"
        result["url"] = url
        return result
    except Exception as exc:
        return {"ok": False, "error": f"Failed to fetch {url}: {str(exc)[:200]}"}


def tool_vision_compare(args: dict) -> dict:
    """Compare two images visually and describe differences."""
    err = _check_enabled()
    if err:
        return err

    image1 = str(args.get("image1", "")).strip()
    image2 = str(args.get("image2", "")).strip()
    if not image1:
        return {"ok": False, "error": "image1 is required"}
    if not image2:
        return {"ok": False, "error": "image2 is required"}

    prompt = str(args.get("prompt", "What changed between these two images?")).strip()
    max_tokens = int(args.get("max_tokens", 1024))

    try:
        img1 = _build_image_content(image1)
        img2 = _build_image_content(image2)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    messages = [{"role": "user", "content": [
        {"type": "text", "text": f"Compare these images. {prompt}"},
        {"type": "text", "text": "Image 1:"}, img1,
        {"type": "text", "text": "Image 2:"}, img2,
    ]}]
    return _call_vision_api(messages, max_tokens=max_tokens)


def tool_vision_extract_text(args: dict) -> dict:
    """OCR: extract all readable text from an image."""
    err = _check_enabled()
    if err:
        return err

    image = str(args.get("image", "")).strip()
    if not image:
        return {"ok": False, "error": "image is required"}

    max_tokens = int(args.get("max_tokens", 2048))

    try:
        image_content = _build_image_content(image)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    messages = [{"role": "user", "content": [
        {"type": "text", "text": (
            "Extract ALL text visible in this image. Reproduce exactly as written, "
            "preserving line breaks and layout. If tables, format clearly. "
            "If no text visible, respond with '(no text detected)'."
        )},
        image_content,
    ]}]

    result = _call_vision_api(messages, max_tokens=max_tokens)
    if result.get("ok"):
        result["extracted_text"] = result["analysis"]
    return result

"""Web automation tools — browser control for Bob.

Tools:
    browser_open      — Open URL, return page text (httpx fallback)
    browser_screenshot — Take page screenshot (Playwright only)
    browser_click     — Click element by CSS selector
    browser_type      — Type text into input field
    browser_extract   — Extract elements by CSS selector (BS4 fallback)
    browser_script    — Execute JavaScript on page
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time
from typing import Any

import logging

log = logging.getLogger("mind_clone.tools.web_automation")

# ---------------------------------------------------------------------------
# Playwright browser singleton
# ---------------------------------------------------------------------------
_browser: Any = None
_playwright: Any = None


async def _ensure_browser():
    """Get or create a headless Playwright Chromium browser."""
    global _browser, _playwright
    if _browser and _browser.is_connected():
        return _browser
    try:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        log.info("Playwright browser launched (headless)")
        return _browser
    except ImportError:
        log.warning("playwright not installed — browser tools will use httpx fallback")
        return None
    except Exception as exc:
        log.warning("Playwright launch failed: %s", exc)
        return None


async def _new_page(url: str, timeout: int = 30_000):
    """Open a new page navigated to *url*. Returns ``None`` if Playwright unavailable."""
    browser = await _ensure_browser()
    if browser is None:
        return None
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception:
        await page.close()
        raise
    return page


# ---------------------------------------------------------------------------
# Lightweight httpx fallback
# ---------------------------------------------------------------------------
async def _httpx_get(url: str) -> dict:
    try:
        import httpx  # noqa: F811
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": "Bob-Agent/1.0"})
            return {"ok": True, "status": resp.status_code, "text": resp.text[:8000], "url": str(resp.url)}
    except ImportError:
        return {"ok": False, "error": "Neither playwright nor httpx installed"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _bs4_extract(html: str, selector: str, attribute: str | None = None) -> list:
    """Extract elements from HTML using BeautifulSoup + CSS selectors."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        elems = soup.select(selector)[:50]
        if attribute:
            return [e.get(attribute, "") for e in elems]
        return [e.get_text(strip=True) for e in elems]
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# Async/sync bridge
# ---------------------------------------------------------------------------
def _run_async(coro):
    """Run an async coroutine from synchronous tool dispatch."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. FastAPI) — schedule as task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=60)
    else:
        return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════

async def _browser_open(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}

    page = await _new_page(url)
    if page:
        try:
            title = await page.title()
            text = await page.inner_text("body")
            return {"ok": True, "url": page.url, "title": title, "text": text[:8000]}
        finally:
            await page.close()

    # Fallback
    log.info("browser_open fallback to httpx for %s", url)
    return await _httpx_get(url)


def tool_browser_open(args: dict) -> dict:
    """Open a URL and return the page text content."""
    log.info("tool_browser_open: %s", args.get("url"))
    try:
        return _run_async(_browser_open(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
async def _browser_screenshot(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}

    page = await _new_page(url)
    if page is None:
        return {"ok": False, "error": "Playwright is required for screenshots (pip install playwright && playwright install)"}

    try:
        full_page = bool(args.get("full_page", False))
        out_dir = pathlib.Path("persist/screenshots")
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"shot_{int(time.time() * 1000)}.png"
        path = out_dir / filename
        await page.screenshot(path=str(path), full_page=full_page)
        return {"ok": True, "url": page.url, "path": str(path)}
    finally:
        await page.close()


def tool_browser_screenshot(args: dict) -> dict:
    """Take a screenshot of a web page."""
    log.info("tool_browser_screenshot: %s", args.get("url"))
    try:
        return _run_async(_browser_screenshot(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
async def _browser_click(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    selector = str(args.get("selector", "")).strip()
    if not url or not selector:
        return {"ok": False, "error": "url and selector are required"}

    page = await _new_page(url)
    if page is None:
        return {"ok": False, "error": "Playwright is required for click actions"}

    try:
        wait_after = int(args.get("wait_after", 1000))
        await page.click(selector, timeout=10_000)
        await page.wait_for_timeout(wait_after)
        text = await page.inner_text("body")
        return {"ok": True, "clicked": selector, "page_text": text[:8000]}
    finally:
        await page.close()


def tool_browser_click(args: dict) -> dict:
    """Click an element on a web page by CSS selector."""
    log.info("tool_browser_click: %s on %s", args.get("selector"), args.get("url"))
    try:
        return _run_async(_browser_click(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
async def _browser_type(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    selector = str(args.get("selector", "")).strip()
    text = str(args.get("text", ""))
    if not url or not selector or not text:
        return {"ok": False, "error": "url, selector, and text are required"}

    page = await _new_page(url)
    if page is None:
        return {"ok": False, "error": "Playwright is required for type actions"}

    try:
        await page.fill(selector, text, timeout=10_000)
        if args.get("submit"):
            await page.press(selector, "Enter")
            await page.wait_for_timeout(1000)
        return {"ok": True, "typed": text, "selector": selector}
    finally:
        await page.close()


def tool_browser_type(args: dict) -> dict:
    """Type text into an input field on a web page."""
    log.info("tool_browser_type: '%s' into %s", args.get("text"), args.get("selector"))
    try:
        return _run_async(_browser_type(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
async def _browser_extract(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    selector = str(args.get("selector", "")).strip()
    attribute = args.get("attribute")
    if not url or not selector:
        return {"ok": False, "error": "url and selector are required"}

    page = await _new_page(url)
    if page:
        try:
            elements = await page.query_selector_all(selector)
            results = []
            for el in elements[:50]:
                if attribute:
                    val = await el.get_attribute(attribute)
                    results.append(val or "")
                else:
                    results.append(await el.inner_text())
            return {"ok": True, "count": len(results), "elements": results}
        finally:
            await page.close()

    # Fallback: httpx + BS4
    log.info("browser_extract fallback to httpx+BS4 for %s", url)
    resp = await _httpx_get(url)
    if not resp.get("ok"):
        return resp
    elements = await _bs4_extract(resp["text"], selector, attribute)
    return {"ok": True, "count": len(elements), "elements": elements}


def tool_browser_extract(args: dict) -> dict:
    """Extract elements from a web page using CSS selectors."""
    log.info("tool_browser_extract: '%s' from %s", args.get("selector"), args.get("url"))
    try:
        return _run_async(_browser_extract(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
async def _browser_script(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    script = str(args.get("script", "")).strip()
    if not url or not script:
        return {"ok": False, "error": "url and script are required"}

    page = await _new_page(url)
    if page is None:
        return {"ok": False, "error": "Playwright is required for script execution"}

    try:
        result = await page.evaluate(script)
        # Serialize result
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, default=str, ensure_ascii=False)[:8000]
        else:
            result_str = str(result)[:8000]
        return {"ok": True, "result": result_str}
    finally:
        await page.close()


def tool_browser_script(args: dict) -> dict:
    """Execute JavaScript on a web page and return the result."""
    log.info("tool_browser_script on %s", args.get("url"))
    try:
        return _run_async(_browser_script(args))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
async def browser_cleanup():
    """Close the Playwright browser instance."""
    global _browser, _playwright
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    log.info("Browser automation cleaned up")

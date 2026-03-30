"""
Browser Automation — Browser-Use style headless browsing.

Provides headless Chrome/Edge browsing via Selenium for:
- Page content extraction with optional LLM-guided goal extraction
- Form filling and submission
- Screenshot capture

Uses selenium + webdriver_manager for automatic driver management.
All operations run in headless mode with a 30-second timeout.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from ..config import settings
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.browser_automation")

_SCREENSHOT_DIR = Path.home() / ".mind-clone" / "screenshots"
_PAGE_TIMEOUT = 30  # seconds


def _get_driver():
    """Create and return a headless Selenium WebDriver instance.

    Tries Chrome first, falls back to Edge.

    Returns:
        A Selenium WebDriver instance.

    Raises:
        RuntimeError: If no supported browser / driver can be initialised.
    """
    from selenium import webdriver

    # --- Try Chrome ---
    try:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager

        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-extensions")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(_PAGE_TIMEOUT)
        driver.implicitly_wait(10)
        return driver
    except Exception as chrome_err:
        logger.debug("Chrome driver failed: %s — trying Edge", chrome_err)

    # --- Fallback: Edge ---
    try:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService
        from webdriver_manager.microsoft import EdgeChromiumDriverManager

        opts = EdgeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=opts)
        driver.set_page_load_timeout(_PAGE_TIMEOUT)
        driver.implicitly_wait(10)
        return driver
    except Exception as edge_err:
        logger.error("Edge driver also failed: %s", edge_err)

    raise RuntimeError(
        "Could not initialise any browser driver. "
        "Install Chrome or Edge and ensure selenium + webdriver_manager are available."
    )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def browse_url(url: str, goal: str = "") -> dict:
    """Open *url* in headless Chrome/Edge, extract page text.

    Optionally uses the LLM to extract specific information based on *goal*.

    Args:
        url: The URL to open.
        goal: Optional description of what information to extract.

    Returns:
        Dict with keys: ok, url, title, text, extracted.
    """
    driver = None
    try:
        driver = _get_driver()
        driver.get(url)

        title = driver.title or ""
        # Extract visible text via JS for cleaner output
        text = driver.execute_script(
            "return document.body ? document.body.innerText : '';"
        ) or ""
        text = truncate_text(text, 8000)

        extracted = ""
        if goal and text:
            try:
                from ..agent.llm import call_llm

                prompt = [
                    {"role": "user", "content": (
                        f"Extract the following from this webpage content:\n"
                        f"Goal: {goal}\n\n"
                        f"Page title: {title}\n"
                        f"Page content:\n{truncate_text(text, 4000)}\n\n"
                        f"Return a concise, structured answer with key facts."
                    )},
                ]
                result = call_llm(prompt, temperature=0.2)
                if result.get("ok"):
                    extracted = result.get("content", "")
            except Exception as llm_err:
                logger.warning("LLM extraction failed: %s", llm_err)
                extracted = "[LLM extraction failed]"

        return {
            "ok": True,
            "url": url,
            "title": title,
            "text": text,
            "extracted": extracted,
        }

    except Exception as e:
        logger.error("browse_url failed for %s: %s", url, e, exc_info=True)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def fill_form(url: str, fields: dict) -> dict:
    """Open *url*, fill form fields by name/id, and submit.

    Args:
        url: The URL containing the form.
        fields: Dict mapping field name/id to value to enter.

    Returns:
        Dict with keys: ok, url, fields_filled, result_title.
    """
    driver = None
    try:
        driver = _get_driver()
        driver.get(url)

        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        filled_count = 0
        for field_name, value in fields.items():
            element = None
            # Try by name first, then by id
            try:
                element = driver.find_element(By.NAME, field_name)
            except Exception:
                pass
            if element is None:
                try:
                    element = driver.find_element(By.ID, field_name)
                except Exception:
                    pass
            if element is None:
                logger.warning("Could not find form field: %s", field_name)
                continue

            element.clear()
            element.send_keys(str(value))
            filled_count += 1

        # Submit — try Enter on last element, or look for a submit button
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, '[type="submit"]')
            submit_btn.click()
        except Exception:
            try:
                if element is not None:
                    element.send_keys(Keys.RETURN)
            except Exception:
                pass

        # Wait briefly for navigation
        import time
        time.sleep(2)

        result_title = driver.title or ""
        return {
            "ok": True,
            "url": url,
            "fields_filled": filled_count,
            "result_title": result_title,
        }

    except Exception as e:
        logger.error("fill_form failed for %s: %s", url, e, exc_info=True)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def take_screenshot(url: str) -> dict:
    """Open *url* in headless browser and save a screenshot.

    Screenshots are saved to ``~/.mind-clone/screenshots/``.

    Args:
        url: The URL to screenshot.

    Returns:
        Dict with keys: ok, url, path.
    """
    driver = None
    try:
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        # Generate a safe filename from the URL
        import hashlib
        import time

        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = int(time.time())
        filename = f"screenshot_{timestamp}_{url_hash}.png"
        filepath = _SCREENSHOT_DIR / filename

        driver = _get_driver()
        driver.get(url)

        # Wait a moment for JS rendering
        import time as _t
        _t.sleep(1)

        driver.save_screenshot(str(filepath))
        logger.info("Screenshot saved: %s", filepath)

        return {
            "ok": True,
            "url": url,
            "path": str(filepath),
        }

    except Exception as e:
        logger.error("take_screenshot failed for %s: %s", url, e, exc_info=True)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------

def tool_browse(args: dict) -> dict:
    """Tool wrapper for browse_url.

    Args:
        args: Dict with keys ``url`` (str, required), ``goal`` (str, optional).

    Returns:
        browse_url result dict.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}
    if len(url) > 4096:
        return {"ok": False, "error": "url is too long (max 4096 chars)"}

    goal = str(args.get("goal", "")).strip()
    return browse_url(url, goal=goal)


def tool_screenshot(args: dict) -> dict:
    """Tool wrapper for take_screenshot.

    Args:
        args: Dict with key ``url`` (str, required).

    Returns:
        take_screenshot result dict.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}
    if len(url) > 4096:
        return {"ok": False, "error": "url is too long (max 4096 chars)"}

    return take_screenshot(url)

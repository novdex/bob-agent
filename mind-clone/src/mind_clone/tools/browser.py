"""
Browser Automation Tools (Pillar 5)

Selenium-based browser automation for web scraping, form filling,
and JavaScript execution.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger("mind_clone.browser")

# Configuration (will be imported from settings)
BROWSER_TOOL_ENABLED = True
BROWSER_HEADLESS_DEFAULT = False
BROWSER_SESSION_TIMEOUT_SECONDS = 300
TOOL_CHAINING_HINTS_ENABLED = True
ENVIRONMENT_STATE_ENABLED = True
ENVIRONMENT_STATE_TTL_SECONDS = 60

# Global state
_browser_sessions: dict[int, dict] = {}  # owner_id -> {"driver": WebDriver, "last_used": float}
_browser_lock = threading.Lock()


def _get_or_create_browser(owner_id: int, headless: bool | None = None) -> "WebDriver | None":
    """Get or create a browser session for an owner."""
    if not BROWSER_TOOL_ENABLED:
        return None
    
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
    except ImportError:
        logger.warning("SELENIUM_NOT_AVAILABLE")
        return None
    
    with _browser_lock:
        session = _browser_sessions.get(owner_id)
        if session:
            session["last_used"] = time.monotonic()
            try:
                session["driver"].title  # health check
                return session["driver"]
            except Exception:
                try:
                    session["driver"].quit()
                except Exception:
                    pass
                _browser_sessions.pop(owner_id, None)
        
        # Create new session
        try:
            opts = ChromeOptions()
            if headless if headless is not None else BROWSER_HEADLESS_DEFAULT:
                opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            driver = webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(30)
            _browser_sessions[owner_id] = {"driver": driver, "last_used": time.monotonic()}
            return driver
        except Exception as e:
            logger.warning("BROWSER_CREATE_FAIL owner=%s error=%s", owner_id, str(e)[:200])
            return None


def _cleanup_browser_sessions():
    """Close browser sessions that have been idle too long."""
    now = time.monotonic()
    with _browser_lock:
        for oid in list(_browser_sessions.keys()):
            s = _browser_sessions[oid]
            if (now - s["last_used"]) > BROWSER_SESSION_TIMEOUT_SECONDS:
                try:
                    s["driver"].quit()
                except Exception:
                    pass
                _browser_sessions.pop(oid, None)


_SEMANTIC_SNAPSHOT_JS = """
(function() {
    var snap = {headings: [], links: [], forms: [], buttons: [],
                meta_description: "", lang: ""};
    document.querySelectorAll("h1,h2,h3").forEach(function(h, i) {
        if (i < 20 && h.textContent.trim())
            snap.headings.push({level: h.tagName.toLowerCase(),
                                text: h.textContent.trim().slice(0, 120)});
    });
    document.querySelectorAll("a[href]").forEach(function(a, i) {
        if (i < 30 && a.textContent.trim())
            snap.links.push({text: a.textContent.trim().slice(0, 80),
                             href: a.href.slice(0, 200)});
    });
    document.querySelectorAll("form").forEach(function(f, i) {
        if (i < 5) {
            var inputs = [];
            f.querySelectorAll("input,textarea,select").forEach(function(inp, j) {
                if (j < 10)
                    inputs.push({tag: inp.tagName.toLowerCase(),
                                 type: inp.type || "text",
                                 name: inp.name || ""});
            });
            snap.forms.push({action: (f.action || "").slice(0, 200),
                             method: (f.method || "GET").toUpperCase(),
                             inputs: inputs});
        }
    });
    document.querySelectorAll("button, input[type=submit], input[type=button]")
        .forEach(function(b, i) {
            if (i < 15) {
                var txt = (b.textContent || b.value || "").trim().slice(0, 60);
                if (txt) snap.buttons.push(txt);
            }
        });
    var meta = document.querySelector("meta[name=description]");
    if (meta) snap.meta_description = (meta.content || "").slice(0, 300);
    snap.lang = (document.documentElement.lang || "").slice(0, 10);
    return snap;
})();
"""


def _capture_semantic_snapshot(driver) -> dict:
    """Extract structured page metadata from a Selenium WebDriver session."""
    try:
        return driver.execute_script(_SEMANTIC_SNAPSHOT_JS) or {}
    except Exception:
        return {}


def tool_browser_open(args: dict) -> dict:
    """Open a URL in the browser and return a semantic snapshot."""
    owner_id = int(args.get("_owner_id", 1))
    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "URL required"}

    from ..core.security import apply_url_safety_guard
    safe_ok, safe_reason = apply_url_safety_guard(url, source="browser_open")
    if not safe_ok:
        return {"ok": False, "error": safe_reason, "url": url}

    driver = _get_or_create_browser(owner_id, headless=args.get("headless"))
    if not driver:
        return {"ok": False, "error": "Browser not available (Selenium/Chrome not installed)"}

    try:
        driver.get(url)
        result = {"ok": True, "title": driver.title, "url": driver.current_url}
        snapshot = _capture_semantic_snapshot(driver)
        if snapshot:
            result["snapshot"] = snapshot
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_get_text(args: dict) -> dict:
    """Get text content from a page element."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "body")).strip()
    
    session = _browser_sessions.get(owner_id)
    if not session:
        return {"ok": False, "error": "No browser session. Call browser_open first."}
    
    try:
        from selenium.webdriver.common.by import By
        session["last_used"] = time.monotonic()
        el = session["driver"].find_element(By.CSS_SELECTOR, selector)
        text = el.text[:5000]
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_click(args: dict) -> dict:
    """Click an element on the page."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "")).strip()
    if not selector:
        return {"ok": False, "error": "selector required"}
    
    session = _browser_sessions.get(owner_id)
    if not session:
        return {"ok": False, "error": "No browser session. Call browser_open first."}
    
    try:
        from selenium.webdriver.common.by import By
        session["last_used"] = time.monotonic()
        el = session["driver"].find_element(By.CSS_SELECTOR, selector)
        el.click()
        return {"ok": True, "clicked": selector}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_type(args: dict) -> dict:
    """Type text into an input element."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "")).strip()
    text = str(args.get("text", ""))
    if not selector:
        return {"ok": False, "error": "selector required"}
    
    session = _browser_sessions.get(owner_id)
    if not session:
        return {"ok": False, "error": "No browser session. Call browser_open first."}
    
    try:
        from selenium.webdriver.common.by import By
        session["last_used"] = time.monotonic()
        el = session["driver"].find_element(By.CSS_SELECTOR, selector)
        el.clear()
        el.send_keys(text)
        return {"ok": True, "typed_into": selector}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_screenshot(args: dict) -> dict:
    """Take a screenshot of the current page."""
    owner_id = int(args.get("_owner_id", 1))
    session = _browser_sessions.get(owner_id)
    if not session:
        return {"ok": False, "error": "No browser session. Call browser_open first."}
    
    try:
        session["last_used"] = time.monotonic()
        png = session["driver"].get_screenshot_as_base64()
        return {"ok": True, "screenshot_base64": png[:50000]}  # limit size
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_execute_js(args: dict) -> dict:
    """Execute JavaScript in the browser context."""
    owner_id = int(args.get("_owner_id", 1))
    code = str(args.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "code required"}
    
    session = _browser_sessions.get(owner_id)
    if not session:
        return {"ok": False, "error": "No browser session. Call browser_open first."}
    
    try:
        session["last_used"] = time.monotonic()
        result = session["driver"].execute_script(code)
        return {"ok": True, "result": str(result)[:3000] if result else None}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_close(args: dict) -> dict:
    """Close the browser session."""
    owner_id = int(args.get("_owner_id", 1))
    with _browser_lock:
        session = _browser_sessions.pop(owner_id, None)
    if session:
        try:
            session["driver"].quit()
        except Exception:
            pass
        return {"ok": True, "message": "Browser closed."}
    return {"ok": True, "message": "No browser session was open."}


# ============================================================================
# Environment State Capture (Pillar 7)
# ============================================================================

_env_state_cache: dict[str, dict] = {}  # "state" -> {"data": {...}, "ts": float}


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def capture_environment_state(owner_id: int | None = None) -> dict:
    """Capture current environment state: open windows, key processes, etc."""
    if not ENVIRONMENT_STATE_ENABLED:
        return {}
    
    # Check cache
    now = time.monotonic()
    cached = _env_state_cache.get("state")
    if cached and (now - cached["ts"]) < ENVIRONMENT_STATE_TTL_SECONDS:
        return cached["data"]
    
    state = {
        "open_windows": [],
        "key_processes": [],
        "timestamp": utc_now_iso(),
    }
    
    # Note: Import desktop tools would go here, but we avoid circular imports
    # by passing the functions as parameters when needed
    
    # Get key processes
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            seen = set()
            for line in result.stdout.strip().split("\n")[:100]:
                parts = line.strip().strip('"').split('","')
                if parts:
                    name = parts[0].strip('"').lower()
                    if name not in seen and name not in (
                        "system idle process", "system", "svchost.exe", "conhost.exe",
                        "csrss.exe", "lsass.exe", "smss.exe", "wininit.exe", "services.exe",
                        "dwm.exe", "fontdrvhost.exe", "tasklist.exe",
                    ):
                        seen.add(name)
            state["key_processes"] = sorted(list(seen))[:20]
    except Exception:
        pass
    
    _env_state_cache["state"] = {"data": state, "ts": now}
    return state


def format_environment_state_for_prompt(state: dict) -> str:
    """Format environment state as a prompt block."""
    if not state:
        return ""
    parts = ["\n\nENVIRONMENT STATE:"]
    windows = state.get("open_windows", [])
    if windows:
        parts.append(f"Open windows: {', '.join(windows[:10])}")
    procs = state.get("key_processes", [])
    if procs:
        parts.append(f"Key processes: {', '.join(procs[:15])}")
    res = state.get("screen_resolution")
    if res:
        parts.append(f"Screen: {res}")
    return "\n".join(parts) if len(parts) > 1 else ""


def _should_capture_env_state(user_message: str) -> bool:
    """Check if user message warrants environment state capture."""
    text = (user_message or "").lower()
    keywords = (
        "desktop", "screen", "window", "app", "running", "open",
        "process", "laptop", "computer", "screenshot", "browser",
        "what's running", "what is running", "what's open",
    )
    return any(k in text for k in keywords)


def _generate_tool_chaining_hints(user_message: str) -> list[str]:
    """Generate tool chaining hints based on user message keywords."""
    if not TOOL_CHAINING_HINTS_ENABLED:
        return []
    
    text = (user_message or "").lower()
    hints = []
    
    if any(w in text for w in ("scrape", "scraping", "web page", "website content")):
        hints.append("For web scraping: read_webpage or browser_open -> browser_get_text")
    if any(w in text for w in ("login", "sign in", "authenticate")):
        hints.append("For login flows: browser_open -> browser_type (username) -> browser_type (password) -> browser_click (submit)")
    if any(w in text for w in ("screenshot", "capture", "visual")):
        hints.append("For visual capture: browser_open -> browser_screenshot or desktop_screenshot")
    if any(w in text for w in ("fill form", "submit form", "form")):
        hints.append("For forms: browser_open -> browser_type (fields) -> browser_click (submit) -> browser_get_text (confirmation)")
    if any(w in text for w in ("download", "save file")):
        hints.append("For downloads: search_web -> read_webpage or browser_open -> browser_execute_js")
    if any(w in text for w in ("research", "compare", "analysis")):
        hints.append("For research: deep_research or search_web -> read_webpage (multiple) -> save_research_note")
    
    return hints[:3]

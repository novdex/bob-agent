"""
Browser Automation Tools (Pillar 5) — Playwright backend.

Session-based browser control: open a page, interact across multiple tool
calls (type, click, read, screenshot, JS), then close.  Each owner_id gets
one persistent browser context that auto-closes after idle timeout.

Requires: pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import base64
import logging
import pathlib
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("mind_clone.browser")

# ── Configuration ───────────────────────────────────────────────────────
BROWSER_TOOL_ENABLED = True
BROWSER_SESSION_TIMEOUT_SECONDS = 300  # auto-close after 5 min idle
TOOL_CHAINING_HINTS_ENABLED = True
ENVIRONMENT_STATE_ENABLED = True
ENVIRONMENT_STATE_TTL_SECONDS = 60

# ── Global state ────────────────────────────────────────────────────────
# owner_id -> {"pw", "browser", "page", "last_used"}
_sessions: Dict[int, Dict[str, Any]] = {}
_lock = threading.Lock()


# ── Semantic snapshot JS (extracts structured page metadata) ────────────
_SEMANTIC_SNAPSHOT_JS = """
() => {
    const snap = {headings: [], links: [], forms: [], buttons: [],
                  meta_description: "", lang: "", url: location.href,
                  title: document.title};
    document.querySelectorAll("h1,h2,h3").forEach((h, i) => {
        if (i < 20 && h.textContent.trim())
            snap.headings.push({level: h.tagName.toLowerCase(),
                                text: h.textContent.trim().slice(0, 120)});
    });
    document.querySelectorAll("a[href]").forEach((a, i) => {
        if (i < 30 && a.textContent.trim())
            snap.links.push({text: a.textContent.trim().slice(0, 80),
                             href: a.href.slice(0, 200)});
    });
    document.querySelectorAll("form").forEach((f, i) => {
        if (i < 5) {
            const inputs = [];
            f.querySelectorAll("input,textarea,select").forEach((inp, j) => {
                if (j < 10)
                    inputs.push({tag: inp.tagName.toLowerCase(),
                                 type: inp.type || "text",
                                 name: inp.name || "",
                                 placeholder: inp.placeholder || ""});
            });
            snap.forms.push({action: (f.action || "").slice(0, 200),
                             method: (f.method || "GET").toUpperCase(),
                             inputs: inputs});
        }
    });
    document.querySelectorAll("button, input[type=submit], input[type=button]")
        .forEach((b, i) => {
            if (i < 15) {
                const txt = (b.textContent || b.value || "").trim().slice(0, 60);
                if (txt) snap.buttons.push(txt);
            }
        });
    const meta = document.querySelector("meta[name=description]");
    if (meta) snap.meta_description = (meta.content || "").slice(0, 300);
    snap.lang = (document.documentElement.lang || "").slice(0, 10);
    return snap;
}
"""


# ═══════════════════════════════════════════════════════════════════════
# Session management
# ═══════════════════════════════════════════════════════════════════════

def _get_session(owner_id: int) -> Optional[Dict[str, Any]]:
    """Return existing session if alive, else None."""
    with _lock:
        s = _sessions.get(owner_id)
        if not s:
            return None
        try:
            # Health check — if browser crashed this throws
            s["page"].url  # noqa: B018
            s["last_used"] = time.monotonic()
            return s
        except Exception:
            _destroy_session_unlocked(owner_id)
            return None


def _create_session(owner_id: int) -> Dict[str, Any]:
    """Launch Playwright + Chromium and store session."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(15_000)

    session = {
        "pw": pw,
        "browser": browser,
        "context": context,
        "page": page,
        "last_used": time.monotonic(),
    }
    with _lock:
        # Close any existing session for this owner
        _destroy_session_unlocked(owner_id)
        _sessions[owner_id] = session
    logger.info("Browser session created for owner=%s", owner_id)
    return session


def _get_or_create_session(owner_id: int) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (session, error). error is None on success."""
    if not BROWSER_TOOL_ENABLED:
        return {}, "Browser tools are disabled"

    s = _get_session(owner_id)
    if s:
        return s, None

    try:
        return _create_session(owner_id), None
    except ImportError:
        return {}, "Playwright not installed (pip install playwright && python -m playwright install chromium)"
    except Exception as e:
        return {}, f"Browser launch failed: {str(e)[:200]}"


def _require_session(owner_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[dict]]:
    """Get existing session or return error dict. Does NOT auto-create."""
    s = _get_session(owner_id)
    if s:
        return s, None
    return None, {"ok": False, "error": "No browser session. Call browser_open first."}


def _destroy_session_unlocked(owner_id: int):
    """Close and remove session. Must hold _lock."""
    s = _sessions.pop(owner_id, None)
    if not s:
        return
    for key in ("page", "context", "browser"):
        try:
            s[key].close()
        except Exception:
            pass
    try:
        s["pw"].stop()
    except Exception:
        pass


def cleanup_idle_sessions():
    """Close sessions idle beyond timeout. Called by heartbeat."""
    now = time.monotonic()
    with _lock:
        for oid in list(_sessions.keys()):
            if (now - _sessions[oid]["last_used"]) > BROWSER_SESSION_TIMEOUT_SECONDS:
                logger.info("Closing idle browser session for owner=%s", oid)
                _destroy_session_unlocked(oid)


def _snapshot(page) -> dict:
    """Capture semantic snapshot from current page."""
    try:
        return page.evaluate(_SEMANTIC_SNAPSHOT_JS) or {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════

def tool_browser_open(args: dict) -> dict:
    """Open a URL in the browser. Creates session if needed."""
    owner_id = int(args.get("_owner_id", 1))
    url = str(args.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}

    # URL safety check
    try:
        from ..core.security import apply_url_safety_guard
        safe_ok, safe_reason = apply_url_safety_guard(url, source="browser_open")
        if not safe_ok:
            return {"ok": False, "error": safe_reason}
    except Exception:
        pass  # Security module optional

    session, err = _get_or_create_session(owner_id)
    if err:
        return {"ok": False, "error": err}

    page = session["page"]
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        result = {
            "ok": True,
            "title": page.title(),
            "url": page.url,
        }
        snap = _snapshot(page)
        if snap:
            result["snapshot"] = snap
        # Include visible text summary
        try:
            body_text = page.inner_text("body")
            result["text"] = body_text[:4000]
        except Exception:
            pass
        return result
    except Exception as e:
        return {"ok": False, "error": f"Failed to open {url}: {str(e)[:200]}"}


def tool_browser_get_text(args: dict) -> dict:
    """Get text content from the current page or a specific element."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "body")).strip()

    session, err = _require_session(owner_id)
    if err:
        return err

    page = session["page"]
    try:
        if selector == "body":
            text = page.inner_text("body")
        else:
            el = page.query_selector(selector)
            if not el:
                return {"ok": False, "error": f"Element not found: {selector}"}
            text = el.inner_text()
        return {"ok": True, "text": text[:5000], "selector": selector, "url": page.url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_click(args: dict) -> dict:
    """Click an element on the current page."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "")).strip()
    if not selector:
        return {"ok": False, "error": "selector is required"}

    session, err = _require_session(owner_id)
    if err:
        return err

    page = session["page"]
    try:
        page.click(selector, timeout=10_000)
        page.wait_for_timeout(1000)
        result = {
            "ok": True,
            "clicked": selector,
            "url": page.url,
            "title": page.title(),
        }
        snap = _snapshot(page)
        if snap:
            result["snapshot"] = snap
        return result
    except Exception as e:
        return {"ok": False, "error": f"Click failed on '{selector}': {str(e)[:200]}"}


def tool_browser_type(args: dict) -> dict:
    """Type text into an input field on the current page."""
    owner_id = int(args.get("_owner_id", 1))
    selector = str(args.get("selector", "")).strip()
    text = str(args.get("text", ""))
    if not selector:
        return {"ok": False, "error": "selector is required"}

    session, err = _require_session(owner_id)
    if err:
        return err

    page = session["page"]
    try:
        page.fill(selector, text, timeout=10_000)
        if args.get("submit"):
            page.press(selector, "Enter")
            page.wait_for_timeout(1500)
        return {
            "ok": True,
            "typed": text,
            "selector": selector,
            "url": page.url,
        }
    except Exception as e:
        return {"ok": False, "error": f"Type failed on '{selector}': {str(e)[:200]}"}


def tool_browser_screenshot(args: dict) -> dict:
    """Take a screenshot of the current page."""
    owner_id = int(args.get("_owner_id", 1))

    session, err = _require_session(owner_id)
    if err:
        return err

    page = session["page"]
    try:
        full_page = bool(args.get("full_page", False))
        png_bytes = page.screenshot(full_page=full_page)

        out_dir = pathlib.Path("persist/screenshots")
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"shot_{int(time.time() * 1000)}.png"
        path = out_dir / filename
        path.write_bytes(png_bytes)

        b64 = base64.b64encode(png_bytes).decode("ascii")
        return {
            "ok": True,
            "path": str(path),
            "url": page.url,
            "title": page.title(),
            "screenshot_base64": b64[:50000],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_execute_js(args: dict) -> dict:
    """Execute JavaScript in the browser context."""
    owner_id = int(args.get("_owner_id", 1))
    code = str(args.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "code is required"}

    session, err = _require_session(owner_id)
    if err:
        return err

    page = session["page"]
    try:
        # Wrap in arrow function if it doesn't look like one
        if not code.startswith("(") and not code.startswith("async"):
            code = f"() => {{ return {code} }}"
        result = page.evaluate(code)
        import json
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, default=str, ensure_ascii=False)[:5000]
        elif result is None:
            result_str = "null"
        else:
            result_str = str(result)[:5000]
        return {"ok": True, "result": result_str}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def tool_browser_close(args: dict) -> dict:
    """Close the browser session and free resources."""
    owner_id = int(args.get("_owner_id", 1))
    with _lock:
        s = _sessions.get(owner_id)
        if s:
            _destroy_session_unlocked(owner_id)
            return {"ok": True, "message": "Browser session closed."}
    return {"ok": True, "message": "No browser session was open."}


# ═══════════════════════════════════════════════════════════════════════
# Environment State Capture (Pillar 7) — kept from original
# ═══════════════════════════════════════════════════════════════════════

_env_state_cache: Dict[str, dict] = {}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def capture_environment_state(owner_id: int | None = None) -> dict:
    """Capture current environment state: open windows, key processes."""
    if not ENVIRONMENT_STATE_ENABLED:
        return {}

    now = time.monotonic()
    cached = _env_state_cache.get("state")
    if cached and (now - cached["ts"]) < ENVIRONMENT_STATE_TTL_SECONDS:
        return cached["data"]

    state = {"open_windows": [], "key_processes": [], "timestamp": _utc_now_iso()}

    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            seen = set()
            skip = frozenset({
                "system idle process", "system", "svchost.exe", "conhost.exe",
                "csrss.exe", "lsass.exe", "smss.exe", "wininit.exe",
                "services.exe", "dwm.exe", "fontdrvhost.exe", "tasklist.exe",
            })
            for line in result.stdout.strip().split("\n")[:100]:
                parts = line.strip().strip('"').split('","')
                if parts:
                    name = parts[0].strip('"').lower()
                    if name not in seen and name not in skip:
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
    text = (user_message or "").lower()
    keywords = (
        "desktop", "screen", "window", "app", "running", "open",
        "process", "laptop", "computer", "screenshot", "browser",
        "what's running", "what is running", "what's open",
    )
    return any(k in text for k in keywords)


def _generate_tool_chaining_hints(user_message: str) -> list[str]:
    if not TOOL_CHAINING_HINTS_ENABLED:
        return []

    text = (user_message or "").lower()
    hints = []

    if any(w in text for w in ("scrape", "scraping", "web page", "website content")):
        hints.append("For web scraping: browser_open -> browser_get_text")
    if any(w in text for w in ("login", "sign in", "authenticate")):
        hints.append("For login: browser_open -> browser_type (user) -> browser_type (pass) -> browser_click (submit)")
    if any(w in text for w in ("screenshot", "capture", "visual")):
        hints.append("For screenshots: browser_open -> browser_screenshot")
    if any(w in text for w in ("fill form", "submit form", "form")):
        hints.append("For forms: browser_open -> browser_type (fields) -> browser_click (submit)")
    if any(w in text for w in ("download", "save file")):
        hints.append("For downloads: browser_open -> browser_execute_js")
    if any(w in text for w in ("research", "compare", "analysis")):
        hints.append("For research: search_web -> browser_open -> browser_get_text")

    return hints[:3]

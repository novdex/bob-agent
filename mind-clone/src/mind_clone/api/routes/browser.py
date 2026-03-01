"""
Browser automation API routes for web interaction.

Endpoints:
    POST /api/browser/open       — Open a URL and return page content
    POST /api/browser/screenshot — Capture a screenshot of a URL
    POST /api/browser/click      — Click an element on a page
    POST /api/browser/type       — Type text into an element
    POST /api/browser/extract    — Extract content from an element
    POST /api/browser/script     — Execute JavaScript on a page
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

import logging

log = logging.getLogger("mind_clone.api.browser")

router = APIRouter(prefix="/api/browser", tags=["browser"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BrowseOpenRequest(BaseModel):
    """Open a URL."""
    url: str = Field(..., description="URL to open")


class BrowseScreenshotRequest(BaseModel):
    """Capture a screenshot."""
    url: str = Field(..., description="URL to screenshot")
    full_page: bool = Field(default=False, description="Capture the full scrollable page")


class BrowseClickRequest(BaseModel):
    """Click an element."""
    url: str = Field(..., description="URL of the page")
    selector: str = Field(..., description="CSS selector of the element to click")
    wait_after: int = Field(default=1000, description="Milliseconds to wait after click")


class BrowseTypeRequest(BaseModel):
    """Type text into an element."""
    url: str = Field(..., description="URL of the page")
    selector: str = Field(..., description="CSS selector of the input element")
    text: str = Field(..., description="Text to type")
    submit: bool = Field(default=False, description="Submit the form after typing")


class BrowseExtractRequest(BaseModel):
    """Extract content from an element."""
    url: str = Field(..., description="URL of the page")
    selector: str = Field(..., description="CSS selector of the element")
    attribute: Optional[str] = Field(default=None, description="Attribute to extract (None = text content)")


class BrowseScriptRequest(BaseModel):
    """Execute JavaScript on a page."""
    url: str = Field(..., description="URL of the page")
    script: str = Field(..., description="JavaScript code to execute")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/open")
async def browser_open(req: BrowseOpenRequest):
    """Open a URL and return page content."""
    log.info("Browser open: %s", req.url)
    try:
        from mind_clone.tools.web_automation import tool_browser_open
        return tool_browser_open({"url": req.url})
    except Exception as e:
        log.exception("Browser open failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/screenshot")
async def browser_screenshot(req: BrowseScreenshotRequest):
    """Capture a screenshot of a page."""
    log.info("Browser screenshot: %s (full_page=%s)", req.url, req.full_page)
    try:
        from mind_clone.tools.web_automation import tool_browser_screenshot
        return tool_browser_screenshot({"url": req.url, "full_page": req.full_page})
    except Exception as e:
        log.exception("Browser screenshot failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/click")
async def browser_click(req: BrowseClickRequest):
    """Click an element on a page."""
    log.info("Browser click: %s -> %s", req.url, req.selector)
    try:
        from mind_clone.tools.web_automation import tool_browser_click
        return tool_browser_click({
            "url": req.url,
            "selector": req.selector,
            "wait_after": req.wait_after,
        })
    except Exception as e:
        log.exception("Browser click failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/type")
async def browser_type(req: BrowseTypeRequest):
    """Type text into an element on a page."""
    log.info("Browser type: %s -> %s", req.url, req.selector)
    try:
        from mind_clone.tools.web_automation import tool_browser_type
        return tool_browser_type({
            "url": req.url,
            "selector": req.selector,
            "text": req.text,
            "submit": req.submit,
        })
    except Exception as e:
        log.exception("Browser type failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/extract")
async def browser_extract(req: BrowseExtractRequest):
    """Extract content from an element on a page."""
    log.info("Browser extract: %s -> %s", req.url, req.selector)
    try:
        from mind_clone.tools.web_automation import tool_browser_extract
        return tool_browser_extract({
            "url": req.url,
            "selector": req.selector,
            "attribute": req.attribute,
        })
    except Exception as e:
        log.exception("Browser extract failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/script")
async def browser_script(req: BrowseScriptRequest):
    """Execute JavaScript on a page."""
    log.info("Browser script: %s", req.url)
    try:
        from mind_clone.tools.web_automation import tool_browser_script
        return tool_browser_script({"url": req.url, "script": req.script})
    except Exception as e:
        log.exception("Browser script failed: %s", e)
        return {"ok": False, "error": str(e)}

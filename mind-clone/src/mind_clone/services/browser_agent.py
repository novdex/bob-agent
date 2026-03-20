"""
Browser Agent — Bob can USE websites, not just read them.

Wraps existing browser tools into intelligent sequences:
- Navigate to URL, extract structured data
- Fill forms and submit
- Scrape JS-heavy pages
- Multi-step web workflows

Uses existing browser_open/click/type/get_text tools.
"""
from __future__ import annotations
import logging
from ..utils import truncate_text
logger = logging.getLogger("mind_clone.services.browser_agent")


def browse_and_extract(url: str, goal: str, owner_id: int = 1) -> dict:
    """Navigate to URL and extract information matching a goal."""
    from ..tools.browser import tool_browser_open, tool_browser_get_text, tool_browser_close
    from ..agent.llm import call_llm

    open_r = tool_browser_open({"url": url})
    if not open_r.get("ok"):
        return {"ok": False, "error": f"Could not open {url}: {open_r.get('error', '?')}"}

    session_id = open_r.get("session_id", "")
    text_r = tool_browser_get_text({"session_id": session_id})
    raw_text = text_r.get("text", "") if text_r.get("ok") else ""
    tool_browser_close({"session_id": session_id})

    if not raw_text:
        return {"ok": False, "error": "No text extracted from page"}

    # Use LLM to extract what we need
    prompt = [{"role": "user", "content":
        f"Extract the following from this webpage content:\nGoal: {goal}\n\n"
        f"Page content:\n{truncate_text(raw_text, 3000)}\n\n"
        f"Return a concise, structured answer. Include key facts and data."}]
    try:
        result = call_llm(prompt, temperature=0.2)
        answer = ""
        if isinstance(result, dict) and result.get("ok"):
            answer = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                answer = choices[0].get("message", {}).get("content", answer)
        return {"ok": True, "url": url, "extracted": truncate_text(answer, 1500), "raw_chars": len(raw_text)}
    except Exception as e:
        return {"ok": True, "url": url, "extracted": truncate_text(raw_text, 1000), "raw_chars": len(raw_text)}


def fill_form_and_submit(url: str, form_data: dict, submit_selector: str = "") -> dict:
    """Navigate to a form page, fill fields, and submit."""
    from ..tools.browser import tool_browser_open, tool_browser_type, tool_browser_click, tool_browser_close
    open_r = tool_browser_open({"url": url})
    if not open_r.get("ok"):
        return {"ok": False, "error": f"Could not open {url}"}
    session_id = open_r.get("session_id", "")
    try:
        for selector, value in form_data.items():
            tool_browser_click({"session_id": session_id, "selector": selector})
            tool_browser_type({"session_id": session_id, "text": str(value)})
        if submit_selector:
            tool_browser_click({"session_id": session_id, "selector": submit_selector})
        return {"ok": True, "url": url, "fields_filled": len(form_data)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    finally:
        tool_browser_close({"session_id": session_id})


def tool_browse_and_extract(args: dict) -> dict:
    """Tool: Navigate to URL and extract information matching a goal."""
    url = str(args.get("url", "")).strip()
    goal = str(args.get("goal", "extract all important information")).strip()
    owner_id = int(args.get("_owner_id", 1))
    if not url:
        return {"ok": False, "error": "url required"}
    return browse_and_extract(url, goal, owner_id)

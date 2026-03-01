"""
Basic tool implementations (file, code, web, email).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from ..config import settings
from ..utils import truncate_text, utc_now_iso
from ..database.session import SessionLocal
from ..database.models import ResearchNote

logger = logging.getLogger("mind_clone.tools")

# Web session
REQUESTS_SESSION = requests.Session()
REQUESTS_SESSION.trust_env = False


def tool_read_file(args: dict) -> dict:
    """Read content from a file.

    Input validation:
    - file_path must be a non-empty string
    - file_path length must be <= 4096 chars
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    file_path = str(args.get("file_path", "")).strip()
    if not file_path:
        return {"ok": False, "error": "file_path is required"}
    if len(file_path) > 4096:
        return {"ok": False, "error": "file_path is too long (max 4096 chars)"}

    try:
        path = Path(file_path).expanduser()
        if not path.exists():
            return {"ok": False, "error": f"File not found: {file_path}"}
        if not path.is_file():
            return {"ok": False, "error": f"Path is not a file: {file_path}"}

        content = path.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "content": content, "path": str(path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_write_file(args: dict) -> dict:
    """Write content to a file.

    Input validation:
    - file_path must be non-empty string (max 4096 chars)
    - content length must be <= 10MB (10485760 bytes)
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    file_path = str(args.get("file_path", "")).strip()
    content = str(args.get("content", ""))
    append = bool(args.get("append", False))

    if not file_path:
        return {"ok": False, "error": "file_path is required"}
    if len(file_path) > 4096:
        return {"ok": False, "error": "file_path is too long (max 4096 chars)"}

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > 10485760:  # 10MB
        return {"ok": False, "error": "content is too large (max 10MB)"}

    try:
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)

        return {"ok": True, "path": str(path), "bytes_written": len(content_bytes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_list_directory(args: dict) -> dict:
    """List contents of a directory.

    Input validation:
    - dir_path must be non-empty string (max 4096 chars)
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    dir_path = str(args.get("dir_path", ".")).strip()

    if len(dir_path) > 4096:
        return {"ok": False, "error": "dir_path is too long (max 4096 chars)"}

    try:
        path = Path(dir_path).expanduser()
        if not path.exists():
            return {"ok": False, "error": f"Directory not found: {dir_path}"}
        if not path.is_dir():
            return {"ok": False, "error": f"Path is not a directory: {dir_path}"}

        items = []
        for item in path.iterdir():
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })

        return {"ok": True, "path": str(path), "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_run_command(args: dict) -> dict:
    """Run a shell command.

    Input validation:
    - command must be non-empty string (max 4096 chars)
    - timeout must be positive integer between 1 and 3600 seconds
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    command = str(args.get("command", "")).strip()
    timeout_raw = args.get("timeout", 30)

    if not command:
        return {"ok": False, "error": "command is required"}
    if len(command) > 4096:
        return {"ok": False, "error": "command is too long (max 4096 chars)"}

    try:
        timeout = int(timeout_raw)
        if timeout < 1 or timeout > 3600:
            return {"ok": False, "error": "timeout must be between 1 and 3600 seconds"}
    except (ValueError, TypeError):
        return {"ok": False, "error": "timeout must be a positive integer"}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:10000],  # Limit output
            "stderr": result.stderr[:5000],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_execute_python(args: dict) -> dict:
    """Execute Python code.

    Input validation:
    - code must be non-empty string (max 100KB)
    - timeout must be positive integer between 1 and 300 seconds
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    code = str(args.get("code", "")).strip()
    timeout_raw = args.get("timeout", 15)

    if not code:
        return {"ok": False, "error": "code is required"}
    if len(code.encode("utf-8")) > 102400:  # 100KB
        return {"ok": False, "error": "code is too large (max 100KB)"}

    try:
        timeout = int(timeout_raw)
        if timeout < 1 or timeout > 300:
            return {"ok": False, "error": "timeout must be between 1 and 300 seconds"}
    except (ValueError, TypeError):
        return {"ok": False, "error": "timeout must be a positive integer"}

    try:
        # Create temp file for code
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
            }
        finally:
            os.unlink(temp_path)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Code execution timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_search_web(args: dict) -> dict:
    """Search the web using DuckDuckGo.

    Input validation:
    - query must be non-empty string (max 500 chars)
    - num_results must be positive integer between 1 and 100
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    query = str(args.get("query", "")).strip()
    num_results_raw = args.get("num_results", 5)

    if not query:
        return {"ok": False, "error": "query is required"}
    if len(query) > 500:
        return {"ok": False, "error": "query is too long (max 500 chars)"}

    try:
        num_results = int(num_results_raw)
        if num_results < 1 or num_results > 100:
            return {"ok": False, "error": "num_results must be between 1 and 100"}
    except (ValueError, TypeError):
        return {"ok": False, "error": "num_results must be a positive integer"}

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))

        return {
            "ok": True,
            "query": query,
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _extract_semantic_snapshot_bs(soup) -> dict:
    """Extract structured page metadata from a BeautifulSoup tree."""
    snapshot: dict = {
        "headings": [],
        "links": [],
        "forms": [],
        "buttons": [],
        "meta_description": "",
        "lang": "",
    }
    for tag in soup.find_all(["h1", "h2", "h3"], limit=20):
        text = tag.get_text(strip=True)[:120]
        if text:
            snapshot["headings"].append({"level": tag.name, "text": text})
    for a in soup.find_all("a", href=True, limit=30):
        text = a.get_text(strip=True)[:80]
        href = str(a["href"])[:200]
        if text and href:
            snapshot["links"].append({"text": text, "href": href})
    for form in soup.find_all("form", limit=5):
        inputs = []
        for inp in form.find_all(["input", "textarea", "select"], limit=10):
            inputs.append({
                "tag": inp.name,
                "type": inp.get("type", "text"),
                "name": inp.get("name", ""),
            })
        snapshot["forms"].append({
            "action": str(form.get("action", ""))[:200],
            "method": str(form.get("method", "GET")).upper(),
            "inputs": inputs,
        })
    for btn in soup.find_all(["button"], limit=15):
        text = btn.get_text(strip=True)[:60]
        if text:
            snapshot["buttons"].append(text)
    for inp in soup.find_all("input", {"type": ["submit", "button"]}, limit=10):
        val = str(inp.get("value", ""))[:60]
        if val:
            snapshot["buttons"].append(val)
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        snapshot["meta_description"] = str(meta["content"])[:300]
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        snapshot["lang"] = str(html_tag["lang"])[:10]
    return snapshot


def tool_read_webpage(args: dict) -> dict:
    """Read and extract text from a webpage."""
    url = str(args.get("url", "")).strip()

    if not url:
        return {"ok": False, "error": "url is required"}

    from ..core.security import apply_url_safety_guard, circuit_allow_call, circuit_record_success, circuit_record_failure
    allowed, cb_reason = circuit_allow_call("web_fetch")
    if not allowed:
        return {"ok": False, "error": cb_reason, "url": url}
    safe_ok, safe_reason = apply_url_safety_guard(url, source="read_webpage")
    if not safe_ok:
        return {"ok": False, "error": safe_reason, "url": url}

    try:
        response = REQUESTS_SESSION.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator="\n", strip=True)
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines[:500])  # Limit lines

        snapshot = _extract_semantic_snapshot_bs(soup)
        circuit_record_success("web_fetch")
        return {
            "ok": True,
            "url": url,
            "title": soup.title.string if soup.title else None,
            "text": text[:15000],  # Limit content
            "snapshot": snapshot,
        }
    except Exception as e:
        circuit_record_failure("web_fetch", str(e))
        return {"ok": False, "error": str(e)}


def tool_deep_research(args: dict) -> dict:
    """Perform deep research on a topic."""
    topic = str(args.get("topic", "")).strip()
    num_results = int(args.get("num_results", 8))
    
    if not topic:
        return {"ok": False, "error": "topic is required"}
    
    try:
        # Multi-query approach
        queries = [
            topic,
            f"{topic} guide",
            f"{topic} tutorial",
            f"{topic} documentation",
        ]
        
        all_results = []
        seen_urls = set()
        
        with DDGS() as ddgs:
            for query in queries[:3]:
                try:
                    results = list(ddgs.text(query, max_results=num_results // 3))
                    for r in results:
                        url = r.get("href", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append({
                                "title": r.get("title", ""),
                                "url": url,
                                "snippet": r.get("body", ""),
                            })
                except Exception:
                    continue
        
        return {
            "ok": True,
            "topic": topic,
            "sources": all_results[:num_results],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_send_email(args: dict) -> dict:
    """Send an email via SMTP."""
    to = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", ""))
    
    if not to or not subject:
        return {"ok": False, "error": "to and subject are required"}
    
    if not settings.smtp_username or not settings.smtp_password:
        return {"ok": False, "error": "SMTP not configured"}
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_username}>"
        msg["To"] = to
        msg["Subject"] = subject
        
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        
        return {"ok": True, "to": to, "subject": subject}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_save_research_note(args: dict) -> dict:
    """Save a research note to persistent storage."""
    topic = str(args.get("topic", "")).strip()
    summary = str(args.get("summary", "")).strip()
    owner_id = int(args.get("owner_id") or args.get("_owner_id") or 1)
    sources = args.get("sources") or []
    tags = args.get("tags") or []
    
    if not topic or not summary:
        return {"ok": False, "error": "topic and summary are required"}
    
    db = SessionLocal()
    try:
        source_list = [str(item).strip() for item in list(sources) if str(item).strip()]
        tag_list = [str(item).strip() for item in list(tags) if str(item).strip()]
        note = ResearchNote(
            owner_id=owner_id,
            topic=truncate_text(topic, 200),
            summary=truncate_text(summary, 8000),
            sources_json=json.dumps(source_list),
            tags_json=json.dumps(tag_list),
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return {
            "ok": True,
            "saved": True,
            "note_id": int(note.id),
            "owner_id": int(note.owner_id),
            "topic": str(note.topic),
        }
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


# Backward-compatible convenience aliases used by legacy modules/tests.
def read_file(file_path: str) -> str:
    """Compatibility wrapper around `tool_read_file` returning plain text/error string."""
    result = tool_read_file({"file_path": file_path})
    if result.get("ok"):
        return str(result.get("content", ""))
    return str(result.get("error", "read_file failed"))


def search_web(query: str, num_results: int = 5) -> str:
    """
    Compatibility wrapper around `tool_search_web`.

    If this symbol is monkeypatched at module level, delegate to the patched
    function so callsites that imported `search_web` before patching still
    observe the override.
    """
    override = globals().get("search_web")
    if override is not _SEARCH_WEB_COMPAT_REF and callable(override):
        return str(override(query))

    result = tool_search_web({"query": query, "num_results": num_results})
    if not result.get("ok"):
        return f"error: {result.get('error', 'search failed')}"

    lines = []
    for item in list(result.get("results") or []):
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if title and url:
            lines.append(f"{title} - {url}")
        elif title:
            lines.append(title)
        elif url:
            lines.append(url)
    return "\n".join(lines) if lines else "no results"


_SEARCH_WEB_COMPAT_REF = search_web

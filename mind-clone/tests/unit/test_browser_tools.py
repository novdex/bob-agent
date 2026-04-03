"""
Unit tests for mind_clone.tools.browser — Playwright session-based browser tools.

Tests tool logic with mocked Playwright to avoid needing a real browser in CI.
"""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import threading


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Reset global session state between tests."""
    from mind_clone.tools import browser
    with browser._lock:
        browser._sessions.clear()
    yield
    with browser._lock:
        browser._sessions.clear()


def _make_mock_page(url="https://example.com", title="Example", body_text="Hello World"):
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    page.inner_text.return_value = body_text
    page.evaluate.return_value = {
        "headings": [{"level": "h1", "text": "Example"}],
        "links": [], "forms": [], "buttons": [],
        "meta_description": "", "lang": "en",
        "url": url, "title": title,
    }
    page.screenshot.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    page.query_selector.return_value = MagicMock(inner_text=MagicMock(return_value="element text"))
    page.set_default_timeout = MagicMock()
    return page


def _inject_mock_session(browser_mod, owner_id=1, url="https://example.com"):
    import time
    page = _make_mock_page(url=url)
    session = {
        "pw": MagicMock(), "browser": MagicMock(),
        "context": MagicMock(), "page": page,
        "last_used": time.monotonic(),
    }
    with browser_mod._lock:
        browser_mod._sessions[owner_id] = session
    return session, page


class TestBrowserOpen:
    def test_missing_url_returns_error(self):
        from mind_clone.tools.browser import tool_browser_open
        result = tool_browser_open({})
        assert result["ok"] is False
        assert "url is required" in result["error"]

    def test_empty_url_returns_error(self):
        from mind_clone.tools.browser import tool_browser_open
        result = tool_browser_open({"url": "  "})
        assert result["ok"] is False

    @patch("mind_clone.core.security.apply_url_safety_guard", return_value=(True, ""))
    @patch("mind_clone.tools.browser._create_session")
    def test_successful_open(self, mock_create, _mock_ssrf):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_open
        session, page = _inject_mock_session(browser)
        mock_create.return_value = session
        result = tool_browser_open({"url": "https://example.com"})
        assert result["ok"] is True
        assert result["title"] == "Example"
        assert "snapshot" in result

    @patch("mind_clone.tools.browser._create_session")
    def test_open_with_navigation_error(self, mock_create):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_open
        session, page = _inject_mock_session(browser)
        page.goto.side_effect = Exception("Timeout")
        mock_create.return_value = session
        result = tool_browser_open({"url": "https://bad.example.com"})
        assert result["ok"] is False
        assert result["error"]


class TestBrowserGetText:
    def test_no_session_returns_error(self):
        from mind_clone.tools.browser import tool_browser_get_text
        result = tool_browser_get_text({})
        assert result["ok"] is False
        assert "browser_open" in result["error"].lower()

    def test_get_body_text(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_get_text
        _inject_mock_session(browser)
        result = tool_browser_get_text({"_owner_id": 1})
        assert result["ok"] is True
        assert "Hello World" in result["text"]

    def test_get_element_text(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_get_text
        _inject_mock_session(browser)
        result = tool_browser_get_text({"_owner_id": 1, "selector": "h1"})
        assert result["ok"] is True

    def test_element_not_found(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_get_text
        session, page = _inject_mock_session(browser)
        page.query_selector.return_value = None
        result = tool_browser_get_text({"_owner_id": 1, "selector": "#nonexistent"})
        assert result["ok"] is False


class TestBrowserClick:
    def test_no_session_returns_error(self):
        from mind_clone.tools.browser import tool_browser_click
        result = tool_browser_click({"selector": "button"})
        assert result["ok"] is False

    def test_missing_selector_returns_error(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_click
        _inject_mock_session(browser)
        result = tool_browser_click({"_owner_id": 1})
        assert result["ok"] is False

    def test_successful_click(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_click
        _inject_mock_session(browser)
        result = tool_browser_click({"_owner_id": 1, "selector": "button.submit"})
        assert result["ok"] is True
        assert result["clicked"] == "button.submit"

    def test_click_failure(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_click
        session, page = _inject_mock_session(browser)
        page.click.side_effect = Exception("Element detached")
        result = tool_browser_click({"_owner_id": 1, "selector": "button"})
        assert result["ok"] is False


class TestBrowserType:
    def test_no_session_returns_error(self):
        from mind_clone.tools.browser import tool_browser_type
        result = tool_browser_type({"selector": "input", "text": "hi"})
        assert result["ok"] is False

    def test_missing_selector(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_type
        _inject_mock_session(browser)
        result = tool_browser_type({"_owner_id": 1, "text": "hi"})
        assert result["ok"] is False

    def test_successful_type(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_type
        _inject_mock_session(browser)
        result = tool_browser_type({"_owner_id": 1, "selector": "input[name=q]", "text": "hello"})
        assert result["ok"] is True
        assert result["typed"] == "hello"

    def test_type_with_submit(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_type
        session, page = _inject_mock_session(browser)
        result = tool_browser_type({"_owner_id": 1, "selector": "input", "text": "search", "submit": True})
        assert result["ok"] is True
        page.press.assert_called_once_with("input", "Enter")


class TestBrowserScreenshot:
    def test_no_session_returns_error(self):
        from mind_clone.tools.browser import tool_browser_screenshot
        result = tool_browser_screenshot({})
        assert result["ok"] is False

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_bytes")
    def test_successful_screenshot(self, mock_write, mock_mkdir):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_screenshot
        _inject_mock_session(browser)
        result = tool_browser_screenshot({"_owner_id": 1})
        assert result["ok"] is True
        assert "path" in result


class TestBrowserExecuteJs:
    def test_no_session_returns_error(self):
        from mind_clone.tools.browser import tool_browser_execute_js
        result = tool_browser_execute_js({"code": "1+1"})
        assert result["ok"] is False

    def test_missing_code(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_execute_js
        _inject_mock_session(browser)
        result = tool_browser_execute_js({"_owner_id": 1})
        assert result["ok"] is False

    def test_successful_js_execution(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_execute_js
        session, page = _inject_mock_session(browser)
        page.evaluate.return_value = 42
        result = tool_browser_execute_js({"_owner_id": 1, "code": "document.title"})
        assert result["ok"] is True
        assert result["result"] == "42"

    def test_js_returns_dict(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_execute_js
        session, page = _inject_mock_session(browser)
        page.evaluate.return_value = {"key": "value"}
        result = tool_browser_execute_js({"_owner_id": 1, "code": "({key:'value'})"})
        assert result["ok"] is True

    def test_js_returns_null(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_execute_js
        session, page = _inject_mock_session(browser)
        page.evaluate.return_value = None
        result = tool_browser_execute_js({"_owner_id": 1, "code": "void 0"})
        assert result["ok"] is True
        assert result["result"] == "null"


class TestBrowserClose:
    def test_close_no_session(self):
        from mind_clone.tools.browser import tool_browser_close
        result = tool_browser_close({"_owner_id": 1})
        assert result["ok"] is True

    def test_close_existing_session(self):
        from mind_clone.tools import browser
        from mind_clone.tools.browser import tool_browser_close
        _inject_mock_session(browser)
        assert 1 in browser._sessions
        result = tool_browser_close({"_owner_id": 1})
        assert result["ok"] is True
        assert 1 not in browser._sessions


class TestSessionManagement:
    def test_cleanup_idle_sessions(self):
        from mind_clone.tools import browser
        import time
        session, page = _inject_mock_session(browser)
        browser._sessions[1]["last_used"] = time.monotonic() - 600
        browser.cleanup_idle_sessions()
        assert 1 not in browser._sessions

    def test_session_health_check_failure(self):
        from mind_clone.tools import browser
        session, page = _inject_mock_session(browser)
        type(page).url = PropertyMock(side_effect=Exception("Browser crashed"))
        result = browser._get_session(1)
        assert result is None
        assert 1 not in browser._sessions


class TestBrowserSchemas:
    def test_all_browser_schemas_in_registry(self):
        from mind_clone.tools.schemas import get_all_schema_names
        from mind_clone.tools.registry import TOOL_DISPATCH, TOOL_CATEGORIES
        expected = {"browser_open", "browser_get_text", "browser_click",
                    "browser_type", "browser_screenshot", "browser_execute_js", "browser_close"}
        schema_names = set(get_all_schema_names())
        dispatch_names = set(TOOL_DISPATCH.keys())
        category_names = TOOL_CATEGORIES.get("browser", set())
        for name in expected:
            assert name in schema_names, f"{name} missing from schemas"
            assert name in dispatch_names, f"{name} missing from TOOL_DISPATCH"
            assert name in category_names, f"{name} missing from browser category"

    def test_schema_descriptions_are_detailed(self):
        from mind_clone.tools.schemas import get_tool_schema_by_name
        for name in ("browser_open", "browser_click", "browser_type"):
            schema = get_tool_schema_by_name(name)
            assert schema is not None
            desc = schema["function"]["description"]
            assert len(desc) > 40, f"{name} description too short"

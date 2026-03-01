"""
Parallel tool execution engine.

Allows Bob to execute multiple independent tool calls concurrently,
dramatically reducing latency on multi-tool turns.

Pillar: Autonomy, Tool Mastery
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger("mind_clone.core.parallel")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PARALLEL_TOOL_ENABLED = True
PARALLEL_TOOL_MAX_WORKERS = 4

# ---------------------------------------------------------------------------
# Tool independence classification
# ---------------------------------------------------------------------------
_READ_ONLY_TOOLS: frozenset = frozenset({
    # File read
    "read_file", "list_directory",
    # Web read
    "search_web", "read_webpage", "deep_research", "read_pdf_url",
    # Memory read
    "research_memory_search", "semantic_memory_search",
    # Browser read
    "browser_open", "browser_get_text", "browser_screenshot",
    "web_browser_open", "web_browser_extract", "web_browser_screenshot",
    # Desktop read
    "desktop_screen_state", "desktop_screenshot", "desktop_list_windows",
    "desktop_uia_tree", "desktop_locate_on_screen", "desktop_get_clipboard",
    "desktop_session_status",
    # Codebase read
    "codebase_read", "codebase_search", "codebase_structure",
    "codebase_git_status",
    # Git read
    "git_status", "git_diff", "git_log",
    # Query tools
    "list_scheduled_jobs", "list_execution_nodes",
    "sessions_list", "sessions_history",
    "list_plugin_tools", "list_custom_tools",
    # Vision read
    "vision_analyze", "vision_webpage", "vision_compare", "vision_extract_text",
    # Knowledge read
    "query_knowledge", "knowledge_summary",
})

_WRITE_TOOLS: frozenset = frozenset({
    "write_file", "run_command", "execute_python",
    "send_email", "save_research_note",
    "browser_click", "browser_type", "browser_execute_js", "browser_close",
    "web_browser_click", "web_browser_type", "web_browser_script",
    "desktop_click", "desktop_type_text", "desktop_key_press",
    "desktop_hotkey", "desktop_launch_app", "desktop_move_mouse",
    "desktop_drag_mouse", "desktop_scroll", "desktop_set_clipboard",
    "desktop_click_image", "desktop_focus_window",
    "desktop_session_start", "desktop_session_stop",
    "schedule_job", "disable_scheduled_job",
    "run_command_node",
    "sessions_spawn", "sessions_send", "sessions_stop",
    "create_tool", "disable_custom_tool", "llm_structured_task",
    "codebase_edit", "codebase_write", "codebase_run_tests",
    "git_commit", "git_branch", "git_push", "git_pull",
    "index_codebase",
    "spawn_agents", "decompose_task",
})


def classify_tool_independence(
    tool_calls: List[dict],
) -> Tuple[List[dict], List[dict]]:
    """Split tool calls into independent (read-only) and dependent (write) groups.

    Returns:
        (independent, dependent) — each is a list of tool_call dicts
        with an added '_original_index' key for reordering.
    """
    independent: List[dict] = []
    dependent: List[dict] = []

    for idx, tc in enumerate(tool_calls):
        name = tc.get("function", {}).get("name", "")
        tagged = {**tc, "_original_index": idx}
        if name in _READ_ONLY_TOOLS:
            independent.append(tagged)
        else:
            dependent.append(tagged)

    return independent, dependent


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------

def _execute_single(
    tool_call: dict,
    execute_fn: Callable,
) -> Dict[str, Any]:
    """Execute one tool call, returning a result dict with timing."""
    tool_name = tool_call.get("function", {}).get("name", "")
    tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
    tool_call_id = tool_call.get("id", "")

    try:
        args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
    except json.JSONDecodeError:
        args = {}

    start = time.monotonic()
    try:
        result = execute_fn(tool_name, args)
        success = bool(result.get("ok", False)) if isinstance(result, dict) else True
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        success = False

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "result": result,
        "success": success,
        "duration_ms": duration_ms,
        "_original_index": tool_call.get("_original_index", 0),
    }


def execute_tools_parallel(
    tool_calls: List[dict],
    execute_fn: Callable,
    max_workers: int = PARALLEL_TOOL_MAX_WORKERS,
) -> List[Dict[str, Any]]:
    """Execute multiple tool calls concurrently.

    Args:
        tool_calls: List of OpenAI-format tool_call dicts.
        execute_fn: Function(tool_name, args) -> dict to execute each tool.
        max_workers: Maximum concurrent threads.

    Returns:
        List of result dicts in the SAME ORDER as input tool_calls.
    """
    if not tool_calls:
        return []

    _track_metric("parallel_batches_total")

    # Tag with original indices
    tagged = [{**tc, "_original_index": i} for i, tc in enumerate(tool_calls)]

    start = time.monotonic()
    results: List[Dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_execute_single, tc, execute_fn): tc
            for tc in tagged
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=120)
            except Exception as exc:
                tc = futures[future]
                result = {
                    "tool_call_id": tc.get("id", ""),
                    "tool_name": tc.get("function", {}).get("name", ""),
                    "result": {"ok": False, "error": str(exc)},
                    "success": False,
                    "duration_ms": 0,
                    "_original_index": tc.get("_original_index", 0),
                }
            results.append(result)
            _track_metric("parallel_tools_executed")

    # Restore original order
    results.sort(key=lambda r: r.get("_original_index", 0))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    sequential_ms = sum(r.get("duration_ms", 0) for r in results)
    saved_ms = max(0, sequential_ms - elapsed_ms)
    _track_metric("parallel_time_saved_ms", saved_ms)

    logger.info(
        "PARALLEL_BATCH tools=%d elapsed=%dms sequential=%dms saved=%dms",
        len(results), elapsed_ms, sequential_ms, saved_ms,
    )

    return results


def execute_tools_smart(
    tool_calls: List[dict],
    execute_fn: Callable,
) -> List[Dict[str, Any]]:
    """Smart execution: parallel for reads, sequential for writes.

    Runs all independent (read-only) tools in parallel first,
    then executes dependent (write) tools sequentially.
    Results are returned in the original tool_call order.
    """
    if not PARALLEL_TOOL_ENABLED or len(tool_calls) <= 1:
        # Sequential fallback
        return [_execute_single({**tc, "_original_index": i}, execute_fn)
                for i, tc in enumerate(tool_calls)]

    independent, dependent = classify_tool_independence(tool_calls)

    all_results: List[Dict[str, Any]] = []

    # Phase 1: Parallel read-only tools
    if independent:
        logger.info("PARALLEL_SMART independent=%d dependent=%d", len(independent), len(dependent))
        parallel_results = execute_tools_parallel(independent, execute_fn)
        all_results.extend(parallel_results)

    # Phase 2: Sequential write tools
    for tc in dependent:
        result = _execute_single(tc, execute_fn)
        all_results.append(result)

    # Restore original order
    all_results.sort(key=lambda r: r.get("_original_index", 0))

    return all_results


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

def _track_metric(key: str, value: int = 1) -> None:
    """Increment a runtime state metric (best-effort)."""
    try:
        from ..core.state import increment_runtime_state, RUNTIME_STATE
        if key.endswith("_ms"):
            RUNTIME_STATE[key] = RUNTIME_STATE.get(key, 0) + value
        else:
            increment_runtime_state(key)
    except Exception:
        pass

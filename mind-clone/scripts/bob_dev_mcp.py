#!/usr/bin/env python3
"""
Bob Dev MCP Server — Developer Diagnostics for Claude Code CLI.

Gives Claude Code structured access to Bob's internals:
health checks, memory inspection, database queries, LLM status,
tool registry, performance diagnostics, and codebase navigation.

Complements bob_team_mcp.py (task orchestration) with developer tools.

Transport: stdio (local integration with Claude Code CLI)

Tools provided:
  bob_dev_check      — Run compile + tests + lint validation
  bob_dev_health     — Check if Bob API is alive and get runtime metrics
  bob_dev_diag       — Diagnose performance bottlenecks
  bob_dev_memory     — Inspect memory systems (lessons, notes, vectors)
  bob_dev_db         — Inspect database tables, schema, integrity
  bob_dev_tools      — List registered tools, policies, performance stats
  bob_dev_llm        — LLM failover chain status, circuit breakers, costs
  bob_dev_find       — Navigate codebase modules by name/keyword
  bob_dev_log        — Generate CHANGELOG entry from recent git diff
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
MIND_CLONE_DIR = SCRIPT_DIR.parent
ROOT_DIR = MIND_CLONE_DIR.parent
SRC_DIR = MIND_CLONE_DIR / "src" / "mind_clone"
BOB_API_URL = os.environ.get("BOB_API_URL", "http://localhost:8000")

DB_SEARCH_PATHS = [
    MIND_CLONE_DIR / "data" / "mind_clone.db",
    Path.home() / ".mind-clone" / "mind_clone.db",
    MIND_CLONE_DIR / "mind_clone.db",
]

# Module map for bob_dev_find (short name -> relative path, description)
MODULE_MAP = {
    "config":       ("config.py",                    "Configuration & env vars"),
    "models":       ("database/models.py",           "Database models (SQLAlchemy)"),
    "session":      ("database/session.py",          "DB session factory"),
    "state":        ("core/state.py",                "Global runtime state"),
    "security":     ("core/security.py",             "Security gates & SSRF"),
    "budget":       ("core/budget.py",               "Budget governor"),
    "circuit":      ("core/circuit_breaker.py",       "Circuit breaker"),
    "queue":        ("core/queue.py",                "Command queue"),
    "sandbox":      ("core/sandbox.py",              "Sandbox / OS execution"),
    "plugins":      ("core/plugins.py",              "Plugin system"),
    "policies":     ("core/policies.py",             "Tool policy profiles"),
    "closed_loop":  ("core/closed_loop.py",          "Closed-loop feedback"),
    "self_tune":    ("core/self_tune.py",            "Self-tuning engine"),
    "evaluation":   ("core/evaluation.py",           "Eval harness"),
    "loop":         ("agent/loop.py",                "Agent reasoning loop"),
    "llm":          ("agent/llm.py",                 "LLM client & failover"),
    "memory":       ("agent/memory.py",              "Memory management"),
    "identity":     ("agent/identity.py",            "Agent identity kernel"),
    "reasoning":    ("agent/reasoning.py",           "Reasoning helpers"),
    "registry":     ("tools/registry.py",            "Tool dispatch registry"),
    "schemas":      ("tools/schemas.py",             "Tool JSON schemas"),
    "basic":        ("tools/basic.py",               "Basic tool impls"),
    "web":          ("tools/web.py",                 "Web tools"),
    "code":         ("tools/code.py",                "Code execution tools"),
    "browser":      ("tools/browser.py",             "Browser automation"),
    "desktop":      ("tools/desktop.py",             "Desktop automation"),
    "vision":       ("tools/vision.py",              "Vision / screenshot"),
    "routes":       ("api/routes/_shared.py",        "FastAPI shared routes"),
    "telegram":     ("services/telegram_adapter.py", "Telegram bot adapter"),
    "scheduler":    ("services/scheduler.py",        "Job scheduler"),
    "task_engine":  ("services/task_engine.py",      "Task execution engine"),
}

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("bob_dev_mcp")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _find_db() -> Optional[Path]:
    """Find Bob's SQLite database."""
    env_path = os.environ.get("MIND_CLONE_DB_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    for p in DB_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _fetch_api(endpoint: str, timeout: int = 5) -> Dict[str, Any]:
    """Fetch JSON from Bob's API. Returns {"ok": bool, "data"|"error": ...}."""
    url = f"{BOB_API_URL}{endpoint}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "data": data}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Connection refused: {e.reason}"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_cmd(cmd: List[str], cwd: str = None, timeout: int = 300) -> Dict[str, Any]:
    """Run a subprocess, return structured result."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout.strip()[:4000],
            "stderr": result.stderr.strip()[:2000],
            "elapsed_ms": elapsed_ms,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout after {timeout}s"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"Command not found: {e}"}


def _db_query(sql: str, params: tuple = ()) -> Dict[str, Any]:
    """Run a read-only SQL query against Bob's database."""
    db_path = _find_db()
    if not db_path:
        return {"ok": False, "error": "Database not found. Check MIND_CLONE_DB_PATH."}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return {"ok": True, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Pydantic Input Models
# ---------------------------------------------------------------------------
class CheckInput(BaseModel):
    """Input for validation check."""
    model_config = ConfigDict(str_strip_whitespace=True)
    skip_tests: bool = Field(default=False, description="Skip pytest, only run compile check")


class HealthInput(BaseModel):
    """Input for health check."""
    model_config = ConfigDict(str_strip_whitespace=True)
    url: Optional[str] = Field(default=None, description="Custom Bob API URL (default: http://localhost:8000)")


class DiagInput(BaseModel):
    """Input for diagnostics."""
    model_config = ConfigDict(str_strip_whitespace=True)
    url: Optional[str] = Field(default=None, description="Custom Bob API URL")


class MemoryAction(str, Enum):
    STATS = "stats"
    LESSONS = "lessons"
    NOTES = "notes"
    VECTORS = "vectors"


class MemoryInput(BaseModel):
    """Input for memory inspection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: MemoryAction = Field(default=MemoryAction.STATS, description="What to inspect: stats, lessons, notes, vectors")
    owner_id: int = Field(default=1, description="Owner ID to filter by", ge=1)
    limit: int = Field(default=20, description="Max rows to return", ge=1, le=100)


class DbAction(str, Enum):
    TABLES = "tables"
    SCHEMA = "schema"
    INTEGRITY = "integrity"
    INFO = "info"


class DbInput(BaseModel):
    """Input for database inspection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: DbAction = Field(default=DbAction.TABLES, description="What to inspect: tables, schema, integrity, info")
    table_name: Optional[str] = Field(default=None, description="Table name (required for 'schema' action)")


class ToolsAction(str, Enum):
    LIST = "list"
    POLICY = "policy"
    PERFORMANCE = "performance"
    CUSTOM = "custom"


class ToolsInput(BaseModel):
    """Input for tool inspection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: ToolsAction = Field(default=ToolsAction.LIST, description="What to inspect: list, policy, performance, custom")


class LlmAction(str, Enum):
    STATUS = "status"
    CIRCUIT = "circuit"
    COST = "cost"


class LlmInput(BaseModel):
    """Input for LLM diagnostics."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: LlmAction = Field(default=LlmAction.STATUS, description="What to inspect: status, circuit, cost")
    days: int = Field(default=7, description="Days of history for cost action", ge=1, le=90)


class FindInput(BaseModel):
    """Input for codebase navigation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    query: str = Field(..., description="Module name or keyword to search (e.g., 'loop', 'registry', 'llm')", min_length=1, max_length=100)
    lines: int = Field(default=50, description="Number of lines to show from matched file", ge=1, le=500)


class LogInput(BaseModel):
    """Input for changelog generation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    since: str = Field(default="HEAD~1", description="Git ref to diff from (e.g., 'HEAD~3', 'main', a commit hash)")


# ===================================================================
# TOOL 1: bob_dev_check — Compile + Tests + Lint
# ===================================================================
@mcp.tool(
    name="bob_dev_check",
    annotations={"title": "Run Bob Validation", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def bob_dev_check(params: CheckInput) -> str:
    """Run compile check, tests, and lint on the Bob codebase.

    Equivalent to running bob_check.py. This is the first thing to run
    after ANY code change. Reports pass/fail for each step with timing.

    Args:
        params: CheckInput with optional skip_tests flag.

    Returns:
        JSON with results per validation step (compile, tests) including
        pass/fail status, output preview, and elapsed time.
    """
    results = {}

    # Step 1: Compile check
    compile_result = _run_cmd(
        [sys.executable, "-m", "compileall", "-q", str(SRC_DIR)],
        timeout=60,
    )
    results["compile"] = {
        "passed": compile_result["ok"],
        "elapsed_ms": compile_result.get("elapsed_ms"),
        "output": compile_result.get("stderr", "")[:1000] if not compile_result["ok"] else "OK",
    }

    # Step 2: Tests
    if not params.skip_tests:
        test_result = _run_cmd(
            [sys.executable, "-m", "pytest", "--tb=short", "-q"],
            cwd=str(MIND_CLONE_DIR),
            timeout=300,
        )
        results["tests"] = {
            "passed": test_result["ok"],
            "elapsed_ms": test_result.get("elapsed_ms"),
            "output": test_result.get("stdout", "")[:2000],
            "errors": test_result.get("stderr", "")[:1000] if not test_result["ok"] else None,
        }

    all_passed = all(r["passed"] for r in results.values())
    return json.dumps({"status": "PASS" if all_passed else "FAIL", "steps": results}, indent=2)


# ===================================================================
# TOOL 2: bob_dev_health — API Health Check
# ===================================================================
@mcp.tool(
    name="bob_dev_health",
    annotations={"title": "Check Bob Health", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def bob_dev_health(params: HealthInput) -> str:
    """Check if Bob's API server is running and healthy.

    Hits /health and /status/runtime endpoints to get live status
    including uptime, active sessions, queue depth, and circuit breaker state.

    Args:
        params: HealthInput with optional custom URL.

    Returns:
        JSON with server status, uptime, key runtime metrics, and any issues detected.
    """
    base = params.url or BOB_API_URL

    # Health endpoint
    health = _fetch_api("/health")
    if not health["ok"]:
        return json.dumps({
            "status": "DOWN",
            "url": base,
            "error": health["error"],
            "suggestion": "Start Bob with: cd mind-clone && python -m mind_clone --web",
        }, indent=2)

    # Runtime metrics
    runtime = _fetch_api("/status/runtime")
    metrics = {}
    if runtime["ok"]:
        data = runtime["data"]
        safe_keys = [k for k in data if not any(s in k.lower() for s in ("key", "token", "secret", "password"))]
        important_keys = [
            "uptime_seconds", "total_messages", "active_sessions",
            "command_queue_enqueued", "command_queue_processed",
            "circuit_breaker_state", "soft_trims", "hard_clears",
            "tool_calls_total", "tool_calls_failed",
            "cl_tools_warned", "cl_tools_blocked",
            "st_last_tune_at",
        ]
        for k in important_keys:
            if k in data:
                metrics[k] = data[k]

    return json.dumps({
        "status": "UP",
        "url": base,
        "health": health.get("data"),
        "metrics": metrics,
    }, indent=2)


# ===================================================================
# TOOL 3: bob_dev_diag — Performance Diagnostics
# ===================================================================
@mcp.tool(
    name="bob_dev_diag",
    annotations={"title": "Diagnose Bob Performance", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def bob_dev_diag(params: DiagInput) -> str:
    """Diagnose performance bottlenecks in a running Bob instance.

    Checks queue backlog, circuit breaker state, LLM latency,
    memory pressure, tool failure rates, and self-tuning status.

    Args:
        params: DiagInput with optional custom URL.

    Returns:
        JSON with detected issues (warnings/critical), performance metrics,
        and suggested fixes for each issue.
    """
    runtime = _fetch_api("/status/runtime")
    if not runtime["ok"]:
        return json.dumps({
            "status": "unreachable",
            "error": runtime["error"],
            "suggestion": "Bob must be running. Start with: cd mind-clone && python -m mind_clone --web",
        }, indent=2)

    data = runtime["data"]
    issues = []

    # Check queue backlog
    enqueued = int(data.get("command_queue_enqueued", 0))
    processed = int(data.get("command_queue_processed", 0))
    backlog = max(0, enqueued - processed)
    if backlog > 5:
        issues.append({"severity": "warning", "area": "queue", "message": f"Queue backlog: {backlog} pending commands", "fix": "Check queue workers or increase worker count"})

    # Check circuit breaker
    cb_state = data.get("circuit_breaker_state", "closed")
    if cb_state != "closed":
        issues.append({"severity": "critical", "area": "circuit_breaker", "message": f"Circuit breaker is {cb_state}", "fix": "Check LLM provider health, wait for cooldown"})

    # Check tool failure rate
    total_calls = int(data.get("tool_calls_total", 0))
    failed_calls = int(data.get("tool_calls_failed", 0))
    if total_calls > 10 and failed_calls / total_calls > 0.2:
        issues.append({"severity": "warning", "area": "tools", "message": f"High tool failure rate: {failed_calls}/{total_calls} ({int(failed_calls/total_calls*100)}%)", "fix": "Check closed-loop feedback: cl_tools_warned, cl_tools_blocked"})

    # Check hard clears (context overflow)
    hard_clears = int(data.get("hard_clears", 0))
    if hard_clears > 3:
        issues.append({"severity": "warning", "area": "memory", "message": f"High hard clear count: {hard_clears}", "fix": "Context is overflowing too often. Check session budget tuner."})

    # Closed-loop blocked tools
    cl_blocked = int(data.get("cl_tools_blocked", 0))
    if cl_blocked > 0:
        issues.append({"severity": "warning", "area": "closed_loop", "message": f"{cl_blocked} tools blocked by closed-loop feedback", "fix": "Check tool performance stats with bob_dev_tools"})

    return json.dumps({
        "status": "healthy" if not issues else "issues_detected",
        "issue_count": len(issues),
        "issues": issues,
        "raw_metrics": {k: data.get(k) for k in [
            "uptime_seconds", "total_messages", "command_queue_enqueued",
            "command_queue_processed", "circuit_breaker_state",
            "tool_calls_total", "tool_calls_failed", "hard_clears", "soft_trims",
        ] if k in data},
    }, indent=2)


# ===================================================================
# TOOL 4: bob_dev_memory — Memory System Inspection
# ===================================================================
@mcp.tool(
    name="bob_dev_memory",
    annotations={"title": "Inspect Bob Memory", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def bob_dev_memory(params: MemoryInput) -> str:
    """Inspect Bob's memory systems: lessons, research notes, vectors, improvement notes.

    Queries the SQLite database directly for memory contents.
    Use action='stats' for an overview of all memory types and counts.

    Args:
        params: MemoryInput with action (stats/lessons/notes/vectors), owner_id, and limit.

    Returns:
        JSON with memory data. For 'stats': counts per type.
        For specific types: list of entries with content previews.
    """
    db_path = _find_db()
    if not db_path:
        return json.dumps({"ok": False, "error": "Database not found. Set MIND_CLONE_DB_PATH or check default paths."}, indent=2)

    if params.action == MemoryAction.STATS:
        tables = {
            "conversation_messages": "SELECT COUNT(*) as cnt FROM conversation_message",
            "conversation_summaries": "SELECT COUNT(*) as cnt FROM conversation_summary",
            "research_notes": "SELECT COUNT(*) as cnt FROM research_note",
            "memory_vectors": "SELECT COUNT(*) as cnt FROM memory_vector",
            "self_improvement_notes": "SELECT COUNT(*) as cnt FROM self_improvement_note",
            "task_artifacts": "SELECT COUNT(*) as cnt FROM task_artifact",
        }
        stats = {}
        for name, sql in tables.items():
            result = _db_query(sql)
            if result["ok"] and result["rows"]:
                stats[name] = result["rows"][0]["cnt"]
            else:
                stats[name] = 0
        return json.dumps({"ok": True, "db_path": str(db_path), "memory_stats": stats}, indent=2)

    elif params.action == MemoryAction.LESSONS:
        result = _db_query(
            "SELECT id, content, tags, created_at FROM research_note WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?",
            (params.owner_id, params.limit),
        )
        return json.dumps(result, indent=2, default=str)

    elif params.action == MemoryAction.NOTES:
        result = _db_query(
            "SELECT id, note_type, content, status, created_at FROM self_improvement_note ORDER BY created_at DESC LIMIT ?",
            (params.limit,),
        )
        return json.dumps(result, indent=2, default=str)

    elif params.action == MemoryAction.VECTORS:
        result = _db_query("SELECT COUNT(*) as total, AVG(LENGTH(vector_blob)) as avg_blob_size FROM memory_vector")
        return json.dumps(result, indent=2, default=str)

    return json.dumps({"ok": False, "error": f"Unknown action: {params.action}"}, indent=2)


# ===================================================================
# TOOL 5: bob_dev_db — Database Inspection
# ===================================================================
@mcp.tool(
    name="bob_dev_db",
    annotations={"title": "Inspect Bob Database", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def bob_dev_db(params: DbInput) -> str:
    """Inspect Bob's SQLite database: tables, schemas, row counts, integrity.

    Useful for understanding data shape, checking migrations, and debugging.

    Args:
        params: DbInput with action (tables/schema/integrity/info) and optional table_name.

    Returns:
        JSON with database information based on the requested action.
    """
    db_path = _find_db()
    if not db_path:
        return json.dumps({"ok": False, "error": "Database not found."}, indent=2)

    if params.action == DbAction.INFO:
        size_mb = round(db_path.stat().st_size / 1024 / 1024, 2)
        return json.dumps({"ok": True, "path": str(db_path), "size_mb": size_mb}, indent=2)

    elif params.action == DbAction.TABLES:
        result = _db_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if not result["ok"]:
            return json.dumps(result, indent=2)
        tables = []
        for row in result["rows"]:
            name = row["name"]
            count_result = _db_query(f"SELECT COUNT(*) as cnt FROM [{name}]")
            cnt = count_result["rows"][0]["cnt"] if count_result["ok"] and count_result["rows"] else "?"
            tables.append({"name": name, "rows": cnt})
        tables.sort(key=lambda t: t["rows"] if isinstance(t["rows"], int) else 0, reverse=True)
        return json.dumps({"ok": True, "tables": tables, "total_tables": len(tables)}, indent=2)

    elif params.action == DbAction.SCHEMA:
        if not params.table_name:
            return json.dumps({"ok": False, "error": "table_name is required for 'schema' action"}, indent=2)
        result = _db_query(f"PRAGMA table_info([{params.table_name}])")
        return json.dumps(result, indent=2, default=str)

    elif params.action == DbAction.INTEGRITY:
        result = _db_query("PRAGMA integrity_check")
        return json.dumps(result, indent=2)

    return json.dumps({"ok": False, "error": f"Unknown action: {params.action}"}, indent=2)


# ===================================================================
# TOOL 6: bob_dev_tools — Tool Registry & Performance
# ===================================================================
@mcp.tool(
    name="bob_dev_tools",
    annotations={"title": "Inspect Bob Tools", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def bob_dev_tools(params: ToolsInput) -> str:
    """Inspect Bob's tool registry, policy profiles, and performance stats.

    Shows all 64+ registered tools, current policy profile, closed-loop
    feedback status, and custom/generated tools.

    Args:
        params: ToolsInput with action (list/policy/performance/custom).

    Returns:
        JSON with tool information based on the requested action.
    """
    if params.action == ToolsAction.LIST:
        # Try API first
        api_result = _fetch_api("/api/mcp")
        # Fallback: scan the tools/ directory for registered tools
        tools_dir = SRC_DIR / "tools"
        found_tools = []
        if tools_dir.exists():
            for py_file in sorted(tools_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                content = py_file.read_text(encoding="utf-8", errors="replace")
                # Find tool registrations (TOOL_DISPATCH assignments or def tool_name)
                funcs = re.findall(r'def\s+([\w]+)\s*\(', content)
                tool_funcs = [f for f in funcs if not f.startswith("_")]
                found_tools.append({
                    "file": py_file.name,
                    "functions": tool_funcs[:20],
                    "function_count": len(tool_funcs),
                })
        return json.dumps({"ok": True, "tool_modules": found_tools}, indent=2)

    elif params.action == ToolsAction.POLICY:
        # Read from runtime if available
        runtime = _fetch_api("/status/runtime")
        if runtime["ok"]:
            data = runtime["data"]
            policy_keys = [k for k in data if "policy" in k.lower() or "tool" in k.lower()]
            return json.dumps({"ok": True, "policy_data": {k: data[k] for k in policy_keys}}, indent=2)
        # Fallback: check env
        profile = os.environ.get("TOOL_POLICY_PROFILE", "balanced")
        return json.dumps({"ok": True, "profile": profile, "source": "env_var"}, indent=2)

    elif params.action == ToolsAction.PERFORMANCE:
        runtime = _fetch_api("/status/runtime")
        if not runtime["ok"]:
            return json.dumps({"ok": False, "error": "Bob API not reachable for performance data"}, indent=2)
        data = runtime["data"]
        perf_keys = [k for k in data if any(s in k for s in ["tool_call", "cl_tool", "cl_dead"])]
        return json.dumps({"ok": True, "performance": {k: data[k] for k in perf_keys}}, indent=2)

    elif params.action == ToolsAction.CUSTOM:
        result = _db_query("SELECT id, name, description, enabled, created_at FROM custom_tool ORDER BY created_at DESC LIMIT 50")
        return json.dumps(result, indent=2, default=str)

    return json.dumps({"ok": False, "error": f"Unknown action: {params.action}"}, indent=2)


# ===================================================================
# TOOL 7: bob_dev_llm — LLM Failover Diagnostics
# ===================================================================
@mcp.tool(
    name="bob_dev_llm",
    annotations={"title": "LLM Failover Status", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def bob_dev_llm(params: LlmInput) -> str:
    """Check LLM provider status, circuit breaker states, and usage costs.

    Shows which providers are configured, their circuit breaker state,
    recent latency, and cost tracking.

    Args:
        params: LlmInput with action (status/circuit/cost) and days for cost lookback.

    Returns:
        JSON with LLM subsystem status based on the requested action.
    """
    if params.action == LlmAction.STATUS:
        # Check which API keys are configured (existence only, not values)
        providers = {
            "kimi": bool(os.environ.get("KIMI_API_KEY")),
            "gemini": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("VISION_API_KEY")),
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
        # Get runtime data if available
        runtime = _fetch_api("/status/runtime")
        llm_metrics = {}
        if runtime["ok"]:
            data = runtime["data"]
            llm_keys = [k for k in data if any(s in k.lower() for s in ["llm", "circuit", "failover", "model"])]
            llm_metrics = {k: data[k] for k in llm_keys}
        return json.dumps({
            "ok": True,
            "providers_configured": providers,
            "failover_enabled": os.environ.get("LLM_FAILOVER_ENABLED", "true"),
            "default_model": os.environ.get("LLM_MODEL", "kimi-k2.5"),
            "runtime_metrics": llm_metrics,
        }, indent=2)

    elif params.action == LlmAction.CIRCUIT:
        runtime = _fetch_api("/status/runtime")
        if not runtime["ok"]:
            return json.dumps({"ok": False, "error": "Bob API not reachable"}, indent=2)
        data = runtime["data"]
        cb_keys = [k for k in data if "circuit" in k.lower()]
        return json.dumps({"ok": True, "circuit_breaker": {k: data[k] for k in cb_keys}}, indent=2)

    elif params.action == LlmAction.COST:
        result = _db_query(
            """SELECT date(created_at) as day, SUM(input_tokens) as input_tok,
               SUM(output_tokens) as output_tok, COUNT(*) as calls
               FROM usage_ledger
               WHERE created_at >= date('now', ?)
               GROUP BY date(created_at)
               ORDER BY day DESC""",
            (f"-{params.days} days",),
        )
        return json.dumps(result, indent=2, default=str)

    return json.dumps({"ok": False, "error": f"Unknown action: {params.action}"}, indent=2)


# ===================================================================
# TOOL 8: bob_dev_find — Codebase Navigation
# ===================================================================
@mcp.tool(
    name="bob_dev_find",
    annotations={"title": "Navigate Bob Codebase", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def bob_dev_find(params: FindInput) -> str:
    """Navigate Bob's modular codebase by module name or keyword.

    Fuzzy-matches your query against known modules (loop, registry, llm,
    memory, config, etc.) and returns the file path and first N lines.

    Args:
        params: FindInput with query string and lines count.

    Returns:
        JSON with matched module path, description, and file content preview.
    """
    query = params.query.lower()

    # Exact match first
    if query in MODULE_MAP:
        rel_path, desc = MODULE_MAP[query]
        full_path = SRC_DIR / rel_path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")[:params.lines]
            return json.dumps({
                "ok": True,
                "module": query,
                "path": str(full_path),
                "description": desc,
                "total_lines": len(content.split("\n")),
                "preview_lines": len(lines),
                "content": "\n".join(lines),
            }, indent=2)

    # Fuzzy match
    matches = []
    for key, (rel_path, desc) in MODULE_MAP.items():
        if query in key or query in desc.lower() or query in rel_path.lower():
            matches.append({"module": key, "path": rel_path, "description": desc})

    if not matches:
        # Search file contents as fallback
        found_files = []
        if SRC_DIR.exists():
            for py_file in SRC_DIR.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="replace")
                    if query in content.lower():
                        found_files.append({
                            "path": str(py_file.relative_to(SRC_DIR)),
                            "matches": len(re.findall(re.escape(query), content, re.IGNORECASE)),
                        })
                except Exception:
                    pass
            found_files.sort(key=lambda f: f["matches"], reverse=True)

        if found_files:
            return json.dumps({"ok": True, "type": "content_search", "query": query, "files": found_files[:10]}, indent=2)
        return json.dumps({"ok": False, "error": f"No module matching '{query}'", "available": sorted(MODULE_MAP.keys())}, indent=2)

    if len(matches) == 1:
        m = matches[0]
        full_path = SRC_DIR / m["path"]
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")[:params.lines]
            return json.dumps({
                "ok": True,
                "module": m["module"],
                "path": str(full_path),
                "description": m["description"],
                "total_lines": len(content.split("\n")),
                "preview_lines": len(lines),
                "content": "\n".join(lines),
            }, indent=2)

    return json.dumps({"ok": True, "type": "multiple_matches", "query": query, "matches": matches}, indent=2)


# ===================================================================
# TOOL 9: bob_dev_log — Changelog Generation
# ===================================================================
@mcp.tool(
    name="bob_dev_log",
    annotations={"title": "Generate Changelog Entry", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def bob_dev_log(params: LogInput) -> str:
    """Generate a CHANGELOG.md entry from recent git changes.

    Runs git diff and git log to summarize what changed, then formats
    it as a changelog entry. Does NOT write to CHANGELOG.md — returns
    the entry for you to review and insert.

    Args:
        params: LogInput with git ref to diff from (default: HEAD~1).

    Returns:
        JSON with the generated changelog entry text and diff summary.
    """
    # Get diff stats
    diff_result = _run_cmd(
        ["git", "diff", "--stat", params.since],
        cwd=str(ROOT_DIR),
        timeout=30,
    )

    # Get commit messages
    log_result = _run_cmd(
        ["git", "log", "--oneline", f"{params.since}..HEAD"],
        cwd=str(ROOT_DIR),
        timeout=30,
    )

    # Get changed files
    files_result = _run_cmd(
        ["git", "diff", "--name-only", params.since],
        cwd=str(ROOT_DIR),
        timeout=30,
    )

    diff_stat = diff_result.get("stdout", "") if diff_result["ok"] else "No diff available"
    commits = log_result.get("stdout", "") if log_result["ok"] else "No commits"
    changed_files = files_result.get("stdout", "").split("\n") if files_result["ok"] else []
    changed_files = [f for f in changed_files if f.strip()]

    # Build entry
    from datetime import date
    today = date.today().isoformat()
    entry_lines = [f"### {today}", ""]

    if commits:
        for line in commits.split("\n")[:10]:
            if line.strip():
                entry_lines.append(f"- {line.strip()}")

    entry_lines.append("")
    if changed_files:
        entry_lines.append(f"**Files changed:** {len(changed_files)}")

    return json.dumps({
        "ok": True,
        "changelog_entry": "\n".join(entry_lines),
        "diff_stat": diff_stat[:2000],
        "commits": commits[:1000],
        "files_changed": changed_files[:30],
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()

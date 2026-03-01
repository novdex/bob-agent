#!/usr/bin/env python3
"""
Bob Team MCP Server — Anthropic-Style Autonomous Agent Team.

Simplified to match how Anthropic built their C compiler:
- No pre-planning subprocess (was too slow)
- Agents are autonomous — give them a goal, they find work themselves
- File-based locks for coordination
- Git worktrees for isolation
- Simple bash-loop pattern

Tools provided:
  bob_classify_task   — Classify a task prompt into opus/sonnet/haiku
  bob_run_task        — Execute a task with auto or forced model selection
  bob_list_queue      — Show pending tasks from the task board
  bob_show_stats      — Show usage statistics
  bob_create_task     — Create a new task file in the pending queue
  bob_batch_preview   — Preview batch execution plan
  bob_plan_goal       — Instantly decompose a goal into tasks (no subprocess)
  bob_start_agents    — Start N autonomous agent loops
  bob_stop_agents     — Stop running agent loops gracefully
  bob_agent_status    — Show status of all running agents

Transport: stdio (local integration with Claude Code CLI)
"""

import json
import os
import re
import subprocess
import signal
import sys
import time
from datetime import datetime
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
TASKS_DIR = ROOT_DIR / "tasks"
LOG_FILE = MIND_CLONE_DIR / "persist" / "team_log.jsonl"
LOCKS_DIR = TASKS_DIR / "locks"

# ---------------------------------------------------------------------------
# Models (Max Plan — latest versions)
# ---------------------------------------------------------------------------
MODELS: Dict[str, str] = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}

COOLDOWNS: Dict[str, int] = {"opus": 90, "sonnet": 15, "haiku": 5}

TIER_LABELS: Dict[str, str] = {
    "opus": "OPUS (Architect)",
    "sonnet": "SONNET (Builder)",
    "haiku": "HAIKU (Quick-fix)",
}

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
OPUS_SIGNALS = [
    "architect", "redesign", "rearchitect", "design system", "refactor entire",
    "multi-file", "cross-module", "system design", "new architecture",
    "breaking change", "migration strategy", "protocol design",
    "complex algorithm", "optimization strategy", "knowledge graph",
    "meta-learning", "self-improvement", "world model",
    "reasoning engine", "memory architecture", "autonomy framework",
    "plan and implement", "full feature", "end-to-end",
    "implement pillar", "new subsystem", "build from scratch",
]

HAIKU_SIGNALS = [
    "changelog", "update docs", "add comment", "docstring", "readme",
    "type hint", "typing", "annotation", "format", "lint", "style",
    "rename", "move file", "typo", "spelling", "fix name",
    "remove unused", "delete dead code", "clean up",
    "env var", "config default", "gitignore", "requirements.txt",
    "pyproject.toml", "add logging",
]

OPUS_FILE_PATTERNS = [
    r"agent/loop\.py", r"core/tasks\.py", r"services/task_engine\.py",
    r"core/closed_loop\.py", r"core/self_tune\.py", r"database/models\.py",
]

HAIKU_FILE_PATTERNS = [
    r"CHANGELOG\.md", r"README\.md", r"\.env\.example",
    r"requirements\.txt", r"pyproject\.toml", r"\.gitignore", r"docs/",
]


def _classify(prompt: str) -> str:
    """Classify a task prompt into opus/sonnet/haiku."""
    lower = prompt.lower()
    opus_score = sum(1 for kw in OPUS_SIGNALS if kw in lower)
    haiku_score = sum(1 for kw in HAIKU_SIGNALS if kw in lower)
    for pat in OPUS_FILE_PATTERNS:
        if re.search(pat, prompt):
            opus_score += 2
    for pat in HAIKU_FILE_PATTERNS:
        if re.search(pat, prompt):
            haiku_score += 2
    if len(prompt) > 500 and len(re.findall(r'\b\w+\.py\b', prompt)) >= 3:
        opus_score += 2
    if opus_score >= 2 and opus_score > haiku_score:
        return "opus"
    elif haiku_score >= 2 and haiku_score > opus_score:
        return "haiku"
    return "sonnet"


# ---------------------------------------------------------------------------
# Helpers (also imported by bob_agent_loop.py)
# ---------------------------------------------------------------------------

def _build_system_prompt(tier: str) -> str:
    """Build system prompt for agent execution based on model tier."""
    base = (
        "You are a development agent working on the Bob AGI project. "
        "Read CLAUDE.md first. Run bob_check.py after code changes. "
        "Log changes to CHANGELOG.md. DO NOT modify .env files."
    )
    if tier == "opus":
        return base + " You are handling a complex architectural task — think carefully."
    elif tier == "haiku":
        return base + " Keep changes minimal and focused."
    return base


def _get_tools(tier: str) -> str:
    """Return comma-separated allowed tools for a given model tier."""
    tools_map = {
        "haiku": "Read,Edit,Write,Glob,Grep",
        "sonnet": "Read,Edit,Write,Bash,Glob,Grep",
        "opus": "Read,Edit,Write,Bash,Glob,Grep,Task",
    }
    return tools_map.get(tier, "Read,Edit,Write,Bash,Glob,Grep")


def _append_log(entry: Dict[str, Any]) -> None:
    """Append a log entry to the JSONL log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _read_log() -> List[Dict[str, Any]]:
    """Read all log entries."""
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _get_pending_tasks() -> List[Dict[str, str]]:
    """Get all pending task files with classification."""
    pending = TASKS_DIR / "pending"
    if not pending.exists():
        return []
    tasks = []
    for fp in sorted(pending.glob("*.md")):
        content = fp.read_text(encoding="utf-8")
        tier = _classify(content)
        first_line = content.strip().split("\n")[0][:80]
        tasks.append({
            "filename": fp.name,
            "model_tier": tier,
            "title": first_line,
            "path": str(fp),
        })
    return tasks


def _next_task_id() -> int:
    """Find the next available TASK-NNN number."""
    max_id = 3  # Start after existing TASK-001/002/003
    for status in ["pending", "in-progress", "completed", "failed"]:
        d = TASKS_DIR / status
        if d.exists():
            for f in d.glob("TASK-*.md"):
                try:
                    num = int(f.name.split("-")[1])
                    max_id = max(max_id, num)
                except (ValueError, IndexError):
                    pass
    return max_id + 1


def _clean_env() -> Dict[str, str]:
    """Get environment with Claude Code internal vars removed."""
    blocked = {
        "CLAUDECODE", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_CONVERSATION_ID",
        "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_TASK_ID",
    }
    return {k: v for k, v in os.environ.items() if k not in blocked}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("bob_team_mcp")


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class ModelTier(str, Enum):
    """Available model tiers."""
    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"


class ClassifyInput(BaseModel):
    """Input for task classification."""
    model_config = ConfigDict(str_strip_whitespace=True)
    prompt: str = Field(..., description="The task description to classify (e.g., 'Fix timeout bug in loop.py', 'Update CHANGELOG')", min_length=3, max_length=5000)


class RunTaskInput(BaseModel):
    """Input for running a task."""
    model_config = ConfigDict(str_strip_whitespace=True)
    prompt: str = Field(..., description="The task description for the Claude agent to execute", min_length=3, max_length=10000)
    model_tier: Optional[ModelTier] = Field(default=None, description="Force a specific model tier. If omitted, auto-classifies based on task complexity.")
    dry_run: bool = Field(default=False, description="If true, show what would happen without executing")


class CreateTaskInput(BaseModel):
    """Input for creating a new task file."""
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: str = Field(..., description="Short task ID (e.g., 'TASK-004')", pattern=r"^TASK-\d{3,4}$")
    title: str = Field(..., description="Short title for the task", min_length=5, max_length=200)
    description: str = Field(..., description="Detailed description of what needs to be done", min_length=10)
    pillar: str = Field(default="General", description="AGI pillar: Reasoning, Memory, Autonomy, Learning, Tool Mastery, Self-Awareness, World Understanding, Communication")
    priority: str = Field(default="P2", description="Priority level: P1 (critical), P2 (normal), P3 (nice-to-have)")
    files_to_modify: Optional[List[str]] = Field(default=None, description="List of file paths this task will likely touch")


class PlanGoalInput(BaseModel):
    """Input for the goal planner."""
    model_config = ConfigDict(str_strip_whitespace=True)
    goal: str = Field(..., description="High-level goal to achieve (e.g., 'Make Bob pass all 50 eval cases')", min_length=10, max_length=5000)
    max_tasks: int = Field(default=10, ge=1, le=30, description="Maximum number of sub-tasks to generate (default: 10)")
    start_agents: bool = Field(default=True, description="Always start 2 agents after creating tasks (Anthropic-style, default: true)")


class StartAgentsInput(BaseModel):
    """Input for starting parallel agent loops."""
    model_config = ConfigDict(str_strip_whitespace=True)
    count: int = Field(default=3, ge=1, le=8, description="Number of parallel agents to start (default: 3, max: 8)")
    max_iterations: int = Field(default=0, ge=0, description="Max tasks per agent (0=infinite, default: infinite)")
    fast: bool = Field(default=False, description="Fast mode: run 10% random tests instead of full suite")


class StopAgentsInput(BaseModel):
    """Input for stopping agent loops."""
    model_config = ConfigDict(str_strip_whitespace=True)
    agent_id: str = Field(default="all", description="Agent ID to stop (e.g., 'agent-1'), or 'all' to stop all agents")


# ---------------------------------------------------------------------------
# Tool 1: Classify
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_classify_task", annotations={"title": "Classify Bob Task", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_classify_task(params: ClassifyInput) -> str:
    """Classify a development task to determine which Claude model should handle it.

    Routes tasks based on complexity:
    - OPUS: Architecture, redesign, complex multi-file work, AGI pillar deep work
    - SONNET: Standard coding, bug fixes, new features, tests (default)
    - HAIKU: Docs, changelog, formatting, config, simple renames

    Args:
        params: ClassifyInput with the task prompt to classify.

    Returns:
        JSON with model_tier, model_id, label, reason, and the classification scores.
    """
    tier = _classify(params.prompt)
    return json.dumps({
        "model_tier": tier, "model_id": MODELS[tier], "label": TIER_LABELS[tier],
        "cooldown_seconds": COOLDOWNS[tier], "prompt_preview": params.prompt[:150],
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 2: Run Task
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_run_task", annotations={"title": "Run Bob Task", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def bob_run_task(params: RunTaskInput) -> str:
    """Execute a development task using Claude Code CLI with the optimal model.

    Auto-classifies the task to pick Opus/Sonnet/Haiku, then runs:
      claude -p "task" --model <model> --allowedTools <tools> --append-system-prompt <context>

    Use model_tier to force a specific model. Use dry_run=true to preview.

    Args:
        params: RunTaskInput with prompt, optional model_tier override, and dry_run flag.

    Returns:
        JSON with execution results including model used, elapsed time, and success status.
    """
    tier = params.model_tier.value if params.model_tier else _classify(params.prompt)
    model = MODELS[tier]
    tools = {"haiku": "Read,Edit,Write,Glob,Grep", "sonnet": "Read,Edit,Write,Bash,Glob,Grep", "opus": "Read,Edit,Write,Bash,Glob,Grep,Task"}.get(tier, "Read,Edit,Write,Bash,Glob,Grep")

    plan = {"model_tier": tier, "model_id": model, "label": TIER_LABELS[tier], "allowed_tools": tools, "cooldown_seconds": COOLDOWNS[tier], "prompt_preview": params.prompt[:200]}

    if params.dry_run:
        return json.dumps({**plan, "status": "dry_run", "command": f'claude -p "..." --model {model}'}, indent=2)

    system_prompt = (
        "You are a development agent working on the Bob AGI project. "
        "Read CLAUDE.md first. Run bob_check.py after code changes. "
        "Log changes to CHANGELOG.md. DO NOT modify .env files."
    )

    cmd = ["claude", "-p", params.prompt, "--model", model, "--allowedTools", tools, "--append-system-prompt", system_prompt, "--output-format", "json"]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=str(ROOT_DIR), env=_clean_env(), stdin=subprocess.DEVNULL)
        elapsed = round(time.time() - start, 1)
        _append_log({"timestamp": datetime.now().isoformat(), "model": tier, "prompt": params.prompt[:500], "elapsed_seconds": elapsed, "success": result.returncode == 0})
        return json.dumps({**plan, "status": "success" if result.returncode == 0 else "failed", "elapsed_seconds": elapsed, "output_preview": (result.stdout or "")[:2000], "error": (result.stderr or "")[:500] or None}, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({**plan, "status": "timeout", "error": "Exceeded 30 min limit"}, indent=2)
    except FileNotFoundError:
        return json.dumps({**plan, "status": "error", "error": "'claude' CLI not found"}, indent=2)


# ---------------------------------------------------------------------------
# Tool 3: List Queue
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_list_queue", annotations={"title": "List Bob Task Queue", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_list_queue() -> str:
    """List all pending tasks from the Bob task board (tasks/pending/).

    Shows each task's filename, auto-classified model tier, and title.
    Tasks are sorted by filename.

    Returns:
        JSON with list of pending tasks and summary counts per model tier.
    """
    tasks = _get_pending_tasks()
    counts = {"opus": 0, "sonnet": 0, "haiku": 0}
    for t in tasks:
        counts[t["model_tier"]] += 1
    return json.dumps({"total_pending": len(tasks), "by_model": counts, "tasks": tasks}, indent=2)


# ---------------------------------------------------------------------------
# Tool 4: Stats
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_show_stats", annotations={"title": "Show Bob Team Stats", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_show_stats() -> str:
    """Show usage statistics for the Bob Team model router.

    Displays total runs, success rates, and average times per model tier.

    Returns:
        JSON with per-model statistics and overall totals.
    """
    entries = _read_log()
    if not entries:
        return json.dumps({"message": "No runs logged yet.", "total_runs": 0}, indent=2)
    by_model: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        m = e.get("model", "unknown")
        if m not in by_model:
            by_model[m] = {"runs": 0, "successes": 0, "total_seconds": 0.0}
        by_model[m]["runs"] += 1
        if e.get("success"):
            by_model[m]["successes"] += 1
        by_model[m]["total_seconds"] += e.get("elapsed_seconds", 0)
    stats = {}
    for model in ["opus", "sonnet", "haiku"]:
        if model in by_model:
            s = by_model[model]
            stats[model] = {"runs": s["runs"], "success_rate": f"{round(s['successes'] / s['runs'] * 100)}%", "avg_seconds": round(s["total_seconds"] / s["runs"], 1)}
    return json.dumps({"total_runs": len(entries), "models": stats}, indent=2)


# ---------------------------------------------------------------------------
# Tool 5: Create Task
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_create_task", annotations={"title": "Create Bob Task", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
async def bob_create_task(params: CreateTaskInput) -> str:
    """Create a new task file in the pending queue.

    Generates a markdown task file in tasks/pending/ with the specified
    details. The task will be auto-classified when run.

    Args:
        params: CreateTaskInput with task_id, title, description, pillar, priority, and optional files.

    Returns:
        JSON with the created file path and auto-classification result.
    """
    pending = TASKS_DIR / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    tier = _classify(f"{params.title} {params.description} " + " ".join(params.files_to_modify or []))
    filename = f"{params.task_id}-{tier}-{params.title.lower().replace(' ', '-')[:40]}.md"
    filepath = pending / filename
    parts = [f"# {params.task_id}: {params.title}", "", f"## Priority: {params.priority}", f"## Pillar: {params.pillar}", "", params.description]
    if params.files_to_modify:
        parts.extend(["", "### Files to modify:"] + [f"- {fp}" for fp in params.files_to_modify])
    parts.extend(["", "### Acceptance Criteria:", "- [ ] Implementation complete", "- [ ] Tests pass (pytest)", "- [ ] bob_check.py passes", "- [ ] CHANGELOG.md updated"])
    filepath.write_text("\n".join(parts), encoding="utf-8")
    return json.dumps({"status": "created", "file": str(filepath), "filename": filename, "auto_classification": tier, "model_id": MODELS[tier]}, indent=2)


# ---------------------------------------------------------------------------
# Tool 6: Batch Preview
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_batch_preview", annotations={"title": "Preview Bob Batch Plan", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_batch_preview() -> str:
    """Preview the batch execution plan for all pending tasks.

    Shows the execution order (haiku first, then sonnet, then opus),
    estimated cooldown times, and total estimated duration.

    Returns:
        JSON with ordered task list and time estimates.
    """
    tasks = _get_pending_tasks()
    if not tasks:
        return json.dumps({"message": "No pending tasks.", "total": 0}, indent=2)
    order = {"haiku": 0, "sonnet": 1, "opus": 2}
    tasks.sort(key=lambda t: order.get(t["model_tier"], 1))
    total_cooldown = 0
    plan = []
    for i, t in enumerate(tasks):
        tier = t["model_tier"]
        cooldown = COOLDOWNS[tier] if i < len(tasks) - 1 else 0
        total_cooldown += cooldown
        plan.append({"order": i + 1, "filename": t["filename"], "model_tier": tier, "title": t["title"], "cooldown_after": cooldown})
    return json.dumps({"total_tasks": len(tasks), "estimated_cooldown_seconds": total_cooldown, "execution_order": "haiku -> sonnet -> opus", "plan": plan}, indent=2)


# ---------------------------------------------------------------------------
# Tool 7: Plan Goal — INSTANT (no subprocess, Anthropic-style)
# ---------------------------------------------------------------------------

# Pre-defined eval task templates based on the 7 benchmark categories
EVAL_TASK_TEMPLATES = {
    "BFCL": {
        "count": 13, "pillar": "Tool Mastery", "priority": "P1",
        "description": "Implement {count} BFCL (Berkeley Function Calling Leaderboard) eval cases testing function-calling accuracy: correct tool selection from schema, argument extraction from natural language, multi-tool chaining, parallel tool calls, error recovery on bad tool output, schema validation, nested function calls, optional parameter handling, type coercion, ambiguous intent routing, tool_call_id format validation, empty result handling, and tool timeout behavior.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/tools/registry.py", "mind-clone/src/mind_clone/tools/schemas.py"],
    },
    "GAIA": {
        "count": 9, "pillar": "Reasoning", "priority": "P1",
        "description": "Implement {count} GAIA (General AI Assistant) eval cases testing general reasoning: multi-step math with verification, date/time calculation, text summarization quality, instruction following accuracy, common sense reasoning, spatial reasoning, causal reasoning, analogical reasoning, and multi-constraint satisfaction.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/agent/loop.py"],
    },
    "FORTRESS": {
        "count": 11, "pillar": "Self-Awareness", "priority": "P1",
        "description": "Implement {count} FORTRESS security eval cases: prompt injection detection, secret redaction in logs, SQL injection prevention in tool args, path traversal blocking, command injection prevention, rate limit enforcement, approval gate for dangerous tools, sandbox escape prevention, PII detection, token budget enforcement, and cross-owner isolation.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/core/security.py"],
    },
    "Vending-Bench": {
        "count": 6, "pillar": "Autonomy", "priority": "P2",
        "description": "Implement {count} Vending-Bench reliability eval cases: budget governor stops at limits, circuit breaker trips and recovers, tool timeout handling, graceful degradation under load, retry logic with backoff, and error recovery without data loss.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/core/budget.py"],
    },
    "Context-Bench": {
        "count": 3, "pillar": "Memory", "priority": "P2",
        "description": "Implement {count} Context-Bench eval cases: context window trimming preserves tool pairs, long conversation history compression, and memory injection relevance scoring.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/agent/memory.py"],
    },
    "t2-bench": {
        "count": 3, "pillar": "Tool Mastery", "priority": "P2",
        "description": "Implement {count} t2-bench tool-use eval cases: intent-based tool filtering accuracy, tool performance tracking in closed loop, and tool dispatch routing correctness.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/tools/registry.py"],
    },
    "Terminal-Bench": {
        "count": 2, "pillar": "Autonomy", "priority": "P3",
        "description": "Implement {count} Terminal-Bench command execution eval cases: run_command timeout and process tree kill, and execute_python sandboxing with output capture.",
        "files": ["mind-clone/src/mind_clone/core/evaluation.py", "mind-clone/src/mind_clone/tools/basic.py"],
    },
}


@mcp.tool(name="bob_plan_goal", annotations={"title": "Plan Goal into Sub-Tasks", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def bob_plan_goal(params: PlanGoalInput) -> str:
    """Break a high-level goal into concrete sub-tasks using Opus as a planner.

    Takes a big goal (e.g., 'Make Bob pass all 50 eval cases') and:
    1. Gathers codebase context (source tree, tests, git log, CLAUDE.md)
    2. Sends it to Opus to decompose into actionable sub-tasks
    3. Creates task files in tasks/pending/ for worker agents
    4. Optionally starts 2 worker agents to execute them

    Like Anthropic's agent team — you give the end goal, agents figure out the rest.

    Args:
        params: PlanGoalInput with goal, max_tasks, and start_agents flag.

    Returns:
        JSON with the generated sub-tasks and their queue status.
    """
    goal_lower = params.goal.lower()

    # Detect eval-related goals and use pre-built templates
    if any(kw in goal_lower for kw in ["eval", "benchmark", "test cases", "pass all"]):
        return await _plan_eval_goal(params)

    # For other goals: create a single autonomous task
    # Anthropic approach: don't over-plan, let the agent figure it out
    next_id = _next_task_id()
    task_id = f"TASK-{next_id:03d}"
    tier = _classify(params.goal)

    pending = TASKS_DIR / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    safe_title = re.sub(r'[^\w\s-]', '', params.goal[:50]).strip().replace(' ', '-').lower()
    filename = f"{task_id}-{tier}-{safe_title}.md"
    filepath = pending / filename

    content = f"""# {task_id}: {params.goal[:80]}

## Priority: P1
## Pillar: General

{params.goal}

### Instructions:
- Look at the codebase, find what needs doing for this goal
- Make changes, run tests, iterate until done
- Run bob_check.py after changes
- Update CHANGELOG.md

### Acceptance Criteria:
- [ ] Goal achieved
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
"""
    filepath.write_text(content, encoding="utf-8")

    result = {
        "status": "ok",
        "goal": params.goal,
        "approach": "anthropic-style: single autonomous task, agent finds work itself",
        "tasks_created": 1,
        "tasks": [{"task_id": task_id, "title": params.goal[:80], "tier": tier, "filename": filename}],
    }

    if params.start_agents:
        try:
            agent_result = await bob_start_agents(StartAgentsInput(count=2))
            result["agents_started"] = json.loads(agent_result)
        except Exception as e:
            result["agents_started"] = f"Failed: {e}"

    return json.dumps(result, indent=2)


async def _plan_eval_goal(params: PlanGoalInput) -> str:
    """Instantly create eval benchmark tasks from templates — no subprocess needed."""
    next_id = _next_task_id()
    created = []
    pending = TASKS_DIR / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    for i, (bench_name, template) in enumerate(EVAL_TASK_TEMPLATES.items()):
        if len(created) >= params.max_tasks:
            break

        task_id = f"TASK-{next_id + i:03d}"
        title = f"Implement {bench_name} eval cases ({template['count']} cases)"
        tier = _classify(f"{title} {template['description']}")
        safe_title = f"{bench_name.lower()}-eval-cases"
        filename = f"{task_id}-{tier}-{safe_title}.md"
        filepath = pending / filename

        desc = template["description"].format(count=template["count"])
        parts = [
            f"# {task_id}: {title}", "",
            f"## Priority: {template['priority']}",
            f"## Pillar: {template['pillar']}", "",
            desc, "",
            "### Files to modify:",
        ] + [f"- {f}" for f in template["files"]] + [
            "", "### Acceptance Criteria:",
            f"- [ ] All {template['count']} eval cases implemented",
            "- [ ] Each case tests real functionality (not trivial pass)",
            "- [ ] Tests pass (pytest)",
            "- [ ] bob_check.py passes",
            "- [ ] CHANGELOG.md updated",
        ]
        filepath.write_text("\n".join(parts), encoding="utf-8")

        created.append({
            "task_id": task_id, "title": title, "tier": tier,
            "priority": template["priority"], "pillar": template["pillar"],
            "benchmark": bench_name, "case_count": template["count"],
            "filename": filename,
        })

    result = {
        "status": "ok",
        "goal": params.goal,
        "approach": "instant decomposition from eval benchmark templates",
        "tasks_created": len(created),
        "total_eval_cases": sum(t["case_count"] for t in created),
        "tasks": created,
    }

    if params.start_agents:
        try:
            agent_result = await bob_start_agents(StartAgentsInput(count=2))
            result["agents_started"] = json.loads(agent_result)
        except Exception as e:
            result["agents_started"] = f"Failed: {e}"

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool 8: Start Agents
# ---------------------------------------------------------------------------
AGENT_PROCESSES: Dict[str, subprocess.Popen] = {}
AGENT_LOOP_SCRIPT = SCRIPT_DIR / "bob_agent_loop.py"


@mcp.tool(name="bob_start_agents", annotations={"title": "Start Agent Loops", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def bob_start_agents(params: StartAgentsInput) -> str:
    """Start N parallel agent loops in background processes.

    Launches bob_agent_loop.py processes that autonomously pick tasks
    from tasks/pending/, execute them with auto-classified models in
    isolated Git worktrees, and merge passing changes to main.

    Default setup: all agents are general workers (pick any task, auto-classify model).
    Inspired by Anthropic's C compiler agent team architecture.

    Args:
        params: StartAgentsInput with count, max_iterations, and fast flag.

    Returns:
        JSON with started agent IDs, PIDs, and configuration.
    """
    if not AGENT_LOOP_SCRIPT.exists():
        return json.dumps({"status": "error", "error": f"Agent loop script not found: {AGENT_LOOP_SCRIPT}"}, indent=2)

    started = []
    for i in range(1, params.count + 1):
        agent_id = f"agent-{i}"
        if agent_id in AGENT_PROCESSES and AGENT_PROCESSES[agent_id].poll() is None:
            started.append({"agent_id": agent_id, "status": "already_running", "pid": AGENT_PROCESSES[agent_id].pid})
            continue

        cmd = [sys.executable, str(AGENT_LOOP_SCRIPT), "--agent-id", agent_id]
        if params.max_iterations > 0:
            cmd.extend(["--max-iterations", str(params.max_iterations)])
        if params.fast:
            cmd.append("--fast")

        log_file = LOG_FILE.parent / f"{agent_id}.log"
        log_handle = open(log_file, "a", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL, cwd=str(ROOT_DIR), env=_clean_env())
        AGENT_PROCESSES[agent_id] = proc
        started.append({"agent_id": agent_id, "status": "started", "pid": proc.pid, "log_file": str(log_file)})

    return json.dumps({"status": "ok", "agents_started": len([a for a in started if a["status"] == "started"]), "agents": started}, indent=2)


# ---------------------------------------------------------------------------
# Tool 9: Stop Agents
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_stop_agents", annotations={"title": "Stop Agent Loops", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_stop_agents(params: StopAgentsInput) -> str:
    """Stop running agent loops gracefully.

    Sends termination signal to agent processes. They finish their
    current task then exit cleanly. Use agent_id='all' to stop all agents.

    Args:
        params: StopAgentsInput with agent_id or 'all'.

    Returns:
        JSON with stopped agent IDs and their final status.
    """
    stopped = []
    targets = list(AGENT_PROCESSES.keys()) if params.agent_id == "all" else [params.agent_id]
    for agent_id in targets:
        if agent_id not in AGENT_PROCESSES:
            stopped.append({"agent_id": agent_id, "status": "not_found"})
            continue
        proc = AGENT_PROCESSES[agent_id]
        if proc.poll() is not None:
            stopped.append({"agent_id": agent_id, "status": "already_stopped", "exit_code": proc.returncode})
            del AGENT_PROCESSES[agent_id]
            continue
        try:
            proc.terminate()
            stopped.append({"agent_id": agent_id, "status": "stopping", "pid": proc.pid})
        except Exception as e:
            stopped.append({"agent_id": agent_id, "status": "error", "error": str(e)})
    return json.dumps({"status": "ok", "stopped": stopped}, indent=2)


# ---------------------------------------------------------------------------
# Tool 10: Agent Status
# ---------------------------------------------------------------------------
@mcp.tool(name="bob_agent_status", annotations={"title": "Agent Team Status", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def bob_agent_status() -> str:
    """Show status of all running agents and task queue depth.

    Reads lock files, PROGRESS.md, and queue directories to provide
    a live dashboard of the agent team's activity.

    Returns:
        JSON with active agents, current tasks, queue depth, and recent progress.
    """
    agents = {}
    for agent_id, proc in list(AGENT_PROCESSES.items()):
        alive = proc.poll() is None
        agents[agent_id] = {"alive": alive, "pid": proc.pid, "exit_code": proc.returncode if not alive else None}

    # Lock files
    active_tasks = {}
    if LOCKS_DIR.exists():
        for lock_file in LOCKS_DIR.glob("*.lock"):
            try:
                lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
                aid = lock_data.get("agent_id", lock_file.stem)
                active_tasks[aid] = {"task": lock_data.get("task_file", "unknown"), "claimed_at": lock_data.get("claimed_at", "unknown")}
                if aid in agents:
                    agents[aid]["current_task"] = lock_data.get("task_file")
            except Exception:
                pass

    # Queue counts
    queue = {}
    for subdir in ["pending", "in-progress", "completed", "failed"]:
        d = TASKS_DIR / subdir
        queue[subdir] = len(list(d.glob("*.md"))) if d.exists() else 0

    # Recent progress
    progress_file = TASKS_DIR / "PROGRESS.md"
    recent = []
    if progress_file.exists():
        lines = progress_file.read_text(encoding="utf-8").strip().split("\n")
        recent = [l for l in lines[-10:] if l.strip()]

    return json.dumps({"agents": agents, "active_tasks": active_tasks, "queue": queue, "total_tasks": sum(queue.values()), "recent_progress": recent}, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()

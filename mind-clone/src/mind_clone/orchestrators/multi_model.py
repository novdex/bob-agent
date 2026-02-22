#!/usr/bin/env python3
"""
MULTI_MODEL_ORCHESTRATOR v2.0 — Updated with Exact Model IDs
Routes tasks to optimal model within each CLI tool stack.

Stack Priority:
  1. GEMINI (FREE, 1000/day) — Exhaust first
  2. CODEX (Paid) — Model selection by task
  3. CLAUDE (Pro) — Model selection by task  
  4. KIMI (API) — Only when others exhausted

Updated: 2026-02-10 with verified model IDs
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================================
# EXACT MODEL CONFIGURATIONS (Verified 2026-02-10)
# ============================================================================

class TaskComplexity(Enum):
    TRIVIAL = "trivial"    # Single line, typos, formatting
    SIMPLE = "simple"      # Docs, boilerplate, patterns
    MEDIUM = "medium"      # Features, refactoring, debugging
    COMPLEX = "complex"    # Architecture, design
    RESEARCH = "research"  # Open-ended exploration

@dataclass
class ModelConfig:
    name: str              # Display name
    model_id: str          # Exact ID for CLI
    cost_tier: str         # free/very_low/low/medium/high/very_high
    speed: str             # very_fast/fast/medium/slow
    best_for: List[str]    # Task types
    context_window: int    # Token limit
    description: str       # When to use

@dataclass  
class ToolStack:
    name: str
    command: str
    daily_limit: Optional[int]
    models: Dict[str, ModelConfig]
    default_model: str
    env_var: Optional[str]  # Environment variable for model selection
    flag: Optional[str]     # CLI flag for model selection

# ============================================================================
# CLAUDE CODE (Anthropic) — Pro Subscription
# ============================================================================
CLAUDE_STACK = ToolStack(
    name="Claude Code (Anthropic)",
    command="claude",
    daily_limit=None,
    env_var="ANTHROPIC_MODEL",
    flag=None,
    models={
        "haiku_3": ModelConfig(
            name="Claude 3 Haiku",
            model_id="claude-3-haiku-20240307",
            cost_tier="very_low",
            speed="very_fast",
            best_for=["trivial", "simple", "docs", "quick_edits"],
            context_window=200000,
            description="Fastest Claude, cheapest, good for quick tasks"
        ),
        "sonnet_35": ModelConfig(
            name="Claude 3.5 Sonnet",
            model_id="claude-3-5-sonnet-20241022",
            cost_tier="medium",
            speed="fast",
            best_for=["medium", "coding", "refactoring", "debugging"],
            context_window=200000,
            description="Best balance of speed and capability"
        ),
        "sonnet_45": ModelConfig(
            name="Claude 4.5 Sonnet",
            model_id="claude-sonnet-4-5-20250929",
            cost_tier="medium",
            speed="fast",
            best_for=["medium", "coding", "analysis"],
            context_window=200000,
            description="Latest Sonnet, improved over 3.5"
        ),
        "opus_3": ModelConfig(
            name="Claude 3 Opus",
            model_id="claude-3-opus-20240229",
            cost_tier="high",
            speed="medium",
            best_for=["complex", "architecture", "reasoning"],
            context_window=200000,
            description="Deep reasoning, most capable"
        ),
        "opus_4": ModelConfig(
            name="Claude 4 Opus",
            model_id="claude-opus-4-6",
            cost_tier="high",
            speed="medium",
            best_for=["complex", "architecture", "research"],
            context_window=200000,
            description="Latest Opus, best reasoning available"
        ),
    },
    default_model="sonnet_35"
)

# ============================================================================
# CODEX CLI (OpenAI) — ChatGPT Plus Subscription
# ============================================================================
CODEX_STACK = ToolStack(
    name="Codex CLI (OpenAI)",
    command="codex",
    daily_limit=None,
    env_var="OPENAI_MODEL",
    flag="--model",
    models={
        "o3_mini": ModelConfig(
            name="o3-mini",
            model_id="o3-mini",
            cost_tier="very_low",
            speed="fast",
            best_for=["trivial", "simple", "quick_coding"],
            context_window=200000,
            description="Fast reasoning model, efficient for quick tasks"
        ),
        "gpt4o_mini": ModelConfig(
            name="GPT-4o mini",
            model_id="gpt-4o-mini",
            cost_tier="low",
            speed="very_fast",
            best_for=["simple", "boilerplate", "docs"],
            context_window=128000,
            description="Fastest GPT, good for simple code"
        ),
        "gpt4o": ModelConfig(
            name="GPT-4o",
            model_id="gpt-4o",
            cost_tier="medium",
            speed="fast",
            best_for=["medium", "coding", "debugging"],
            context_window=128000,
            description="Best balance for most coding tasks"
        ),
        "gpt52": ModelConfig(
            name="GPT-5.2-Codex",
            model_id="gpt-5.2-codex",
            cost_tier="medium",
            speed="fast",
            best_for=["medium", "agentic_coding", "implementation"],
            context_window=200000,
            description="Optimized for agentic coding tasks"
        ),
        "gpt53": ModelConfig(
            name="GPT-5.3-Codex",
            model_id="gpt-5.3-codex",
            cost_tier="medium",
            speed="medium",
            best_for=["medium", "complex_coding", "features"],
            context_window=200000,
            description="Default for Codex, great for most coding"
        ),
        "gpt5": ModelConfig(
            name="GPT-5",
            model_id="gpt-5",
            cost_tier="high",
            speed="medium",
            best_for=["complex", "reasoning", "architecture"],
            context_window=128000,
            description="Strong reasoning, complex tasks"
        ),
        "o1": ModelConfig(
            name="o1",
            model_id="o1",
            cost_tier="very_high",
            speed="slow",
            best_for=["research", "complex_reasoning", "planning"],
            context_window=200000,
            description="Best reasoning, slowest, most expensive"
        ),
        "o3": ModelConfig(
            name="o3",
            model_id="o3",
            cost_tier="very_high",
            speed="medium",
            best_for=["research", "advanced_reasoning"],
            context_window=200000,
            description="Advanced reasoning, successor to o1"
        ),
    },
    default_model="gpt53"
)

# ============================================================================
# GEMINI CLI (Google) — FREE TIER
# ============================================================================
GEMINI_STACK = ToolStack(
    name="Gemini CLI (Google)",
    command="gemini",
    daily_limit=1000,
    env_var=None,
    flag="--model",
    models={
        "flash_25": ModelConfig(
            name="Gemini 2.5 Flash",
            model_id="gemini-2.5-flash",
            cost_tier="free",
            speed="very_fast",
            best_for=["trivial", "simple", "high_volume"],
            context_window=1000000,
            description="FASTEST, good for quick tasks"
        ),
        "pro_25": ModelConfig(
            name="Gemini 2.5 Pro",
            model_id="gemini-2.5-pro",
            cost_tier="free",
            speed="fast",
            best_for=["simple", "medium", "coding", "analysis"],
            context_window=2000000,
            description="More capable, still FREE"
        ),
        "flash_3": ModelConfig(
            name="Gemini 3 Flash",
            model_id="gemini-3-flash",
            cost_tier="free",
            speed="very_fast",
            best_for=["trivial", "simple"],
            context_window=1000000,
            description="Latest fast model"
        ),
        "pro_3": ModelConfig(
            name="Gemini 3 Pro",
            model_id="gemini-3-pro",
            cost_tier="free",
            speed="fast",
            best_for=["medium", "complex", "coding"],
            context_window=2000000,
            description="Latest Pro, most capable FREE model"
        ),
    },
    default_model="pro_3"
)

# ============================================================================
# KIMI CODE (Moonshot) — API Key (Pay as you go)
# ============================================================================
KIMI_STACK = ToolStack(
    name="Kimi Code (Moonshot)",
    command="kimi",
    daily_limit=None,
    env_var=None,
    flag="--model",
    models={
        "k25_32k": ModelConfig(
            name="Kimi K2.5 (32K)",
            model_id="kimi-k2.5-32k",
            cost_tier="api_low",
            speed="fast",
            best_for=["trivial", "simple"],
            context_window=32000,
            description="Cheapest API option, quick tasks"
        ),
        "k25": ModelConfig(
            name="Kimi K2.5",
            model_id="kimi-k2.5",
            cost_tier="api_medium",
            speed="medium",
            best_for=["simple", "medium"],
            context_window=256000,
            description="Default K2.5, good balance"
        ),
        "k25_128k": ModelConfig(
            name="Kimi K2.5 (128K)",
            model_id="kimi-k2.5-128k",
            cost_tier="api_medium",
            speed="medium",
            best_for=["medium", "complex"],
            context_window=128000,
            description="Larger context for medium tasks"
        ),
        "k25_256k": ModelConfig(
            name="Kimi K2.5 (256K)",
            model_id="kimi-k2.5-256k",
            cost_tier="api_high",
            speed="medium",
            best_for=["complex", "long_context"],
            context_window=256000,
            description="Most capable, largest context"
        ),
        "k2_instant": ModelConfig(
            name="Kimi K2 Instant",
            model_id="kimi-k2-instant",
            cost_tier="api_low",
            speed="very_fast",
            best_for=["trivial", "quick_responses"],
            context_window=32000,
            description="Fastest responses, lowest latency"
        ),
        "k2_thinking": ModelConfig(
            name="Kimi K2 Thinking",
            model_id="kimi-k2-thinking",
            cost_tier="api_high",
            speed="slow",
            best_for=["research", "complex_reasoning"],
            context_window=256000,
            description="Deep reasoning mode, slow but thorough"
        ),
    },
    default_model="k25"
)

ALL_STACKS = {
    "gemini": GEMINI_STACK,
    "codex": CODEX_STACK,
    "claude": CLAUDE_STACK,
    "kimi": KIMI_STACK,
}

# ============================================================================
# USAGE TRACKING
# ============================================================================

DB_PATH = Path(__file__).parent / "ai_orchestrator_v2.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stack TEXT NOT NULL,
            model TEXT NOT NULL,
            task_preview TEXT,
            complexity TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_today_usage(stack: str) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT COUNT(*) FROM usage WHERE stack = ? AND DATE(timestamp) = ?",
            (stack, today)
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def log_usage(stack: str, model: str, task: str, complexity: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usage (stack, model, task_preview, complexity) VALUES (?, ?, ?, ?)",
            (stack, model, task[:200], complexity)
        )
        conn.commit()
        conn.close()
    except:
        pass

# ============================================================================
# TASK ANALYSIS
# ============================================================================

def analyze_task(task: str) -> TaskComplexity:
    """First-principles task complexity analysis."""
    task_lower = task.lower()
    
    # RESEARCH (open-ended)
    research_signals = [
        "research", "explore", "investigate", "compare approaches",
        "what if", "how to best", "analyze options"
    ]
    
    # COMPLEX (architecture, design)
    complex_signals = [
        "architecture", "design", "system", "framework", "restructure",
        "redesign", "strategy", "optimize", "performance critical",
        "security model", "algorithm design", "trade-offs"
    ]
    
    # MEDIUM (implementation)
    medium_signals = [
        "implement", "refactor", "debug", "fix", "feature",
        "improve", "enhance", "integration", "error handling"
    ]
    
    # SIMPLE (docs, boilerplate)
    simple_signals = [
        "doc", "comment", "format", "style", "lint", "typo",
        "rename", "cleanup", "boilerplate", "template"
    ]
    
    # TRIVIAL (single action)
    trivial_signals = [
        "change line", "fix typo", "add import", "rename var"
    ]
    
    if any(s in task_lower for s in research_signals):
        return TaskComplexity.RESEARCH
    if any(s in task_lower for s in complex_signals):
        return TaskComplexity.COMPLEX
    if any(s in task_lower for s in medium_signals):
        return TaskComplexity.MEDIUM
    if any(s in task_lower for s in trivial_signals):
        return TaskComplexity.TRIVIAL
    if any(s in task_lower for s in simple_signals):
        return TaskComplexity.SIMPLE
    
    words = len(task.split())
    if words < 5:
        return TaskComplexity.TRIVIAL
    elif words < 10:
        return TaskComplexity.SIMPLE
    elif words < 20:
        return TaskComplexity.MEDIUM
    return TaskComplexity.COMPLEX

# ============================================================================
# MODEL SELECTION (Exact Model IDs)
# ============================================================================

def select_model_for_stack(stack: ToolStack, complexity: TaskComplexity, task: str) -> tuple[str, ModelConfig, str]:
    """Select optimal model within stack based on task."""
    task_lower = task.lower()
    
    # GEMINI: Use latest Pro for most, Flash for trivial
    if stack.name.startswith("Gemini"):
        if complexity == TaskComplexity.TRIVIAL:
            return ("flash_3", stack.models["flash_3"], "Trivial -> Gemini 3 Flash (FREE, fastest)")
        elif complexity == TaskComplexity.SIMPLE:
            return ("flash_3", stack.models["flash_3"], "Simple -> Gemini 3 Flash (FREE, fast)")
        elif complexity == TaskComplexity.MEDIUM:
            return ("pro_3", stack.models["pro_3"], "Medium -> Gemini 3 Pro (FREE, capable)")
        else:
            return ("pro_3", stack.models["pro_3"], "Complex -> Gemini 3 Pro (FREE, best)")
    
    # CODEX: Select by capability needs
    if stack.name.startswith("Codex"):
        if complexity == TaskComplexity.TRIVIAL:
            return ("o3_mini", stack.models["o3_mini"], "Trivial -> o3-mini (fast, cheap)")
        elif complexity == TaskComplexity.SIMPLE:
            if "test" in task_lower:
                return ("gpt4o_mini", stack.models["gpt4o_mini"], "Simple testing -> GPT-4o mini")
            return ("gpt4o", stack.models["gpt4o"], "Simple coding -> GPT-4o (fast)")
        elif complexity == TaskComplexity.MEDIUM:
            if "implement" in task_lower or "code" in task_lower:
                return ("gpt53", stack.models["gpt53"], "Medium coding -> GPT-5.3-Codex (default, great)")
            return ("gpt52", stack.models["gpt52"], "Medium -> GPT-5.2-Codex")
        elif complexity == TaskComplexity.COMPLEX:
            return ("gpt5", stack.models["gpt5"], "Complex -> GPT-5 (strong reasoning)")
        else:  # RESEARCH
            return ("o1", stack.models["o1"], "Research -> o1 (best reasoning)")
    
    # CLAUDE: Select by reasoning needs
    if stack.name.startswith("Claude"):
        if complexity == TaskComplexity.TRIVIAL:
            return ("haiku_3", stack.models["haiku_3"], "Trivial -> Haiku 3 (fastest, cheapest)")
        elif complexity == TaskComplexity.SIMPLE:
            return ("haiku_3", stack.models["haiku_3"], "Simple -> Haiku 3 (efficient)")
        elif complexity == TaskComplexity.MEDIUM:
            if "debug" in task_lower:
                return ("sonnet_45", stack.models["sonnet_45"], "Debugging -> Sonnet 4.5 (latest)")
            return ("sonnet_35", stack.models["sonnet_35"], "Medium -> Sonnet 3.5 (balanced)")
        else:  # COMPLEX or RESEARCH
            return ("opus_4", stack.models["opus_4"], "Complex/Research -> Opus 4 (best reasoning)")
    
    # KIMI: Select by context needs
    if stack.name.startswith("Kimi"):
        if complexity in [TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE]:
            return ("k2_instant", stack.models["k2_instant"], "Simple -> K2 Instant (fastest API)")
        elif complexity == TaskComplexity.MEDIUM:
            return ("k25", stack.models["k25"], "Medium -> K2.5 (default, good)")
        elif complexity == TaskComplexity.COMPLEX:
            return ("k25_256k", stack.models["k25_256k"], "Complex -> K2.5 256K (most capable)")
        else:  # RESEARCH
            return ("k2_thinking", stack.models["k2_thinking"], "Research -> K2 Thinking (deep reasoning)")
    
    return (stack.default_model, stack.models[stack.default_model], "Default")

def select_stack_and_model(task: str, complexity_override: Optional[str] = None, 
                           force_stack: Optional[str] = None) -> tuple[str, str, ModelConfig, str]:
    """First-principles stack selection."""
    
    if complexity_override:
        complexity = TaskComplexity(complexity_override.lower())
    else:
        complexity = analyze_task(task)
    
    gemini_used = get_today_usage("gemini")
    task_lower = task.lower()
    
    # FORCE specific stack
    if force_stack and force_stack in ALL_STACKS:
        model_key, model_config, reasoning = select_model_for_stack(ALL_STACKS[force_stack], complexity, task)
        return (force_stack, model_key, model_config, f"[FORCED] {reasoning}")
    
    # PRINCIPLE 1: Use Gemini FREE tier first
    if gemini_used < 950:
        model_key, model_config, reasoning = select_model_for_stack(GEMINI_STACK, complexity, task)
        return ("gemini", model_key, model_config, f"FREE: {reasoning}")
    
    # PRINCIPLE 2: Codex for code, Claude for analysis
    code_keywords = ["implement", "code", "function", "class", "write", "generate code"]
    analysis_keywords = ["analyze", "review", "design", "debug", "explain"]
    
    is_code = any(kw in task_lower for kw in code_keywords)
    is_analysis = any(kw in task_lower for kw in analysis_keywords)
    
    if is_code and not is_analysis:
        model_key, model_config, reasoning = select_model_for_stack(CODEX_STACK, complexity, task)
        return ("codex", model_key, model_config, reasoning)
    else:
        model_key, model_config, reasoning = select_model_for_stack(CLAUDE_STACK, complexity, task)
        return ("claude", model_key, model_config, reasoning)

# ============================================================================
# EXECUTION
# ============================================================================

def build_command(stack_key: str, model_key: str, model_config: ModelConfig, task: str) -> tuple[str, dict]:
    """Build command with exact model IDs."""
    stack = ALL_STACKS[stack_key]
    env_vars = {}
    
    if stack.env_var:
        env_vars[stack.env_var] = model_config.model_id
    
    if stack.flag:
        cmd = f'{stack.command} {stack.flag} {model_config.model_id} "{task}"'
    else:
        cmd = f'{stack.command} "{task}"'
    
    return cmd, env_vars

def orchestrate(task: str, complexity_override: Optional[str] = None, 
                demo: bool = True, execute: bool = False, 
                force_stack: Optional[str] = None) -> dict:
    """Main orchestration."""
    
    print("=" * 75)
    print("MULTI-MODEL ORCHESTRATOR v2.0 — Exact Model IDs")
    print("=" * 75)
    
    init_db()
    
    gemini_used = get_today_usage("gemini")
    print(f"\n[USAGE]")
    print(f"  Gemini (FREE): {gemini_used}/1000 today")
    
    # Analyze
    if complexity_override:
        complexity = TaskComplexity(complexity_override.lower())
    else:
        complexity = analyze_task(task)
    
    print(f"\n[TASK]")
    print(f"  {task}")
    print(f"  Complexity: {complexity.value.upper()}")
    
    # Select
    stack_key, model_key, model_config, reasoning = select_stack_and_model(task, complexity_override, force_stack)
    stack = ALL_STACKS[stack_key]
    
    print(f"\n[SELECTION]")
    print(f"  Stack: {stack.name}")
    print(f"  Model: {model_config.name}")
    print(f"  ID: {model_config.model_id}")
    print(f"  Cost: {model_config.cost_tier.upper()}")
    print(f"  Speed: {model_config.speed}")
    print(f"  Context: {model_config.context_window:,} tokens")
    print(f"  Why: {reasoning}")
    
    # Build command
    cmd, env_vars = build_command(stack_key, model_key, model_config, task)
    
    print(f"\n[COMMAND]")
    for var, val in env_vars.items():
        print(f"  $env:{var} = \"{val}\"")
    print(f"  $ {cmd}")
    
    if demo:
        print(f"\n[MODE: DEMO — Use --run to execute]")
    
    if execute:
        print(f"\n[EXECUTING...]")
        for var, val in env_vars.items():
            os.environ[var] = val
        log_usage(stack_key, model_key, task, complexity.value)
        print(f"  -> Routed to {model_config.name}")
    
    print("=" * 75)
    
    return {
        "stack": stack_key,
        "model": model_key,
        "model_name": model_config.name,
        "model_id": model_config.model_id,
        "complexity": complexity.value,
        "command": cmd,
        "env_vars": env_vars
    }

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Multi-Model Orchestrator v2.0 — Exact Model IDs",
        epilog="""
Examples:
  python multi_model_orchestrator.py --demo "add docstrings"
  python multi_model_orchestrator.py --demo "design system" --complexity complex
  python multi_model_orchestrator.py --run "refactor code" --force-stack codex

Model Hierarchy:
  FREE: Gemini 3 Flash/Pro (1000/day)
  PAID: Codex (o3-mini → GPT-4o → GPT-5.3 → o1)
  PAID: Claude (Haiku → Sonnet → Opus)
  API: Kimi (K2 Instant → K2.5 → K2.5 256K)
        """
    )
    
    parser.add_argument("task", nargs="?", help="Task to execute")
    parser.add_argument("--complexity", choices=["trivial", "simple", "medium", "complex", "research"])
    parser.add_argument("--demo", action="store_true", default=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--force-stack", choices=["gemini", "codex", "claude", "kimi"])
    parser.add_argument("--list-models", action="store_true", help="List all available models")
    
    args = parser.parse_args()
    
    if args.list_models:
        print("\nAVAILABLE MODELS BY STACK:")
        print("=" * 75)
        for stack_key, stack in ALL_STACKS.items():
            print(f"\n{stack.name}:")
            print("-" * 75)
            for model_key, model in stack.models.items():
                print(f"  {model_key:12} → {model.name:25} ({model.model_id})")
                print(f"               Cost: {model.cost_tier:12} | Context: {model.context_window:,} tokens")
                print(f"               Best for: {', '.join(model.best_for[:3])}")
        return
    
    if not args.task:
        parser.print_help()
        return
    
    orchestrate(
        task=args.task,
        complexity_override=args.complexity,
        demo=not args.run,
        execute=args.run,
        force_stack=args.force_stack
    )

if __name__ == "__main__":
    main()

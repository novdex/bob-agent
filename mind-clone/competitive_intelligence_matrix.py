"""
COMPETITIVE INTELLIGENCE MATRIX v2 — Top Autonomous AI Agents 2026
Scores Bob (Mind Clone) against the world's top autonomous agents.
Updated: 2026-02-25
Sources: Chrome browser research, background agent research, public docs

Agents compared:
  1. Bob (Mind Clone)     — Our AGI agent (Telegram + API, 45+ tools, 8 pillars)
  2. Devin AI             — Cognition Labs' autonomous software engineer
  3. Manus AI             — Monica.im's general autonomous agent (acquired by Meta)
  4. Claude Code          — Anthropic's agentic CLI for coding
  5. OpenAI Codex         — OpenAI's cloud-based coding agent
  6. OpenAI Operator      — OpenAI's browser CUA agent
  7. Cursor AI            — AI-native IDE
  8. GitHub Copilot       — AI pair programmer
"""

from dataclasses import dataclass, field
from typing import Dict, List


# ── Scoring dimensions mapped to Bob's 8 AGI pillars + 2 practical dims ──

DIMENSIONS = {
    "reasoning":           0.14,  # Logical problem-solving, multi-step planning
    "memory":              0.12,  # Persistent context, cross-session learning
    "autonomy":            0.14,  # Independent multi-step task execution
    "learning":            0.10,  # Self-improvement, feedback loops
    "tool_mastery":        0.12,  # Breadth & depth of tool integrations
    "self_awareness":      0.08,  # Meta-cognition, confidence, limitations
    "world_understanding": 0.10,  # Real-world knowledge, web research
    "communication":       0.10,  # Multi-modal, clarity, adaptability
    "pricing":             0.05,  # Cost-effectiveness (10=free, 1=very expensive)
    "ux":                  0.05,  # User experience, onboarding, polish
}


@dataclass
class Agent:
    name: str
    category: str
    pricing: str
    scores: Dict[str, float]
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    benchmark_notes: str = ""

    @property
    def weighted_score(self) -> float:
        return sum(self.scores[d] * DIMENSIONS[d] for d in DIMENSIONS)

    @property
    def raw_average(self) -> float:
        return sum(self.scores.values()) / len(self.scores)


# ═══════════════════════════════════════════════════════════════════════════
# AGENT DATA — scored 1-10 per dimension based on research
# ═══════════════════════════════════════════════════════════════════════════

AGENTS: List[Agent] = [

    # ── 1. BOB (Mind Clone) ──────────────────────────────────────────────
    Agent(
        name="Bob (Mind Clone)",
        category="AGI Personal Agent",
        pricing="Self-hosted (free)",
        scores={
            "reasoning":           7.0,   # Kimi K2.5 is solid but not frontier
            "memory":              8.5,   # Episodic + semantic + lessons + world model
            "autonomy":            8.0,   # 30-step tool loops, task graph, async queue
            "learning":            9.0,   # Closed-loop feedback, self-tune, dead-letter
            "tool_mastery":        9.0,   # 45+ tools, 7 codebase tools, desktop, browser
            "self_awareness":      8.5,   # Self-eval (50 cases), codebase introspection
            "world_understanding": 7.5,   # Deep research, web scraping, GloVe embeddings
            "communication":       7.5,   # Telegram + API + voice (TTS/STT) + streaming
            "pricing":             10.0,  # Self-hosted, only LLM API costs
            "ux":                  6.0,   # Telegram-first, web UI basic, no IDE plugin
        },
        strengths=[
            "Self-hosted & free (only LLM API costs)",
            "45+ tools including desktop automation & browser",
            "Closed-loop feedback engine (6 learning loops)",
            "Self-tuning performance engine (4 auto-tuners)",
            "Self-eval framework (50 real benchmark cases)",
            "Voice assistant (TTS + STT)",
            "Codebase self-modification (7 tools)",
            "LLM failover chain (Kimi -> Gemini -> GPT -> Claude)",
            "Task decomposition with graph branching",
            "402 automated tests",
        ],
        weaknesses=[
            "Kimi K2.5 reasoning < Claude Opus / GPT-4o",
            "No native IDE integration",
            "Web UI needs polish",
            "Single-user focus (no team features)",
            "No sandboxed execution environment",
            "Requires technical setup",
        ],
        benchmark_notes="7-phase AGI Gauntlet: 21 tool calls, 11 types, ~4min. Self-scored 82.5%.",
    ),

    # ── 2. DEVIN AI (Cognition Labs) ─────────────────────────────────────
    Agent(
        name="Devin AI",
        category="Autonomous Software Engineer",
        pricing="$20/mo Core, $500/mo Teams",
        scores={
            "reasoning":           9.0,   # Multi-model, strong at complex coding tasks
            "memory":              7.5,   # Session memory, limited cross-session
            "autonomy":            9.5,   # Fully autonomous: plan → code → test → PR
            "learning":            7.0,   # Learns from repos but no persistent feedback
            "tool_mastery":        8.5,   # IDE, terminal, browser, Git, deployment
            "self_awareness":      7.0,   # Knows its limits, asks for clarification
            "world_understanding": 7.0,   # Web browsing for docs/research
            "communication":       7.5,   # Slack integration, PR descriptions
            "pricing":             5.0,   # $20/mo Core, but ACUs add up fast
            "ux":                  8.0,   # Polished web IDE, real-time screen view
        },
        strengths=[
            "Fully autonomous end-to-end software engineering",
            "Sandboxed VM per task (IDE + terminal + browser)",
            "Real-time screen view of agent working",
            "SWE-bench Verified: ~50% (top tier at launch)",
            "Slack/GitHub/Jira integration",
            "Multi-file, multi-step coding workflows",
            "Deploys, tests, and creates PRs autonomously",
            "Interactive Planning (Devin 2.0) -- scopes tasks before executing",
            "$10.2B valuation, enterprise-proven (Nubank: 8x efficiency)",
        ],
        weaknesses=[
            "Teams plan still $500/mo, Core is $20 but ACU costs add up",
            "Coding-only (not general-purpose)",
            "Can go in loops on complex tasks",
            "Limited cross-session memory",
            "No voice/multimodal support",
            "Closed source",
        ],
        benchmark_notes="SWE-bench Verified ~50% at launch. Devin 2.0 (Apr 2025): $20/mo Core, Interactive Planning. $10.2B valuation (Sept 2025).",
    ),

    # ── 3. MANUS AI (Monica.im / Meta) ──────────────────────────────────
    Agent(
        name="Manus AI",
        category="Autonomous General Agent",
        pricing="Credit-based (~$20-100/mo)",
        scores={
            "reasoning":           8.5,   # Multi-model orchestration (Claude + GPT-4)
            "memory":              6.5,   # No persistent cross-task memory
            "autonomy":            9.5,   # Highest: full VM, async background tasks
            "learning":            6.5,   # No learning loops, each task starts fresh
            "tool_mastery":        8.5,   # Browser, terminal, file system, code exec
            "self_awareness":      6.0,   # Limited meta-cognition
            "world_understanding": 9.0,   # Full browser, visits dozens of sites per task
            "communication":       7.5,   # Visible step-by-step plan, file delivery
            "pricing":             5.0,   # Credit system, burns fast on complex tasks
            "ux":                  8.0,   # Watch agent work in real-time, async delivery
        },
        strengths=[
            "True end-to-end task execution (research → code → deploy)",
            "Full sandboxed VM per task (Linux + browser + terminal)",
            "Asynchronous: assign task, come back later for results",
            "Delivers complete artifacts (files, websites, reports)",
            "Multi-model orchestration (picks best LLM per subtask)",
            "Real-time 'computer use' view of agent's screen",
            "General-purpose (not limited to coding)",
        ],
        weaknesses=[
            "No persistent memory across tasks",
            "Complex tasks can take 10-30+ minutes",
            "Browser automation can be brittle",
            "Credit consumption unpredictable",
            "No native API integrations (everything via browser)",
            "Limited mid-task redirection",
        ],
        benchmark_notes="GAIA benchmark leader at launch (March 2025). General-purpose agent.",
    ),

    # ── 4. CLAUDE CODE (Anthropic) ───────────────────────────────────────
    Agent(
        name="Claude Code",
        category="Agentic Coding CLI",
        pricing="$20-100/mo (API usage)",
        scores={
            "reasoning":           9.5,   # Claude Opus 4.6 = frontier reasoning
            "memory":              8.5,   # CLAUDE.md + MEMORY.md + 200K context
            "autonomy":            8.0,   # Multi-step plan-and-execute, self-correction
            "learning":            7.0,   # CLAUDE.md persists, but no feedback loops
            "tool_mastery":        9.0,   # Read/Edit/Bash/Glob/Grep + MCP extensibility
            "self_awareness":      9.0,   # Constitutional AI, explicit safety checks
            "world_understanding": 7.5,   # WebSearch/WebFetch via MCP, no native browsing
            "communication":       9.0,   # Clear, structured, great at explanation
            "pricing":             6.0,   # API usage can get expensive on large tasks
            "ux":                  7.0,   # Terminal-native, IDE extensions, but CLI-first
        },
        strengths=[
            "Frontier reasoning (Claude Opus 4.6)",
            "200K token context window",
            "MCP protocol for unlimited extensibility",
            "Agent SDK for embedding in applications",
            "Constitutional AI safety guarantees",
            "CLAUDE.md project-level persistent instructions",
            "Multi-modal (images, PDFs, notebooks)",
            "Git-native (commits, PRs, branches)",
        ],
        weaknesses=[
            "Terminal/CLI-first (not visual)",
            "No persistent feedback loops",
            "Requires user direction (not fully autonomous)",
            "API costs scale with usage",
            "No desktop/browser automation built-in",
            "Single-tool focus (coding)",
        ],
        benchmark_notes="SWE-bench top tier. Powered by Opus 4.6, best-in-class reasoning.",
    ),

    # ── 5. OPENAI CODEX ─────────────────────────────────────────────────
    Agent(
        name="OpenAI Codex",
        category="Cloud Coding Agent",
        pricing="CLI free, Web $200/mo (Pro)",
        scores={
            "reasoning":           9.0,   # GPT-5.3-Codex, strong multi-step reasoning
            "memory":              7.0,   # Session-based, GitHub repo context
            "autonomy":            8.5,   # Sandboxed parallel tasks, async execution
            "learning":            6.5,   # No persistent learning, each session fresh
            "tool_mastery":        8.0,   # Terminal + code execution in sandbox
            "self_awareness":      7.0,   # Reviews own output, but limited meta-cognition
            "world_understanding": 6.5,   # Limited to repo context, no web browsing
            "communication":       8.0,   # Clean UI, PR descriptions, terminal output
            "pricing":             5.5,   # CLI free, but web app needs $200/mo Pro
            "ux":                  8.5,   # Polished ChatGPT-integrated UI, GitHub sync
        },
        strengths=[
            "Cloud-based sandboxed Linux environment per task",
            "Multi-agent parallel task execution (N tasks simultaneously)",
            "GitHub integration (reads repos, creates PRs, worktrees)",
            "GPT-5.3-Codex model (latest)",
            "Codex CLI is open-source and FREE (github.com/openai/codex)",
            "Codex App (Feb 2026): skills, automations, modes, voice input",
            "Part of ChatGPT + GitHub Copilot ecosystem",
        ],
        weaknesses=[
            "Web app requires $200/mo ChatGPT Pro (CLI is free)",
            "Coding-only focus",
            "No persistent cross-session memory or learning loops",
            "No desktop/browser automation",
            "Requires GitHub integration for full workflow",
        ],
        benchmark_notes="Powered by GPT-5.3-Codex. SWE-bench competitive. Launched May 2025.",
    ),

    # ── 6. OPENAI OPERATOR ───────────────────────────────────────────────
    Agent(
        name="OpenAI Operator",
        category="Browser Automation Agent",
        pricing="$200/mo (ChatGPT Pro)",
        scores={
            "reasoning":           8.0,   # GPT-4o + CUA reinforcement learning
            "memory":              5.5,   # No cross-session memory, task-based only
            "autonomy":            8.5,   # Autonomous web task execution, self-correction
            "learning":            5.0,   # No learning loops, no persistence
            "tool_mastery":        7.0,   # Browser-only (no code exec, no desktop)
            "self_awareness":      7.0,   # Self-corrects on failures, asks for help
            "world_understanding": 8.5,   # Full web browsing, real-world interaction
            "communication":       7.0,   # Task status, asks for confirmation
            "pricing":             3.5,   # $200/mo ChatGPT Pro required
            "ux":                  7.5,   # Clean web UI, real-time browser view
        },
        strengths=[
            "Full browser automation (clicks, types, navigates)",
            "GPT-4o vision + CUA reinforcement learning",
            "Self-corrects when encountering errors",
            "Handles real-world web tasks (ordering, booking, forms)",
            "Hands back to user for sensitive actions (login)",
        ],
        weaknesses=[
            "Browser-only (no code, no terminal, no desktop)",
            "No persistent memory across sessions",
            "Slow for complex multi-step tasks",
            "Cannot handle authenticated sessions well",
            "Very expensive ($200/mo)",
            "Still research preview / beta",
        ],
        benchmark_notes="CUA model (Computer-Using Agent). WebVoyager/WebArena benchmarks. Launched Jan 2025.",
    ),

    # ── 7. CURSOR AI ─────────────────────────────────────────────────────
    Agent(
        name="Cursor AI",
        category="AI-Native IDE",
        pricing="$20-200/mo",
        scores={
            "reasoning":           8.0,   # Multi-model (Claude + GPT-4), strong coding
            "memory":              8.0,   # Codebase indexing, .cursorrules persistence
            "autonomy":            7.0,   # Composer mode for multi-file, but IDE-bound
            "learning":            7.5,   # Learns codebase patterns, but no feedback loops
            "tool_mastery":        8.5,   # IDE tools, terminal, multi-model, extensions
            "self_awareness":      6.5,   # Limited meta-cognition
            "world_understanding": 6.5,   # Can browse docs but not general web
            "communication":       8.0,   # Clear inline suggestions, chat panel
            "pricing":             6.5,   # $20 hobby, $40 pro, $200 business
            "ux":                  9.0,   # Best-in-class IDE UX, VSCode-based
        },
        strengths=[
            "Best IDE UX (VSCode fork, native feel)",
            "Composer mode for multi-file editing",
            "Multi-model support (Claude, GPT-4, Gemini)",
            ".cursorrules for project-level instructions",
            "Codebase-wide understanding via indexing",
        ],
        weaknesses=[
            "IDE-bound (not a standalone agent)",
            "No desktop/browser automation",
            "Limited to coding tasks",
            "No feedback loops or self-tuning",
            "Credit system can be confusing",
        ],
        benchmark_notes="75-85% accuracy on coding tasks. Popular with individual developers.",
    ),

    # ── 8. GITHUB COPILOT ────────────────────────────────────────────────
    Agent(
        name="GitHub Copilot",
        category="AI Pair Programmer",
        pricing="$10-39/mo",
        scores={
            "reasoning":           7.5,   # GPT-4o-based, decent but not frontier
            "memory":              6.5,   # File context, limited codebase awareness
            "autonomy":            6.0,   # Reactive completions, Copilot Workspace emerging
            "learning":            7.0,   # Learns from repo, but no persistent loops
            "tool_mastery":        9.0,   # Best IDE ecosystem (VS Code, JetBrains, Neovim)
            "self_awareness":      6.0,   # Limited
            "world_understanding": 5.5,   # Coding context only
            "communication":       7.0,   # Inline suggestions, chat panel
            "pricing":             8.5,   # $10-39/mo is very accessible
            "ux":                  9.0,   # Seamless IDE integration, zero friction
        },
        strengths=[
            "Unmatched IDE ecosystem coverage",
            "IP indemnity for enterprise",
            "Most affordable option",
            "Zero-friction inline completions",
            "Enterprise-grade security & compliance",
        ],
        weaknesses=[
            "Reactive only (not autonomous)",
            "Limited context window",
            "Narrow coding focus",
            "No desktop/browser/voice support",
            "No feedback loops or learning",
        ],
        benchmark_notes="Most widely adopted AI coding tool. Enterprise standard.",
    ),
]


def rank_agents() -> List[dict]:
    """Rank all agents by weighted score."""
    results = []
    for a in AGENTS:
        results.append({
            "name": a.name,
            "category": a.category,
            "pricing": a.pricing,
            "weighted": round(a.weighted_score, 3),
            "raw_avg": round(a.raw_average, 2),
            "scores": a.scores,
            "strengths": a.strengths,
            "weaknesses": a.weaknesses,
        })
    results.sort(key=lambda x: x["weighted"], reverse=True)
    return results


def dimension_leaders() -> Dict[str, List[str]]:
    """Find the leader(s) in each dimension."""
    leaders = {}
    for dim in DIMENSIONS:
        max_score = max(a.scores[dim] for a in AGENTS)
        leaders[dim] = [a.name for a in AGENTS if a.scores[dim] == max_score]
    return leaders


def bob_gap_analysis() -> List[dict]:
    """Identify Bob's gaps vs the competition."""
    bob = next(a for a in AGENTS if "Bob" in a.name)
    gaps = []
    for dim in DIMENSIONS:
        best = max(a.scores[dim] for a in AGENTS if "Bob" not in a.name)
        best_name = [a.name for a in AGENTS if a.scores[dim] == best and "Bob" not in a.name]
        diff = best - bob.scores[dim]
        if diff > 0:
            gaps.append({
                "dimension": dim,
                "bob_score": bob.scores[dim],
                "best_score": best,
                "best_agent": best_name[0],
                "gap": round(diff, 1),
            })
    gaps.sort(key=lambda x: x["gap"], reverse=True)
    return gaps


def generate_report() -> str:
    """Generate the full competitive intelligence report."""
    rankings = rank_agents()
    leaders = dimension_leaders()
    gaps = bob_gap_analysis()

    lines = []
    W = 80

    # ── Header ──
    lines.append("=" * W)
    lines.append("  COMPETITIVE INTELLIGENCE MATRIX v2")
    lines.append("  Bob (Mind Clone) vs World's Top Autonomous AI Agents")
    lines.append("  Generated: 2026-02-25")
    lines.append("=" * W)

    # ── Dimension weights ──
    lines.append("\nSCORING DIMENSIONS (weighted):")
    lines.append("-" * W)
    for dim, weight in sorted(DIMENSIONS.items(), key=lambda x: -x[1]):
        bar = "#" * int(weight * 100)
        lines.append(f"  {dim.replace('_', ' ').title():<22} {bar:<16} {weight*100:.0f}%")

    # ── Rankings ──
    lines.append("\n" + "=" * W)
    lines.append("OVERALL RANKINGS (weighted score):")
    lines.append("=" * W)
    medals = ["  1st", "  2nd", "  3rd"]
    for i, r in enumerate(rankings):
        rank = medals[i] if i < 3 else f"  {i+1}th"
        marker = " <<<" if "Bob" in r["name"] else ""
        lines.append(
            f"{rank}  {r['name']:<20} {r['weighted']:.3f}/10  "
            f"(avg {r['raw_avg']:.1f})  [{r['category']}]  {r['pricing']}{marker}"
        )

    # ── Per-dimension comparison table ──
    lines.append("\n" + "=" * W)
    lines.append("PER-DIMENSION SCORES:")
    lines.append("=" * W)

    # Header row
    names = [a.name.split(" (")[0][:10] for a in AGENTS]
    header = f"{'Dimension':<20}" + "".join(f"{n:>10}" for n in names)
    lines.append(header)
    lines.append("-" * len(header))

    for dim in DIMENSIONS:
        scores_row = ""
        for a in AGENTS:
            s = a.scores[dim]
            best_in_dim = max(x.scores[dim] for x in AGENTS)
            marker = "*" if s == best_in_dim else " "
            scores_row += f"{s:>9.1f}{marker}"
        dim_label = dim.replace("_", " ").title()
        lines.append(f"{dim_label:<20}{scores_row}")

    lines.append(f"\n  * = dimension leader")

    # ── Dimension leaders ──
    lines.append("\n" + "=" * W)
    lines.append("DIMENSION LEADERS:")
    lines.append("=" * W)
    for dim, names_list in leaders.items():
        dim_label = dim.replace("_", " ").title()
        lines.append(f"  {dim_label:<22} {', '.join(names_list)}")

    # ── Bob's gaps ──
    lines.append("\n" + "=" * W)
    lines.append("BOB'S GAPS vs COMPETITION (sorted by gap size):")
    lines.append("=" * W)
    for g in gaps:
        dim_label = g["dimension"].replace("_", " ").title()
        lines.append(
            f"  {dim_label:<22} Bob: {g['bob_score']:.1f}  "
            f"Best: {g['best_score']:.1f} ({g['best_agent']})  "
            f"Gap: -{g['gap']:.1f}"
        )

    # ── Bob's unique advantages ──
    lines.append("\n" + "=" * W)
    lines.append("BOB'S UNIQUE COMPETITIVE ADVANTAGES:")
    lines.append("=" * W)
    bob_advantages = [
        "ONLY agent with closed-loop feedback engine (6 learning loops)",
        "ONLY agent with self-tuning performance engine (4 auto-tuners)",
        "ONLY agent with built-in real eval framework (50 benchmark cases)",
        "ONLY agent that is 100% self-hosted (zero vendor lock-in)",
        "ONLY agent with LLM failover chain (4 providers)",
        "ONLY agent with codebase self-modification (7 tools)",
        "ONLY agent with integrated voice assistant (TTS + STT)",
        "ONLY agent with 45+ tools spanning ALL domains (desktop/browser/code/research)",
        "402 automated tests = highest test coverage of any personal agent",
        "FREE (self-hosted, only pay for LLM API calls)",
    ]
    for i, adv in enumerate(bob_advantages, 1):
        lines.append(f"  {i:2d}. {adv}")

    # ── Priority upgrades to close gaps ──
    lines.append("\n" + "=" * W)
    lines.append("PRIORITY UPGRADES TO CLOSE GAPS:")
    lines.append("=" * W)
    priorities = [
        ("P0: Upgrade LLM",
         "Switch primary LLM from Kimi K2.5 to Claude Sonnet 4.6 or GPT-4o",
         "reasoning +2.0, communication +1.0",
         "Closes the biggest gap (reasoning: 7.0 → 9.0)"),
        ("P1: IDE Plugin",
         "Build VS Code extension for Bob (code actions, inline suggestions)",
         "ux +2.0, tool_mastery +0.5",
         "Matches Cursor/Copilot UX, reaches developer audience"),
        ("P2: Sandboxed Execution",
         "Docker/Firecracker sandbox per task (like Devin/Manus)",
         "autonomy +1.0, self_awareness +0.5",
         "Enables safe untrusted code execution"),
        ("P3: Multi-user & Teams",
         "Add user roles, shared memory, team workspaces",
         "ux +1.0, communication +0.5",
         "Opens enterprise market"),
        ("P4: Persistent Workflows",
         "Background async tasks with checkpoint/resume",
         "autonomy +0.5, learning +0.5",
         "Matches Manus async task model"),
    ]
    for label, desc, impact, rationale in priorities:
        lines.append(f"\n  {label}")
        lines.append(f"    What: {desc}")
        lines.append(f"    Impact: {impact}")
        lines.append(f"    Why: {rationale}")

    # ── After upgrades projection ──
    lines.append("\n" + "=" * W)
    lines.append("PROJECTED RANKING AFTER P0-P2 UPGRADES:")
    lines.append("=" * W)
    projected = {
        "reasoning": 9.0, "memory": 8.5, "autonomy": 9.0, "learning": 9.0,
        "tool_mastery": 9.5, "self_awareness": 9.0, "world_understanding": 7.5,
        "communication": 8.5, "pricing": 10.0, "ux": 8.0,
    }
    proj_weighted = sum(projected[d] * DIMENSIONS[d] for d in DIMENSIONS)
    lines.append(f"  Bob (projected): {proj_weighted:.3f}/10 weighted")
    lines.append(f"  Current #1:      {rankings[0]['weighted']:.3f}/10 ({rankings[0]['name']})")
    if proj_weighted > rankings[0]["weighted"]:
        lines.append(f"  => Bob would be #1 overall!")
    else:
        lines.append(f"  => Bob would be competitive with top 3")

    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_report())

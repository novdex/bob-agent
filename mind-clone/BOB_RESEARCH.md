# BOB_RESEARCH.md - Autonomous Self-Improvement Steering
# Edit this file to steer Bob's nightly experiments.
# This is Bob's equivalent of Karpathy's program.md.

## Current Focus
Improve Bob's response quality, tool reliability, and memory recall accuracy.

## Concrete Experiment Ideas (pick one per night)

### Tier 1 — High Impact, Low Risk
1. **Improve retro analysis prompt** — retro.py `_build_retro_prompt()`: add structured sections for "tool failures", "missed follow-ups", "response quality issues". Better prompts → better self-insight.
2. **Add recall confidence scoring** — recall.py: when injecting past memories, score each by recency + importance. Only inject top-3 highest scoring. Reduces noise in context.
3. **Add hypothesis diversity check** — auto_research.py `generate_hypotheses()`: before returning hypotheses, filter out any that target the same file as the last 3 failed experiments. Forces variety.
4. **Improve prediction threshold** — prediction.py: lower auto-schedule threshold from 4x to 3x for topics. More proactive monitoring.
5. **Add retry on tool timeout** — basic.py or relevant tool: wrap tool calls with 1 automatic retry on timeout errors. Reduces transient failures.

### Tier 2 — Medium Impact
6. **Memory injection deduplication** — recall.py: deduplicate injected memories by semantic similarity (simple string overlap check). Avoids repeating same context twice.
7. **Reasoning strategy logging** — reasoning.py: log which strategy was selected per turn + outcome. After 10 turns, auto-tune selection weights.
8. **Proactive message quality gate** — proactive.py: add a simple quality check — if generated message is <50 chars or contains "error", skip sending. Prevents garbage messages.
9. **Scheduler jitter** — scheduler.py: add ±5 minute random jitter to scheduled jobs to prevent thundering herd. Smoother load.
10. **Retro insight retention** — retro.py: after retro, save top 2 insights as SelfImprovementNotes with priority=0.9. Ensures retro learnings feed back into hypothesis generation.

### Tier 3 — Lower Priority
11. **Tool performance summary** — basic.py: add `get_performance_summary` tool that returns tool success rates for last 7 days in a readable format for Bob to inspect.
12. **Memory graph auto-cleanup** — memory_graph.py: if a memory has 0 links and importance < 0.3 and is >30 days old, mark for pruning. Keeps graph clean.

## Allowed Target Files
- src/mind_clone/services/prediction.py
- src/mind_clone/services/retro.py
- src/mind_clone/services/proactive.py
- src/mind_clone/tools/basic.py
- src/mind_clone/tools/memory.py
- src/mind_clone/tools/scheduler.py
- src/mind_clone/agent/reasoning.py
- src/mind_clone/agent/recall.py
- src/mind_clone/services/auto_research.py (only for hypothesis generation improvements, NOT experiment runner)
- src/mind_clone/services/memory_graph.py

## Constraints
- Max 50 lines changed per experiment
- All tests must pass after change
- Never modify: database/models.py, config.py, api/factory.py
- Conservative mode only — small targeted improvements
- Never change function signatures or DB schema

## Metrics (composite score 0.0-1.0, higher = better)
- tool_success_rate: fraction of tool calls with ok=True in last 200 ToolPerformanceLogs
- error_rate: fraction of ExecutionEvents with event_type=error in last 100
- composite = 0.6 * tool_success_rate + 0.4 * (1.0 - error_rate)

## Schedule
- Runs nightly at 2:00 AM UTC
- Conservative mode: only small safe changes

## History Note
Bob tracks every experiment in ExperimentLog table.
Failed experiments are automatically reverted via git stash.
When score is high (>0.90), focus on quality improvements not metric-gaming.

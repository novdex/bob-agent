# BOB_RESEARCH.md - Autonomous Self-Improvement Steering
# Edit this file to steer Bob's nightly experiments.
# This is Bob's equivalent of Karpathy's program.md.

## Current Focus
Improve Bob's tool success rate and reduce errors in service layer code.

## Hypothesis Generation Instructions
When generating hypotheses, read this file first. Then:
1. Look at recent ExperimentLog entries to avoid repeating failed experiments
2. Look at SelfImprovementNotes (priority desc) for known issues
3. Look at ToolPerformanceLog for tools with low success rates
4. Propose 3 specific, testable hypotheses ranked by expected impact

## Allowed Target Files
- src/mind_clone/services/prediction.py
- src/mind_clone/services/retro.py
- src/mind_clone/services/proactive.py
- src/mind_clone/tools/basic.py
- src/mind_clone/tools/memory.py
- src/mind_clone/tools/scheduler.py
- src/mind_clone/agent/reasoning.py
- src/mind_clone/agent/recall.py

## Constraints
- Max 50 lines changed per experiment
- All tests must pass after change
- Never modify: database/models.py, config.py, api/factory.py, auto_research.py
- Conservative mode only — small targeted improvements

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

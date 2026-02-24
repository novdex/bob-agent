# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mission

This is an **AGI project** (see `../docs/VISION.md`). Every feature must serve one of the 8 intelligence pillars: Reasoning, Memory, Autonomy, Learning, Tool Mastery, Self-Awareness, World Understanding, Communication. Read `../docs/VISION.md` before making changes.

## Runtime

| Runtime | Path | Status | Entry Point |
|---------|------|--------|-------------|
| **Modular** | `src/mind_clone/` | Production | `python -m mind_clone --web` |

## Commands

```bash
# Tests (31 tests, all must pass)
cd mind-clone
pytest                              # all tests
pytest tests/unit/test_config.py    # single file
pytest -k test_health               # single test by name
pytest --cov=mind_clone             # with coverage

# Compile check
python -m compileall -q src/

# Lint
ruff check src/
mypy src/mind_clone/

# Start server
python -m mind_clone --web           # production (requires pip install -e .)
python -m mind_clone --telegram-poll # telegram polling mode

# Bob helper (PowerShell only, defined in user's PS profile)
bob start | bob stop | bob restart | bob status | bob chat | bob say "msg"
```

## Architecture

**Data flow:** User (Telegram/API) -> FastAPI -> Agent Loop -> Kimi K2.5 LLM -> Tool Execution -> Result fed back to LLM -> Response -> User

**Modular package** (`src/mind_clone/`):
- `config.py` — Pydantic Settings (80+ env vars)
- `agent/` — identity, LLM client, reasoning loop, memory
- `api/` — FastAPI factory + routes
- `core/` — state, security, budget, circuit breaker, queue, sandbox, plugins
- `database/` — 40+ SQLAlchemy models + session factory
- `tools/` — implementations, schemas, registry (TOOL_DISPATCH)
- `services/` — scheduler, task engine, telegram adapter

**Key globals** (`core/state.py`):
- `RUNTIME_STATE` — mutable dict tracking all runtime state (60+ keys)
- `TOOL_DISPATCH` — function registry mapping tool names to implementations
- `SessionLocal` — SQLAlchemy session factory
- `log` — `logging.getLogger("mind_clone")`

**LLM:** Kimi K2.5 via Moonshot AI API (OpenAI-compatible). Temperature **must be 1.0** when using tools. Failover chain: Kimi -> Gemini -> GPT -> Claude.

**Semantic search:** GloVe 6B 100d vectors (50K words, numpy-only, no native DLL deps). Used for lesson retrieval, task artifacts, episodic memory, world model.

## Key Configuration (.env)

Critical env vars (see `.env.example` for all 200+):
- `KIMI_API_KEY` — Moonshot AI key (required)
- `TOOL_POLICY_PROFILE` — safe | balanced | power
- `BOB_FULL_POWER_ENABLED` / `BOB_FULL_POWER_SCOPE` — capability elevation
- `OS_SANDBOX_MODE` — off | docker (must be `off` without Docker)
- `MIND_CLONE_DB_PATH` — SQLite path (default: `~/.mind-clone/mind_clone.db`)
- `COMMAND_QUEUE_MODE` — off | on | auto

## Worker Rules

1. Read `AGENTS.md` before making changes
2. Log all changes in `CHANGELOG.md` when done (template at bottom of file)
3. **DO NOT** modify `.env` (contains secrets)
4. **DO NOT** add pip packages without updating both `requirements.txt` and `pyproject.toml`
5. All tests must pass after changes (`pytest`)
6. General solutions over specific hacks

## Closed Loop Feedback Engine (Section 5B)

Feature-flagged with `CLOSED_LOOP_ENABLED` (default: true). Six feedback loops that make Bob adapt from experience:

| Loop | Function | What It Does |
|------|----------|-------------|
| 1+6 | `cl_filter_tools_by_performance()` | Warns/blocks/reorders tools by success rate |
| 2 | `cl_track_lesson_usage()` | Tracks if LLM references injected lessons |
| 3 | `cl_close_improvement_notes()` | Marks notes "applied" or "dismissed" based on usage |
| 4 | `cl_adjust_for_forecast_confidence()` | Adjusts task steps when forecast confidence is low |
| 5 | `cl_check_dead_letter_pattern()` | Blocks strategies that fail 3+ times in 7 days |

Runtime metrics: check `cl_*` keys in `/status/runtime` (tools_warned, tools_blocked, lessons_used, lessons_ignored, notes_applied, notes_dismissed, strategies_blocked, forecasts_adjusted, loops_closed_total).

Config vars: `CLOSED_LOOP_TOOL_WARN_THRESHOLD` (40%), `CLOSED_LOOP_TOOL_BLOCK_THRESHOLD` (15%), `CLOSED_LOOP_TOOL_MIN_CALLS` (5), `CLOSED_LOOP_LESSON_MATCH_THRESHOLD` (0.25), `CLOSED_LOOP_NOTE_MAX_RETRIEVALS` (5), `CLOSED_LOOP_DEAD_LETTER_BLOCK_COUNT` (3), `CLOSED_LOOP_FORECAST_LOW_CONFIDENCE` (30).

## Self-Tuning Performance Engine (Section 5C)

Feature-flagged with `SELF_TUNE_ENABLED` (default: true). Four auto-tuners that run every 2 heartbeat ticks (~90s):

| Tuner | Function | What It Does |
|-------|----------|-------------|
| Queue | `st_tune_queue_mode()` | Switches queue from "on" to "auto" when backlog builds |
| Session | `st_tune_session_budget()` | Raises/lowers context char budgets based on hard clear rate |
| Workers | `st_tune_workers()` | Scales queue workers up/down based on queue depth |
| Budget | `st_tune_budget_mode()` | Loosens budget governor when too many runs get degraded |

Runtime metrics: check `st_*` keys in `/status/runtime` (tunes_total, queue_mode_switches, session_budget_adjustments, worker_scale_events, budget_mode_switches, last_tune_at, current_session_soft_budget, current_session_hard_budget, current_worker_count, last_action).

Config vars: `SELF_TUNE_INTERVAL_TICKS` (2), `SELF_TUNE_QUEUE_BACKLOG_THRESHOLD` (3), `SELF_TUNE_HARD_CLEAR_RATE_THRESHOLD` (5), `SELF_TUNE_SESSION_BUDGET_STEP` (8000), `SELF_TUNE_SESSION_BUDGET_MAX` (80000), `SELF_TUNE_SESSION_BUDGET_MIN` (20000), `SELF_TUNE_WORKER_MAX` (6).

## Bob Subagents (scripts/bob_*.py)

Developer helper scripts. Use these automatically instead of doing tasks manually:

| Script | When to Use | Command |
|--------|------------|---------|
| **bob-check** | After ANY code change | `python scripts/bob_check.py` |
| **bob-find** | When navigating the codebase | `python scripts/bob_find.py <section>` |
| **bob-newtool** | When adding a new tool | `python scripts/bob_newtool.py <name> <desc>` |
| **bob-log** | At end of work session | `python scripts/bob_log.py --auto` |
| **bob-health** | Check if Bob is running | `python scripts/bob_health.py` |
| **bob-diag** | Diagnose performance issues | `python scripts/bob_diag.py` |
| **bob-security** | Security audit (8 checks) | `python scripts/bob_security.py` |
| **bob-test-live** | Live end-to-end tests | `python scripts/bob_test_live.py` |
| **bob-memory** | Inspect memory systems | `python scripts/bob_memory.py stats` |
| **bob-api** | Test API endpoints | `python scripts/bob_api.py` |
| **bob-bench** | Measure performance | `python scripts/bob_bench.py latency` |
| **bob-telegram** | Debug Telegram integration | `python scripts/bob_telegram.py status` |
| **bob-tasks** | Inspect task engine | `python scripts/bob_tasks.py list` |
| **bob-llm** | Debug LLM failover chain | `python scripts/bob_llm.py status` |
| **bob-db** | Database inspector | `python scripts/bob_db.py tables` |
| **bob-queue** | Queue diagnostics | `python scripts/bob_queue.py status` |
| **bob-cron** | Scheduler diagnostics | `python scripts/bob_cron.py status` |
| **bob-tools** | Tool usage diagnostics | `python scripts/bob_tools.py list` |
| **bob-identity** | User/identity diagnostics | `python scripts/bob_identity.py users` |

## Known Gotchas

- **Python 3.14 on Windows:** `onnxruntime`, `torch`, `fastembed` all fail with DLL errors. GloVe+numpy is the solution.
- **Proxy env vars** break DuckDuckGo searches — uses `without_proxy_env()` context manager.
- **Port 8000 conflicts:** Kill existing python.exe before starting server.
- **Circuit breaker cascades:** Failed tasks can trip the circuit breaker and block chat. Check `/status/runtime` for breaker state.
- **Task graph branching:** Max depth is 3 (`_b` suffix count in step_id). Without this limit, recovery chains go infinite.
- **Short messages in chat:** Task artifact retrieval requires 3+ query terms to avoid injecting irrelevant context.

## Frontend (mind-clone-ui/)

React 18 + TypeScript + Vite. Base path: `/ui/`. Dev server: port 5173.
```bash
cd mind-clone-ui
npm install && npm run dev     # development
npm run build                  # production build
```

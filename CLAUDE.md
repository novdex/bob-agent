# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mission

This is an **AGI project**. Every feature must serve one of the 8 intelligence pillars: Reasoning, Memory, Autonomy, Learning, Tool Mastery, Self-Awareness, World Understanding, Communication. Read `docs/VISION.md` and `docs/AGENTS.md` before making changes.

## Project Structure

```
ai-agent-platform/
├── mind-clone/                # Backend (the Bob agent)
│   ├── mind_clone_agent.py    # Monolith — 24K lines, PRODUCTION
│   ├── src/mind_clone/        # Modular package — migration target
│   ├── scripts/               # bob-* developer tools
│   ├── tests/                 # Unit + integration tests
│   ├── persist/               # Runtime data (gitignored)
│   ├── CHANGELOG.md
│   ├── CLAUDE.md              # Mind-clone specific guidance
│   └── pyproject.toml
├── mind-clone-ui/             # Frontend (React 18 + TypeScript + Vite)
│   ├── src/
│   └── dist/
├── docs/                      # All project documentation
│   ├── VISION.md              # AGI manifesto & 8 pillars
│   ├── AGENTS.md              # Worker rules & protocols
│   ├── API.md                 # API reference
│   ├── DEPLOYMENT.md          # Deployment guide
│   ├── extraction/            # Monolith extraction docs
│   └── refactor/              # Refactoring docs
├── .github/workflows/         # CI/CD pipelines
├── CLAUDE.md                  # This file
├── README.md
├── pyproject.toml             # Root package config
├── Dockerfile
├── docker-compose.yml
└── .gitignore
```

## Two Runtimes (Both Must Stay Functional)

| Runtime | Path | Status | Entry Point |
|---------|------|--------|-------------|
| **Monolith** | `mind-clone/mind_clone_agent.py` (~24K lines) | Production (live traffic) | `python mind_clone_agent.py` |
| **Modular** | `mind-clone/src/mind_clone/` | Development/migration target | `python -m mind_clone --web` |

Prefer changes to the modular package over the monolith.

## Commands

```bash
# Tests (all must pass)
cd mind-clone
pytest                              # all tests
pytest tests/unit/test_config.py    # single file
pytest -k test_health               # single test by name

# Compile check
python -m compileall -q mind-clone/src/

# Start servers
cd mind-clone
python mind_clone_agent.py           # monolith (production, port 8000)
python -m mind_clone --web           # modular (requires pip install -e . from root)

# Frontend
cd mind-clone-ui
npm install && npm run dev           # dev server on port 5173
npm run build                        # production build -> dist/

# Docker
docker-compose up -d mind-clone                     # production
docker-compose --profile dev up -d mind-clone-dev   # dev with hot reload

# Bob helper (PowerShell only)
bob start | bob stop | bob restart | bob status | bob chat | bob say "msg"
```

## Architecture

**Data flow:** User (Telegram/API) -> FastAPI (port 8000) -> Agent Loop -> Kimi K2.5 LLM -> Tool Execution -> Result fed back to LLM -> Response -> User

**Monolith claude --version
sections** (approximate line ranges in `mind-clone/mind_clone_agent.py`):
- 1-933: Imports, env vars, constants, RUNTIME_STATE, policy packs
- 934-1599: GloVe word vectors (semantic search engine)
- 1600-2699: Database models (70+ SQLAlchemy tables)
- 2700-8155: Tool implementations (38+ tools) + browser tools
- 8156-9116: Tool registry (TOOL_DEFINITIONS + TOOL_DISPATCH)
- 9117-12378: Pillar systems (memory, learning, autonomy, performance)
- 12379-14160: Identity, authority, conversation memory
- 14161-15100: Section 5B: Closed Loop Feedback Engine
- 15101-15800: LLM client (failover chain, circuit breakers) + agent loop
- 15801-17600: Task engine (planning, graph, branching, checkpoints)
- 17601-20000: User management + Telegram adapter
- 20001-23200: FastAPI application (routes, middleware, lifespan, entry point)

**Modular package** (`mind-clone/src/mind_clone/`):
- `config.py` — Pydantic Settings (80+ env vars)
- `agent/` — identity, LLM client, reasoning loop, memory
- `api/` — FastAPI factory + route modules
- `core/` — state, security, budget, circuit breaker, queue, sandbox, plugins
- `database/` — 40+ SQLAlchemy models + session factory
- `tools/` — implementations, schemas, registry
- `services/` — scheduler, task engine, telegram adapter

**Key globals** (monolith, or `core/state.py` in modular):
- `RUNTIME_STATE` — mutable dict tracking all runtime state (60+ keys)
- `TOOL_DISPATCH` — function registry mapping tool names to implementations
- `SessionLocal` — SQLAlchemy session factory
- `log` — `logging.getLogger("mind_clone")`

**Frontend** (`mind-clone-ui/`): React 18 + TypeScript + Vite. Base path: `/ui/`.

## LLM & Embeddings

- **LLM:** Kimi K2.5 via Moonshot AI API (OpenAI-compatible). Temperature **must be 1.0** when using tools. Failover chain: Kimi -> Gemini -> GPT -> Claude.
- **Semantic search:** GloVe 6B 100d vectors (50K words, numpy-only). Used for lesson retrieval, task artifacts, episodic memory, world model.

## Key Configuration (.env in mind-clone/)

Critical env vars (see `.env.example` for all 200+):
- `KIMI_API_KEY` — Moonshot AI key (required)
- `TOOL_POLICY_PROFILE` — safe | balanced | power
- `BOB_FULL_POWER_ENABLED` / `BOB_FULL_POWER_SCOPE` — capability elevation
- `OS_SANDBOX_MODE` — off | docker (must be `off` without Docker)
- `MIND_CLONE_DB_PATH` — SQLite path (default: `~/.mind-clone/mind_clone.db`)
- `CLOSED_LOOP_ENABLED` — true | false (feedback loop engine)

## Closed Loop Feedback Engine (Section 5B)

Feature-flagged with `CLOSED_LOOP_ENABLED` (default: true). Six feedback loops that make Bob adapt from experience:

| Loop | Function | What It Does |
|------|----------|-------------|
| 1+6 | `cl_filter_tools_by_performance()` | Warns/blocks/reorders tools by success rate |
| 2 | `cl_track_lesson_usage()` | Tracks if LLM references injected lessons |
| 3 | `cl_close_improvement_notes()` | Marks notes "applied" or "dismissed" based on usage |
| 4 | `cl_adjust_for_forecast_confidence()` | Adjusts task steps when forecast confidence is low |
| 5 | `cl_check_dead_letter_pattern()` | Blocks strategies that fail 3+ times in 7 days |

Runtime metrics: check `cl_*` keys in `/status/runtime`.

## Self-Tuning Performance Engine (Section 5C)

Feature-flagged with `SELF_TUNE_ENABLED` (default: true). Four auto-tuners run every ~90s via heartbeat:

| Tuner | Function | What It Does |
|-------|----------|-------------|
| Queue | `st_tune_queue_mode()` | Switches queue "on" to "auto" when backlog builds |
| Session | `st_tune_session_budget()` | Raises/lowers context char budgets based on hard clear rate |
| Workers | `st_tune_workers()` | Scales queue workers up/down based on queue depth |
| Budget | `st_tune_budget_mode()` | Loosens budget governor when too many runs degraded |

Runtime metrics: check `st_*` keys in `/status/runtime`.

## Bob Subagents (mind-clone/scripts/bob_*.py)

Developer helper scripts. Claude Code should use these automatically:

| Script | When to Use | Command |
|--------|------------|---------|
| **bob-check** | After ANY code change | `python mind-clone/scripts/bob_check.py` |
| **bob-find** | When navigating the monolith | `python mind-clone/scripts/bob_find.py <section>` |
| **bob-sync** | When changing something in both runtimes | `python mind-clone/scripts/bob_sync.py` |
| **bob-newtool** | When adding a new tool | `python mind-clone/scripts/bob_newtool.py <name> <desc> --params ...` |
| **bob-log** | At end of work session | `python mind-clone/scripts/bob_log.py --auto` |
| **bob-health** | When checking if Bob is running | `python mind-clone/scripts/bob_health.py` |
| **bob-diag** | When diagnosing performance | `python mind-clone/scripts/bob_diag.py` |
| **bob-security** | Before/after security changes | `python mind-clone/scripts/bob_security.py` |
| **bob-test-live** | When testing Bob live end-to-end | `python mind-clone/scripts/bob_test_live.py` |
| **bob-memory** | When inspecting memory systems | `python mind-clone/scripts/bob_memory.py stats` |
| **bob-api** | When testing API endpoints | `python mind-clone/scripts/bob_api.py` |
| **bob-migrate** | When syncing monolith to modular | `python mind-clone/scripts/bob_migrate.py all` |
| **bob-bench** | When measuring performance | `python mind-clone/scripts/bob_bench.py latency` |
| **bob-telegram** | When debugging Telegram integration | `python mind-clone/scripts/bob_telegram.py status` |
| **bob-tasks** | When inspecting task engine | `python mind-clone/scripts/bob_tasks.py list` |
| **bob-llm** | When debugging LLM failover chain | `python mind-clone/scripts/bob_llm.py status` |
| **bob-db** | When inspecting database | `python mind-clone/scripts/bob_db.py tables` |
| **bob-queue** | When debugging command queue | `python mind-clone/scripts/bob_queue.py status` |
| **bob-cron** | When debugging scheduler/heartbeat | `python mind-clone/scripts/bob_cron.py status` |
| **bob-tools** | When checking tool usage/policies | `python mind-clone/scripts/bob_tools.py list` |
| **bob-identity** | When debugging users/approvals | `python mind-clone/scripts/bob_identity.py users` |

## Worker Rules

1. Read `docs/AGENTS.md` before making changes
2. Log all changes in `mind-clone/CHANGELOG.md` when done
3. **DO NOT** modify `.env` (contains secrets)
4. **DO NOT** delete `mind_clone_agent.py` (still production)
5. **DO NOT** add pip packages without updating both `mind-clone/requirements.txt` and root `pyproject.toml`
6. All tests must pass after changes (`pytest`)
7. General solutions over specific hacks

## Known Gotchas

- **Python 3.14 on Windows:** `onnxruntime`, `torch`, `fastembed` all fail with DLL errors. GloVe+numpy is the solution.
- **Proxy env vars** break DuckDuckGo searches — monolith uses `without_proxy_env()` context manager.
- **Port 8000 conflicts:** Kill existing python.exe before starting server.
- **Circuit breaker cascades:** Failed tasks can trip the circuit breaker and block chat. Check `/status/runtime`.
- **Task graph branching:** Max depth is 3 (`_b` suffix count in step_id).
- **Short messages in chat:** Task artifact retrieval requires 3+ query terms.
- **Windows paths:** Use raw strings (`r'c:\...'`) in Python. Git Bash uses forward slashes.

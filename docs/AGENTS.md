# AGENTS.md — AI Agent Platform

> **This is an AGI project.** Read this file completely before making any changes.
> Every feature should push toward general intelligence.

## Project Overview

This is a **multi-component AI Agent Platform** centered around the "Mind Clone Agent" — a sovereign AI agent that can reason, learn, act autonomously, and generalize across domains.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT PLATFORM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐  │
│  │   mind-clone    │◄──►│  mind-clone-ui  │    │   Multi-Model           │  │
│  │   (Agent Core)  │    │  (Ops Console)  │    │   Orchestrator          │  │
│  │                 │    │                 │    │   (Cost Router)         │  │
│  │ • Kimi K2.5     │    │ • React + Vite  │    │                         │  │
│  │ • FastAPI       │    │ • TypeScript    │    │ • Gemini (FREE)         │  │
│  │ • SQLite        │    │ • 7 Panels      │    │ • Codex (OpenAI)        │  │
│  │ • 25+ Tools     │    │                 │    │ • Claude (Anthropic)    │  │
│  │ • Telegram Bot  │    │ • Runtime       │    │ • Kimi (Moonshot)       │  │
│  │                 │    │ • Chat          │    │                         │  │
│  │                 │    │ • Tasks         │    │                         │  │
│  │                 │    │ • Approvals     │    │                         │  │
│  └────────┬────────┘    └─────────────────┘    └─────────────────────────┘  │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         EXTERNAL SERVICES                            │   │
│  │  • Moonshot AI API (Kimi K2.5)  • Telegram Bot API                   │   │
│  │  • DuckDuckGo Search            • Gmail SMTP                         │   │
│  │  • GloVe Embeddings (local)     • Selenium/WebDriver                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. mind-clone/ — The Agent Core

**Primary file:** `mind_clone_agent.py` (single-file architecture)

A sovereign AI agent with the following capabilities:

| Pillar | Status | Implementation |
|--------|--------|----------------|
| Reasoning | ✅ Foundation | Agent loop with iterative tool use, in-loop reflection |
| Memory | ✅ Growing | Conversation history + GloVe vector embeddings + episodic memory |
| Autonomy | ✅ Growing | Task engine with planning, execution, goal management |
| Learning | ✅ Growing | Research memory, lesson extraction, self-improvement notes |
| Tool Mastery | ✅ Solid | 25+ tools (files, shell, web, code, desktop, browser, email) |
| Self-Awareness | ✅ Basic | Identity kernel, tool performance tracking |
| World Understanding | ✅ Growing | Action forecasting, environment state capture |
| Communication | ✅ Working | Telegram, email (SMTP), REST API, progress reporting |

**Tech Stack:**
- Python 3.14+
- FastAPI + Uvicorn (ASGI server)
- SQLAlchemy 2.0 + SQLite (database)
- Kimi K2.5 via Moonshot AI API
- python-telegram-bot (webhook-based)
- PyAutoGUI + MSS (desktop automation)
- Selenium (browser automation)
- GloVe 100d vectors (semantic search)

**Tools Available:**
```
Web & Research:      search_web, read_webpage, deep_research, read_pdf_url
File Operations:     read_file, write_file, list_directory
Code Execution:      execute_python, run_command
Memory:              save_research_note, research_memory_search, semantic_memory_search
Communication:       send_email
Desktop Control:     desktop_*, screenshot, click, type, hotkey, etc.
Browser Automation:  browser_open, browser_click, browser_type, browser_screenshot
Task Management:     schedule_job, list_scheduled_jobs, disable_scheduled_job
Remote Execution:    list_execution_nodes, run_command_node
```

**Key Sections in mind_clone_agent.py:**
- SECTION 1: Database Models (User, IdentityKernel, ConversationMessage, Task, Goal, etc.)
- SECTION 2: Tool Implementations (all tool functions)
- SECTION 3: Tool Registry (TOOL_DEFINITIONS + TOOL_DISPATCH)
- SECTION 4: Identity Loader
- SECTION 5: Authority Bounds Checker
- SECTION 6: Conversation Memory
- SECTION 7: LLM Client (Kimi K2.5 API with failover)
- SECTION 8: Agent Loop (the main reasoning loop)
- SECTION 9: User/Identity Management
- SECTION 10: Telegram Adapter
- SECTION 11: FastAPI Application
- SECTION 12: Entry Point

### 2. mind-clone-ui/ — Ops Console UI

**Tech Stack:**
- React 18.3 + TypeScript 5.6
- Vite 5.4 (build tool)
- No external UI libraries (pure CSS)

**Panels:**
1. **Runtime** — Health metrics polled every 5s
2. **Chat** — Direct message interface
3. **Tasks** — Create, inspect, cancel graph tasks
4. **Approvals** — Approve/reject pending tool actions
5. **Cron** — Scheduled job management
6. **Blackbox** — Session diagnostics and traces
7. **Nodes/Plugins** — Execution nodes and dynamic tools

**Build Commands:**
```bash
cd mind-clone-ui
npm install
npm run build    # Outputs to dist/
npm run preview  # Preview production build
```

The built UI is served by FastAPI at `http://localhost:8000/ui`

### 3. Orchestrators — Model Router & Cost Optimization

**ai_orchestrator.py** — First-principles task router
- Routes to Gemini (FREE) → Codex → Claude → Kimi (fallback)
- SQLite usage tracking
- Task complexity analysis

**multi_model_orchestrator.py** — Advanced multi-model orchestrator v2.0
- Exact model ID configurations for all stacks
- Stack priority: Gemini (1000/day FREE) → Codex → Claude → Kimi
- Model selection by task complexity (trivial → research)
- Usage logging to SQLite

**Usage:**
```bash
# Demo mode (show what would be selected)
python multi_model_orchestrator.py --demo "your task"

# Execute with selected model
python multi_model_orchestrator.py --run "your task"

# Force specific stack
python multi_model_orchestrator.py --demo "task" --force-stack claude

# Override complexity
python multi_model_orchestrator.py --demo "task" --complexity complex

# List all available models
python multi_model_orchestrator.py --list-models
```

## Directory Structure

```
C:\Users\mader\OneDrive\Desktop\ai-agent-platform\
│
├── mind-clone/                    # Main agent implementation
│   ├── mind_clone_agent.py        # ← ALL agent code (single file)
│   ├── requirements.txt           # Python dependencies
│   ├── .env                       # Secrets (DO NOT TOUCH)
│   ├── .env.example               # Template for env vars
│   ├── README.md                  # User-facing docs
│   ├── AGENTS.md                  # AI worker instructions
│   ├── CHANGELOG.md               # Work log
│   ├── VISION.md                  # AGI mission statement
│   ├── CLAUDE.md                  # Claude Code instructions
│   ├── EXACT_MODEL_REFERENCE.md   # Model ID reference
│   ├── MODEL_HIERARCHY.md         # Selection strategy
│   ├── data/                      # SQLite databases
│   ├── persist/                   # Persistent storage
│   │   ├── workspaces/            # Per-owner workspace isolation
│   │   ├── team_workspaces/       # Team-mode workspaces
│   │   ├── memory_vault/          # Git-backed memory export
│   │   └── desktop/               # Screenshots & sessions
│   ├── scripts/                   # Utility scripts
│   │   ├── release_gate_check.py  # CI validation
│   │   └── hardening_s1_checks.py # Security checks
│   └── plugins/                   # Dynamic tool plugins
│
├── mind-clone-ui/                 # React frontend
│   ├── src/
│   │   ├── App.tsx                # Main application
│   │   ├── main.tsx               # Entry point
│   │   ├── types.ts               # TypeScript types
│   │   ├── api/client.ts          # API client
│   │   └── styles.css             # Styles
│   ├── package.json
│   ├── tsconfig.json
│   └── dist/                      # Build output
│
├── ai_orchestrator.py             # Basic model router
├── multi_model_orchestrator.py    # Advanced orchestrator v2
├── ai_orchestrator.db             # Usage tracking DB
├── ai_orchestrator_v2.db          # v2 usage tracking DB
│
├── EXACT_MODEL_REFERENCE.md       # Model ID reference
├── MODEL_HIERARCHY.md             # Selection strategy
│
└── .github/
    └── workflows/
        └── eval-gate.yml          # CI/CD pipeline
```

## Build and Run Commands

### Backend (mind-clone)

```bash
# Setup
cd mind-clone
pip install -r requirements.txt

# Configure
copy .env.example .env
# Edit .env with your API keys

# Run
cd mind-clone
python mind_clone_agent.py
# Server starts at http://localhost:8000

# Expose with ngrok (for Telegram webhooks)
ngrok http 8000
# Copy HTTPS URL to .env as WEBHOOK_BASE_URL
```

Note (Windows convenience on this machine):
- A PowerShell profile defines a `bob` helper command. Run `bob` for help; typical: `bob start`, `bob bg`, `bob chat`, `bob stop`.
- For multi-line paste behavior and deterministic tool path handling, see `mind-clone/AGENTS.md` -> "Recent Operational Changes (2026-02-18)".

### Frontend (mind-clone-ui)

```bash
cd mind-clone-ui
npm install
npm run build
# Access at http://localhost:8000/ui (served by backend)
```

### Orchestrator

```bash
# Demo mode
python multi_model_orchestrator.py --demo "add docstrings"

# Execute mode
python multi_model_orchestrator.py --run "refactor code"

# Check usage stats
python multi_model_orchestrator.py --stats
```

## Environment Configuration

Key environment variables (see `.env.example` for full list):

```bash
# Required APIs
KIMI_API_KEY=your_moonshot_key
TELEGRAM_BOT_TOKEN=your_bot_token
WEBHOOK_BASE_URL=https://your-domain.com

# Email (Gmail)
SMTP_HOST=smtp.gmail.com
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Policy & Autonomy
POLICY_PACK=dev                    # dev | staging | prod
AUTONOMY_MODE=openclaw_max         # openclaw_max | standard
APPROVAL_GATE_MODE=off             # off | balanced | strict

# Budget Governor
BUDGET_GOVERNOR_ENABLED=true
BUDGET_MAX_SECONDS=180
BUDGET_MAX_TOOL_CALLS=40

# Desktop Control
DESKTOP_CONTROL_ENABLED=true
DESKTOP_FAILSAFE_ENABLED=false

# Feature Flags
WORKFLOW_V2_ENABLED=true
CRON_ENABLED=true
EVAL_HARNESS_ENABLED=true
```

## Code Style Guidelines

### Python (mind_clone_agent.py)

1. **Single-file architecture** — Keep all code in `mind_clone_agent.py`
2. **Section organization** — Follow the existing section comments
3. **Type hints** — Use for function signatures where practical
4. **Error handling** — Use try/except with specific exceptions
5. **Logging** — Use `log = logging.getLogger("mind_clone")`
6. **Database** — Use SQLAlchemy 2.0 style (declarative mapping)
7. **Async/await** — FastAPI endpoints are async; tools may be sync

### TypeScript/React (mind-clone-ui)

1. **Functional components** with hooks
2. **Type safety** — All props and state typed
3. **CSS classes** — Use the existing CSS variable system
4. **Error boundaries** — Wrap panels in PanelErrorBoundary
5. **API calls** — Use the apiGet/apiPost helpers from api/client.ts

## Testing Strategy

### Release Gate (CI/CD)

The GitHub Actions workflow (`.github/workflows/eval-gate.yml`) runs:

1. Python compilation check: `python -m py_compile mind_clone_agent.py`
2. Release gate evaluation: `python scripts/release_gate_check.py`

### Local Validation

```bash
# Compile check
cd mind-clone
python -m py_compile mind_clone_agent.py

# Run release gate
python scripts/release_gate_check.py

# Test API endpoints
curl http://localhost:8000/status/runtime
```

### Eval Harness

The agent has a built-in continuous evaluation system:
- Configurable via `EVAL_HARNESS_ENABLED`
- Runs test cases automatically
- Gates releases based on pass rate (`RELEASE_GATE_MIN_PASS_RATE`)

## Security Considerations

1. **Secrets** — Never commit `.env` files
2. **Approval Gates** — Sensitive tools require approval in non-dev modes
3. **Sandboxing** — Code execution can be Docker-isolated (`OS_SANDBOX_MODE`)
4. **SSRF Guard** — Outbound URL fetches are validated
5. **Secret Redaction** — API keys are redacted from logs
6. **Workspace Isolation** — Per-owner workspace boundaries
7. **Host Execution Interlock** — Additional allowlist for shell commands

## Rules for AI Workers

1. **Read VISION.md first** — Understand the AGI mission
2. **Read this file** — Understand the architecture
3. **Read CHANGELOG.md** — See what previous workers did
4. **Log your changes** — Update CHANGELOG.md when done
5. **DO NOT modify `.env`** — Contains secrets
6. **DO NOT split files** — Keep agent code in single file unless told otherwise
7. **Test before committing** — Run compile checks
8. **Document reasoning** — Explain WHY, not just WHAT

## Adding New Features

### Adding a New Tool to mind_clone_agent.py

1. **Implement** the function in SECTION 2 (Tool Implementations)
2. **Add schema** in SECTION 3 (TOOL_DEFINITIONS list)
3. **Add dispatch** in SECTION 3 (TOOL_DISPATCH dict)
4. **Update tool sets** — Add to ALL_TOOL_NAMES, SAFE_TOOL_NAMES if applicable
5. **Update .env.example** — Document any new env vars
6. **Test** — Verify the tool works via Telegram or API

### Adding a New Panel to mind-clone-ui

1. **Add type** to `PanelKey` union in App.tsx
2. **Add panel def** to `PANELS` array
3. **Create component** (e.g., `NewPanel`)
4. **Add route** in the switch statement
5. **Test** — Verify UI renders without errors

## Troubleshooting

### Common Issues

**Agent not responding to Telegram:**
- Check `WEBHOOK_BASE_URL` matches ngrok URL
- Verify `TELEGRAM_BOT_TOKEN`
- Check server logs: `server.err.log`

**UI not loading:**
- Ensure `npm run build` completed successfully
- Check dist/ folder exists with index.html
- Access via `http://localhost:8000/ui`

**Database issues:**
- Check `MIND_CLONE_DB_PATH` in .env
- Ensure directory exists and is writable
- Default: `%LOCALAPPDATA%/mind-clone/mind_clone.db`

**Model routing failures:**
- Check API keys in .env
- Verify `LLM_FAILOVER_ENABLED=true`
- Check circuit breaker status in runtime

## Contact & Resources

- **Moonshot AI API:** https://platform.moonshot.cn
- **Telegram Bot API:** https://core.telegram.org/bots/api
- **FastAPI Docs:** https://fastapi.tiangolo.com
- **SQLAlchemy Docs:** https://docs.sqlalchemy.org

---

*Last updated: 2026-02-10*
*AGI is the goal. Every commit should make the system more generally intelligent.*

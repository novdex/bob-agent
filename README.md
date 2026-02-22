# AI Agent Platform

A multi-component AI Agent Platform centered around **Mind Clone Agent (Bob)** — a sovereign AI agent that can reason, learn, act autonomously, and generalize across domains. Built on 8 intelligence pillars toward AGI.

## Architecture

```
User (Telegram / API) --> FastAPI (:8000) --> Agent Loop --> Kimi K2.5 LLM --> Tool Execution --> Response
                                                            |  failover: Gemini -> GPT -> Claude
                                                            v
                                              SQLite + GloVe Semantic Memory
```

**Three components:**

| Component | Tech | Purpose |
|-----------|------|---------|
| **mind-clone/** | Python, FastAPI, SQLAlchemy | Agent core (reasoning, tools, memory, tasks) |
| **mind-clone-ui/** | React 18, TypeScript, Vite | Ops console (runtime, chat, tasks, approvals) |
| **docs/** | Markdown | Vision, API reference, deployment guide |

## Project Structure

```
ai-agent-platform/
├── .github/workflows/         # CI/CD (lint, test, security, build, release)
├── docs/
│   ├── AGENTS.md              # Worker rules & protocols
│   ├── API.md                 # API endpoint reference
│   ├── DEPLOYMENT.md          # Production deployment guide
│   ├── VISION.md              # AGI manifesto & 8 pillars
│   └── archive/               # Historical documentation
├── mind-clone/
│   ├── mind_clone_agent.py    # Production monolith (~25K lines)
│   ├── src/mind_clone/        # Modular package (migration target)
│   ├── scripts/               # 21+ bob-* developer tools
│   ├── tests/                 # Unit + integration tests
│   ├── persist/               # Runtime data (gitignored)
│   ├── pyproject.toml
│   └── requirements.txt
├── mind-clone-ui/
│   ├── src/                   # React TypeScript source
│   ├── package.json
│   └── vite.config.ts
├── pyproject.toml             # Root package config
├── Dockerfile
├── docker-compose.yml
└── CLAUDE.md                  # AI assistant guidance
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)

### Setup

```bash
# Install backend dependencies
cd mind-clone
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys (KIMI_API_KEY required)

# Start the agent (production monolith)
python mind_clone_agent.py
# Server: http://localhost:8000
# UI: http://localhost:8000/ui

# Or use the modular package
cd ..
pip install -e .
python -m mind_clone --web
```

### Frontend Development

```bash
cd mind-clone-ui
npm install
npm run dev          # Dev server on http://localhost:5173
npm run build        # Production build -> dist/
```

### Docker

```bash
docker-compose up -d mind-clone                     # Production
docker-compose --profile dev up -d mind-clone-dev   # Dev with hot reload
```

## Configuration

Create `mind-clone/.env` from `.env.example`. Key variables:

```bash
KIMI_API_KEY=your_moonshot_key         # Required: Moonshot AI API key
TELEGRAM_BOT_TOKEN=your_bot_token      # Required for Telegram
TOOL_POLICY_PROFILE=balanced           # safe | balanced | power
AUTONOMY_MODE=openclaw_max             # openclaw_max | standard
```

See `.env.example` for all 200+ configuration options.

## Testing

```bash
cd mind-clone
pytest                              # All tests
pytest tests/unit/test_config.py    # Single file
pytest -k test_health               # By name
python scripts/bob_check.py         # Full compile + test + lint check
```

## Developer Tools

21 `bob-*` scripts in `mind-clone/scripts/` for common tasks:

| Script | Purpose |
|--------|---------|
| `bob_check.py` | Run after ANY code change (compile + test + lint) |
| `bob_find.py` | Navigate monolith sections |
| `bob_health.py` | Check if Bob is running |
| `bob_diag.py` | Diagnose performance issues |
| `bob_memory.py` | Inspect memory systems |
| `bob_tools.py` | Check tool usage and policies |

## Documentation

- [Vision & 8 Pillars](docs/VISION.md)
- [Worker Rules](docs/AGENTS.md)
- [API Reference](docs/API.md)
- [Deployment Guide](docs/DEPLOYMENT.md)

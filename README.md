# AI Agent Platform

A multi-component AI Agent Platform centered around the "Mind Clone Agent" — a sovereign AI agent that can reason, learn, act autonomously, and generalize across domains.

## 🏗️ Architecture

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

## 📁 Project Structure

```
ai-agent-platform/
├── pyproject.toml              # Python packaging configuration
├── Dockerfile                  # Container image definition
├── docker-compose.yml          # Full stack orchestration
├── README.md                   # This file
│
├── src/
│   ├── mind_clone/             # Main agent package
│   │   ├── __init__.py
│   │   ├── __main__.py         # CLI entry point
│   │   ├── config.py           # Settings & environment
│   │   ├── database/
│   │   │   ├── models.py       # 40+ SQLAlchemy models
│   │   │   └── session.py      # DB connection
│   │   ├── agent/
│   │   │   ├── llm.py          # Kimi API client
│   │   │   ├── memory.py       # Conversation & vectors
│   │   │   ├── identity.py     # Identity kernel
│   │   │   └── loop.py         # Main agent loop
│   │   ├── tools/
│   │   │   ├── schemas.py      # Tool definitions
│   │   │   ├── registry.py     # Tool dispatch
│   │   │   ├── files.py        # File operations
│   │   │   ├── web.py          # Web search/scrape
│   │   │   ├── code.py         # Code execution
│   │   │   └── email.py        # SMTP tools
│   │   └── api/
│   │       ├── app.py          # FastAPI factory
│   │       └── routes/         # API endpoints
│   │
│   └── orchestrators/          # Multi-model router
│       ├── models.py           # Model configurations
│       └── router.py           # Task routing logic
│
├── mind-clone-ui/              # React frontend
│   ├── src/
│   ├── package.json
│   └── dist/                   # Built assets
│
├── tests/                      # Test suite
│   ├── unit/
│   └── integration/
│
└── .github/workflows/          # CI/CD
    └── ci.yml
```

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ai-agent-platform.git
cd ai-agent-platform

# Install dependencies
pip install -e ".[dev]"

# Or with Docker
docker-compose up -d
```

### Configuration

Create a `.env` file:

```bash
# Required
KIMI_API_KEY=your_moonshot_key
TELEGRAM_BOT_TOKEN=your_bot_token
WEBHOOK_BASE_URL=https://your-domain.com

# Optional
POLICY_PACK=dev                    # dev | staging | prod
AUTONOMY_MODE=openclaw_max         # openclaw_max | standard
APPROVAL_GATE_MODE=off             # off | balanced | strict
```

### Running

```bash
# Initialize database
python -m mind_clone --init-db

# Run the server
python -m mind_clone

# Or with auto-reload (development)
python -m mind_clone --reload
```

### Using Docker

```bash
# Production
docker-compose up -d mind-clone

# Development with hot reload
docker-compose --profile dev up -d mind-clone-dev
```

## 🔧 API Usage

### Chat Endpoint

```bash
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, agent!", "owner_id": 1}'
```

### Tool Execution

```bash
curl -X POST http://localhost:8000/api/v1/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "search_web",
    "arguments": {"query": "Python best practices"}
  }'
```

### Health Check

```bash
curl http://localhost:8000/health
```

## 🧪 Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=mind_clone --cov-report=html

# Specific test file
pytest tests/unit/test_tools.py -v
```

## 🐝 Multi-Model Orchestrator

Route tasks to the optimal AI model:

```bash
# Demo mode (shows what would be selected)
python -m orchestrators "add docstrings to functions"

# Force specific stack
python -m orchestrators "refactor code" --force-stack codex

# Specify complexity
python -m orchestrators "design system" --complexity complex
```

## 📝 Development

### Code Quality

```bash
# Format code
black src/

# Lint
ruff check src/

# Type check
mypy src/
```

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

## 🔒 Security

- API keys stored in environment variables
- No secrets in code
- Sandbox mode for code execution
- Approval gates for dangerous tools
- Audit logging for all actions

## 📚 Documentation

- [API Documentation](http://localhost:8000/docs) (when running)
- [Architecture Guide](docs/architecture.md)
- [Agent Capabilities](AGENTS.md)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file

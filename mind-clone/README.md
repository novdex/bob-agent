# Mind Clone Agent

A sovereign AI agent platform with reasoning, memory, autonomy, and tool mastery.

## Overview

Mind Clone Agent is a modular Python-based AI agent system that provides:

- **Reasoning**: Multi-step reasoning with iterative tool use
- **Memory**: Conversation history with vector embeddings (GloVe)
- **Autonomy**: Task engine with planning and execution
- **Learning**: Research memory and self-improvement notes
- **Tools**: 25+ tools including web search, file operations, code execution
- **Communication**: Telegram bot, email (SMTP), REST API

## Architecture

```
mind-clone/
├── src/mind_clone/
│   ├── config.py          # Pydantic settings
│   ├── runner.py          # CLI entry point
│   ├── database/          # SQLAlchemy models
│   ├── agent/             # Core agent logic
│   ├── api/               # FastAPI endpoints
│   ├── core/              # Infrastructure (state, security, etc.)
│   ├── services/          # Background services
│   ├── tools/             # Tool implementations
│   └── utils/             # Utility functions
└── tests/                 # Test suite
```

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd mind-clone

# Install in development mode
pip install -e .

# Or install from PyPI (when published)
pip install mind-clone
```

## Configuration

Create a `.env` file in the project root:

```bash
# Required
KIMI_API_KEY=your_moonshot_api_key
TELEGRAM_BOT_TOKEN=your_bot_token
WEBHOOK_BASE_URL=https://your-domain.com

# Optional
SMTP_HOST=smtp.gmail.com
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
POLICY_PACK=dev  # dev | staging | prod
```

## Usage

### CLI

```bash
# Start web server
python -m mind_clone --web --host 0.0.0.0 --port 8000

# Start Telegram polling mode
python -m mind_clone --telegram-poll

# Run one-shot task
python -m mind_clone --run "Analyze this file"
```

### Python API

```python
from mind_clone.agent.loop import run_agent_turn
from mind_clone.database.session import get_db

# Get database session
db = next(get_db())

# Run agent turn
response = run_agent_turn(
    db=db,
    owner_id=1,
    user_message="Hello, what can you do?"
)
print(response)
```

### FastAPI Endpoints

```python
from mind_clone.api.factory import create_app

app = create_app()

# Run with uvicorn
# uvicorn mind_clone.api.factory:create_app --factory
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/heartbeat` | GET | Health check |
| `/status/runtime` | GET | Runtime metrics |
| `/chat` | POST | Send message to agent |
| `/ui/tasks` | GET/POST | List/create tasks |
| `/goals` | GET/POST | List/create goals |
| `/telegram/webhook` | POST | Telegram webhook |
| `/debug/blackbox` | GET | Event logs |

## Tools Available

### Web & Research
- `search_web` - DuckDuckGo search
- `read_webpage` - Extract webpage content
- `deep_research` - Multi-source research

### File Operations
- `read_file` - Read file contents
- `write_file` - Write file contents
- `list_directory` - List directory contents

### Code Execution
- `run_command` - Execute shell commands
- `execute_python` - Run Python code

### Communication
- `send_email` - Send emails via SMTP

### Memory
- `save_research_note` - Save research findings
- `research_memory_search` - Search research notes
- `semantic_memory_search` - Vector similarity search

### Task Management
- `create_task` - Create autonomous tasks
- `list_tasks` - List tasks
- `cancel_task` - Cancel tasks

### Browser Automation
- `browser_open` - Open URL in browser
- `browser_click` - Click element
- `browser_type` - Type text
- `browser_screenshot` - Take screenshot

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_config.py -v

# Run with coverage
pytest --cov=mind_clone --cov-report=html
```

## Development

```bash
# Setup development environment
pip install -e ".[dev]"

# Run linting
flake8 src/mind_clone

# Run type checking
mypy src/mind_clone

# Format code
black src/mind_clone
```

## Project Structure

### Database Models

- `User` - Human owners
- `Task` - Autonomous tasks
- `Goal` - Long-term goals
- `ConversationMessage` - Chat history
- `ScheduledJob` - Cron jobs
- `ApprovalRequest` - Pending approvals
- `TeamAgent` - Multi-agent support

### Core Modules

- `state.py` - Runtime state management
- `security.py` - Tool policies and approval gates
- `budget.py` - Resource limiting
- `queue.py` - Command queue management
- `circuit.py` - Circuit breaker pattern
- `tasks.py` - Task engine
- `approvals.py` - Approval system
- `goals.py` - Goal management
- `blackbox.py` - Event logging

## License

MIT License - See LICENSE file for details

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## Support

- Issues: [GitHub Issues](https://github.com/yourusername/mind-clone/issues)
- Documentation: [Full Docs](https://mind-clone.readthedocs.io)

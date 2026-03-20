# Bob — Open Source Personal AGI Agent

> *Not a chatbot wrapper. A self-improving autonomous agent that learns, plans, and acts.*

Bob is a personal AGI agent you run on your own machine. Talk to it via Telegram or web chat. It remembers everything, learns from every mistake, researches the internet autonomously, and improves its own code every night while you sleep.

---

## What makes Bob different

Most AI tools are just API wrappers. Bob is an agent with:

- **Persistent memory** — remembers everything across sessions, links knowledge together in a graph
- **Self-improvement** — reads its own code every night, runs experiments, keeps what works, reverts what doesn't
- **Real autonomy** — spawns sub-agents, monitors signals, acts proactively without being asked
- **117 tools** — web search, browser control, code execution, email, calendar, voice, file ops, and more
- **Learns from mistakes** — writes verbal reflections after every failure, never repeats the same error
- **Gets better over time** — every conversation makes Bob smarter via Bob Teaches Bob

---

## Features

### 🧠 Intelligence
| Feature | What it does |
|---|---|
| Multi-turn Planning | Writes a numbered execution plan before any complex task |
| Tree of Thoughts | Generates 3 approaches, evaluates each, picks the best |
| Generator → Verifier | Separate LLM call critiques every plan before execution |
| Constitutional AI | Self-critiques responses against 7 core principles |
| Reflexion | Learns from every failure: "I tried X, failed because Y, next time Z" |
| ReAct + Reflection | Structured observe/reason/act/reflect after every multi-step task |
| Self-Play | Devil's advocate debate for opinion/evaluation questions |

### 💾 Memory
| Feature | What it does |
|---|---|
| Memory Graph | Zettelkasten-style linked knowledge network (A-MEM / MAGMA) |
| Ebbinghaus Decay | Important memories stay sharp, noise fades automatically |
| Episodic Memory | Recalls similar past situations before acting |
| RAG Knowledge Base | Semantic vector search across all stored knowledge |
| Context Compression | Summarises old turns when context gets too large |
| JitRL | Retrieves highest-scoring past experiences as few-shot examples |

### 🚀 Self-Improvement
| Feature | What it does |
|---|---|
| Karpathy Loop | Nightly 2am: read code → hypotheses → implement → test → keep/revert |
| DSPy Prompt Optimiser | Auto-tunes tool descriptions based on real failure data |
| Co-Evolving Critic | Critic principles update as Bob improves — never goes stale |
| Bob Teaches Bob | Best conversations stored as teaching moments for future Bob |
| Auto-merge | Merges to main automatically after 3+ consecutive improvements |

### 🔧 Tools & Capabilities
| Tool | What it does |
|---|---|
| Browser Agent | Navigates real websites, fills forms, extracts structured data |
| Code Sandbox | Safe isolated Python/shell execution with timeout |
| Multi-agent Spawning | Parallel sub-agents for complex multi-part tasks |
| GitHub Research | Searches repos, reads READMEs, stores insights in knowledge graph |
| Continuous Learning | Learns from arXiv, GitHub trending, Hacker News every 6 hours |
| Voice Interface | Sends voice message responses to Telegram |
| Calendar + Email | Get events, send emails, create reminders |
| Observability Dashboard | Live: tool success rates, experiments, memory stats, jobs |

### 🤖 Autonomous Behaviours
- **7am daily**: Morning research briefing on your interests → Telegram
- **Every 6h**: Learns from arXiv, GitHub, Hacker News automatically
- **2am nightly**: Self-improvement experiment loop
- **3am nightly**: Ebbinghaus memory decay and pruning
- **Event-driven**: Fires on error spikes, memory bloat, stale experiments

---

## Quick Start

### Prerequisites
- Python 3.11+
- [Moonshot AI API key](https://platform.moonshot.cn) (for Kimi K2.5)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

### Install

```bash
git clone https://github.com/YOUR_USERNAME/bob-agent.git
cd bob-agent/mind-clone
pip install -e .
```

### Configure

```bash
cp .env.example .env
# Edit .env with your keys
```

Minimum required in `.env`:
```env
KIMI_API_KEY=your_moonshot_api_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
```

### Run

```bash
python -m mind_clone --web
```

Bob starts on `http://localhost:8000`. Set up your Telegram webhook or use polling mode:

```bash
python -m mind_clone --telegram-poll
```

### Run DB migrations (first time)

```bash
python migrate_db.py
```

---

## Architecture

```
bob-agent/
└── mind-clone/
    ├── src/mind_clone/
    │   ├── agent/          # Core reasoning loop, memory, identity
    │   │   ├── loop.py     # Main agent turn (all hooks wired here)
    │   │   ├── memory.py   # Message history + context management
    │   │   ├── episodes.py # Episodic memory recall
    │   │   ├── recall.py   # Long-term memory injection
    │   │   └── vectors.py  # GloVe embeddings (no API key needed)
    │   ├── services/       # 40+ intelligence services
    │   │   ├── auto_research.py      # Karpathy experiment loop
    │   │   ├── reflexion.py          # Verbal RL from failures
    │   │   ├── verifier.py           # Generator → Verifier → Reviser
    │   │   ├── memory_graph.py       # Zettelkasten knowledge graph
    │   │   ├── ebbinghaus.py         # Memory decay + spaced repetition
    │   │   ├── constitutional.py     # Self-critique (7 principles)
    │   │   ├── planner.py            # Multi-turn planning
    │   │   ├── tree_of_thoughts.py   # Multi-path reasoning
    │   │   ├── observability.py      # Dashboard
    │   │   ├── bob_teaches_bob.py    # Self-compounding learning
    │   │   └── ...                   # 30+ more
    │   ├── tools/          # 117 tool implementations
    │   ├── database/       # SQLAlchemy models + session
    │   └── api/            # FastAPI routes + lifespan
    ├── tests/              # 161+ tests
    ├── BOB_RESEARCH.md     # Edit this to steer nightly experiments
    ├── e2e_test.py         # End-to-end test (19 checks)
    └── migrate_db.py       # DB migration script
```

### Data flow

```
User (Telegram/API)
    → FastAPI
    → Agent Loop
        → Inject: user profile, world model, JitRL examples
        → Inject: skill playbooks, episodic memories, reflexion lessons
        → Inject: execution plan, tree of thoughts
        → Context compression
        → Kimi K2.5 LLM
        → Tool execution (117 tools)
        → Verify response (Generator → Verifier)
        → Constitutional review
        → Co-critic check
        → Self-play improvement
        → Background: update profile, world model, teach Bob, reflect
    → Response → User
```

---

## Configuration

Key `.env` options:

```env
# Required
KIMI_API_KEY=                    # Moonshot AI key
TELEGRAM_BOT_TOKEN=              # From @BotFather

# Optional
SMTP_HOST=smtp.gmail.com         # For email tools
SMTP_USERNAME=                   # Gmail address
SMTP_PASSWORD=                   # Gmail app password

# Behaviour
AUTONOMY_MODE=openclaw_max       # or: standard
BOB_FULL_POWER_ENABLED=false     # true = full system access (careful)
CUSTOM_TOOL_TRUST_MODE=safe      # or: full
```

---

## Steering Bob's Self-Improvement

Edit `BOB_RESEARCH.md` to control what Bob experiments on at night:

```markdown
## Current Focus
Improve Bob's response quality and tool success rate.

## Allowed Target Files
- src/mind_clone/services/retro.py
- src/mind_clone/tools/basic.py

## Constraints
- Max 50 lines changed per experiment
- All tests must pass
```

Bob reads this file before every nightly experiment loop.

---

## The 8 AGI Pillars

Bob is built around 8 intelligence pillars from `VISION.md`:

1. **Reasoning** — Planning, Tree of Thoughts, Verifier, Constitutional AI
2. **Memory** — Knowledge graph, Ebbinghaus, RAG, Episodic, JitRL
3. **Autonomy** — Scheduled jobs, event triggers, proactive research
4. **Learning** — Reflexion, DSPy, Co-critic, Bob Teaches Bob
5. **Tool Mastery** — 117 tools across web, code, browser, voice, files
6. **Self-Awareness** — Observability dashboard, retro, composite score
7. **World Understanding** — World model, continuous learning, GitHub research
8. **Communication** — Telegram, voice, email, multi-agent coordination

---

## Benchmarks & Research Basis

Every feature is based on proven research:

| Feature | Source | Proven Result |
|---|---|---|
| Karpathy Loop | autoresearch (Mar 2026) | ~100 experiments/night |
| Reflexion | Stanford 2023 | Beats GPT-4 on many benchmarks |
| Generator→Verifier | DeepMind Aletheia | 95.1% on IMO-Proof Bench |
| Tree of Thoughts | Princeton/Google 2023 | Significant improvement on hard problems |
| Co-Evolving Critic | VoltAgent 2026 | Prevents critic staleness |
| CORPGEN Isolation | Microsoft Research 2026 | 3.5x improvement in completion rate |
| Ebbinghaus Decay | SAGE 2025 | Beats Reflexion on all benchmarks |
| DSPy Optimisation | Stanford DSPy | +10pp accuracy on AIME 2025 |
| DeerFlow Multi-agent | ByteDance 2026 | #1 GitHub trending Feb 2026 |

---

## Running Tests

```bash
# Unit tests
python -m pytest tests/ -q --ignore=tests/unit/test_agents.py

# End-to-end test (19 checks)
python e2e_test.py
```

---

## License

MIT — use freely, modify freely, deploy commercially.

---

## Built with

- **LLM**: [Kimi K2.5](https://platform.moonshot.cn) via Moonshot AI
- **Framework**: FastAPI + SQLAlchemy + SQLite
- **Embeddings**: GloVe 6B (no API key needed)
- **Bot**: python-telegram-bot
- **Inspired by**: Karpathy autoresearch, DeerFlow, OpenHands, Voyager, Reflexion, DeepMind Aletheia

---

*Bob gets smarter every night. The longer you run it, the better it gets.*

# EXACT MODEL REFERENCE — Multi-Model Orchestrator v2.0
**Updated:** 2026-02-10 with verified model IDs

---

## QUICK REFERENCE TABLE

| Tool | Model Name | Exact Model ID | Cost | Context | Speed |
|------|------------|----------------|------|---------|-------|
| **Gemini** | Gemini 3 Flash | `gemini-3-flash` | FREE | 1M | Very Fast |
| **Gemini** | Gemini 3 Pro | `gemini-3-pro` | FREE | 2M | Fast |
| **Gemini** | Gemini 2.5 Flash | `gemini-2.5-flash` | FREE | 1M | Very Fast |
| **Gemini** | Gemini 2.5 Pro | `gemini-2.5-pro` | FREE | 2M | Fast |
| **Codex** | o3-mini | `o3-mini` | Very Low | 200K | Fast |
| **Codex** | GPT-4o mini | `gpt-4o-mini` | Low | 128K | Very Fast |
| **Codex** | GPT-4o | `gpt-4o` | Medium | 128K | Fast |
| **Codex** | GPT-5.2-Codex | `gpt-5.2-codex` | Medium | 200K | Fast |
| **Codex** | GPT-5.3-Codex | `gpt-5.3-codex` | Medium | 200K | Medium |
| **Codex** | GPT-5 | `gpt-5` | High | 128K | Medium |
| **Codex** | o1 | `o1` | Very High | 200K | Slow |
| **Codex** | o3 | `o3` | Very High | 200K | Medium |
| **Claude** | Claude 3 Haiku | `claude-3-haiku-20240307` | Very Low | 200K | Very Fast |
| **Claude** | Claude 3.5 Sonnet | `claude-3-5-sonnet-20241022` | Medium | 200K | Fast |
| **Claude** | Claude 4.5 Sonnet | `claude-sonnet-4-5-20250929` | Medium | 200K | Fast |
| **Claude** | Claude 3 Opus | `claude-3-opus-20240229` | High | 200K | Medium |
| **Claude** | Claude 4 Opus | `claude-opus-4-6` | High | 200K | Medium |
| **Kimi** | K2 Instant | `kimi-k2-instant` | API Low | 32K | Very Fast |
| **Kimi** | K2.5 32K | `kimi-k2.5-32k` | API Low | 32K | Fast |
| **Kimi** | K2.5 | `kimi-k2.5` | API Medium | 256K | Medium |
| **Kimi** | K2.5 128K | `kimi-k2.5-128k` | API Medium | 128K | Medium |
| **Kimi** | K2.5 256K | `kimi-k2.5-256k` | API High | 256K | Medium |
| **Kimi** | K2 Thinking | `kimi-k2-thinking` | API High | 256K | Slow |

---

## DETAILED MODEL INFO

### GEMINI CLI (Google) — FREE TIER

**Free Limit:** 1,000 requests/day, 60 requests/minute

| Model ID | Display Name | Context | When to Use |
|----------|--------------|---------|-------------|
| `gemini-3-flash` | Gemini 3 Flash | 1,000,000 | **Trivial/Simple tasks** — fastest responses |
| `gemini-3-pro` | Gemini 3 Pro | 2,000,000 | **Medium/Complex tasks** — most capable FREE |
| `gemini-2.5-flash` | Gemini 2.5 Flash | 1,000,000 | High volume, quick tasks |
| `gemini-2.5-pro` | Gemini 2.5 Pro | 2,000,000 | Complex coding, analysis |

**How to use:**
```bash
gemini --model gemini-3-pro "your task"
```

---

### CODEX CLI (OpenAI) — ChatGPT Plus Subscription

**Models available with subscription:**

| Model ID | Display Name | Context | Best For | Speed |
|----------|--------------|---------|----------|-------|
| `o3-mini` | o3-mini | 200K | Quick coding, reasoning | Fast |
| `gpt-4o-mini` | GPT-4o mini | 128K | Simple code, tests | Very Fast |
| `gpt-4o` | GPT-4o | 128K | General coding | Fast |
| `gpt-5.2-codex` | GPT-5.2-Codex | 200K | Agentic coding, implementation | Fast |
| `gpt-5.3-codex` | GPT-5.3-Codex | 200K | **DEFAULT** — great for most coding | Medium |
| `gpt-5` | GPT-5 | 128K | Complex reasoning | Medium |
| `o1` | o1 | 200K | Research, deep reasoning | Slow |
| `o3` | o3 | 200K | Advanced reasoning | Medium |

**How to use:**
```bash
# Via environment variable
set OPENAI_MODEL=gpt-5.3-codex
codex "your task"

# Via flag
codex --model gpt-5.3-codex "your task"
```

---

### CLAUDE CODE (Anthropic) — Pro Subscription

**Models available with subscription:**

| Model ID | Display Name | Context | Best For | Speed |
|----------|--------------|---------|----------|-------|
| `claude-3-haiku-20240307` | Claude 3 Haiku | 200K | Quick edits, docs | Very Fast |
| `claude-3-5-sonnet-20241022` | Claude 3.5 Sonnet | 200K | **DEFAULT** — balanced | Fast |
| `claude-sonnet-4-5-20250929` | Claude 4.5 Sonnet | 200K | Latest Sonnet, debugging | Fast |
| `claude-3-opus-20240229` | Claude 3 Opus | 200K | Deep reasoning | Medium |
| `claude-opus-4-6` | Claude 4 Opus | 200K | Best reasoning available | Medium |

**How to use:**
```bash
# Via environment variable
set ANTHROPIC_MODEL=claude-opus-4-6
claude "your task"

# Interactive: type /model inside Claude Code
```

---

### KIMI CODE (Moonshot) — API Key (Pay as you go)

**Pricing:** $0.60/1M input tokens, $2.50/1M output tokens

| Model ID | Display Name | Context | Best For | Speed |
|----------|--------------|---------|----------|-------|
| `kimi-k2-instant` | K2 Instant | 32K | Quick responses | Very Fast |
| `kimi-k2.5-32k` | K2.5 32K | 32K | Simple tasks | Fast |
| `kimi-k2.5` | K2.5 | 256K | **DEFAULT** — good balance | Medium |
| `kimi-k2.5-128k` | K2.5 128K | 128K | Medium complexity | Medium |
| `kimi-k2.5-256k` | K2.5 256K | 256K | Complex, long context | Medium |
| `kimi-k2-thinking` | K2 Thinking | 256K | Deep reasoning | Slow |

**How to use:**
```bash
kimi --model kimi-k2.5 "your task"
```

---

## MODEL SELECTION BY COMPLEXITY

### TRIVIAL (Single line changes, typos, formatting)
1. **Gemini 3 Flash** — FREE, fastest
2. **Claude 3 Haiku** — Very cheap, very fast
3. **Codex o3-mini** — Very cheap, fast
4. **Kimi K2 Instant** — API paid, fastest

### SIMPLE (Docs, boilerplate, simple code)
1. **Gemini 3 Pro** — FREE, capable
2. **Codex GPT-4o mini** — Cheap, very fast
3. **Claude 3 Haiku** — Very cheap, very fast
4. **Kimi K2.5 32K** — API paid, fast

### MEDIUM (Features, refactoring, debugging)
1. **Gemini 3 Pro** — FREE, best value
2. **Codex GPT-5.3-Codex** — Default, great at coding
3. **Claude 3.5/4.5 Sonnet** — Balanced, good debugging
4. **Kimi K2.5** — API paid, good balance

### COMPLEX (Architecture, design, reasoning)
1. **Gemini 3 Pro** — FREE, try first
2. **Codex GPT-5** — Strong reasoning
3. **Claude 4 Opus** — Best reasoning
4. **Kimi K2.5 256K** — API paid, large context

### RESEARCH (Open-ended, exploration)
1. **Codex o1** — Best reasoning, expensive
2. **Claude 4 Opus** — Deep analysis
3. **Kimi K2 Thinking** — API paid, reasoning mode

---

## USAGE EXAMPLES

```bash
# FREE tier first (automatic)
python multi_model_orchestrator.py --run "add docstrings"
# → Uses: Gemini 3 Flash (FREE)

# Force specific stack
python multi_model_orchestrator.py --demo "write tests" --force-stack codex
# → Uses: GPT-5.3-Codex (or GPT-4o mini for simple)

python multi_model_orchestrator.py --demo "debug issue" --force-stack claude
# → Uses: Sonnet 4.5 (or Opus 4 for complex)

python multi_model_orchestrator.py --demo "analyze code" --force-stack kimi
# → Uses: K2.5 (or K2.5 256K for complex)

# Override complexity
python multi_model_orchestrator.py --demo "design system" --complexity complex
# → Uses: Gemini 3 Pro (FREE) or forces paid tier if specified
```

---

## COMMAND REFERENCE

```bash
# List all available models
python multi_model_orchestrator.py --list-models

# Demo mode (show what would be selected)
python multi_model_orchestrator.py --demo "your task"

# Execute with selected model
python multi_model_orchestrator.py --run "your task"

# Force specific stack
python multi_model_orchestrator.py --demo "task" --force-stack gemini
python multi_model_orchestrator.py --demo "task" --force-stack codex
python multi_model_orchestrator.py --demo "task" --force-stack claude
python multi_model_orchestrator.py --demo "task" --force-stack kimi

# Override complexity detection
python multi_model_orchestrator.py --demo "task" --complexity trivial
python multi_model_orchestrator.py --demo "task" --complexity simple
python multi_model_orchestrator.py --demo "task" --complexity medium
python multi_model_orchestrator.py --demo "task" --complexity complex
python multi_model_orchestrator.py --demo "task" --complexity research
```

---

## FILES

- **Orchestrator:** `multi_model_orchestrator.py`
- **This Reference:** `EXACT_MODEL_REFERENCE.md`
- **Usage DB:** `ai_orchestrator_v2.db` (auto-created)

---

## FIRST PRINCIPLES

1. **Exhaust FREE tier** (Gemini 1000/day)
2. **Right model for task** — don't overpay for simple tasks
3. **Use specialized tools** — Codex for code, Claude for analysis
4. **Save API tools for last** — Kimi only when needed
5. **Track everything** — SQLite database logs all requests

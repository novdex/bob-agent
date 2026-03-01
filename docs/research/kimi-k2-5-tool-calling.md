# Kimi K2.5 Tool-Calling: Research Findings

**Date:** 2026-02-24
**Author:** Cowork (Research Partner)
**AGI Pillar:** Tool Mastery
**Notion Task:** Evaluate Kimi K2.5 tool-calling best practices

---

## Executive Summary

Kimi K2.5 is Moonshot AI's frontier model (1T MoE, 32B active params, 256K context) with best-in-class tool-augmented performance. This research evaluates its tool-calling capabilities, identifies gaps in Bob's current implementation, and recommends actionable improvements.

**Key findings:**
1. Bob's temperature=1.0 setting is correct for Thinking mode but suboptimal for Instant mode (should be 0.6)
2. The tool-call ID format (`functions.func_name:idx`) is a critical compatibility requirement Bob may not handle correctly
3. Parallel tool execution could yield 4.5x speedups but requires architectural changes
4. Context management for long tool chains needs a discard strategy
5. The failover chain (Kimi -> Gemini -> GPT -> Claude) is configured but not implemented

---

## 1. Temperature for Tool Calling

### Current State in Bob
Bob sets `llm_temperature = 1.0` globally for all LLM calls, including tool-calling. This is referenced in `config.py` and passed to every API request via `agent/llm.py`.

### Moonshot Recommendations

| Mode | Temperature | Top-p | Use Case |
|------|------------|-------|----------|
| Thinking | 1.0 | 0.95 | Complex reasoning, multi-step tool chains |
| Instant | 0.6 | 0.95 | Fast responses, simple tool calls |

Additional recommendations:
- Set `min_p = 0.01` to suppress unlikely tokens with low probabilities
- The Anthropic-compatible API maps temperature internally: `real_temperature = request_temperature * 0.6`

### Recommendation
**Add mode-aware temperature.** Bob should use temperature=1.0 for complex agentic tasks (multi-tool reasoning chains) and 0.6 for simple single-tool calls. This could be implemented as a per-call override in `call_llm()` based on the number of tools being sent or the task complexity.

---

## 2. Parallel Tool Calls

### Current State in Bob
Bob's `agent/loop.py` receives parallel tool calls from the LLM but executes them **sequentially** in a for loop:

```python
for tool_call in tool_calls:
    tool_result = execute_tool(tool_name, tool_args)
    messages.append({"role": "tool", ...})
```

### K2.5's Agent Swarm Capability
K2.5 supports an "Agent Swarm" paradigm:
- Decomposes tasks into parallel sub-tasks executed by dynamically instantiated agents
- Up to 100 sub-agents and 1,500 tool calls per task
- Trained with Parallel-Agent Reinforcement Learning (PARL)
- 4.5x execution time reduction vs sequential processing
- Known failure mode: "serial collapse" where the orchestrator defaults to single-agent execution

### Benchmark Results (Swarm Mode)

| Benchmark | K2.5 Score | Notes |
|-----------|-----------|-------|
| HLE (with tools) | 50.2 | Outperforms GPT-5.2 (45.5), Claude Opus 4.5 (43.2) |
| BrowseComp | 78.4 | Main agent 15 steps, sub-agents 100 steps |
| WideSearch | 79.0 | Both main/sub agents 100 steps |

### Recommendation
**Phase 1:** Use `asyncio.gather()` or `concurrent.futures.ThreadPoolExecutor` to execute independent tool calls in parallel. This is a straightforward change to `loop.py` that could significantly reduce latency for multi-tool turns.

**Phase 2 (future):** Evaluate Agent Swarm integration once the API exposes it directly. Currently Swarm is a model-internal capability, not an API parameter.

---

## 3. Token Limits for Function Definitions

### K2.5 Specifications

| Parameter | Value |
|-----------|-------|
| Context window | 256K tokens |
| Max completion tokens | 96K (reasoning tasks) |
| Max vision tokens | 64K |

### Current Bob Configuration

| Parameter | Value | Assessment |
|-----------|-------|------------|
| `llm_max_tokens` | 4,096 | **Too low** for complex tool chains. K2.5 can generate up to 96K tokens in reasoning mode. Consider raising to 8,192-16,384 for agentic tasks. |
| `session_soft_trim_char_budget` | 42,000 (~10.5K tokens) | **Conservative** relative to 256K context. Could be raised for tool-heavy sessions. |
| `budget_max_est_tokens` | 90,000 | Reasonable ceiling for a single session. |

### Tool Definition Token Budget
Bob uses **intent-based filtering** (`registry.py: effective_tool_definitions()`) to reduce the number of tools sent per request. This is a good practice since:
- K2.5's 256K context is shared between tool definitions, conversation history, and completions
- Always-included categories: file, code, memory
- Dynamically filtered: web, email, browser, desktop, scheduler, etc.

### Recommendation
- Raise `llm_max_tokens` to at least 8,192 for tool-calling turns
- Consider separate `llm_max_tokens_tool` config for agentic vs chat modes
- Token estimation (`4 chars/token`) is rough; K2.5 uses a different tokenizer. Consider adding actual tokenizer-based counting.

---

## 4. Tool-Call ID Format (Critical)

### The Problem
K2.5 (inheriting from K2) requires tool-call IDs in a **specific format**:

```
functions.{func_name}:{idx}
```

Where:
- `functions` is a fixed prefix
- `{func_name}` is the function name (e.g., `search_web`)
- `{idx}` is a **global counter starting at 0**, incrementing across all tool calls in the conversation

Examples:
```
functions.search_web:0
functions.read_file:1
functions.search_web:2   # Same function, but idx keeps incrementing
```

### Why This Matters
- **Incorrect IDs cause crashes**: Special tokens (`<|tool_call_begin|>`) leak into content fields
- This is the #1 cause of multi-turn tool-calling failures
- The official API handles this automatically, but if Bob ever migrates to self-hosted K2.5 (via vLLM/SGLang), this becomes critical
- Third-party platforms (OpenRouter) have reported issues with K2 not invoking tools properly, sometimes generating JSON in text instead of proper tool calls

### Current Bob State
Bob's `agent/llm.py` extracts `tool_call_id` from the response and passes it back correctly. Since Bob uses the official Moonshot API (`api.moonshot.ai/v1`), the API server handles ID generation. However, the code does not validate or enforce the ID format.

### Recommendation
- **Add ID format validation** in `loop.py` when processing tool calls: verify IDs match `functions.{name}:{idx}` pattern
- **Log warnings** if IDs don't match expected format (early detection of API changes)
- **If self-hosting later**: ensure vLLM is launched with `--tool-call-parser kimi_k2 --enable-auto-tool-choice`

---

## 5. Known Issues with Tool Schema Patterns

### Schema Format
K2.5 uses standard OpenAI function-calling schema, which Bob already implements correctly:

```json
{
  "type": "function",
  "function": {
    "name": "tool_name",
    "description": "What this tool does",
    "parameters": {
      "type": "object",
      "properties": { ... },
      "required": [ ... ]
    }
  }
}
```

### Known Issues

1. **Tool result format**: Tool results must be JSON strings in the `content` field. Bob serializes results to strings in `loop.py`, which is correct.

2. **Streaming tool calls**: When streaming, tool call arguments arrive in chunks. Bob currently uses non-streaming mode for tool calls, which avoids this complexity.

3. **Context overflow**: K2.5 has no built-in context management. Tasks exceeding 256K context simply fail. Bob's `session_soft_trim` handles this, but:
   - K2.5's recommended strategy for long tool chains: retain only the latest round of tool messages
   - Bob's trimming preserves the 8 most recent messages, which may not align with this

4. **Thinking mode interleaving**: K2.5 supports interleaved thinking and tool calls (model reasons, calls a tool, reasons more, calls another). Bob's loop supports this pattern naturally since it loops on `tool_calls` responses.

### Recommendation
- Implement K2.5's "latest round only" context management as an option alongside Bob's current trimming
- Add a `tool_result_max_chars` config to truncate large tool results before injecting them (prevents context blowout)

---

## 6. Comparison with GPT-4 and Claude

### Tool-Calling Approach Differences

| Aspect | Kimi K2.5 | GPT-4/4o | Claude |
|--------|-----------|----------|--------|
| API format | OpenAI-compatible | Native | Native (different format) |
| Temperature for tools | 1.0 (thinking) / 0.6 (instant) | 0-1 (no strict requirement) | 0-1 (no strict requirement) |
| Tool-call IDs | `functions.name:idx` (strict) | Random UUIDs | Not applicable (different format) |
| Parallel calls | Swarm (up to 100 agents) | Parallel tool calls | Parallel tool use |
| Context window | 256K | 128K | 200K |
| Strengths | Deep agentic reasoning, Agent Swarm | Broad ecosystem, reliable | Strong reasoning, safety |

### Benchmark Comparison (Tool-Augmented)

| Benchmark | K2.5 | GPT-5.2 | Claude Opus 4.5 | Gemini 3 Pro |
|-----------|------|---------|-----------------|-------------|
| HLE (tools) | **50.2** | 45.5 | 43.2 | 45.8 |
| DeepSearchQA | **77.1** | 71.3 | 76.1 | 63.2 |
| Seal-0 | **57.4** | 45.0 | 47.7 | 45.5 |

K2.5 leads on tool-augmented benchmarks, justifying its use as Bob's primary LLM.

---

## 7. Actionable Recommendations for Bob

### Priority 1 (Quick Wins)

| # | Change | File | Effort |
|---|--------|------|--------|
| 1 | Add mode-aware temperature (1.0 for multi-tool, 0.6 for single-tool) | `config.py`, `llm.py` | Small |
| 2 | Raise `llm_max_tokens` to 8192 for tool-calling turns | `config.py`, `llm.py` | Small |
| 3 | Add tool-call ID format validation with logging | `loop.py` | Small |
| 4 | Add `tool_result_max_chars` config to prevent context blowout | `config.py`, `loop.py` | Small |

### Priority 2 (Medium Effort)

| # | Change | File | Effort |
|---|--------|------|--------|
| 5 | Parallel tool execution with ThreadPoolExecutor | `loop.py` | Medium |
| 6 | Implement "latest round only" context management for tool chains | `loop.py`, `memory.py` | Medium |
| 7 | Add `min_p=0.01` to LLM payload | `llm.py` | Small |

### Priority 3 (Architecture)

| # | Change | Effort |
|---|--------|--------|
| 8 | Implement the failover chain (Kimi -> Gemini -> GPT -> Claude) | Large |
| 9 | Evaluate Agent Swarm integration when API support lands | Research |
| 10 | Replace rough token estimation with actual tokenizer | Medium |

---

## Sources

- [Kimi K2.5 - Hugging Face](https://huggingface.co/moonshotai/Kimi-K2.5)
- [Kimi K2.5 - GitHub](https://github.com/MoonshotAI/Kimi-K2.5)
- [Tool Use - Moonshot AI Platform Docs](https://platform.moonshot.ai/docs/api/tool-use)
- [Tool Calling Guide - Moonshot AI](https://platform.moonshot.ai/docs/guide/use-kimi-api-to-complete-tool-calls)
- [K2 Tool Call Guidance](https://huggingface.co/moonshotai/Kimi-K2-Thinking/blob/main/docs/tool_call_guidance.md)
- [K2.5 Tech Blog](https://www.kimi.com/blog/kimi-k2-5.html)
- [Kimi K2-Instruct - Hugging Face](https://huggingface.co/moonshotai/Kimi-K2-Instruct)

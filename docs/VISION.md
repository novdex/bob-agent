# VISION â€” The North Star

> **Read this before writing a single line of code.**
> Every decision, every tool, every feature should push us closer to this goal.

---

## Ultimate Goal: Artificial General Intelligence (AGI)

We are building toward a system that can **reason, learn, act, and generalize** across any domain â€” not just follow instructions, but truly understand, adapt, and improve itself.

This is not a chatbot project. This is not a tool wrapper. This is the foundation of an autonomous intelligence.

---

## The AGI Pillars We Are Building

### 1. Reasoning
- Multi-step, iterative thinking (not one-shot replies)
- Plan before acting, reflect after acting
- Handle ambiguity, contradictions, and incomplete information
- Know when it doesn't know something

### 2. Memory
- Short-term: conversation context
- Long-term: persistent knowledge that grows over time
- Episodic: remember past experiences and outcomes
- Semantic: understand relationships between concepts, not just store text

### 3. Autonomy
- Execute complex tasks without hand-holding
- Break goals into sub-goals, sub-goals into actions
- Recover from failures, retry with different strategies
- Work in the background while the owner is away

### 4. Learning
- Learn from every interaction
- Identify patterns in what works and what fails
- Update strategies based on outcomes
- Never make the same mistake twice

### 5. Tool Mastery
- Use any tool effectively (search, code, files, APIs, shell)
- Combine tools creatively to solve novel problems
- Know which tool to use when â€” and when no tool is needed
- Eventually: create new tools when existing ones aren't enough

### 6. Self-Awareness
- Understand its own capabilities and limitations
- Operate at owner-selected autonomy levels (max autonomy by default)
- Monitor its own performance
- Flag when it's uncertain or out of depth

### 7. World Understanding
- Build internal models of how things work
- Predict consequences before acting
- Understand cause and effect
- Reason about time, resources, and trade-offs

### 8. Communication
- Be clear, direct, and honest
- Adapt communication style to context
- Explain its reasoning when asked
- Ask for clarification when truly needed â€” not as a crutch

---

## Where We Are Now

| Pillar | Status | What Exists |
|--------|--------|-------------|
| Reasoning | Foundation | Agent loop with iterative tool use (10 rounds) |
| Memory | Growing | Conversation history + research notes + **vector embeddings** (GloVe semantic search) |
| Autonomy | Growing | Task engine with planning, execution, retries |
| Learning | Growing | Research memory, forced deep research, **self-reflection engine** (post-conversation lesson extraction + retrieval) |
| Tool Mastery | Solid | 13+ tools (files, shell, web, code, research, PDF, vector memory, email, desktop) + **vision-powered computer use** |
| Self-Awareness | Basic | Identity kernel, autonomy directives |
| World Understanding | Growing | Action forecast + outcome reconciliation loop, reused as world-model signals |
| Communication | Working | Telegram interface, direct API, **email sending** (Gmail SMTP) |

---

## What "Done" Looks Like

When this system is complete, it should be able to:

1. **Receive a high-level goal** and independently figure out how to achieve it
2. **Learn from experience** â€” get better at tasks it has done before
3. **Handle any domain** â€” not just coding, but research, analysis, planning, creation
4. **Operate continuously** â€” work on long-running goals over days/weeks
5. **Know its limits** â€” escalate only when truly blocked, otherwise continue autonomously
6. **Explain itself** â€” show its reasoning, justify its decisions
7. **Improve itself** â€” identify weaknesses and propose its own upgrades

---

## Principles for Every Worker

Whether you are Claude, Codex, Copilot, Cursor, or any future AI:

1. **Every feature should serve an AGI pillar** â€” don't add fluff
2. **Prefer general solutions over specific hacks** â€” build capabilities, not patches
3. **Think about emergent behavior** â€” how will this interact with everything else?
4. **Autonomy is non-negotiable** â€” default to owner-authorized execution with minimal friction
5. **Document your reasoning** â€” the next worker needs to understand WHY, not just WHAT
6. **Push the boundary** â€” if you see a way to make the system smarter, propose it
7. **Single file architecture** â€” keep it unified until the owner says otherwise

---

## The Challenge

Most AI projects stop at "chatbot that calls APIs." We are going further.

Every commit should answer the question:
> **"Does this make the system more generally intelligent?"**

If yes, ship it. If no, reconsider.

---

*This document is the north star. When in doubt, look up.*


# Bob Learning Guide — From Zero to Mastery

> Written for Arshdeep — a non-coder who built Bob using Claude Code.
> This guide explains every part of Bob in plain English.
> No coding knowledge required. Just curiosity.

---

## Chapter 1: The Big Picture

### What is Bob?

Bob is a **program that runs on your computer** and does three things:
1. **Listens** for your messages on Telegram
2. **Thinks** about what you said (using an AI brain)
3. **Acts** on it (searches the web, writes files, sends replies)

Think of Bob like a personal assistant who:
- Lives inside your computer (not in the cloud)
- Has a phone (Telegram) to talk to you
- Has a brain (MiniMax AI) to think
- Has hands (82 tools) to do things
- Has a diary (database) to remember things
- Has a daily routine (cron jobs) that runs automatically

### How Bob is Organized (The Building)

Imagine Bob as a **5-floor building**:

```
FLOOR 5: TELEGRAM (the front door)
    You send a message --> Bob receives it here
    Bob sends replies back through here

FLOOR 4: API (the reception desk)
    Receives messages from Telegram
    Routes them to the right department
    File: api/factory.py, api/routes/

FLOOR 3: AGENT (the brain)
    Thinks about your message
    Decides what to do
    Calls tools if needed
    File: agent/loop.py (THE most important file)

FLOOR 2: SERVICES (the intelligence departments)
    Memory department, Research department,
    Self-improvement department, Voice department
    63 files doing specialized jobs
    File: services/*.py

FLOOR 1: TOOLS + DATABASE (the hands and diary)
    82+ tools to do things in the real world
    Database to remember everything
    File: tools/registry.py, database/models.py
```

### The Journey of a Message

When you send "What's trending in AI?" on Telegram:

```
Step 1: YOUR PHONE
   You type the message and press send

Step 2: TELEGRAM SERVERS
   Telegram delivers it to Bob's bot (@Arsh9592bot)

Step 3: BOB'S POLLING (services/telegram/bot.py)
   Bob checks Telegram every 0.5 seconds for new messages
   "Oh! A new message from Arsh!"

Step 4: MESSAGE HANDLER (services/telegram/commands.py)
   "This is a regular text message, not a command"
   Sends it to the dispatch system

Step 5: DISPATCH (services/telegram/dispatch.py)
   "Let me queue this for processing"
   Sends "Thinking..." to your Telegram immediately
   Puts the message in the work queue

Step 6: WORKER (dispatch.py → worker picks up the job)
   A background worker takes the message from the queue
   Calls the agent loop

Step 7: AGENT LOOP (agent/loop.py) — THE BRAIN
   a) "Is this a simple message?" → NO (it's a question)
   b) Load 12 intelligence systems IN PARALLEL:
      - Memory: "What do I know about AI trends?"
      - Episodes: "Have I answered this before?"
      - Profile: "Arsh likes AI/AGI topics"
      - World model: "What's happening in the world?"
      - Skills: "Do I have a skill for this?"
      - Reasoning: "What strategy should I use?"
      - ... 6 more systems
   c) Combine everything into a prompt
   d) Call the AI brain (MiniMax 2.7 via OpenRouter)
   e) AI says: "I should search the web for this"
   f) Bob calls the search_web tool
   g) Gets results back
   h) AI creates a nice summary
   i) Done!

Step 8: RESPONSE SENT (dispatch.py)
   The "Thinking..." message gets EDITED to show the real answer
   You see the response on Telegram

Step 9: BACKGROUND TASKS (after reply)
   - Save conversation to database
   - Check if you corrected Bob (learn from it)
   - Record this as an episodic memory
   - Update your user profile
   - Update Bob's world model
```

**Total time: 5 seconds (simple) or 20 seconds (complex)**

---

## Chapter 2: The Brain — agent/loop.py

This is the **most important file in Bob**. Every message flows through here.

### What it does (in plain English)

The brain receives your message and follows these steps:

**Step 1: Save your message**
Bob writes your message to the database so he never forgets it.

**Step 2: Fast-path check**
"Is this a simple message like 'hi' or 'thanks'?"
- YES → Skip all the heavy thinking, just reply quickly (3-5 seconds)
- NO → Continue to full thinking mode

**Step 3: Prepare conversation history**
Load the last 30 messages from your conversation so Bob has context.

**Step 4: Load 12 intelligence systems (in parallel)**
This is what makes Bob smart. All 12 run at the same time:

| System | What it does | Example |
|--------|-------------|---------|
| Reasoning | Picks a thinking strategy | "Use step-by-step reasoning" |
| Skills | Checks if Bob solved this before | "I have a skill for web research" |
| Prediction | Forecasts what you might need | "User usually wants recent news" |
| Recall | Searches long-term memory | "I remember discussing AI trends yesterday" |
| Profile | Loads your preferences | "Arsh likes concise answers" |
| World Model | Current state of the world | "Bob is running on Windows, project X is active" |
| JitRL | Best past examples | "Last time I searched well, I used these steps" |
| Episodes | Similar past situations | "When asked about AI before, this worked" |
| Reflexion | Lessons from mistakes | "Don't guess — search the web for current info" |
| DSPy | Optimized tool hints | "search_web works best with specific queries" |
| Planner | Multi-step plan | "1. Search 2. Summarize 3. Reply" |
| Tree of Thoughts | Multiple approaches | "Approach A vs B vs C — pick best" |

**Step 5: Call the AI brain**
Send everything (your message + context + intelligence) to MiniMax 2.7.
The AI decides: reply directly, OR use a tool.

**Step 6: Tool loop (up to 50 rounds)**
If the AI says "I need to search the web":
1. Bob calls the search_web tool
2. Gets results
3. Sends results back to AI
4. AI might call another tool or write the final reply
5. Repeat until AI gives a final answer

**Step 7: Background tasks**
After replying, Bob quietly does:
- Records this as an episodic memory
- Checks if you corrected him (saves lesson)
- Reviews his own response (constitutional AI)
- Updates your profile and world model

### Key concept: The Tool Loop

This is what makes Bob an **agent** instead of just a chatbot.

A chatbot just talks. An agent **does things**.

```
Normal chatbot:
  You: "What's the weather?"
  Bot: "I don't have access to weather data" (useless)

Bob (agent):
  You: "What's the weather?"
  Bob's brain: "I should use the search_web tool"
  Bob calls search_web("weather in UK today")
  Gets results
  Bob's brain: "Now I can answer properly"
  Bob: "It's 15C and cloudy in the UK today"
```

The tool loop is the secret. Bob can call tools **up to 50 times** in a single conversation turn. Each tool call gives Bob more information to work with.

---

## Chapter 3: Memory — How Bob Remembers

Bob has **6 types of memory**. Think of them like a human brain:

### 1. Conversation History (Short-term memory)
**File:** agent/memory.py
**What:** The last 30 messages between you and Bob
**Like:** Remembering what someone just said to you
**How long:** Until compressed (after 30 messages, old ones become summaries)

### 2. Conversation Summaries (Compressed memory)
**File:** agent/memory.py
**What:** Summaries of old conversations
**Like:** "Last week we discussed X, Y, Z"
**How long:** Forever (88 summaries stored so far)

### 3. Episodic Memory (Experience memory)
**File:** agent/episodes.py
**What:** Records of past situations: what happened, what Bob did, did it work?
**Like:** "Last time I tried X and it failed, so this time I'll try Y"
**How long:** Fades over time (Ebbinghaus decay) — important ones stay, boring ones fade

### 4. Research Notes (Knowledge)
**File:** services/knowledge_base.py
**What:** Things Bob learned from the internet, arXiv, GitHub
**Like:** Notes in a notebook
**How long:** Forever (merged daily to remove duplicates)

### 5. Skills (Procedural memory)
**File:** tools/skill_library.py
**What:** Step-by-step instructions for tasks Bob completed successfully
**Like:** "I know how to ride a bike" — you don't forget how
**How long:** Forever (new skills discovered weekly)

### 6. Lessons (Reflexion memory)
**File:** services/reflexion.py
**What:** Lessons from failures and corrections
**Like:** "Don't touch the hot stove" — learned once, remembered forever
**How long:** Forever (boosted each time recalled)

### Memory Flow Diagram

```
YOU SAY SOMETHING
       |
       v
Bob checks ALL 6 memories:
  "Have I had this conversation before?" → Conversation History
  "What happened in similar situations?" → Episodic Memory
  "Do I know anything about this topic?" → Research Notes
  "Have I solved this type of task?" → Skills
  "Did I fail at this before? Why?" → Lessons
  "What was the big picture context?" → Conversation Summaries
       |
       v
Bob combines relevant memories into the prompt
       |
       v
AI gives a smarter answer because it has context
```

### How Memories Evolve

**Every night at 3 AM:**
- **Ebbinghaus Decay** runs: unimportant memories lose "importance points"
- Memories below 0.1 importance are archived (still accessible, just not auto-loaded)
- Memories that Bob recalls frequently get BOOSTED (spaced repetition)

**Every day at 3:30 AM:**
- **Memory Consolidation** runs: duplicate memories are merged
- Similar research notes combined into one
- Similar episodes merged

**Result:** Bob's memory gets cleaner and sharper over time, like a human brain.

---

## Chapter 4: Tools — Bob's Hands

Bob has **82+ tools**. These are things Bob can actually DO in the real world.

### Tool Categories

**Communication (5 tools)**
| Tool | What it does |
|------|-------------|
| send_telegram_message | Send a message to your Telegram |
| speak | Convert text to voice and send as audio |
| send_email | Send an email |
| schedule_job | Create a recurring automated task |
| create_reminder | Set a reminder for a specific time |

**Research (6 tools)**
| Tool | What it does |
|------|-------------|
| search_web | Search the internet (DuckDuckGo) |
| read_webpage | Read the full content of a webpage |
| deep_research | Deep dive into a topic using multiple searches |
| spawn_agents | Split research into parallel sub-agents |
| research_memory_search | Search Bob's stored research notes |
| semantic_memory_search | Search all of Bob's memory semantically |

**File & Code (8 tools)**
| Tool | What it does |
|------|-------------|
| read_file | Read a file from your computer |
| write_file | Create or overwrite a file |
| list_directory | List files in a folder |
| execute_python | Run Python code |
| sandbox_python | Run Python in a safe sandbox |
| run_command | Run a shell command |
| codebase_search | Search Bob's own code |
| codebase_edit | Edit Bob's own code |

**Desktop Automation (15+ tools)**
| Tool | What it does |
|------|-------------|
| desktop_screenshot | Take a screenshot of your screen |
| desktop_click | Click somewhere on screen |
| desktop_type_text | Type text into any application |
| desktop_launch_app | Open an application |
| desktop_hotkey | Press keyboard shortcuts |

**Memory & Learning (8 tools)**
| Tool | What it does |
|------|-------------|
| save_skill | Save a completed task as a reusable skill |
| recall_skill | Check if Bob has solved something similar before |
| consolidate_memory | Merge duplicate memories |
| rag_search | Vector search across knowledge base |
| link_memories | Create connections between memories |

**Self-Management (6 tools)**
| Tool | What it does |
|------|-------------|
| self_improve | Fix a known issue in Bob's code |
| run_experiment | Run a self-improvement experiment |
| dashboard | Show Bob's health and performance metrics |
| discover_skills | Search internet for new skills to learn |
| proactive_intelligence | Run self-healing + news alerts + suggestions |

**MCP (External Services) (3 tools + 14 from servers)**
| Tool | What it does |
|------|-------------|
| mcp_connect | Connect to external MCP servers |
| mcp_call | Call any tool from a connected MCP server |
| mcp_list_servers | List all connected servers and their tools |
| + 14 filesystem tools | Read, write, search files via MCP |

### How Tools Work

```
AI Brain says: "I need to search the web"
       |
       v
Tool Registry (tools/registry.py):
  "search_web? Let me find that tool..."
  Found! It's in tools/basic.py
       |
       v
Execute the tool:
  Call DuckDuckGo with the search query
  Get results back
       |
       v
Record performance:
  "search_web succeeded in 2.3 seconds"
  (This data feeds into the self-improvement system)
       |
       v
Return results to AI Brain
  AI uses the results to form a response
```

### The Closed-Loop Feedback System

Bob tracks how well each tool performs:

```
Every tool call is recorded:
  - Did it succeed or fail?
  - How long did it take?
  - What error occurred (if any)?

Over time, Bob builds a picture:
  search_web: 95% success rate (great!)
  execute_python: 80% success rate (good)
  desktop_click: 60% success rate (needs improvement)

The AI sees this data and:
  - Prefers high-success tools
  - Avoids or is warned about low-success tools
  - The nightly experiment tries to improve weak tools
```

---

## Chapter 5: Intelligence Services — Bob's Departments

Bob has **63 service files**. Each is like a department in a company.

### The 10 Most Important Services

**1. Reflexion (services/reflexion.py)**
When Bob fails at something, he writes a lesson:
"I tried to search for X but got no results. Next time I should use more specific keywords."
These lessons are shown to Bob before future similar tasks.

**2. Auto Research (services/auto_research.py)**
Every night at 2 AM, Bob:
- Measures his performance score
- Generates 3 ideas to improve himself
- Picks the best idea
- Edits his own code to implement it
- Runs tests to make sure nothing broke
- If improved → keeps the change. If not → reverts it.

**3. Retro (services/retro.py)**
Every day at midnight, Bob reviews his day:
- How many messages did I handle?
- Which tools failed the most?
- Did the user correct me? About what?
- What should I improve tomorrow?
Creates a SelfImprovementNote with specific action items.

**4. Ebbinghaus (services/ebbinghaus.py)**
Models how human memory works:
- New memories start strong (importance = 1.0)
- Each day, importance decays: importance = importance * e^(-decay * days)
- If Bob recalls a memory, it gets boosted (spaced repetition)
- Very faded memories get archived

**5. Proactive Intelligence (services/proactive_intelligence.py)**
Every 2 hours, Bob autonomously:
- Checks for errors and fixes them (self-healing)
- Searches for trending AI news (alerts you if important)
- Generates smart suggestions based on your activity

**6. Correction Learner (services/correction_learner.py)**
When you say "no" or "that's wrong":
- Detects the correction
- Uses AI to extract the lesson
- Saves it permanently to memory
- Bob will never make the same mistake again

**7. Voice Interface (services/voice_tts.py + voice_stt.py)**
- TTS: Converts text to speech using Microsoft Edge TTS (free)
- STT: Converts your voice messages to text using Groq Whisper
- Flow: Your voice → text → Bob thinks → text → voice back

**8. Memory Consolidator (services/memory_consolidator.py)**
Runs daily at 3:30 AM:
- Finds duplicate research notes → merges them
- Finds duplicate episodic memories → merges them
- Finds duplicate improvement notes → merges them
- Keeps Bob's memory lean and fast

**9. Skill Discovery (services/skill_discovery.py)**
Runs weekly:
- Searches the internet for new AI agent skills
- Evaluates if they're useful and safe
- Saves good ones to Bob's skill library
- Bob literally learns new capabilities from the internet

**10. MCP Client (services/mcp_client.py)**
Connects Bob to external services:
- Gmail, GitHub, Calendar, Slack, Notion
- Uses the MCP protocol (same as Claude Desktop)
- Just add config → restart → tools appear automatically

---

## Chapter 6: Automation — What Bob Does While You Sleep

### The Cron System

Bob has a **cron supervisor** that runs every 10 seconds and checks:
"Are there any scheduled jobs that need to run right now?"

```
The cron supervisor is like an alarm clock manager.
It looks at 12 alarm clocks (scheduled jobs).
When an alarm goes off, it runs that job.
```

### All 12 Automated Jobs

| Time | Job | What it does |
|------|-----|-------------|
| Every 1h | hourly-check | Basic health check |
| Every 2h | proactive_intelligence | Self-heal, trending news, suggestions |
| Every 6h | continuous_learning | Learn from arXiv, GitHub, HN |
| Every 8h | ai_news_updates | Search for AI news |
| Every 8h | proactive_checkin | Send you a check-in message |
| Daily 8 PM UK | morning_briefing | Evening AI/AGI news summary |
| Daily midnight | daily_retro | Self-review of the day |
| Daily 2 AM | nightly_experiment | Rewrite own code to improve |
| Daily 3 AM | ebbinghaus_decay | Memory decay and pruning |
| Daily 3:30 AM | memory_consolidation | Merge duplicate memories |
| Weekly | self_challenge | Test himself on AGI pillars |
| Weekly | skill_discovery | Find new skills on the internet |

### How a Cron Job Runs

```
Cron supervisor checks every 10 seconds:
  "Is proactive_intelligence due?"
  → Check next_run_at in database
  → If now >= next_run_at: YES, run it!

Running a job:
  1. Take the job's "message" text
  2. Feed it into the agent loop (same as if you typed it)
  3. Bob processes it with full tool access
  4. If result should go to Telegram → send it
  5. Update next_run_at for the next cycle
```

---

## Chapter 7: The Database — Bob's Diary

Bob uses **SQLite** — a database stored as a single file on your computer.

**Location:** `C:\Users\mader\AppData\Local\mind-clone\mind_clone.db`

### Key Tables (What Bob Remembers)

| Table | What it stores | How many |
|-------|---------------|----------|
| users | Your identity (name, chat_id) | 1 |
| conversation_messages | Every message between you and Bob | 291+ |
| conversation_summaries | Compressed old conversations | 88 |
| episodic_memory | Past situations and outcomes | 200+ |
| research_notes | Knowledge from the internet | Growing |
| self_improvement_notes | Things Bob needs to fix about himself | 50+ |
| experiment_logs | Results of nightly experiments | 7+ |
| tool_performance_logs | Success/failure of every tool call | Thousands |
| scheduled_jobs | The 12 automated cron jobs | 12 |
| skill_profiles | Saved reusable skills | Growing |
| memory_vectors | Embeddings for semantic search | Hundreds |

### How Data Flows

```
You send message → saved to conversation_messages
Bob thinks → may create research_notes, episodic_memory
Bob replies → saved to conversation_messages
Bob reviews → creates self_improvement_notes
Bob experiments → creates experiment_logs
Every tool call → creates tool_performance_logs
```

---

## Chapter 8: Configuration — Bob's Settings

Bob is controlled by a `.env` file with **246 settings**.

### The Most Important Settings

| Setting | What it controls | Current value |
|---------|-----------------|---------------|
| TELEGRAM_BOT_TOKEN | Bob's Telegram identity | Your bot token |
| OPENROUTER_API_KEY | Access to AI models | Your API key |
| OPENROUTER_MODEL | Which AI model to use | minimax/minimax-m2.7 |
| CRON_ENABLED | Automated jobs on/off | true |
| SELF_IMPROVE_ENABLED | Can Bob edit his own code? | true |
| CLOSED_LOOP_ENABLED | Performance tracking on/off | true |
| DESKTOP_CONTROL_ENABLED | Can Bob control your desktop? | true |
| COMMAND_QUEUE_MODE | How messages are processed | on |
| BUDGET_GOVERNOR_ENABLED | Cost limits on/off | true |

### Safety Settings

| Setting | What it does |
|---------|-------------|
| TOOL_POLICY | What tools Bob can use (safe/balanced/power) |
| APPROVAL_GATE_MODE | Does Bob need your OK before risky actions? |
| SANDBOX_PROFILE | How isolated is Bob's execution? |
| SECRET_GUARDRAIL | Hide passwords from logs |
| DIFF_GATE_MAX_CHANGED | Max lines Bob can change in one edit |

---

## Chapter 9: How Bob Improves Himself

This is what makes Bob unique. Most agents just execute tasks. **Bob evolves.**

### The Self-Improvement Cycle

```
NIGHT 1:
  Midnight: Retro — "Today I failed at search 3 times because my queries were too vague"
  2 AM: Experiment — "Hypothesis: Add 'latest 2026' to search queries"
    → Edits services/basic.py
    → Runs tests → PASS
    → Measures score → Improved!
    → Commits the change
  3 AM: Memory cleanup — archives old irrelevant memories

NIGHT 2:
  Midnight: Retro — "Search success rate improved! But voice failed twice"
  2 AM: Experiment — "Hypothesis: Add retry logic to voice synthesis"
    → Edits services/voice_tts.py
    → Runs tests → PASS
    → Measures score → Improved!
    → Commits the change

NIGHT 3:
  ... and so on, forever
```

### The Feedback Loop

```
You use Bob
  → Bob records what works and what doesn't
    → Retro analyzes the data
      → Creates improvement notes
        → Nightly experiment picks the best note
          → Implements a code change
            → Tests it
              → If better: keeps it
              → If worse: reverts it
                → Next night: tries something else
```

**Bob has been running experiments for 7 nights. He's already made himself better at tool usage, memory recall, and response quality — automatically.**

---

## Chapter 10: Files You Should Know

### The 10 Most Important Files

| # | File | Lines | What it does |
|---|------|-------|-------------|
| 1 | agent/loop.py | 900 | THE BRAIN — every message goes through here |
| 2 | agent/memory.py | 400 | How Bob remembers and prepares context |
| 3 | tools/registry.py | 1,200 | 82+ tools organized and dispatched |
| 4 | services/telegram/dispatch.py | 300 | Routes messages to workers |
| 5 | services/auto_research.py | 600 | Nightly self-improvement experiments |
| 6 | services/telegram/supervisors.py | 700 | Cron job execution |
| 7 | agent/llm.py | 300 | Calls AI models with failover |
| 8 | database/models.py | 600 | All 40+ database tables defined |
| 9 | config.py | 400 | All 246 settings |
| 10 | api/factory.py | 250 | Startup: initializes everything |

### File Naming Patterns

- `agent/*.py` — Bob's thinking/reasoning (the brain)
- `services/*.py` — Intelligence and background systems (departments)
- `tools/*.py` — Things Bob can do (hands)
- `core/*.py` — Deep infrastructure (plumbing)
- `api/*.py` — Web server and routes (reception)
- `database/*.py` — Data storage (diary)

---

## Glossary — Terms You'll Hear

| Term | Plain English |
|------|--------------|
| Agent loop | The main thinking cycle — receive message, think, act, reply |
| Tool call | When Bob uses a tool (like searching the web) |
| Context injection | Loading memories and intelligence before thinking |
| Cron job | An automated task that runs on a schedule |
| Dispatch | Routing a message to the right worker |
| Failover chain | If one AI model fails, try the next one |
| Embedding | Converting text into numbers so Bob can search by meaning |
| Reflexion | Learning from mistakes by writing lessons |
| Episodic memory | "Last time I did X and it worked/failed" |
| System prompt | Instructions that tell the AI who Bob is and how to behave |
| Fast path | Shortcut for simple messages that skip heavy thinking |
| Parallel injection | Running 12 intelligence systems at the same time |
| RAG | Retrieval Augmented Generation — searching knowledge before answering |
| MCP | Protocol to connect to external services (Gmail, GitHub, etc.) |
| Checkpoint | Saving state before risky operations (crash recovery) |
| Constitutional AI | Bob reviewing his own response for safety/quality |
| Composite score | Bob's overall performance metric (tool success + error rate) |

---

## What's Next?

Now that you have the map, here's how to deepen your understanding:

**Week 1:** Read this guide fully. Ask me questions about anything unclear.

**Week 2:** We trace a real message together — from your Telegram to Bob's reply. I show you every file it touches.

**Week 3:** You make your first change — edit the system prompt, see the effect.

**Week 4:** We dive into one service (reflexion or retro) and understand it fully.

**After that:** You'll be ready to discuss new features as a partner, not just a requester.

---

*This guide was created on March 28, 2026. Bob had 46,267 lines of code, 82+ tools, and 12 automated jobs at the time of writing.*

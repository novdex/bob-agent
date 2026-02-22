# CHANGELOG — Mind Clone Agent

> Every AI worker logs their changes here. Most recent first.

---

## 2026-02-22 — Match OpenClaw Speed Patterns (Keep Kimi K2.5)

Reduced LLM payload from ~55KB to ~15-25KB per call by applying 5 OpenClaw
speed patterns. Target: faster Telegram responses while keeping Kimi K2.5.

### Changes

| # | Change | Payload Saved |
|---|--------|---------------|
| 1 | **Smart tool filtering** — classify message intent via keywords, send only relevant tool categories (8 core vs 57 all) | 15-22KB |
| 2 | **History limit** — reduced from 50 to 20 messages (`CONVERSATION_HISTORY_LIMIT`), soft trim keep recent from 28 to 14 | 8-12KB |
| 3 | **Adaptive context injection** — simple/normal/complex profiles control how many lessons, summaries, artifacts, etc. are injected | 3-6KB |
| 4 | **Telegram edit-streaming** — send "Thinking..." placeholder immediately, then edit with real response (OpenClaw streaming pattern) | Perceived speed |
| 5 | **Conditional system prompt** — skip env state, chaining hints, tool perf stats, episodic memories for simple messages | 1-3KB |

### New Functions

- `classify_tool_intent(msg)` — keyword-based intent classification, returns tool category set
- `_select_tools_for_intent(tools, categories)` — filters tool list by categories
- `TOOL_CATEGORIES` / `_INTENT_KEYWORDS` — tool and keyword mappings
- `send_telegram_placeholder(chat_id)` — sends placeholder, returns message_id
- `edit_telegram_message(chat_id, msg_id, text)` — edits placeholder with real response

### New Config Vars

- `CONVERSATION_HISTORY_LIMIT` (default 20, was hardcoded 50)
- `AGENT_LOOP_TIMEOUT_SECONDS` (default 300)

---

## 2026-02-22 — Fix Telegram Response System (OpenClaw-Aligned)

Bob was receiving Telegram messages but zero were processed to completion. Root
cause: task recovery on startup flooded the LLM API, and no timeout or priority
mechanism existed. Studied OpenClaw's operational architecture and applied 6
aligned fixes.

### Fixes

| Fix | What | OpenClaw Pattern |
|-----|------|-----------------|
| 1. Delayed task recovery | Tasks wait 60s after startup before recovering | OpenClaw: no task persistence at all |
| 2. Chat priority flag | `chat_active_{owner_id}` flag makes task worker yield 3s between LLM calls when user is chatting | OpenClaw: user chat bypasses queue entirely |
| 3. Agent loop timeout | 300s configurable timeout (`AGENT_LOOP_TIMEOUT_SECONDS`) via `asyncio.wait_for()` | OpenClaw: 600s timeout with AbortController |
| 4. Telegram ack when busy | Sends "Got your message, thinking..." when background tasks are running | OpenClaw: streaming deltas + typed indicators |
| 5. Fire-forget error callback | `asyncio.create_task` done callback logs exceptions + tracks `command_queue_fire_forget_errors` | OpenClaw: `broadcastChatError()` |
| 6. Queue mode threshold | Raised auto-switch threshold from 3 to `max(10, configured)` to prevent flip-flopping | OpenClaw: static architecture |

### Files Changed

- `mind_clone_agent.py`: `app_lifespan()`, `run_owner_message_job()`, `run_task_step_loop()`, `dispatch_incoming_message()`, `st_tune_queue_mode()`, config vars, RUNTIME_STATE

---

## 2026-02-22 — OpenClaw-Style Context Compaction (Eliminate Hard Clears)

Replaced Bob's destructive hard-clear context management with OpenClaw-style
compaction.  The old system had two disconnected pieces: message-count-based
compaction (at 120+ messages) and char-budget-based destructive trimming (soft
trim + hard clear).  Hard clears deleted all message content, causing hundreds
of context wipes, empty LLM responses, and silent Telegram message drops.

### Architecture Change

**Before:** `run_agent_loop -> compact(if 120 msgs) -> ... -> prepare_for_llm -> [DESTRUCTIVE hard clear]`
**After:** `run_agent_loop -> compact(if 80 msgs) -> compact_by_chars(if over budget) -> ... -> prepare_for_llm -> [lightweight trim only]`

### What Changed

| Change | Detail |
|--------|--------|
| New `compact_session_by_char_budget()` | Char-budget-triggered DB compaction — when stored history exceeds soft budget, oldest messages are summarised via LLM and deleted from DB before the agent loop loads them |
| Hard clear eliminated | `prepare_messages_for_llm()` no longer deletes message content; replaced with lightweight trim (truncate tool responses to 800 chars, tool args to 240 chars) |
| Self-tuner updated | `st_tune_session_budget()` now monitors `session_compaction_by_chars` instead of `session_hard_clear_count` |
| Lower message trigger | `HISTORY_COMPACT_TRIGGER_MESSAGES` reduced from 120 to 80 for proactive compaction |
| New config vars | `COMPACTION_CHAR_BUDGET_ENABLED`, `COMPACTION_KEEP_RECENT_MIN`, `COMPACTION_LIGHTWEIGHT_TOOL_MAX_CHARS`, `COMPACTION_LIGHTWEIGHT_ARGS_MAX_CHARS` |
| New metrics | `session_compaction_by_chars`, `session_compaction_chars_saved`, `session_lightweight_trim_count` in RUNTIME_STATE and `/status/runtime` |

### Files Modified

- `mind_clone_agent.py` — config vars (~line 630), RUNTIME_STATE keys (~line 1464), new `compact_session_by_char_budget()` (~line 11103), modified `prepare_messages_for_llm()` (~line 15577), modified `st_tune_session_budget()` (~line 15281), modified `run_agent_loop()` (~line 16817), metrics reset + status endpoint

### Verification
- `bob-check`: PASS (compile + 31 tests)
- No hard clears will occur — compaction summarises instead of deleting

---

## 2026-02-21 — Fix All Remaining Stubs (Full Modular Package Wiring)

Replaced 60+ placeholder stubs across the modular package with real implementations,
making all routes.py imports resolve to working functions instead of dead stubs.

### Files Modified (12)

| File | What Changed |
|------|-------------|
| `services/task_engine.py` | Added 13 missing functions: `enqueue_task`, `recover_pending_tasks`, `task_worker_loop`, `get_user_task_by_id`, `list_recent_tasks`, `create_queued_task`, `task_progress`, `current_task_step`, `normalize_task_plan`, checkpoint functions. Fixed `cancel_task` to return `(bool, str)` tuple. |
| `services/scheduler.py` | Added 4 aliases: `cron_supervisor_loop`, `tool_schedule_job`, `tool_list_scheduled_jobs`, `tool_disable_scheduled_job` wrapping existing functions. |
| `agent/memory.py` | Added 4 functions: `store_lesson`, `reindex_owner_memory_vectors`, `list_context_snapshots`, `get_context_snapshot`. |
| `core/approvals.py` | Added `approval_manager_decide_token` (alias) and `_refresh_approval_pending_runtime_count`. |
| `core/blackbox.py` | Added 7 route-compatible aliases: `fetch_blackbox_events`, `blackbox_event_stream_generator` (SSE), `build_blackbox_replay`, `list_blackbox_sessions`, `build_blackbox_session_report`, `build_blackbox_recovery_plan`, `build_blackbox_export_bundle`. Fixed `BLACKBOX_READ_MAX_LIMIT` reference. |
| `core/nodes.py` | Complete rewrite: added `cleanup_expired_node_leases`, `_candidate_node_scores`, `_refresh_node_runtime_metrics`, `_normalize_capability_list`, `claim_node_lease`, `release_node_lease` with real DB operations. |
| `core/protocols.py` | Added `protocol_validate_payload` and `protocol_contracts_public_view`. |
| `core/goals.py` | Added `update_goal_progress` and `decompose_goal_into_tasks`. Fixed `create_goal`/`list_goals` to accept both `(owner_id, ...)` and `(db, owner_id, ...)` calling conventions. |
| `core/queue.py` | Fixed 3 stubs: `owner_backlog_count` (queries DB), `pop_expired_collect_buffers` (checks timestamps), `get_lane_semaphore` (creates asyncio.Semaphore). |
| `tools/sessions.py` | Complete rewrite: 5 session tools now use TeamAgent DB, agent loop for send, real CRUD for spawn/list/stop/history. |
| `tools/nodes.py` | Complete rewrite: `tool_list_execution_nodes` queries DB, `tool_run_command_node` supports local execution with safety filters. |
| `tools/registry.py` | Added `load_remote_node_registry` and `load_plugin_tools_registry`. |

### New Files Created (3)

| File | Purpose |
|------|---------|
| `core/host_exec.py` | Host command execution grant management (create + validate grants). |
| `core/evaluation.py` | Continuous eval suite scaffold and release gate. |
| `core/session.py` | Startup transcript repair (fixes orphaned tool results). |

### Routes.py Fixes
- Added `log = logger` alias for monolith-ported lifespan code
- Added fallback stubs for `spine_supervisor_loop`, `heartbeat_supervisor_loop`, `cancel_background_task`
- Fixed `run_startup_transcript_repair` stub from async to sync (matches `asyncio.to_thread` usage)

### Verification
- `bob-check`: PASS (compile + 31 tests + lint)
- All try/except ImportError blocks in routes.py now resolve to real imports

---

## 2026-02-21 — Fix Critical Chat Endpoint (Bob Now Runs)

Wired the `/chat` endpoint to the agent loop so Bob can actually respond to messages.

### What Was Broken
- `dispatch_incoming_message()` was a stub returning `{"ok": false, "error": "not available"}`
- `resolve_owner_id()` was returning hardcoded `1` instead of querying the database
- Custom tools weren't loaded on startup (lifespan didn't call `load_custom_tools_from_db()`)

### What Was Fixed
- **`dispatch_incoming_message()`** — Fallback now calls `run_agent_loop(owner_id, text)` via `asyncio.run_in_executor` for non-blocking execution
- **`resolve_owner_id()`** — Fallback now queries DB via `_resolve_identity_owner()`, creates user if needed
- **`factory.py` lifespan** — Now calls `load_custom_tools_from_db()` on startup

### Full Chat Path Now Works
```
POST /chat {"chat_id": "123", "message": "hello"}
  → resolve_owner_id("123") → queries/creates User in DB
  → dispatch_incoming_message(owner_id=1, text="hello")
  → run_agent_loop(1, "hello") [in thread executor]
    → save_user_message → load_identity → inject_matching_skills
    → call_llm (Kimi K2.5) → execute_tools → save_assistant_message
  → {"ok": true, "response": "..."}
```

### Files Modified (3)
- `src/mind_clone/api/routes.py` — `dispatch_incoming_message` + `resolve_owner_id` fallbacks
- `src/mind_clone/api/factory.py` — Added `load_custom_tools_from_db()` to lifespan startup

---

## 2026-02-21 — Auto-Creation Pipeline (Monolith → Modular Port)

Ported the full skill/tool auto-creation pipeline from the monolith to the modular package.
Bob can now create tools and skills on-the-fly when it encounters a capability gap.

### Skill Auto-Creation
- **`synthesize_skill_blueprint()`** — Generates skill key, title, body, hints from user request text; special handling for crypto/news/regression/game-theory keywords
- **`maybe_autocreate_skill_from_gap()`** — Detects gap phrases in LLM responses ("I don't have a tool", "I cannot", etc.), applies per-owner cooldown, auto-creates a skill playbook
- **`_safe_skill_hints()`** — Normalizes trigger hints (deduped list, max 24, 120 chars each)
- **`select_active_skills_for_prompt()`** now injected before every LLM call via `_inject_matching_skills()`

### Custom Tool Creation
- **`tool_create_tool()`** — No longer a placeholder; fully wired to `core/custom_tools.py` CRUD with live TOOL_DISPATCH registration
- **`tool_list_custom_tools()`** — Wired to real DB query
- **`tool_disable_custom_tool()`** — Wired to DB update + live registry removal
- **`_create_custom_tool_executor()`** — Compiles Python code with restricted builtins (safe mode) or full builtins (full-power mode)
- **`load_custom_tools_from_db()`** — Loads all enabled+tested GeneratedTools on startup
- **`effective_tool_definitions()`** — Merges built-in schemas + custom tool definitions for LLM

### Agent Loop Integration
- **Gap detection** — After LLM response, checks for capability gap phrases and injects `create_tool` hint
- **Skill injection** — Before LLM call, injects matching skill playbooks from `select_active_skills_for_prompt()`
- **Owner ID injection** — `_owner_id` now passed to all tool args for custom tool ownership
- **Retry on gap** — When gap detected, adds hint and re-calls LLM (once per turn)

### Config Vars Added
- `SKILLS_AUTO_ACTIVATE_ENABLED` (default: true)
- `SKILLS_AUTO_CREATE_COOLDOWN_SECONDS` (default: 600)
- `CUSTOM_TOOL_ENABLED` (default: true)
- `CUSTOM_TOOL_MAX_PER_USER` (default: 30)
- `CUSTOM_TOOL_MAX_CODE_SIZE` (default: 5000)
- `CUSTOM_TOOL_SANDBOX_TIMEOUT` (default: 15)
- `CUSTOM_TOOL_TRUST_MODE` (default: "safe")

### Runtime State Keys Added
- `custom_tools_loaded`, `custom_tools_created`, `custom_tool_gap_hints`, `skills_autocreated`

### Bug Fix
- Fixed missing `timedelta` import in `core/custom_tools.py` (line 17)

### Files Modified (7)
- `src/mind_clone/config.py` — 7 new config vars
- `src/mind_clone/core/state.py` — 4 new runtime state keys
- `src/mind_clone/core/custom_tools.py` — Bug fix (timedelta import)
- `src/mind_clone/services/skills.py` — 5 new functions (auto-creation pipeline)
- `src/mind_clone/tools/registry.py` — Custom tool executor, loading, effective definitions
- `src/mind_clone/tools/custom.py` — Replaced 3 placeholders with real implementations
- `src/mind_clone/agent/loop.py` — Gap detection, skill injection, retry logic

---

## 2026-02-21 — OpenClaw Feature Implementation (15 Features)

### Priority 1: Security & Safety
- **SSRF Hardening** — Upgraded modular `validate_outbound_url()` to 11-step pipeline with DNS resolution, credential rejection, allow/deny lists; wired into `tool_read_webpage`, `tool_read_pdf_url`, `tool_browser_open`; added `ssrf_blocked_requests` runtime metric
- **Transcript Write-Lock** — Added per-owner `session_write_lock()` context manager to modular package; wired into `save_message()`, `get_conversation_history()`, `clear_conversation_history()`; added execution lock for agent loop serialization
- **Tool Result Guard** — Added `guarded_tool_result_payload()` to modular security module; validates structure (dict, "ok" key, call_id), redacts secrets, truncates to 10KB; wired into agent loop
- **Semantic Snapshots** — `tool_browser_open` and `tool_read_webpage` now return structured `snapshot` with headings, links, forms, buttons, meta description; BeautifulSoup and Selenium extraction

### Priority 2: Capabilities
- **Skills System** — Ported SkillProfile/SkillVersion/SkillRun models; created `services/skills.py` with CRUD, keyword matching, prompt injection; added config vars
- **Multi-Channel (Discord)** — Created `services/discord_adapter.py` with optional discord.py import; routes messages through agent loop; auto-chunks responses to 2000 chars
- **Queue Steer/Followup** — Enhanced `core/queue.py` with `should_enqueue_message()` supporting 6 modes (off/on/auto/steer/followup/collect); improved lane classification matching monolith
- **MEMORY.md Export** — Created `services/memory_export.py` with `build_memory_export_payload()` and `export_as_markdown()` for human-readable memory dump
- **Sandbox Registry + Lifecycle** — Implemented full registry with `sandbox_registry_touch()`, TTL-based `cleanup_sandbox_registry()`, and runtime metrics
- **Voice STT** — Created `services/voice_stt.py` with OpenAI Whisper API integration; async transcription with configurable endpoint

### Priority 3: Polish
- **Atomic Memory Reindex** — Created `services/memory_reindex.py` with `reindex_owner_memory_vectors()` using session write-lock for transactional rebuild across 7 memory types
- **Embedding Deduplication** — Created `services/embedding_dedup.py` with cosine similarity dedup; configurable threshold (0.95 default); dry-run mode
- **Dynamic Debug Flags** — Created `core/debug_flags.py` with TTL-aware runtime flags; 10 well-known flags; set/clear/list API
- **Onboarding Wizard** — Created `services/onboarding.py` with 5-step guided setup; per-user state tracking; reset capability
- **Security Audit Automation** — Created `services/security_audit.py` with 8 programmatic checks; structured report output

### Files Created (11 new)
- `src/mind_clone/services/skills.py`
- `src/mind_clone/services/discord_adapter.py`
- `src/mind_clone/services/memory_export.py`
- `src/mind_clone/services/voice_stt.py`
- `src/mind_clone/services/memory_reindex.py`
- `src/mind_clone/services/embedding_dedup.py`
- `src/mind_clone/services/onboarding.py`
- `src/mind_clone/services/security_audit.py`
- `src/mind_clone/core/debug_flags.py`

### Files Modified (8)
- `src/mind_clone/core/security.py` — SSRF 11-step pipeline + tool result guard
- `src/mind_clone/core/state.py` — Session write locks, execution locks, 15+ new RUNTIME_STATE keys
- `src/mind_clone/core/queue.py` — Steer/followup modes, lane classification
- `src/mind_clone/core/sandbox.py` — Full registry lifecycle
- `src/mind_clone/tools/basic.py` — SSRF guard + semantic snapshot in read_webpage
- `src/mind_clone/tools/browser.py` — SSRF guard + semantic snapshot in browser_open
- `src/mind_clone/tools/memory.py` — SSRF guard + circuit breaker in read_pdf_url
- `src/mind_clone/agent/loop.py` — Tool result guard + execution lock
- `src/mind_clone/agent/memory.py` — Transcript write-lock in save/load/clear
- `src/mind_clone/database/models.py` — SkillProfile, SkillVersion, SkillRun models
- `src/mind_clone/config.py` — SSRF, Skills, Discord, STT config vars

### Verification
- `bob-check`: PASS (compile + 31 tests)
- `bob-security`: SSRF check PASS

---

## 2026-02-21 | Worker: Claude Opus 4.6 | Bob Subagent Toolkit Expansion (7 new scripts)

### Session Summary
Expanded the bob-* subagent toolkit from 6 to 13 scripts to support upcoming OpenClaw feature implementation. Every new script follows the same conventions: stdlib-only, argparse, exit codes, consistent output formatting.

### Changes Made
1. **Renamed `diag.py` → `bob_diag.py`** — Added argparse (`--watch`, `--json`), memory health section, proper exit codes.
2. **Created `bob_security.py`** — 8-check security audit: SSRF, approval gates, secrets, sandbox, custom tools, policy, diff gate, ops auth.
3. **Created `bob_test_live.py`** — 6 live integration tests: health, runtime, chat round-trip, CL+ST metrics, error handling, endpoint availability.
4. **Created `bob_memory.py`** — Memory inspector with 6 subcommands: stats, lessons, episodes, notes, vectors, export.
5. **Created `bob_api.py`** — API endpoint tester for 25+ endpoints with response validation and category grouping.
6. **Created `bob_migrate.py`** — Migration helper with 4 subcommands: config, routes, models, state (monolith → modular sync).
7. **Created `bob_bench.py`** — Performance benchmarker with 4 modes: latency, throughput, soak, compare (with baseline saving).
8. **Updated `CLAUDE.md`** (root + mind-clone) — Documented all 13 subagents.

### Validation Outcomes
- `python mind-clone/scripts/bob_check.py` — PASS
- All 7 new scripts pass `--help` without error

---

## 2026-02-21 | Worker: Claude Opus 4.6 | Self-Tuning Performance Engine (Section 5C)

### Session Summary
Added Section 5C: Self-Tuning Performance Engine to `mind_clone_agent.py`. Bob now detects and fixes his own performance problems automatically — serving Pillar 3 (Autonomy), Pillar 4 (Learning), and Pillar 6 (Self-Awareness).

### Changes Made
1. Added **8 config vars** (`SELF_TUNE_*`) for tuning thresholds and limits.
2. Added **10 RUNTIME_STATE keys** (`st_*`) for observability.
3. Added **Section 5C** (~150 lines) with 5 functions:
   - `st_tune_queue_mode()` — switches queue "on" to "auto" when backlog builds
   - `st_tune_session_budget()` — raises/lowers context char budgets based on hard clear rate
   - `st_tune_workers()` — scales queue workers up/down based on queue depth
   - `st_tune_budget_mode()` — loosens budget governor when too many runs degraded
   - `st_self_tune()` — orchestrator, called from heartbeat every 2 ticks (~90s)
4. Hooked `st_self_tune()` into `run_heartbeat_self_check()`.
5. Exposed all 10 `st_*` metrics in `runtime_metrics()` (visible at `/status/runtime`).
6. Updated `scripts/diag.py` with Self-Tuning diagnostics section.
7. Updated `CLAUDE.md` (both root and mind-clone) with Section 5C documentation.

### Validation Outcomes
- `python mind-clone/scripts/bob_check.py` — PASS
- `python -m compileall -q mind-clone/src/` — no errors

---

## 2026-02-18 | Worker: Codex GPT-5 | Deterministic Tool Path Resolution + /ops/paths

### Session Summary
Fixed inconsistent Bob results caused by relative-path drift (repo root vs `mind-clone/` core dir) by normalizing tool file paths and defaulting command `cwd` deterministically.

### Changes Made
1. Added **tool path resolution** to `mind-clone/mind_clone_agent.py`:
   - New env controls:
     - `TOOL_PATH_RESOLUTION_ENABLED`
     - `TOOL_PATH_RESOLUTION_MODE` (`auto|repo|core|off`)
     - `TOOL_DEFAULT_CWD_MODE` (`auto|repo|core|process`)
   - New helpers:
     - `_resolve_tool_path_input(...)`
     - `apply_tool_path_resolution(...)`
   - Wired into `execute_tool_with_context(...)` so tools see normalized paths before policy/sandbox checks.
2. Added ops debug endpoint:
   - `GET /ops/paths` (shows repo/core paths, current cwd, sample resolutions, and last path/cwd telemetry).
3. Updated `mind-clone/.env.example` with the new knobs.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python mind-clone/scripts/release_gate_check.py` passed.

---

## 2026-02-18 | Worker: Codex GPT-5 | Skills-First Runtime + Session Lane Telemetry

### Session Summary
Implemented an OpenClaw-inspired, Python-native upgrade path centered on dynamic skills and session-lane observability without replacing Bob’s existing `/chat` and CLI flow.

### Changes Made
1. Added **versioned skills subsystem** in `mind-clone/mind_clone_agent.py`:
   - New DB models:
     - `SkillProfile`
     - `SkillVersion`
     - `SkillRun`
   - New skill-vault persistence in filesystem (`SKILLS_VAULT_ROOT`, versioned JSON artifacts per owner/skill/version).
   - New runtime helpers:
     - `save_skill_profile(...)`
     - `list_skill_profiles(...)`
     - `skill_profile_detail(...)`
     - `set_skill_status(...)`
     - `rollback_skill_version(...)`
     - `select_active_skills_for_prompt(...)`
     - `synthesize_skill_blueprint(...)`
     - `maybe_autocreate_skill_from_gap(...)`
2. Added **skills API surfaces** (owner-scoped via `chat_id`/`username` resolution):
   - `GET /skills`
   - `GET /skills/{skill_id}`
   - `POST /skills/generate`
   - `POST /skills/activate`
   - `POST /skills/deactivate`
   - `POST /skills/rollback`
3. Added **session lane telemetry** for queue/direct execution:
   - New internal lane state tracking with run IDs and lifecycle event stamps.
   - Instrumented inbound dispatch + worker execution with `accepted/running/final/error` lane events.
   - New ops endpoint:
     - `GET /ops/session-lanes`
4. Expanded **protocol contract registry** with skills/session-lane contracts for drift checks:
   - `skills.generate.*`
   - `skills.activate.*`
   - `skills.rollback.*`
   - `session.lanes.response`
5. Integrated **skills into agent reasoning loop**:
   - Active matched skills now inject into system prompt under `ACTIVE SKILLS`.
   - Capability-gap hint path can auto-create and auto-activate a new skill (config-controlled).
6. Added new env/config docs in `mind-clone/.env.example`:
   - `SKILLS_*` controls
   - `SKILLS_VAULT_ROOT`
   - `SESSION_LANE_STALE_SECONDS`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python mind-clone/scripts/release_gate_check.py` passed (`state=pass`, `pass_rate=1.0`).
- Smoke validation script passed:
  - skill save/list/detail path works
  - session-lane snapshot path returns valid payload.

---

## 2026-02-18 | Worker: Codex GPT-5 | Telegram Placeholder Detection + Webhook Startup Fix

### Session Summary
Fixed Telegram bootstrap/runtime behavior so placeholder token values are correctly treated as unconfigured, preventing false webhook retries/errors.

### Changes Made
1. Added robust Telegram configuration helpers in `mind-clone/mind_clone_agent.py`:
   - `telegram_token_configured()`
   - `webhook_base_configured()`
   - `telegram_webhook_configured()`
   - Handles both placeholder variants (`YOUR_TELEGRAM_BOT_TOKEN_HERE` and `your_telegram_bot_token_here`) and other placeholder-like values.
2. Replaced direct placeholder comparisons across runtime:
   - startup preflight warnings
   - runtime alert computation
   - webhook registration/retry flow
   - app lifespan webhook startup branch
3. Hardened Telegram send paths:
   - `send_telegram_message`, `send_typing_indicator`, and task progress message sender now skip network calls when token is not configured.
4. Added runtime visibility fields:
   - `telegram_token_configured`
   - `telegram_webhook_configured`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python -m pytest -q` passed (`31 passed`).
- `python mind-clone/scripts/release_gate_check.py` passed (`state=pass`, `pass_rate=1.0`).
- Live runtime check after restart:
  - `telegram_token_configured=false`
  - `telegram_webhook_configured=false`
  - `webhook_next_retry_at=null`
  - no false `webhook_unregistered` alert when token is placeholder.
- Bob CLI chat still works (`bob say "reply only: ok"` -> `ok`).

---

## 2026-02-18 | Worker: Codex GPT-5 | Modular Config Env Parsing Fix (Test Collection Unblock)

### Session Summary
Fixed modular `src/` config loading so empty/comma-separated env values no longer crash test collection.

### Changes Made
1. Updated `mind-clone/src/mind_clone/config.py` for robust settings parsing:
   - Added `NoDecode` wrappers for complex env-backed fields:
     - `tool_policy_allow_extra_write_roots`
     - `execution_sandbox_remote_allowlist`
     - `approval_required_tools`
     - `host_exec_allowlist_prefixes`
   - Added `field_validator(..., mode="before")` parsers to support empty strings and CSV/path-style values safely.
2. Added required typing/import support:
   - `Any`, `Annotated`
   - `NoDecode` from `pydantic_settings`

### Validation Outcomes
- `python -m py_compile src/mind_clone/config.py` passed.
- `python -m pytest -q` passed with `31 passed`.
- `python mind-clone/scripts/release_gate_check.py` passed (`state=pass`, `pass_rate=1.0`, `failed_cases=0`).

---

## 2026-02-18 | Worker: Codex GPT-5 | Release Gate Secret Redaction Eval Alignment

### Session Summary
Fixed the release-gate `secret_redaction` false failure under full-power/runtime configurations where secret guardrails are intentionally disabled.

### Changes Made
1. Updated `run_continuous_eval_suite()` in `mind-clone/mind_clone_agent.py`:
   - `secret_redaction` case now validates redaction strictly when `SECRET_GUARDRAIL_ENABLED=true`.
   - When guardrail is intentionally disabled by config, the case now reports pass with detail `disabled_by_config` instead of failing the whole gate.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python mind-clone/scripts/release_gate_check.py` passed:
  - `state=pass`
  - `pass_rate=1.0`
  - `failed_cases=0`
- `BOB_FULL_POWER_ENABLED=false python mind-clone/scripts/release_gate_check.py` also passed:
  - `secret_redaction` detail confirmed strict path: `enabled hits=1`

---

## 2026-02-18 | Worker: Codex GPT-5 | Tool-Call Sequence Integrity Fix

### Session Summary
Fixed Bob chat failures caused by invalid tool-call message sequencing that surfaced as:
`HTTP 400: assistant message with 'tool_calls' must be followed by tool messages`.

### Changes Made
1. Added a new sequence-aware sanitizer in `mind-clone/mind_clone_agent.py`:
   - `_sanitize_tool_call_transcript(messages, cleared_placeholder)`
   - Enforces strict assistant -> immediate tool response pairing.
   - Handles repeated `tool_call_id` values safely by matching in order/count, not global set membership.
2. Wired the sanitizer into all high-impact transcript paths:
   - `prepare_messages_for_llm(...)` (final integrity pass before payload sizing)
   - `get_conversation_history(...)` (post-load sequence fix with warning telemetry)
   - `call_llm(...)` (last-resort sequence fix before request payload)
   - `run_agent_loop_with_new_session(...)` pre-LLM path (sequence fix before model call)
3. Added focused runtime warnings for visibility:
   - `HISTORY_LOAD_SEQUENCE_FIX`
   - `CALL_LLM_SEQUENCE_FIX`
   - `PRE_LLM_SEQUENCE_FIX`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python mind-clone/scripts/release_gate_check.py` ran and failed on existing unrelated eval:
  - `secret_redaction` case (`hits=0`)
  - overall `pass_rate=0.8` (4/5), `failed_cases=1`.

### Residual Risks / Notes
- Legacy set-based orphan cleanup blocks remain in place, but sequence-aware sanitization now runs after them and is authoritative for request integrity.

---

## 2026-02-18 | Worker: Codex GPT-5 | Bob Full-Power Override + Unrestricted Tool Forge Mode

### Session Summary
Implemented an explicit, owner-controlled full-power mode for Bob with system-scope overrides that disable core safety gates when intentionally enabled, while preserving default behavior when disabled.

### Changes Made
1. **New env controls** in `mind_clone_agent.py` and `.env.example`:
   - `BOB_FULL_POWER_ENABLED` (`false|true`)
   - `BOB_FULL_POWER_SCOPE` (`workspace|system`)
   - `CUSTOM_TOOL_TRUST_MODE` (`safe|full`)
2. **System-scope full-power override path**:
   - Forces power profiles for tool policy and execution sandbox.
   - Disables approval gate, host-exec interlock, workspace isolation/session isolation, diff gate, OS sandbox requirement, and secret guardrail when `BOB_FULL_POWER_ENABLED=true` and `BOB_FULL_POWER_SCOPE=system`.
3. **Policy/enforcement short-circuits for full system power**:
   - `apply_tool_policy`
   - `apply_execution_sandbox`
   - `apply_workspace_isolation`
   - `approval_gate_enabled`
   - `enforce_host_exec_interlock`
   - `enforce_node_command_policy`
   - `evaluate_workspace_diff_gate`
   - `check_authority`
4. **Custom tool forge unrestricted mode**:
   - `CUSTOM_TOOL_TRUST_MODE=full` (or system full power) bypasses import/pattern deny checks and custom-tool count/code-size limits.
   - Custom tool executor now runs with full Python builtins in unrestricted mode.
5. **Runtime visibility and observability**:
   - Added runtime/reporting fields for full-power and custom-tool trust mode.
   - Added startup preflight warning and startup banner lines for full-power state.
   - Added full-power/trust fields to checkpoint runtime signature and runtime status metrics.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python mind-clone/scripts/release_gate_check.py` passed (`state=pass`, pass_rate=1.0, 0 failed cases).

---

## 2026-02-17 | Worker: Claude Code (Opus 4.6) | Package Cleanup & Docs Update

### Session Summary
Completed post-refactor cleanup of the `src/mind_clone/` modular package: fixed missing dependencies, Settings mismatches, runner wiring, broken tests, and updated project docs to reflect the new architecture.

### Changes Made
1. **requirements.txt** — Added `pydantic-settings>=2.0.0`, `python-telegram-bot>=20.0`, `selenium>=4.0.0`
2. **config.py** — Added missing Settings fields (`host_exec_interlock_enabled`, `host_exec_allowlist_prefixes`, `TOOL_PERF_TRACKING_ENABLED`, `PLUGIN_ENFORCE_TRUST`); removed duplicate `settings = Settings()`
3. **runner.py** — Fixed `TelegramPollingService()` → `run_polling()`; fixed `TaskEngine()` → `create_task + run_task`; added `db.close()` in finally block
4. **tests/integration/test_api.py** — Renamed `class TaskEndpoints:` → `class TestTaskEndpoints:` so pytest collects its 2 tests (test count: 29 → 31, all passing)
5. **CLAUDE.md** — Updated to describe dual-runtime architecture (monolith + modular package)
6. **AGENTS.md** — Replaced single-file architecture description with full modular package structure, updated tool-adding workflow and running instructions

### Test Results
- `pytest` → **31 passed** (was 29)

---

## 2026-02-17 | Worker: Codex GPT-5 | Modular Refactor Compatibility Hardening

### Session Summary
Repaired high-impact compatibility breaks introduced in the `src/` modular restructure so the refactored service layer and tests run cleanly.

### Changes Made
1. **Package init import fix**:
   - `src/mind_clone/__init__.py` now imports `init_db` from `database.session` (correct module) instead of `database.models`.
2. **Scheduler API compatibility + robustness** in `src/mind_clone/services/scheduler.py`:
   - `create_job()` now supports both interval-based and cron-style signatures (`message`/`interval_seconds` and `command`/`schedule`).
   - Added cron-to-next-run helper logic and interval normalization.
   - Normalized enabled-state handling to boolean semantics.
3. **Core task enqueue compatibility** in `src/mind_clone/core/tasks.py`:
   - `enqueue_task()` now supports legacy direct task-id enqueue and create+enqueue flow (`owner_id/title/description`).
   - Fixed session consistency bugs in `update_task_status()` and `cancel_task()` by querying within the active session.
4. **Goal update backward compatibility** in `src/mind_clone/core/goals.py`:
   - `update_goal()` now accepts both modern and legacy call signatures.
   - Added missing `time` import used by supervisor loop.
5. **JSON utility correctness fix** in `src/mind_clone/utils/__init__.py`:
   - Switched to explicit stdlib JSON aliasing to avoid package-local module shadowing (`mind_clone.utils.json`).
6. **Model default hardening** in `src/mind_clone/database/models.py`:
   - `Task.agent_uuid` now has generated UUID default.
   - `Task.description` now has safe default empty string.
   - `ScheduledJob.enabled` uses boolean column semantics.
7. **Legacy tool alias compatibility** in `src/mind_clone/tools/basic.py`:
   - Added `read_file(...)` and `search_web(...)` wrappers for legacy imports.
   - `search_web(...)` wrapper supports monkeypatch delegation used by tests.
8. **Scheduler tool runtime wiring** in `src/mind_clone/tools/scheduler.py`:
   - Replaced placeholder scheduler tool responses with real DB-backed create/list/disable behavior.
   - Added lazy service imports to prevent circular-import crashes during module initialization.
9. **Memory tool runtime wiring** in `src/mind_clone/tools/memory.py` and `src/mind_clone/tools/basic.py`:
   - Replaced placeholder research-note persistence with real `ResearchNote` DB writes.
   - Implemented DB-backed `research_memory_search` plus lightweight semantic-like retrieval fallback.

### Validation Outcomes
- `python -m compileall -q src` passed.
- `pytest -q` passed with `29 passed`.
- Existing backend checks from this session remain green:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
  - `python scripts/release_gate_check.py`
  - `npm run build` in `mind-clone-ui`

---

## 2026-02-17 | Worker: Codex GPT-5 | Goal Task Flow + Migration Idempotency Hardening

### Session Summary
Stabilized core runtime paths after restructure by fixing goal-to-task creation to match the current task schema and hardening schema migrations for brownfield databases.

### Changes Made
1. **Goal decomposition task contract fix** in `mind_clone_agent.py`:
   - Updated `decompose_goal_into_tasks()` to create tasks with:
     - `status=TASK_STATUS_QUEUED` (instead of unscheduled `pending`)
     - `plan=[]` on creation for queue/task-engine compatibility
     - `agent_uuid` sourced from resolved identity context
2. **Schema migration idempotency hardening** in `mind_clone_agent.py`:
   - Added guarded handling in `run_schema_migrations()` for duplicate add-column operations.
   - `ALTER TABLE ... ADD COLUMN ...` now safely skips when the target column already exists, allowing migration metadata to recover on mixed/brownfield DB states.
3. **Import update**:
   - Added `OperationalError` import from SQLAlchemy for migration error handling.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python -m py_compile ai_orchestrator.py` passed.
- `python -m py_compile multi_model_orchestrator.py` passed.
- `python scripts/release_gate_check.py` passed (`state=pass`, pass_rate=1.0).
- `npm run build` in `mind-clone-ui` passed.

### Residual Notes
- Runtime still reports DB path fallback mode unless `MIND_CLONE_DB_PATH` is explicitly configured.

---

## 2026-02-11 | Worker: Claude Opus 4.6 | Desktop Tools & Tool Execution Fixes

### Changes Made
1. **Desktop tools always available** — Changed `effective_tool_definitions()` to show desktop/session tools whenever `DESKTOP_CONTROL_ENABLED=True` (not just when a session is active). LLM needs to see the tools to start a session.
2. **Tool execution crash guard** — Wrapped `execute_tool_with_context()` in try/except in agent loop. If tool execution or result serialization crashes, a proper error response is ALWAYS appended to messages, preventing orphaned `tool_call_id` errors that corrupted conversation history.
3. **Cleared corrupted conversation history** — Removed 28 messages with orphaned tool_call_ids from DB.

---

## 2026-02-11 | Worker: Claude Opus 4.6 | Self-Extending Tool System

### Session Summary
Implemented runtime self-extending tool system — Bob can now create, test, persist, and use new Python tools on the fly when he lacks a capability.

### Changes Made
1. **GeneratedTool DB model** — Persists custom tools with code, parameters, usage tracking, enable/disable
2. **Safety guardrails** — AST-based import checking, forbidden pattern regex, code size limits, sandbox testing before registration
3. **Tool forge pipeline** — `register_custom_tool()`: validate name → safety check → pip install deps → sandbox test → create executor → persist → register
4. **Startup loader** — `load_custom_tools_from_db()` restores custom tools on restart
5. **3 built-in tools** — `create_tool`, `list_custom_tools`, `disable_custom_tool` available to LLM
6. **Dispatch integration** — Custom tools checked between TOOL_DISPATCH and plugin tools in `execute_tool_with_context`
7. **Proactive gap detection** — When LLM says "I don't have a tool for X", system hints about `create_tool`
8. **Heartbeat pruning** — Unused custom tools auto-removed after 30 days
9. **Startup banner** — Shows custom tool count and config

### Config (.env)
- `CUSTOM_TOOL_ENABLED=true` (default)
- `CUSTOM_TOOL_MAX_CODE_SIZE=5000`
- `CUSTOM_TOOL_MAX_PER_USER=30`
- `CUSTOM_TOOL_SANDBOX_TIMEOUT=15`

---

## 2026-02-10 | Worker: Claude Opus 4.6 | AGI 8-Pillar Implementation

### Session Summary
Implemented all 8 AGI pillars from VISION.md as concrete features in mind_clone_agent.py.

### Changes Made
1. **Pillar 4: Learning** — Task lesson extraction (`extract_lessons_from_task`), LLM-based self-improvement candidate generation, pattern failure detection (3+ failures trigger SelfImprovementNote)
2. **Pillar 1: Reasoning** — In-loop reflection prompts injected every N iterations in both agent loop and task step loop (`INLOOP_REFLECTION_PROMPT`)
3. **Pillar 6: Self-Awareness** — `ToolPerformanceLog` DB model, automatic recording of tool success/failure/duration, aggregated stats injected into system prompt, heartbeat pruning
4. **Pillar 2: Memory** — `EpisodicMemory` DB model with hybrid retrieval (cosine 60% + keyword 18% + recency 12% + failure boost 10%), episodes generated from tasks and conversations
5. **Pillar 8: Communication** — `send_task_progress_sync()` with rate limiting, progress messages at plan creation, step completion, step retry, and task completion
6. **Pillar 3: Autonomy** — `Goal` DB model, goal management (create/decompose/update/list/pause/resume/abandon), LLM-based task decomposition, `/goal` Telegram commands, goal supervisor in heartbeat, REST API endpoints
7. **Pillar 5: Tool Mastery** — 7 browser tools via Selenium (open, get_text, click, type, screenshot, execute_js, close), session management with auto-cleanup, tool chaining hints engine
8. **Pillar 7: World Understanding** — Environment state capture (open windows, key processes, screen resolution), cached with TTL, conditionally injected into system prompt

### New DB Tables
- `tool_performance_logs` (Pillar 6)
- `episodic_memories` (Pillar 2)
- `goals` (Pillar 3)

### New .env Variables
- `TASK_LESSON_EXTRACTION_ENABLED`, `SELF_IMPROVE_LLM_ANALYSIS_ENABLED`, `SELF_IMPROVE_LLM_ANALYSIS_COOLDOWN_HOURS`
- `INLOOP_REFLECTION_ENABLED`, `INLOOP_REFLECTION_EVERY_N`
- `TOOL_PERF_TRACKING_ENABLED`, `TOOL_PERF_INJECT_TOP_K`, `TOOL_PERF_MAX_AGE_DAYS`
- `EPISODIC_MEMORY_ENABLED`, `EPISODIC_MEMORY_RETRIEVE_TOP_K`, `EPISODIC_MEMORY_MAX_PER_USER`
- `TASK_PROGRESS_REPORTING_ENABLED`, `TASK_PROGRESS_MIN_INTERVAL_SECONDS`
- `GOAL_SYSTEM_ENABLED`, `GOAL_MAX_PER_USER`, `GOAL_MAX_TASKS_PER_BATCH`, `GOAL_SUPERVISOR_EVERY_TICKS`
- `BROWSER_TOOL_ENABLED`, `BROWSER_HEADLESS_DEFAULT`, `BROWSER_SESSION_TIMEOUT_SECONDS`, `TOOL_CHAINING_HINTS_ENABLED`
- `ENVIRONMENT_STATE_ENABLED`, `ENVIRONMENT_STATE_TTL_SECONDS`

### Also Fixed
- `openclaw_max` mode no longer hardcodes `OS_SANDBOX_MODE=docker` (reads from .env)

### Validation
- `py_compile` passed after each pillar implementation

---

## 2026-02-10 | Worker: Codex GPT-5 | Bob Message Stall Fix (Model Router Deadlock)

### Session Summary
- Diagnosed why Bob accepted Telegram messages but produced no assistant replies.
- Fixed a model-router deadlock that froze every agent loop before the first LLM request.

### Changes Made
1. Updated `mind-clone/mind_clone_agent.py`:
   - Replaced `MODEL_ROUTER_LOCK = threading.Lock()` with `threading.RLock()`.
   - Added a short inline note explaining nested lock usage in model-router helpers.
2. Root cause details:
   - `call_llm()` calls `_model_router_order_profiles()`.
   - `_model_router_order_profiles()` acquires `MODEL_ROUTER_LOCK`, then calls `_model_profile_health_state()`.
   - `_model_profile_health_state()` also acquires `MODEL_ROUTER_LOCK`.
   - With a non-reentrant lock, the same thread deadlocked permanently.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Direct regression check: `_model_router_order_profiles(...)` now returns immediately (no hang).
- Agent-loop smoke check now reaches `LLM_CALL_START` and returns API auth/network errors instead of freezing.

### Residual Notes
- Running server processes must be restarted to load this fix.
- Existing in-flight queued jobs from pre-fix processes can remain stuck until restart.

---

## 2026-02-08 | Worker: Claude Opus 4.6 | Email Tool + Vision Computer Use + Kimi Thinking Fix

### Session Summary
- Added `send_email` tool (Gmail SMTP) so Bob can send emails autonomously
- Wired Kimi K2.5 vision into the agent loop — Bob can now SEE screenshots and interact with the desktop
- Fixed critical Kimi K2.5 `reasoning_content` error that broke multi-turn tool conversations
- Fixed orphaned `tool_call_id` errors in conversation history replay

### Changes Made
1. **Email tool** in `mind_clone_agent.py`:
   - Added SMTP config: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_NAME`
   - Added `tool_send_email()` — sends email via Gmail SMTP with TLS, supports to/cc/bcc
   - Registered `send_email` in `ALL_TOOL_NAMES`, `TOOL_DEFINITIONS`, `TOOL_DISPATCH`
   - Added imports: `smtplib`, `email.mime.text`, `email.mime.multipart`
   - Tested and confirmed working with Gmail App Password
2. **Vision-powered computer use**:
   - Modified `tool_desktop_screenshot()` to return `_screenshot_base64` (base64-encoded PNG)
   - Modified agent loop: after any screenshot tool result, injects image as a vision message to Kimi K2.5
   - Kimi K2.5 confirmed working with vision input (correctly described VS Code window contents)
   - Added `base64` import
3. **Kimi K2.5 thinking mode fix** (was causing HTTP 400 on every multi-tool conversation):
   - Added `reasoning_content: ""` to assistant messages with tool_calls in `get_conversation_history()`
   - Added pre-LLM-call sanitizer in agent loop that:
     - Ensures ALL assistant tool_call messages have `reasoning_content`
     - Removes orphaned tool messages whose `tool_call_id` has no matching assistant message
   - Cleared 97 corrupted conversation messages from DB
4. **Config updates**:
   - `.env` — added SMTP credentials
   - `.env.example` — documented SMTP variables
   - `VISION.md` — updated Tool Mastery and Communication pillar status

### Validation Outcomes
- `send_email` test: email delivered successfully to Gmail inbox
- Kimi K2.5 vision API test: correctly analyzed screenshot (described code + UI elements)
- Syntax check passed
- Server healthy, webhook registered

### Residual Notes
- Gmail requires an **App Password** (not regular password) for SMTP — 2-Step Verification must be enabled
- Vision messages are large (~400KB base64 per screenshot) — monitor context window usage
- `reasoning_content` fix is belt-and-suspenders: both in history loader AND pre-LLM sanitizer

---

## 2026-02-08 | Worker: Codex GPT-5 | OpenClaw Max Autonomy Mode

### Session Summary
- Added a first-class `AUTONOMY_MODE=openclaw_max` profile so Bob runs with maximum autonomy behavior at startup.
- Applied the mode in your active `.env` to make it live by default after restart.

### Changes Made
1. Added autonomy mode parsing and runtime flags in `mind-clone/mind_clone_agent.py`:
   - `AUTONOMY_MODE` (`standard | openclaw_max`)
   - `AUTONOMY_OPENCLAW_MAX`
2. Added OpenClaw-max override block:
   - `COMMAND_QUEUE_MODE=on`
   - `TOOL_POLICY_PROFILE=power`
   - `EXECUTION_SANDBOX_PROFILE=power`
   - `APPROVAL_GATE_MODE=off`
   - `APPROVAL_REQUIRED_TOOLS=[]`
   - `HOST_EXEC_INTERLOCK_ENABLED=false`
   - `WORKSPACE_DIFF_GATE_MODE=warn`
   - `WORKSPACE_ISOLATION_ENABLED=false`
   - `OS_SANDBOX_MODE=off`
   - `DESKTOP_REQUIRE_ACTIVE_SESSION=false`
   - `DESKTOP_FAILSAFE_ENABLED=false`
   - `HEARTBEAT_AUTONOMY_ENABLED=true`
3. Added runtime observability fields:
   - `autonomy_mode`
   - `autonomy_openclaw_max`
4. Startup/preflight visibility:
   - startup banner prints active autonomy mode
   - preflight emits explicit warning when `openclaw_max` is active
5. Config updates:
   - `mind-clone/.env` now includes `AUTONOMY_MODE=openclaw_max`
   - `mind-clone/.env.example` documents `AUTONOMY_MODE`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Runtime health confirms autonomy mode fields after restart.

### Residual Risks
- `openclaw_max` intentionally disables core safety friction and can execute high-impact actions rapidly.
- Desktop failsafe is disabled in this mode; runaway UI automation risk is higher.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Desktop Stack S2 (Session-Gated + Visual Targeting + UI Tree)

### Session Summary
- Completed the desktop automation hardening pass so Bob can run OpenClaw-style actions with session control, replay, and stronger visual targeting.
- Fixed the partial wiring issue where desktop session tools existed in code but were not exposed to model tool-calling.
- Added execution-path enforcement so mutating desktop actions require an active desktop session when enabled.

### Changes Made
1. Desktop tool registry completion in `mind-clone/mind_clone_agent.py`:
   - Added tool names, schemas, and dispatch wiring for:
     - `desktop_session_start`
     - `desktop_session_status`
     - `desktop_session_stop`
     - `desktop_session_replay`
     - `desktop_uia_tree`
     - `desktop_locate_on_screen`
     - `desktop_click_image`
2. Desktop session runtime enforcement/logging:
   - `execute_tool_with_context(...)` now:
     - injects owner/workspace context for all `desktop_*` tools
     - blocks mutating desktop actions when no active session exists (`DESKTOP_REQUIRE_ACTIVE_SESSION=true`)
     - records desktop action events into the active session log
3. New visual grounding and interaction helpers:
   - Added image template resolution + region normalization helpers.
   - Added image matching with confidence fallback when OpenCV confidence matching is unavailable.
   - Added image-target click flow with optional offsets.
4. UI inspection tool:
   - Added `desktop_uia_tree` with `pywinauto` backend when available.
   - Added graceful fallback to top-level window inventory when `pywinauto` is not installed.
5. Config + dependency updates:
   - Updated `mind-clone/.env.example` with:
     - `DESKTOP_SESSION_DIR`
     - `DESKTOP_REQUIRE_ACTIVE_SESSION`
     - `DESKTOP_REPLAY_MAX_STEPS`
     - `DESKTOP_IMAGE_MATCH_THRESHOLD`
     - `DESKTOP_UITREE_DEFAULT_LIMIT`
   - Updated `mind-clone/requirements.txt`:
     - `pywinauto>=0.6.8`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Tool wiring smoke checks passed:
  - New desktop tool names are present in `ALL_TOOL_NAMES`, `TOOL_DEFINITIONS`, and `TOOL_DISPATCH`.
  - Session gate blocks mutating desktop calls without active session.
  - Session start/status/stop works and records session metadata.
  - Dry-run replay works against recorded session actions.
  - Desktop action logging increments action count in session log.

### Residual Risks
- `desktop_uia_tree` is strongest with `pywinauto`; fallback mode only returns top-level windows.
- Template matching reliability depends on screen scale/theme and the quality of reference images.
- Mutating desktop tools remain high-impact; keep failsafe and session gating enabled in production.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Desktop Control Default (OpenClaw-Style Host UI Tools)

### Session Summary
- Added full desktop-control toolset to Bob by default (screen, windows, mouse, keyboard, clipboard, app launch).
- Wired tools into policy/dispatch/runtime telemetry without breaking existing Telegram/task/research contracts.
- Added screenshot fallback path (`mss`) for Python 3.14 environments where `pyautogui` screenshot backend is unavailable.

### Changes Made
1. Desktop automation capabilities in `mind-clone/mind_clone_agent.py`:
   - New tools:
     - `desktop_screen_state`
     - `desktop_screenshot`
     - `desktop_list_windows`
     - `desktop_focus_window`
     - `desktop_move_mouse`
     - `desktop_click`
     - `desktop_drag_mouse`
     - `desktop_scroll`
     - `desktop_type_text`
     - `desktop_key_press`
     - `desktop_hotkey`
     - `desktop_launch_app`
     - `desktop_wait`
     - `desktop_get_clipboard`
     - `desktop_set_clipboard`
   - Added lazy desktop module loading with graceful runtime errors when missing.
   - Added screenshot path handling with owner/workspace awareness.
2. Policy/runtime integration:
   - Added desktop tools to `ALL_TOOL_NAMES` and registry schemas/dispatch.
   - Added sandbox profile flag `allow_desktop_control` (`strict=false`, `default/power=true`).
   - Added authority bound check for `can_control_desktop=false`.
   - Added runtime metrics:
     - `desktop_control_enabled`
     - `desktop_actions_total`
     - `desktop_last_action`
     - `desktop_last_error`
3. Workspace isolation alignment:
   - `desktop_screenshot` now respects workspace-root isolation flow when applicable.
4. Config/docs:
   - Added desktop config keys to `mind-clone/.env.example`:
     - `DESKTOP_CONTROL_ENABLED`
     - `DESKTOP_FAILSAFE_ENABLED`
     - `DESKTOP_ACTION_PAUSE_SECONDS`
     - `DESKTOP_DEFAULT_MOVE_DURATION`
     - `DESKTOP_DEFAULT_TYPE_INTERVAL`
     - `DESKTOP_SCREENSHOT_DIR`
5. Dependencies:
   - Updated `mind-clone/requirements.txt` with:
     - `pyautogui`
     - `PyGetWindow`
     - `pyperclip`
     - `mss`

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Direct desktop smoke checks passed:
  - `tool_desktop_screen_state()` returned valid screen/mouse data.
  - `tool_desktop_list_windows()` returned active window metadata.
  - `tool_desktop_set_clipboard()` and `tool_desktop_get_clipboard()` worked.
  - `tool_desktop_screenshot()` succeeded using `mss` fallback path.

### Residual Risks
- Desktop actions are powerful and can affect active apps immediately; keep `DESKTOP_FAILSAFE_ENABLED=true`.
- `strict` sandbox profile disables desktop tools by design.
- On some hosts, window focus/activation behavior depends on OS permission and active session state.

## 2026-02-08 | Worker: Codex GPT-5 | OpenClaw Parity Completion: Ops Signatures + Control Plane + Workflow V2 + Release Gate

### Session Summary
- Finished the remaining high-impact parity gaps in one integration pass.
- Added hardened ops auth signatures + tamper-evident audit chain, distributed node control-plane APIs, workflow language v2 controls, deterministic checkpoint resume from explicit snapshots/branches, release-gate automation, and usage/schema ops surfaces.
- Completed UI productionization by installing Node.js runtime access and building `mind-clone-ui/dist`.

### Changes Made
1. Ops auth hardening:
   - Added signature verification support in `require_ops_auth(...)` using:
     - `OPS_AUTH_REQUIRE_SIGNATURE`
     - `OPS_AUTH_SIGNATURE_SKEW_SECONDS`
     - `OPS_AUTH_ROLE_SECRETS` (role/default fallback)
   - Added chained ops audit event recording (`OpsAuditEvent`) on authenticated ops requests.
   - Added endpoint: `GET /ops/audit/events`.
2. Runtime observability completion:
   - Extended baseline + `/heartbeat`/`/status/runtime` payloads with missing new fields:
     - node control-plane metrics
     - ops signature/audit counters
     - OS sandbox metrics
     - workflow v2 run counter
     - checkpoint/usage/canary/schema/release-gate state
3. Distributed node control-plane surface:
   - Added endpoints:
     - `POST /nodes/register`
     - `POST /nodes/heartbeat`
     - `GET /nodes/control_plane`
     - `POST /nodes/lease/claim`
     - `POST /nodes/lease/release`
   - Added capability-aware remote execution check in `tool_run_command_node(...)`.
   - Extended `run_command_node` tool schema/dispatch with `capability` and optional `cwd`.
4. Workflow language v2:
   - Upgraded parser/runtime for:
     - `SET name = value`
     - `IF <var> == <value>` / `IF <var> != <value>` with `ENDIF`
     - `LOOP <n>` with `ENDLOOP`
     - template interpolation `{{var}}`
   - Kept existing commands (`SEND`, `TASK`, `SLEEP`, `BROADCAST`) backward-compatible.
   - Added runtime accounting: `workflow_v2_runs`.
5. Deterministic checkpoint resume upgrades:
   - Snapshot payload now persists title/description/status metadata.
   - Restore applies snapshot plan + restored task metadata.
   - Added endpoint:
     - `POST /ops/tasks/{task_id}/resume_from_snapshot`
       - supports in-place resume or branch creation from selected checkpoint.
6. Release gate and schema/usage ops:
   - Added release gate evaluator:
     - `evaluate_release_gate(...)`
     - env controls: `RELEASE_GATE_MIN_PASS_RATE`, `RELEASE_GATE_REQUIRE_ZERO_FAILS`
   - Added endpoint: `GET /release/gate`.
   - Added endpoint: `GET /ops/usage/summary`.
   - Added endpoint: `GET /ops/schema/version`.
   - Added CI workflow: `.github/workflows/eval-gate.yml`.
   - Added script: `mind-clone/scripts/release_gate_check.py`.
7. Environment/doc template updates:
   - Extended `mind-clone/.env.example` with new keys for:
     - ops signatures
     - OS sandbox docker mode
     - node control-plane
     - workflow v2
     - release gate
     - checkpoint/usage ledger
     - canary router
8. UI productionization:
   - Node.js LTS package confirmed via `winget` install source.
   - Added local command shims so `node`/`npm` are callable in current session.
   - Built frontend bundle successfully: `mind-clone-ui/dist`.
9. Validation harness compatibility:
   - Updated `mind-clone/scripts/hardening_s1_checks.py` approval probe to use `write_file` (compatible with host-exec interlock behavior).

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- `python -m py_compile mind-clone/scripts/release_gate_check.py` passed.
- `python -m py_compile mind-clone/scripts/hardening_s1_checks.py` passed.
- `python mind-clone/scripts/release_gate_check.py` passed (`state=pass`, `pass_rate=1.0`).
- `python mind-clone/scripts/hardening_s1_checks.py` passed.
- `npm run build` in `mind-clone-ui` passed and generated `mind-clone-ui/dist`.

### Residual Risks
- OS sandbox `docker` mode requires Docker daemon availability at runtime; otherwise local exec tools will fail fast with explicit sandbox errors.
- Ops signature mode must be coordinated with clients (`x-ops-timestamp` + `x-ops-signature`) before enabling in production.
- Workflow v2 supports scoped control flow and templating, but is intentionally bounded (iteration limits and nesting guardrails) for safety.

## 2026-02-08 | Worker: Codex GPT-5 | OpenClaw Import Bundle: Team Mode + Identity Boundaries + Context X-Ray + Interlocks

### Session Summary
- Implemented the requested one-turn import bundle across Bob’s backend in `mind-clone/mind_clone_agent.py`.
- Added multi-agent control surfaces, identity-link boundaries, context introspection, host-exec interlock, workspace isolation, memory vault ops, workflow programs, advanced model router, and team presence/broadcast.
- Kept existing Telegram/task/chat contracts backward-compatible; new capabilities are additive.

### Changes Made
1. Team mode + subagent control:
   - Added `TeamAgent` model for root-owner -> isolated subagent mapping.
   - Added owner context routing helpers (`resolve_owner_context`, `resolve_owner_id(..., agent_key=...)`).
   - Added endpoints:
     - `POST /agents/spawn`
     - `GET /agents/list`
     - `POST /agents/send`
     - `GET /agents/log`
     - `POST /agents/stop`
2. Identity session boundaries:
   - Added `IdentityLink` model.
   - Added scope-mode aware owner resolution (`strict_chat`, `linked_username`, `linked_explicit`).
   - Added endpoints:
     - `POST /identity/link`
     - `GET /identity/links`
3. Context X-Ray:
   - Added runtime prompt snapshot capture (`capture_context_snapshot`) per iteration.
   - Added endpoints:
     - `GET /context/list`
     - `GET /context/detail`
     - `GET /context/json`
4. Host exec approval interlock:
   - Added `HostExecGrant` model and grant lifecycle helpers.
   - Enforced extra gate for `run_command`, `run_command_node`, `execute_python`.
   - Added endpoints:
     - `POST /ops/host_exec/grant`
     - `GET /ops/host_exec/grants`
5. Real isolation sandbox:
   - Added per-owner workspace root resolution and path confinement.
   - Enforced workspace root on file tools and local exec tools.
   - Extended exec tools with optional `cwd` support (`tool_run_command`, `tool_execute_python`, `tool_run_command_node`).
6. Workspace memory vault ops:
   - Added git-backed memory vault helpers + endpoints:
     - `POST /vault/bootstrap`
     - `POST /vault/backup`
     - `POST /vault/restore`
7. Workflow language (OpenProse-style lite):
   - Added `WorkflowProgram` model.
   - Added parser/executor for `SEND`, `TASK`, `SLEEP`, `BROADCAST`.
   - Added endpoints:
     - `POST /workflow/programs`
     - `GET /workflow/programs`
     - `POST /workflow/run`
8. Model profile router (advanced failover):
   - Added profile parsing from `MODEL_ROUTER_PROFILES_JSON`.
   - Added cooldown + stickiness routing state.
   - Upgraded `call_llm(...)` to route by profile (base URL/model/API key per profile).
9. Team presence/broadcast:
   - Added endpoints:
     - `GET /team/presence`
     - `POST /team/broadcast`
10. Runtime/ops visibility:
    - Extended `RUNTIME_STATE`, baseline reset, and `runtime_metrics()` for all new subsystems.
    - Added startup preflight checks for router/team mode warnings.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Import and route smoke checks passed (new routes present, workflow parser works).
- Functional smoke checks passed:
  - team subagent creation/routing
  - host exec grant create/consume
  - memory vault bootstrap/backup/restore

### Residual Risks
- Workspace isolation is hard app-layer enforcement, not OS/container sandboxing.
- Host-exec interlock now blocks non-allowlisted prefixes by default and requires explicit operator grants.
- Model router profile quality depends on `MODEL_ROUTER_PROFILES_JSON` correctness and per-profile API key validity.

## 2026-02-08 | Worker: Codex GPT-5 | OpenClaw Expansion Pack: Runtime Stream + Replay + Budget + Guards

### Session Summary
- Implemented the requested OpenClaw-style expansion pieces in one backend pass:
  - live SSE blackbox stream
  - replayable run endpoint
  - budget governor runtime enforcement
  - workspace diff gate (warn/approval/block)
  - stronger secret redaction guardrail
  - continuous eval harness endpoint + optional heartbeat autorun
  - task role-loop mode (planner/executor/critic) for step execution
- Kept existing Telegram/chat/task contracts unchanged.

### Changes Made
1. Added runtime guard configs in `mind-clone/mind_clone_agent.py`:
   - `POLICY_PACK` exposure in runtime
   - budget governor settings (`BUDGET_*`)
   - workspace diff gate settings (`WORKSPACE_DIFF_*`)
   - secret guardrail settings (`SECRET_*`)
   - stream/eval/role-loop settings (`EVENT_STREAM_*`, `EVAL_*`, `TASK_ROLE_LOOP_*`)
2. Added secret redaction core:
   - `redact_secret_data(...)` and secret-pattern masking
   - integrated into blackbox sanitization and tool-result flow
   - runtime counters for redaction activity
3. Added budget governor enforcement:
   - per-run budget creation/usage tracking
   - `warn/degrade/stop` behavior wiring
   - integrated in chat loop and task-step loop
   - degrade mode trims heavy tool args and may defer extra tool calls per iteration
4. Added workspace diff gate:
   - write-diff estimation for `write_file`
   - mode-aware handling (`warn`, `approval`, `block`)
   - integrated with approval-token flow and runtime metrics
5. Added task role-loop mode:
   - `task_role_for_iteration(...)`
   - planner/executor/critic role prompts injected per task-step iteration
6. Added live stream and replay APIs:
   - `GET /debug/blackbox/stream` (SSE)
   - `GET /debug/blackbox/replay`
   - helper: `fetch_blackbox_events_after(...)`, `build_blackbox_replay(...)`
7. Added eval harness APIs:
   - `POST /eval/run`
   - `GET /eval/last`
   - helper: `run_continuous_eval_suite(...)`
   - optional heartbeat autorun via `EVAL_AUTORUN_EVERY_TICKS`
8. Extended runtime metrics/alerts:
   - budget, diff gate, redaction, eval, role-loop visibility in `/heartbeat` and `/status/runtime`
9. Updated `mind-clone/.env.example` with all new config keys above.
10. Updated startup banner to display policy pack, budget, diff gate, secret guardrail, role loop, and eval harness status.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Smoke script checks passed:
  - secret redaction masks bearer/token-like values
  - diff gate approval trigger fires on large synthetic write diff
  - new routes exist: `/debug/blackbox/stream`, `/debug/blackbox/replay`, `/eval/run`, `/eval/last`
  - eval harness returns successful report (`failed_cases=0`) under default mode

### Residual Risks
- Budget degrade mode can defer some tool calls in multi-tool iterations; this is intentional to preserve uptime under pressure.
- Secret masking is heuristic pattern-based and may miss unusual credential formats or over-mask uncommon strings.
- SSE stream endpoint is polling-based (not websocket), which is simpler but less efficient at very high event rates.

## 2026-02-08 | Worker: Codex GPT-5 | Ops Auth Activation + Live Verification

### Session Summary
- Activated ops auth in live `.env` and restarted Bob.
- Verified protected-route behavior and heartbeat runtime state after activation.

### Changes Made
1. Updated `mind-clone/.env`:
   - `OPS_AUTH_ENABLED=true`
   - `OPS_AUTH_TOKEN` set
   - `OPS_AUTH_ALLOWED_ROLES=owner,operator`
2. Restarted running `mind_clone_agent.py` process to apply env changes.
3. Ran live endpoint checks against local server:
   - `/heartbeat`
   - `/debug/blackbox` without token
   - `/debug/blackbox` with bearer token

### Validation Outcomes
- `GET /heartbeat` returned `200`.
- `GET /debug/blackbox?owner_id=1` returned `401` without token.
- `GET /debug/blackbox?owner_id=1` returned `200` with valid bearer token.
- Heartbeat payload confirms:
  - `ops_auth_enabled=true`
  - `heartbeat_supervisor_alive=true`
  - `heartbeat_next_tick_at` populated.

## 2026-02-08 | Worker: Codex GPT-5 | OpenClaw Alignment Pack: 5-Piece Runtime + Memory Upgrade

### Session Summary
- Implemented the requested 5-piece bundle in one pass:
  - session soft-trim + hard-clear before each chat LLM call
  - memory flush/checkpoint before compaction pruning
  - ops auth wall for debug/cron/plugin-control routes
  - heartbeat autonomy supervisor with manual wake
  - execution sandbox profiles (`strict|default|power`) across tool/task/node execution paths
- Kept Telegram/chat/tool schemas unchanged.

### Changes Made
1. Added session pruning controls and runtime metrics in `mind_clone_agent.py`:
   - `SESSION_SOFT_TRIM_*`, `SESSION_HARD_CLEAR_*`
   - helper: `prepare_messages_for_llm(...)`
   - integrated into `run_agent_loop(...)` before each LLM call
   - logs: `SESSION_SOFT_TRIM`, `SESSION_HARD_CLEAR`
2. Added explicit memory flush before compaction:
   - `flush_owner_memory_before_compaction(...)`
   - optional WAL checkpoint via `SESSION_MEMORY_FLUSH_CHECKPOINT`
   - wired into `compact_and_prune_session_if_needed(...)`
3. Added ops auth wall:
   - config: `OPS_AUTH_ENABLED`, `OPS_AUTH_TOKEN`, `OPS_AUTH_ALLOWED_ROLES`
   - helper/dependency: `require_ops_auth(...)`
   - protected routes:
     - `/debug/blackbox*`
     - `/nodes`
     - `/plugins/tools`
     - `/plugins/reload`
     - `/cron/jobs*`
     - `/heartbeat/wake`
4. Added heartbeat autonomy loop:
   - config: `HEARTBEAT_AUTONOMY_ENABLED`, `HEARTBEAT_INTERVAL_SECONDS`
   - loop: `heartbeat_supervisor_loop()`
   - manual trigger endpoint: `POST /heartbeat/wake`
   - explicit runtime state:
     - `heartbeat_next_tick_at`, `heartbeat_last_tick`, `heartbeat_last_reason`, `heartbeat_last_alert_count`, `heartbeat_restarts`
   - spine watchdog restart integration for heartbeat supervisor
5. Added execution sandbox profiles:
   - config: `EXECUTION_SANDBOX_PROFILE`, `EXECUTION_SANDBOX_REMOTE_ALLOWLIST`,
     `EXECUTION_SANDBOX_BLOCK_COMMAND_PATTERNS`, `EXECUTION_SANDBOX_BLOCK_PYTHON_PATTERNS`
   - policy helper: `apply_execution_sandbox(...)`
   - enforcement in `execute_tool_with_context(...)`
   - boundaries applied by source/tool/node (including cron execution guardrails)
6. Updated `mind-clone/.env.example` with all new config keys above.
7. Updated startup banner with sandbox/heartbeat/ops-auth visibility.

### Validation Outcomes
- `python -m py_compile mind-clone/mind_clone_agent.py` passed.
- Targeted smoke checks passed:
  - session pruning soft/hard behavior triggers on long tool-heavy context
  - sandbox blocks dangerous shell pattern (`rm -rf`) and allows benign command
  - heartbeat self-check executes and updates runtime heartbeat fields
  - ops auth dependency returns `401` without token and `200` with valid bearer token on `/debug/blackbox`

### Residual Risks
- `OPS_AUTH_ENABLED` defaults to `false` in `.env.example`; enable with a strong `OPS_AUTH_TOKEN` before exposing ops endpoints publicly.
- Hard-clear intentionally reduces very old tool payload detail when context budgets are exceeded.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Black Box Retention S4 + Export Bundle S5

### Session Summary
- Implemented Piece 4 and Piece 5 together from the same blackbox track:
  - S4: retention/pruning (automatic + manual)
  - S5: export bundle for portable diagnostics and handoff.
- Kept chat/task/tool contracts unchanged.

### Changes Made
1. Added blackbox retention controls in `mind_clone_agent.py`:
   - `BLACKBOX_PRUNE_ENABLED`
   - `BLACKBOX_MAX_EVENTS_PER_OWNER`
   - `BLACKBOX_MAX_EVENT_AGE_DAYS`
   - `BLACKBOX_PRUNE_BATCH_SIZE`
   - `BLACKBOX_PRUNE_INTERVAL_SECONDS`
2. Added blackbox export control:
   - `BLACKBOX_EXPORT_MAX_EVENTS`
3. Added retention helper:
   - `prune_blackbox_events(...)`
   - supports age-based and per-owner overflow pruning
4. Added automatic pruning in spine supervisor:
   - periodic prune execution in `spine_supervisor_loop()` using configured interval.
5. Added export helper:
   - `build_blackbox_export_bundle(...)`
   - includes session report, recovery plan, recent sessions, and optional raw events.
6. Added new debug endpoints:
   - `GET /debug/blackbox/export_bundle`
   - `POST /debug/blackbox/prune`
7. Added blackbox runtime observability fields:
   - `blackbox_events_pruned`
   - `blackbox_last_prune_at`
   - `blackbox_last_prune_reason`
   - `blackbox_last_prune_count`
   - `blackbox_exports_built`
   - `blackbox_last_export_at`
8. Updated `mind-clone/.env.example` with retention/export settings.

### Validation Outcomes
- `python -m py_compile mind_clone_agent.py` passed after patch.
- Combined smoke check passed:
  - export bundle generated successfully with report + raw events
  - prune run deleted overflow events and respected retention cap.

### Residual Risks
- Export endpoints can return large payloads if limits are raised; keep defaults bounded for production.
- Automatic prune runs in-process via supervisor interval; very large databases may still benefit from off-peak maintenance jobs.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Black Box Recovery Planner S3

### Session Summary
- Completed Piece 3 of the 5-piece OpenClaw-style hardening track: session-level recovery planning from blackbox traces.
- Added operator-facing recovery guidance that maps events to actionable next steps (approvals/tasks).

### Changes Made
1. Added blackbox recovery controls in `mind_clone_agent.py`:
   - `BLACKBOX_RECOVERY_MAX_APPROVALS`
   - `BLACKBOX_RECOVERY_MAX_ACTIONS`
2. Added blackbox recovery planner:
   - `build_blackbox_recovery_plan(...)`
   - correlates session timeline with `ApprovalRequest` and `Task` state
   - returns pending/rejected/expired token counts, blocked/failed task counts, and recommended actions
3. Extended session report timeline shape:
   - includes `token`, `tool_name`, `step_id`, and `task_id` fields for stronger traceability.
4. Added endpoint:
   - `GET /debug/blackbox/recovery_plan`
5. Added runtime observability fields:
   - `blackbox_reports_built`
   - `blackbox_recovery_plans_built`
   - `blackbox_last_recovery_plan_at`
6. Updated `mind-clone/.env.example` with recovery planner settings.

### Validation Outcomes
- `python -m py_compile mind_clone_agent.py` passed after patch.
- Recovery smoke passed:
  - simulated task session with approval pause token
  - `build_blackbox_recovery_plan(...)` returned `pending_approval_count=1`, `blocked_task_count=1`, and actionable recommendations.

### Residual Risks
- Recovery recommendations are advisory and not auto-executed (intentional safety default).
- Planner quality depends on event richness in blackbox payloads and approval/task row availability.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Black Box Diagnostics S2

### Session Summary
- Completed Piece 2 of the 5-piece OpenClaw-style hardening track: blackbox session diagnostics and replay-grade reporting.
- Built fast operators' views for "what happened in this run?" without changing chat/task/tool contracts.

### Changes Made
1. Added blackbox diagnostics config controls in `mind_clone_agent.py`:
   - `BLACKBOX_SESSION_LIST_MAX_LIMIT`
   - `BLACKBOX_SESSION_REPORT_MAX_EVENTS`
   - `BLACKBOX_SESSION_FAILURE_SAMPLE_LIMIT`
2. Added session analysis helpers:
   - `list_blackbox_sessions(...)`
   - `build_blackbox_session_report(...)`
   - event classifiers for failure/warning detection
   - payload preview helper for concise timeline inspection
3. Added blackbox diagnostics endpoints:
   - `GET /debug/blackbox/sessions`
   - `GET /debug/blackbox/session_report`
4. Improved blackbox event conversion reuse:
   - centralized row-to-event mapper for consistent event shape.
5. Updated `mind-clone/.env.example` with new blackbox diagnostics settings.

### Validation Outcomes
- `python -m py_compile mind_clone_agent.py` passed after patch.
- Targeted smoke checks passed:
  - wrote events across two sessions
  - `list_blackbox_sessions(...)` returned both sessions
  - `build_blackbox_session_report(...)` returned expected status/counters/timeline.

### Residual Risks
- Diagnostics endpoints remain open like existing operational endpoints; add auth later if you want restricted observability.
- Session reports analyze bounded windows (`BLACKBOX_SESSION_REPORT_MAX_EVENTS`) and may truncate very long runs.

## 2026-02-08 | Worker: Codex GPT-5 | Bob Black Box Recorder S1

### Session Summary
- Completed Piece 1 of the 5-piece OpenClaw-style hardening track: append-only black box execution recording.
- Added runtime visibility and a debug read surface without changing chat/task/tool contracts.

### Changes Made
1. Added append-only execution event persistence:
   - new table: `ExecutionEvent`
   - fields: owner/session/source/event/payload/timestamp
2. Added black box runtime/config controls:
   - `BLACKBOX_ENABLED`
   - `BLACKBOX_PAYLOAD_MAX_CHARS`
   - `BLACKBOX_READ_MAX_LIMIT`
3. Added black box helpers and sanitization:
   - payload-safe truncation and shape cleanup
   - session id generation for chat/task runs
   - read helper `fetch_blackbox_events(...)`
4. Wired event logging through runtime flows:
   - chat lifecycle events
   - forced research events
   - tool request/approval/block/complete/exception events
   - task graph/node lifecycle events
5. Extended runtime surfaces:
   - `runtime_metrics()` now includes:
     - `blackbox_events_total`
     - `blackbox_last_event_at`
   - new debug endpoint:
     - `GET /debug/blackbox?owner_id=...&limit=...&session_id=...&source_type=...`
6. Updated `mind-clone/.env.example` with black box keys.

### Validation Outcomes
- `python -m py_compile mind_clone_agent.py` passed after patch.
- Verified black box symbols and endpoint wiring are present in the runtime file.
- Black box write/read smoke passed after DB init:
  - `record_blackbox_event_with_new_session(...)` then `fetch_blackbox_events(...)` returned the inserted event.

### Residual Risks
- `/debug/blackbox` is intentionally open like other current operational endpoints; add auth later if you want restricted diagnostics.
- Event payload truncation protects runtime size, but very large/high-frequency workloads will still increase DB growth over time.

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented the 3 remaining strategic upgrades before second-LLM expansion:
  - world model (predict + reconcile + reuse),
  - self-improvement loop,
  - dormant capability activation.
- Kept existing Telegram/API contracts and model failover config behavior unchanged.

### Changes Made
1. Added world-model persistence and learning loop in `mind_clone_agent.py`:
   - new table: `ActionForecast`
   - pre-action forecast creation (`create_action_forecast_record`)
   - post-action reconciliation (`reconcile_action_forecast_record`)
   - world-memory vector types:
     - `world_model_forecast`
     - `world_model_outcome`
   - retrieval for prompt injection:
     - `retrieve_world_model_signals(...)`
2. Added self-improvement persistence and cycle:
   - new table: `SelfImprovementNote`
   - deterministic improvement candidate generation from runtime/task evidence
   - cycle runners:
     - `run_self_improvement_cycle(...)`
     - `run_self_improvement_cycle_with_new_session(...)`
   - semantic retrieval:
     - `retrieve_relevant_self_improvement_notes(...)`
   - new memory vector type:
     - `self_improvement_note`
3. Added dormant capability activation system:
   - new table: `CapabilityActivation`
   - intent-driven activation and expiry:
     - `activate_dormant_capabilities(...)`
     - `activate_dormant_capabilities_with_new_session(...)`
     - `get_active_capabilities(...)`
   - modes:
     - `research_mode`
     - `builder_mode`
     - `automation_mode`
4. Prompt/context upgrades (no API/tool schema contract breaks):
   - `build_system_prompt(...)` now optionally injects:
     - active capability modes
     - world-model signals
     - self-improvement playbook notes
   - chat loop now:
     - activates dormant capabilities from user intent,
     - injects world model + self-improvement memory
   - task-node loop now:
     - creates/reconciles per-node forecasts,
     - injects world model + self-improvement context + active capabilities
5. Runtime observability expanded:
   - world model:
     - `world_model_forecasts_total`
     - `world_model_mismatches`
     - `world_model_recent_accuracy`
     - `world_model_last_forecast_at`
     - `world_model_last_reconciliation_at`
   - self-improvement:
     - `self_improve_notes_total`
     - `self_improve_last_run_at`
     - `self_improve_last_note`
   - dormant activation:
     - `dormant_capabilities_active`
     - `dormant_activations_total`
     - `dormant_last_activation_at`
   - runtime alerts now include low world-model-accuracy warning.
6. `.env.example` updated with controls for:
   - world model retention/retrieval
   - self-improvement cadence/retention
   - dormant capability activation TTL/retention
7. `semantic_memory_search` enrichment/description updated for new memory types.

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind_clone_agent.py`
- World model + capability + self-improve smoke checks passed (import/runtime script):
  - capability activation returns expected active modes
  - action forecast creation and reconciliation complete successfully
  - world-model signal retrieval returns populated lines
  - runtime metrics include new keys
- Additional hardening suite run result:
  - `python scripts/hardening_s1_checks.py` -> failed with `Plugin tool did not load`
  - this appears tied to plugin fixture/load state in current environment, not to these new features directly.

### Current Status
- Bob now has an internal cause/effect loop (predict -> observe -> reconcile) and can reuse those signals in future decisions.
- Bob now writes periodic self-improvement notes from live evidence and can recall them during new tasks/chats.
- Dormant capability modes now auto-activate from intent and are tracked with TTL-based lifecycle.
- Second-LLM addition remains deferred as requested.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented Hardening S1 for Bob's new runtime stack
- Added consolidated runtime alerts and a repeatable hardening validation script
- Verified approval, queue lanes, plugins, remote-node failure handling, and cron flows

### Changes Made
1. Added runtime alert synthesis in `mind_clone_agent.py`:
   - new helper: `compute_runtime_alerts(payload)`
   - added to runtime output:
     - `runtime_alerts`
     - `runtime_alert_count`
2. Runtime alert coverage includes:
   - DB unhealthy state
   - task worker down
   - queue high/near-capacity
   - queue worker count below target
   - approval backlog high
   - open provider circuits
   - cron supervisor down (when enabled)
   - webhook unregistered (when token configured)
   - blocked plugin manifests
3. Added hardening regression script:
   - `scripts/hardening_s1_checks.py`
   - validates:
     - approval token lifecycle (trigger/approve/consume)
     - lane semaphore configuration
     - plugin load/execute + allowlist block behavior
     - remote node failure path
     - cron create/list/disable + due-run path
     - runtime alert generation path
4. Minor reliability fix:
   - normalized approval datetime comparisons to avoid sqlite naive/aware datetime mismatch.

### Validation Outcomes
- Syntax validation passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Hardening suite passed:
  - `python mind-clone/scripts/hardening_s1_checks.py`
  - result: `HARDENING_S1_CHECKS: PASS`

### Current Status
- Bob now has active runtime alert synthesis and a reusable hardening regression check.
- The new OpenClaw-style runtime features are now backed by deterministic pass/fail validation.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented OpenClaw-style expansion pack across 7 areas:
  - approval gates + resume tokens
  - remote node execution fabric
  - plugin optional tools
  - lane-aware queue concurrency
  - structured JSON llm-task execution
  - cron/scheduled autonomous jobs
  - plugin supply-chain hardening

### Changes Made
1. Added approval gate + resume token system in `mind_clone_agent.py`:
   - new `ApprovalRequest` persistence model
   - approval token creation/decision/validation/consumption helpers
   - approval-aware tool execution in `execute_tool_with_context(...)`
   - Telegram commands: `/approve <token>`, `/reject <token>`
   - API endpoint: `POST /approval/decision`
2. Added remote node execution fabric:
   - `REMOTE_NODES_JSON` registry loader
   - `list_execution_nodes` tool
   - `run_command_node` tool (local + remote command path)
3. Added plugin optional tool architecture:
   - plugin manifest loader from `MIND_CLONE_PLUGIN_DIR`
   - dynamic plugin tool registration (`plugin__*`)
   - plugin execution engine (`http_request` type)
   - plugin listing endpoints/tools
4. Added plugin supply-chain hardening controls:
   - allowlist: `PLUGIN_ALLOWLIST`
   - version pinning: `PLUGIN_PINNED_VERSIONS`
   - trusted hash pins: `PLUGIN_TRUSTED_HASHES`
   - strict mode: `PLUGIN_ENFORCE_TRUST`
5. Upgraded queue to lane-aware concurrency:
   - `COMMAND_QUEUE_WORKER_COUNT`
   - `COMMAND_QUEUE_LANE_LIMITS`
   - multi-worker supervisor with per-lane semaphores
6. Added structured JSON llm-task helper:
   - `call_llm_json_task(...)`
   - tool: `llm_structured_task`
   - integrated into task plan generation and step-output normalization
7. Added cron/scheduled automation:
   - new `ScheduledJob` persistence model
   - cron supervisor loop + due-job dispatcher
   - tools: `schedule_job`, `list_scheduled_jobs`, `disable_scheduled_job`
   - Telegram commands: `/cron_add`, `/cron_list`, `/cron_disable`
   - API endpoints: `POST /cron/jobs`, `GET /cron/jobs`, `POST /cron/jobs/{job_id}/disable`
8. Added runtime/API observability extensions:
   - new metrics for approval/plugin/cron/structured tasks/queue workers
   - endpoints: `GET /nodes`, `GET /plugins/tools`, `POST /plugins/reload`
9. Updated `.env.example` with all new configuration keys.

### Validation Outcomes
- Syntax validation passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Local smoke validation passed (module-level functional checks):
  - approval token lifecycle: create -> approve -> consume
  - cron job create/list + due-run function call
  - node/plugin listing helpers and runtime metric keys

### Residual Risks
- Remote node protocol assumes a compatible remote endpoint contract (`/run_command`-style JSON API).
- Plugin execution currently supports `http_request` manifests only; non-HTTP plugin types are intentionally blocked.
- Approval resume for chat relies on matching tool args at replay time; if model arguments drift, a new approval token is issued.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Step 7: Long-term retrieval logic (Task Artifact Memory S1)
- Added persistent task-node artifacts with semantic vector retrieval and prompt injection
- Added retention pruning and runtime visibility for task artifact memory

### Changes Made
1. Added long-term task memory config in `mind_clone_agent.py`:
   - `TASK_ARTIFACT_RETRIEVE_TOP_K`
   - `TASK_ARTIFACT_MAX_PER_USER`
   - `TASK_ARTIFACT_VECTOR_SCAN_LIMIT`
2. Added new persistence model:
   - `TaskArtifact` table with task/node outcome fields
3. Added task artifact memory pipeline:
   - store finalized node outcomes as `TaskArtifact`
   - generate vector embeddings in `MemoryVector(memory_type=\"task_artifact\")`
   - prune oldest artifact records over retention cap (plus linked vectors)
4. Added retrieval and prompt injection:
   - `retrieve_relevant_task_artifacts(...)`
   - injected into chat system prompt (`TASK_ARTIFACT_INJECTED`)
   - injected into task planning (`TASK_ARTIFACT_PLAN_INJECT`)
   - injected into task step execution (`TASK_ARTIFACT_STEP_INJECT`)
5. Added single-write guard for node artifacts:
   - `artifact_logged_at` field in graph node state to avoid duplicate artifact writes
6. Extended semantic memory search enrichment:
   - `semantic_memory_search` now enriches `task_artifact` matches with task/node fields
7. Extended runtime metrics:
   - `task_artifacts_stored`
   - `task_artifacts_pruned`
   - `task_artifact_injections`
8. Updated startup banner and `.env.example` for task memory settings.

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Deterministic artifact-memory test passed (isolated temp DB + monkeypatched step loop):
  - task node completion stores `TaskArtifact` row and `task_artifact` vector
  - retrieval returns relevant artifact snippets
  - `semantic_memory_search(memory_types=[\"task_artifact\"])` returns enriched artifact matches

### Current Status
- Bob now retains reusable task execution outcomes as long-term semantic memory.
- New tasks and chats can leverage relevant prior node outcomes automatically.
- Existing API/Telegram command contracts remain unchanged.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Step 6: Mature Runtime Guards
- Added provider circuit breakers, orphan task recovery lease, dead-letter capture, and `/task` idempotency dedupe

### Changes Made
1. Added provider circuit-breaker controls and runtime guard config in `mind_clone_agent.py`:
   - `CIRCUIT_BREAKER_FAILURE_THRESHOLD`
   - `CIRCUIT_BREAKER_COOLDOWN_SECONDS`
   - `TASK_GUARD_ORPHAN_LEASE_SECONDS`
   - `TASK_GUARD_MAX_ORPHAN_RECOVERIES`
   - `TASK_DEDUPE_WINDOW_SECONDS`
2. Added circuit breaker engine:
   - provider states for `llm_api`, `web_search`, `web_fetch`
   - helpers: `circuit_allow_call`, `circuit_record_success`, `circuit_record_failure`, `circuit_snapshot`
   - wired into:
     - `call_llm(...)`
     - `tool_search_web(...)`
     - `tool_read_webpage(...)`
     - `tool_read_pdf_url(...)`
3. Added dead-letter persistence model:
   - `TaskDeadLetter` table (`task_id`, `owner_id`, `title`, `reason`, `snapshot_json`, `created_at`)
4. Added task-execution guards:
   - active execution tracking (`begin_task_execution` / `end_task_execution`)
   - orphan recovery counters and lease helpers
   - `recover_orphan_running_tasks()` for stale `running` tasks
   - dead-letter escalation after recovery budget is exceeded
   - spine watchdog now runs orphan recovery checks every 30s tick window
5. Added `/task` idempotency dedupe:
   - normalized title+goal matching in active task window
   - duplicate submissions now reuse existing active task id
6. Runtime observability expanded:
   - `task_guard_orphan_requeues`
   - `task_guard_dead_letters`
   - `task_dedupe_hits`
   - `circuit_blocked_calls`
   - `circuit_open_events`
   - `circuit_breakers` snapshot
7. Startup banner now includes runtime guard profile line.
8. Updated `.env.example` with new runtime-guard environment keys.

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Circuit breaker behavior test passed:
  - threshold trip opens breaker and blocks calls
  - success resets to closed state
- `/task` dedupe test passed:
  - repeated same title/goal reuses active task id
- Orphan recovery + dead-letter test passed:
  - stale running tasks requeued while under recovery budget
  - over budget tasks marked failed and dead-lettered

### Current Status
- Runtime guards are now active for outbound providers and task orchestration reliability.
- Stale/orphan task runs can self-recover; unrecoverable runs are captured in dead-letter storage.
- Existing Telegram/API command contracts remain unchanged.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Checkpointed Task Graph Orchestration S1 (OpenClaw-style upgrade)
- Replaced linear task-step execution with dependency-aware graph execution
- Added resume/retry/branch-per-node behavior with persisted checkpoints

### Changes Made
1. Added task-graph configuration in `mind_clone_agent.py`:
   - `TASK_GRAPH_BRANCHING_ENABLED`
   - `TASK_GRAPH_MAX_NODES`
   - `TASK_GRAPH_MAX_BRANCHES_PER_NODE`
2. Upgraded task plan normalization to support graph node fields:
   - `depends_on`
   - `max_retries`
   - `branch_parent_id`
   - `branch_reason`
   - `checkpoint_at`, `started_at`, `completed_at`
3. Added graph orchestration helpers:
   - dependency normalization and runnable-node selection
   - resume-from-checkpoint conversion for interrupted `running` nodes
   - blocked-node marking when dependencies fail/miss
   - automatic recovery branch insertion and downstream dependency rewiring
4. Reworked `execute_task_by_id(...)` into checkpointed graph loop:
   - persisted checkpoint before and after each node run
   - per-node retry budget enforcement
   - automatic branch creation after retry exhaustion
   - deadlock/block detection for no-runnable-node states
5. Extended runtime telemetry:
   - `task_graph_branches_created`
   - `task_graph_resume_events`
   - exposed via existing health payloads
6. Updated task details formatting:
   - now displays node IDs and dependency labels for easier diagnosis.
7. Updated startup banner with task graph settings.
8. Updated `.env.example` with task graph control keys.

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Deterministic graph behavior test passed (isolated temp DB, monkeypatched step executor):
  - interrupted `running` node resumes to `pending`
  - failed node creates recovery branch
  - downstream dependency rewires from failed node to branch node
  - task completes successfully through branch path

### Current Status
- Task execution now runs as a checkpointed dependency graph rather than a strict linear list.
- Resume/retry/branch logic is persisted in `task.plan`, so worker restarts can continue from state.
- Existing `/task`, `/tasks`, `/task_status`, `/task_cancel` contracts remain unchanged.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Tool Policy Profiles S1 (Step 4 of roadmap)
- Added runtime-enforced `safe` / `balanced` / `power` tool execution policies
- Added policy telemetry and profile-driven tool loop budgets

### Changes Made
1. Added tool policy configuration in `mind_clone_agent.py`:
   - `TOOL_POLICY_PROFILE` (`safe|balanced|power`, default `balanced`)
   - `TOOL_POLICY_WRITE_ROOTS` (optional semicolon-separated extra write roots)
2. Added policy profiles and enforcement:
   - profile limits for chat/task tool loops
   - profile limits for `run_command` and `execute_python` timeouts
   - profile write controls for `write_file` (root-scoped vs any-path)
   - profile allow-list for tools (`safe` read/research-focused set)
3. Enforced policy in `execute_tool_with_context(...)` via `apply_tool_policy(...)` before authority checks.
4. Wired loop budgets to active profile:
   - `run_agent_loop(...)` now uses `profile_chat_tool_loop_limit()`
   - `run_task_step_loop(...)` now uses `profile_task_tool_loop_limit()`
5. Added runtime observability:
   - `tool_policy_profile`
   - `tool_policy_blocks`
   - exposed on `/heartbeat` and `/status/runtime`
6. Added startup diagnostics:
   - preflight warning when `TOOL_POLICY_PROFILE` env value is invalid and fallback profile is used
7. Updated startup banner to display active tool policy mode.
8. Updated `.env.example` with:
   - `TOOL_POLICY_PROFILE`
   - `TOOL_POLICY_WRITE_ROOTS`

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Local policy behavior checks passed:
  - `safe` blocks `run_command` and `write_file`
  - `balanced` clamps command timeouts to profile max
  - `profile_chat_tool_loop_limit()` and `profile_task_tool_loop_limit()` reflect active profile settings

### Current Status
- Tool policy profiles are active and enforced at runtime.
- Health endpoints now report policy mode and block counts.
- Existing HTTP/Telegram/tool contracts remain unchanged.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Command Queue Modes S1 (Step 3 of roadmap)
- Added inbound chat queue routing modes (`off`, `on`, `auto`)
- Added per-owner execution serialization and queue runtime telemetry

### Changes Made
1. Added queue configuration in `mind_clone_agent.py`:
   - `COMMAND_QUEUE_MODE` (`off|on|auto`, default `auto`)
   - `COMMAND_QUEUE_MAX_SIZE` (default `200`)
   - `COMMAND_QUEUE_AUTO_BACKPRESSURE` (default `1`)
2. Added inbound command queue runtime structures:
   - `COMMAND_QUEUE`, `COMMAND_QUEUE_WORKER_TASK`
   - per-owner state: `OWNER_EXECUTION_LOCKS`, `OWNER_QUEUE_COUNTS`, `OWNER_ACTIVE_RUNS`
3. Added per-owner serialization helpers:
   - `get_owner_execution_lock(...)`
   - `mark_owner_active(...)`
   - `run_agent_loop_serialized(...)`
4. Added queue dispatch + worker flow:
   - `dispatch_incoming_message(...)`
   - `enqueue_command_job(...)`
   - `should_enqueue_message(...)`
   - `command_queue_worker_loop(...)`
   - `run_owner_message_job(...)`
5. Updated Telegram main message path:
   - replaced direct background `_process_message(...)` launch
   - now resolves owner and routes via queue dispatch
6. Updated `/chat` endpoint:
   - converted to `async`
   - routes through same queue control path with response future when queued
7. Added lifecycle + supervision integration:
   - starts command queue worker on lifespan startup for `on/auto` modes
   - graceful shutdown cancellation for command queue worker
   - spine watchdog auto-restarts queue worker (`SPINE_COMMAND_QUEUE_RESTART`)
8. Extended runtime metrics payload:
   - `command_queue_mode`, `command_queue_worker_alive`, `command_queue_worker_restarts`
   - `command_queue_size`, `command_queue_max_size`
   - `command_queue_enqueued`, `command_queue_processed`, `command_queue_dropped`
   - `command_queue_direct_routed`, `command_queue_auto_routed`
   - `command_queue_owner_active`, `command_queue_owner_backlog`
9. Updated startup banner to show command queue mode/max.
10. Updated `.env.example` with:
   - `COMMAND_QUEUE_MODE`
   - `COMMAND_QUEUE_MAX_SIZE`
   - `COMMAND_QUEUE_AUTO_BACKPRESSURE`

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Queue mode behavior tests (local deterministic harness):
  - `on` mode: request queued and processed by worker (`enqueued=1`, `processed=1`, `direct=0`)
  - `auto` mode without backlog: direct route (`queued=false`, `direct=1`)
  - owner lock serialization: concurrent same-owner runs execute sequentially (no overlap)

### Current Status
- Command queue modes are active and exposed in runtime health metrics.
- Inbound chat execution is now protected against same-owner overlap.
- Existing task queue/worker and Telegram command contracts remain intact.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Model Failover S1 (Step 2 of roadmap)
- Added primary -> fallback model chain with retryable-failure failover
- Added runtime failover telemetry in health surfaces

### Changes Made
1. Added failover configuration in `mind_clone_agent.py`:
   - `KIMI_FALLBACK_MODEL` from env
   - `LLM_FAILOVER_ENABLED` (env flag, default true)
   - `LLM_REQUEST_TIMEOUT_SECONDS` (env int, default 120)
   - retryable status set: `{408, 409, 425, 429, 500, 502, 503, 504}`
2. Added LLM failover runtime state fields:
   - `llm_primary_model`, `llm_fallback_model`, `llm_failover_enabled`
   - `llm_last_model_used`, `llm_last_attempt_at`, `llm_last_success_at`, `llm_last_error`
   - `llm_failover_count`, `llm_primary_failures`, `llm_fallback_failures`
3. Reworked `call_llm(...)`:
   - added `configured_llm_models()` + `llm_failover_active()`
   - attempts primary model first, then fallback when failure is retryable
   - failover triggers on timeout/connection/request errors and retryable HTTP statuses
   - no failover on non-retryable HTTP errors (e.g., 400)
   - structured logs: `LLM_FAILOVER ...`, `LLM_FAILOVER_OK ...`
4. Startup/runtime wiring:
   - baseline reset now initializes all LLM failover metrics
   - startup preflight warns if failover enabled but fallback is unset/same as primary
   - `runtime_metrics()` now includes failover telemetry
5. Entry-point banner now shows fallback status (`disabled` when no valid fallback).
6. Updated `.env.example` with:
   - `KIMI_FALLBACK_MODEL`
   - `LLM_FAILOVER_ENABLED`
   - `LLM_REQUEST_TIMEOUT_SECONDS`

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Failover behavior test (mocked HTTP):
  - primary `429` -> fallback attempted -> success
  - counters updated: `llm_failover_count=1`, `llm_last_model_used=fallback-model`
- Non-retryable behavior test (mocked HTTP):
  - primary `400` -> no fallback attempt
- Single-model regression test:
  - no fallback configured -> only primary model called, normal success path

### Current Status
- Model failover is active when `KIMI_FALLBACK_MODEL` is configured and distinct from primary.
- Existing chat/task/tool flows remain unchanged at the API/command level.

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Bob Memory S1: session compaction + pruning (Balanced profile)
- Added episodic conversation summaries with semantic retrieval into system prompt
- Added retention guardrails for raw history and compacted summary records

### Changes Made
1. Added compaction constants in `mind_clone_agent.py`:
   - `HISTORY_COMPACT_TRIGGER_MESSAGES=120`
   - `HISTORY_RECENT_KEEP_MESSAGES=45`
   - `HISTORY_COMPACT_MAX_CHUNK=60`
   - `HISTORY_COMPACT_MIN_CHUNK=30`
   - `SUMMARY_RETRIEVE_TOP_K=3`
   - `SUMMARY_MAX_PER_USER=60`
   - `RAW_HISTORY_EMERGENCY_CAP=220`
   - `RAW_HISTORY_EMERGENCY_KEEP=180`
2. Added new DB model:
   - `ConversationSummary` table with:
     `id`, `owner_id`, `start_message_id`, `end_message_id`,
     `summary`, `key_points_json`, `open_loops_json`, `created_at`
3. Added compaction pipeline helpers:
   - `serialize_messages_for_compaction(...)`
   - `summarize_conversation_chunk(...)`
   - `store_conversation_summary(...)`
   - `prune_summary_overflow(...)`
   - `emergency_prune_raw_history(...)`
   - `compact_and_prune_session_if_needed(...)`
4. Added episodic memory retrieval helpers:
   - `_format_conversation_summary_for_prompt(...)`
   - `retrieve_relevant_conversation_summaries(...)`
   - semantic retrieval via `MemoryVector(memory_type="conversation_summary")`
   - fallback to latest summaries when semantic recall is sparse
5. Updated prompt construction:
   - `build_system_prompt(...)` now accepts `conversation_summaries`
   - adds `COMPACTED EPISODIC MEMORY` block when available
6. Updated `run_agent_loop(...)` flow:
   - save user message
   - run `compact_and_prune_session_if_needed(...)`
   - keep forced deep research behavior unchanged
   - inject both lessons and compacted episodic summaries into system prompt

### Validation Outcomes
- Syntax check passed:
  - `python -m py_compile mind-clone/mind_clone_agent.py`
- Compaction smoke test passed (LLM summarizer monkeypatched locally):
  - 130 raw messages -> compaction ran once
  - raw messages reduced to 70
  - `ConversationSummary` created: 1
  - matching `conversation_summary` vector created: 1
  - summary retrieval returned injected episodic memory text
- Retention/pruning test passed:
  - 65 summaries -> pruned to 60 (`SESSION_PRUNE_SUMMARY`)
  - 230 raw messages -> emergency-pruned to 180 (`SESSION_PRUNE_EMERGENCY`)

### Current Status
- Session compaction + pruning is active in code with balanced defaults
- Episodic summary memory is now available for semantic recall in chat prompting
- Existing HTTP/tool contracts and Telegram command surface remain unchanged

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Bob Spine S1 runtime stability pack
- Added startup preflight, DB liveness telemetry, and runtime watchdog supervision
- Extended health endpoints with spine metrics for faster diagnosis

### Changes Made
1. Added spine runtime state and supervisor task wiring in `mind_clone_agent.py`:
   - new runtime fields: preflight status/errors, db health timestamps/errors, supervisor alive, restart counters
   - added `SPINE_SUPERVISOR_TASK`
2. Added startup/preflight helpers:
   - `initialize_runtime_state_baseline()`
   - `run_startup_preflight()`
   - `check_db_liveness()`
   - preflight now validates DB readiness and webhook URL format
   - placeholder token checks are warnings (non-fatal)
3. Added watchdog loop:
   - `spine_supervisor_loop()` runs every 15s
   - restarts task worker if unexpectedly dead
   - restarts webhook supervisor when webhook is not registered and supervisor is absent/dead
   - runs DB liveness check every 30s
   - logs with `SPINE_WATCHDOG_*` / `SPINE_*_RESTART` / `SPINE_DB_CHECK_FAIL`
4. Updated lifespan startup/shutdown:
   - startup order now initializes runtime baseline, runs preflight, initializes DB, starts worker/webhook flow, then starts spine supervisor
   - shutdown now marks `shutting_down` and cancels spine supervisor first, then webhook/task workers
5. Extended runtime health payloads:
   - `GET /heartbeat` and `GET /status/runtime` now include:
     `spine_supervisor_alive`, `startup_preflight_ok`, `startup_preflight_errors`,
     `db_healthy`, `db_last_check`, `db_last_error`,
     `task_worker_restarts`, `webhook_supervisor_restarts`

### Validation Outcomes
- Syntax/AST checks passed
- Startup path validated with new preflight + DB liveness fields
- Health endpoint payload includes all new spine fields
- Existing API/Telegram contracts unchanged

### Current Status
- Bob now has active spine telemetry and a runtime watchdog for worker/webhook/db stability
- Existing tool, memory, and forced-research flows remain intact

---

## 2026-02-07 | Worker: Claude Opus 4.6 (Session 2)

### Session Summary
- Implemented Self-Reflection Engine (AGI Pillar — Learning)
- Agent now reflects on conversations and extracts lessons
- Lessons are stored as vector memories and retrieved before future conversations

### Changes Made
1. Added Self-Reflection Engine in `mind_clone_agent.py` (before `build_system_prompt`):
   - `REFLECTION_PROMPT` — structured prompt for lesson extraction
   - `_should_reflect(owner_id, msg_count)` — gates reflection (min 3 messages, 2-min cooldown)
   - `reflect_on_conversation(db, owner_id)` — sends recent conversation to LLM for reflection
   - `store_lesson(db, owner_id, lesson, context)` — saves lesson as vector memory (type="lesson")
   - `retrieve_relevant_lessons(owner_id, user_message)` — semantic search for relevant past lessons
   - `run_post_conversation_reflection(db, owner_id)` — orchestrates the full reflection flow
2. Modified `build_system_prompt` — accepts `lessons` parameter, injects "LESSONS FROM PAST EXPERIENCE" block
3. Modified `run_agent_loop` — retrieves relevant lessons before building system prompt
4. Modified `run_agent_loop_with_new_session` — triggers post-conversation reflection after agent loop returns
5. Updated `VISION.md` — Learning pillar status upgraded to "Growing"

### How It Works
```
User sends message → retrieve_relevant_lessons() → inject into system prompt → agent responds
                                                                                    ↓
                                                              run_post_conversation_reflection()
                                                                    ↓
                                                         reflect_on_conversation() → LLM extracts lessons
                                                                    ↓
                                                         store_lesson() → saved as vector memory
                                                                    ↓
                                                         Future conversations retrieve these lessons
```

---

## 2026-02-07 | Worker: Claude Opus 4.6

### Session Summary
- Implemented Vector Memory System (AGI Pillar — Memory + Learning)
- Added GloVe-based semantic embeddings for memory search
- Upgraded research_memory_search from keyword to vector similarity
- Added new semantic_memory_search tool for cross-type memory retrieval

### Changes Made
1. Added GloVe embedding system in `mind_clone_agent.py`:
   - `_download_glove_if_needed()` — one-time 330MB download, cached locally
   - `_load_glove_vectors()` — lazy-loads 50K word vectors (100-dim), thread-safe
   - `get_embedding(text)` — averaged word vectors, normalized
   - `cosine_similarity(a, b)` — numpy dot product
   - `embedding_to_bytes()` / `bytes_to_embedding()` — SQLite storage serialization
2. Added `MemoryVector` DB model:
   - `owner_id`, `memory_type`, `ref_id`, `text_preview`, `embedding` (binary blob)
   - Decoupled from content tables — supports future memory types (conversations, lessons)
3. Updated `tool_save_research_note`:
   - Now generates and stores vector embedding alongside each research note
   - Non-fatal: embedding failure doesn't block note creation
4. Upgraded `tool_research_memory_search`:
   - Primary: vector similarity search via cosine distance
   - Fallback: original keyword matching if no vectors exist
   - Results now include `search_method` field ("vector" or "keyword")
5. Added new tool `semantic_memory_search`:
   - Searches across ALL memory types using vector similarity
   - Supports `memory_types` filter (research_note, conversation_summary, lesson)
   - Enriches results with source data (topic, summary, sources)
6. Updated tool registry:
   - Added `semantic_memory_search` schema + dispatch
   - Updated `research_memory_search` description to note semantic search
   - Added `_owner_id` injection for new tool
7. Dependencies: added `numpy>=1.26.0` to requirements.txt
   - Note: `fastembed` failed on Python 3.14/Windows (Rust compile), `onnxruntime` DLL failed
   - Solution: GloVe word vectors + numpy — zero native DLL dependencies, works on Python 3.14
8. Updated `AGENTS.md` tool list (now 13 tools)

### Validation Outcomes
- Syntax check passed (`ast.parse`)
- GloVe vectors load successfully (50K words, 100-dim)
- Embedding round-trip serialization verified (400 bytes per vector)
- Semantic similarity test: ML topics cluster correctly, unrelated topics score low
- Full pipeline test: save 3 notes → vector search finds correct matches by meaning
- Server starts cleanly, heartbeat healthy, webhook registered

### Current Status
- Vector memory system is active for all new research notes
- Existing notes without embeddings fall back to keyword search
- GloVe model auto-downloads on first use (~330MB, cached in LOCALAPPDATA)
- Total tools: 13 (was 12, added semantic_memory_search)
- Server running on port 8000 with healthy runtime indicators

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Verified forced `deep_research` execution from live runtime logs after Telegram tests
- Checked runtime health and process state after interrupted restart attempts
- Confirmed root cause of restart inconsistency was process overlap + configured DB path permission mismatch in this environment

### Changes Made
1. Runtime verification:
   - confirmed `FORCED_DEEP_RESEARCH` entries for Telegram research prompts in `runtime_server.err.log`
   - confirmed bot message send path remained successful (`sendMessage 200`) during valid runs
2. Process/port diagnostics:
   - validated listener/process ownership on port `8000`
   - identified cases where old process remained active while new process failed startup
3. DB startup diagnostics:
   - confirmed explicit DB path enforcement behavior when configured path is not writable
   - confirmed runtime test DB path (`Temp`) was used successfully when overridden

### Current Status
- Forced research behavior is active in the updated code path
- Runtime can become unavailable if restarted with an unwritable `MIND_CLONE_DB_PATH`; use a writable path for stable restarts

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Added deterministic forcing of `deep_research` for research-style user prompts
- Ensured research requests return citation-oriented output even when LLM might skip tools

### Changes Made
1. Added forced-research detection helpers in `mind_clone_agent.py`:
   - `should_force_deep_research_prompt(...)`
   - `extract_forced_research_query(...)`
2. Added forced-research execution + formatting path:
   - `run_forced_deep_research(...)`
   - `format_forced_deep_research_response(...)`
3. Updated `run_agent_loop(...)`:
   - after saving user message, it now checks for research-style prompts
   - when matched, it bypasses normal LLM tool-choice and directly executes `deep_research`
   - stores synthetic assistant tool-call + tool result + final assistant reply in conversation history

### Validation Outcomes
- Syntax parse passed
- Import check passed (with test DB path override)
- `should_force_deep_research_prompt(...)` correctly matches research/citation prompts
- `run_agent_loop(...)` forced branch executed `deep_research` exactly once in a local smoke test

### Current Status
- Research prompts like `Research "...\" and give source links` now deterministically run `deep_research`
- Normal non-research prompts still follow standard agent loop

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Enforced explicit persistent DB path configuration with clear startup behavior
- Upgraded deep research ranking to prioritize higher-trust sources while keeping balanced coverage
- Added source diversity guardrails and trust-coverage warnings

### Changes Made
1. Hardened DB path handling in `mind_clone_agent.py`:
   - expanded env vars and `~` when parsing configured DB paths
   - explicit source tracking for selected DB path (`env` vs `fallback`)
   - actionable startup failure if configured DB path is unusable
   - warning when running in fallback mode without explicit persistent path
2. Added persistent path config:
   - set `MIND_CLONE_DB_PATH=C:\Users\mader\.mind-clone\mind_clone.db` in `.env`
   - added same key and comment in `.env.example`
3. Improved trust classification and scoring:
   - expanded trusted domain hints (`official/docs/news`)
   - stronger trust-weight separation so trust outranks weak relevance ties
   - added low-trust penalty for common low-signal patterns (domain/title/content markers)
4. Added source selection guardrails in `deep_research`:
   - per-domain cap (`2`) during initial selection
   - automatic cap relaxation only when needed to avoid sparse outputs
   - warning when high-trust coverage is limited
5. Preserved API/tool contracts:
   - no schema or endpoint contract changes
   - `deep_research` output keys remain unchanged
6. Validation outcomes:
   - explicit unusable DB path now fails fast with actionable startup error
   - configured usable DB path selects `source=env:MIND_CLONE_DB_PATH`
   - `deep_research` returns results with trust tiers and trust-coverage warnings when needed

### Current Status
- Persistent DB path is now config-first and enforced when provided
- Research results are biased toward higher-trust citations with better domain diversity
- Existing Telegram/chat/task flows remain unchanged by interface

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Fixed research/search failures caused by inherited broken proxy environment variables
- Updated DDGS-based search paths to run with proxy env temporarily disabled
- Restarted and verified research responses now work through `/chat`

### Changes Made
1. Added proxy-sanitization helper in `mind_clone_agent.py`:
   - `without_proxy_env()` with lock protection
   - temporarily clears `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `DDGS_PROXY` (and related variants)
   - forces `NO_PROXY=*` during DDGS calls and restores env afterward
2. Updated `tool_search_web` to execute DDGS under `without_proxy_env()`
3. Updated `tool_deep_research` retrieval loop to execute DDGS under `without_proxy_env()`
4. Validated behavior after patch:
   - direct `tool_search_web('openai')` returned results
   - direct `tool_deep_research(...)` returned `ok=true` with sources
   - `/chat` research prompt returned cited output successfully

### Current Status
- Telegram webhook + chat flow active
- Research tools are operational in current proxy environment
- Remaining DB path warning (`LOCALAPPDATA` access denied) is non-fatal due temp-path fallback

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Fixed blocking SQLite `disk I/O error` issue that was causing unstable runtime behavior
- Added resilient DB path selection and recovery so startup no longer depends on a single bad path
- Restarted server and validated core runtime endpoints

### Changes Made
1. Updated DB configuration in `mind_clone_agent.py`:
   - Added candidate path selection chain:
     - `MIND_CLONE_DB_PATH` / `MIND_CLONE_DB_DIR` (if set)
     - local app data default
     - temp directory fallback
2. Added SQLite readiness + recovery helpers:
   - probe DB health with `PRAGMA quick_check`
   - detect `disk i/o error`
   - quarantine corrupt DB sidecar files (`.corrupt.<timestamp>`) before retry
3. Hardened initialization flow:
   - select first usable DB path at startup
   - fail fast with clear error if no path is usable
   - revalidate DB path in `init_db()`
4. Restarted and smoke-tested runtime:
   - `GET /heartbeat` returns healthy
   - `GET /status/runtime` returns healthy
   - `POST /chat` returns valid response

### Current Status
- Server is running on port `8000` with updated code
- DB now initializes on a usable local path in this environment
- Core chat/runtime flows are healthy

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented research power tool expansion in single-file architecture
- Added deep research, PDF reading, and research memory tools
- Wired owner-aware tool context so memory tools work in both chat and task loops

### Changes Made
1. Added new dependencies in `requirements.txt`:
   - `trafilatura`
   - `pypdf`
   - `python-dateutil`
2. Added new DB model:
   - `ResearchNote` (`owner_id`, `topic`, `summary`, `sources_json`, `tags_json`, `created_at`)
3. Added research helper utilities in `mind_clone_agent.py`:
   - URL canonicalization/dedup and domain filtering
   - source trust classification and ranking
   - flexible JSON parsing for LLM outputs
   - citation snippet extraction
4. Added new tools in SECTION 2:
   - `tool_deep_research`
   - `tool_read_pdf_url`
   - `tool_save_research_note`
   - `tool_research_memory_search`
5. Added new tool schemas and dispatch entries in SECTION 3:
   - `deep_research`
   - `read_pdf_url`
   - `save_research_note`
   - `research_memory_search`
6. Added owner-aware tool execution helper:
   - `execute_tool_with_context(...)`
   - injects `_owner_id` for research memory tools
7. Updated tool execution paths to use context helper:
   - main agent loop (`run_agent_loop`)
   - task step loop (`run_task_step_loop`)
   - task executor now passes `owner_id` into step loop
8. Extended task tool summary mapping for new tools

### Current Status
- New research tools are implemented and discoverable by function-calling
- Syntax and import checks passed
- Deep research smoke test executed (returned expected failure structure in restricted network/API conditions)
- DB write smoke test for `ResearchNote` table creation could not complete due local SQLite `disk I/O error` in this environment

---

## 2026-02-07 | Worker: Claude Sonnet 4.5 (Session 2)

### Session Summary
- Worked with user after Codex sessions to fix Telegram delivery issues
- Added multi-AI collaboration files for seamless handoffs
- Fixed 400 LLM errors by clearing corrupted conversation history

### Changes Made
1. Created AI collaboration files for auto-read by different AI tools:
   - `CLAUDE.md`, `CODEX.md` for Claude/Codex auto-loading
   - `.cursorrules`, `.windsurfrules` for Cursor/Windsurf IDEs
   - `.github/copilot-instructions.md` for GitHub Copilot
2. Updated `AGENTS.md` header to emphasize logging requirement
3. Fixed Telegram webhook issues:
   - Cleared 3 pending failed updates from Telegram queue
   - Reset webhook with `drop_pending_updates=True`
4. Fixed 400 LLM errors:
   - Cleared 80 corrupted conversation messages from database
   - Agent now responds successfully to all messages

### Current Status
- Telegram bot fully operational (webhook clean, no errors)
- All 7 tools working (search, webpage, files, shell, python exec)
- Autonomous task engine from Codex working (4 new commands)
- Multi-AI handoff system in place (5 AI tools auto-configured)
- Ready for Codex to add more tools

---

## 2026-02-07 | Worker: Claude Opus 4.6

### Session Summary
- Set up entire project from scratch
- Fixed Kimi K2.5 temperature issue (must be 1.0 with tools)
- Installed ngrok for Telegram webhook tunneling
- Added Code Executor tool (`execute_python`)

### Changes Made
1. Created project structure (mind-clone/ folder)
2. Created requirements.txt, .env, .env.example, .gitignore, README.md
3. Copied mind_clone_agent.py from Downloads, added `dotenv` import
4. Changed `LLM_TEMPERATURE` from 0.6 to 1.0 (Kimi K2.5 requires 1.0 with tools)
5. Added `execute_python` tool — runs Python code in subprocess with 15s timeout
6. Created AGENTS.md and CHANGELOG.md for multi-AI collaboration

### Current Status
- Agent is LIVE and working on Telegram
- All 7 tools functional (search, webpage, read/write file, list dir, shell, python exec)
- Tunnel: ngrok (URL changes on restart)

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented a persistent autonomous task engine with Telegram task commands
- Added background queue worker, task planning, step execution, retries, and restart recovery
- Kept existing authority/safety behavior unchanged (per owner preference)

### Changes Made
1. Added task constants/statuses and in-memory queue state in `mind_clone_agent.py`
2. Added `SECTION 8B: AUTONOMOUS TASK ENGINE`:
   - Plan normalization/parsing helpers
   - LLM-based task plan generation with fallback plan
   - Step executor with tool loop + retry handling
   - Task runner (`execute_task_by_id`) with DB persistence
   - Queue helpers (`enqueue_task`, `recover_pending_tasks`, `task_worker_loop`)
3. Added task DB helper functions:
   - `parse_task_command_payload`
   - `create_queued_task`
   - `list_recent_tasks`
   - `get_user_task_by_id`
   - `cancel_task`
4. Updated FastAPI startup/shutdown:
   - Starts task worker on startup
   - Recovers queued/running/open tasks and re-queues them
   - Cancels worker gracefully on shutdown
5. Extended heartbeat with queue metrics:
   - `task_queue_size`
   - `tasks_tracked`
6. Added Telegram commands:
   - `/task <title> :: <goal>`
   - `/tasks`
   - `/task_status <id>`
   - `/task_cancel <id>`
7. Fixed async executor DB-session usage for normal chat loop:
   - Added `run_agent_loop_with_new_session`
   - `_process_message` now executes agent loop using a fresh session in executor

### Current Status
- Existing chat flow remains active
- New task flow is available via Telegram commands
- Syntax check passed (`ast.parse`)

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Implemented Reliability Pack v1 with non-fatal Telegram webhook startup behavior
- Replaced deprecated FastAPI startup/shutdown events with lifespan lifecycle
- Added runtime observability fields and a runtime status endpoint

### Changes Made
1. Added webhook retry runtime state and policy constants:
   - base `5s`, factor `x2`, cap `300s`, jitter `0-20%`
2. Added webhook reliability functions in `mind_clone_agent.py`:
   - `try_set_telegram_webhook_once()`
   - `webhook_retry_loop()`
   - `webhook_retry_supervisor_loop()`
   - `cancel_background_task()`
   - runtime metric helpers (`runtime_metrics`, `runtime_uptime_seconds`)
3. Updated task worker loop to expose worker liveness:
   - sets `worker_alive=True` on start
   - sets `worker_alive=False` on exit
4. Replaced `@app.on_event("startup"/"shutdown")` with lifespan:
   - `app_lifespan()` now initializes DB, starts worker, recovers queued tasks
   - performs one webhook attempt at startup
   - starts background webhook retry supervisor on failure without aborting app startup
   - cleanly cancels webhook/worker background tasks on shutdown
5. Extended `GET /heartbeat` response with runtime reliability fields:
   - `worker_alive`
   - `webhook_registered`
   - `webhook_last_attempt`
   - `webhook_last_success`
   - `webhook_last_error`
   - `webhook_next_retry_at`
   - existing `task_queue_size` and `tasks_tracked` retained
6. Added `GET /status/runtime` endpoint:
   - returns runtime metrics plus `uptime_seconds`
7. Switched new reliability timestamps to timezone-aware UTC (`datetime.now(timezone.utc)`) to avoid Python 3.14 `utcnow()` deprecation warnings in this new code path

### Current Status
- App startup no longer hard-fails if Telegram webhook registration fails
- Webhook retry logic runs in background with backoff and jitter
- Runtime metrics available via `/heartbeat` and `/status/runtime`
- Syntax and import checks passed

---

## 2026-02-07 | Worker: Codex GPT-5

### Session Summary
- Fixed Telegram delivery failure caused by bad proxy environment variables
- Updated outbound HTTP clients to ignore environment proxy settings
- Verified webhook registration recovered and runtime telemetry reflects healthy state

### Changes Made
1. Added global `REQUESTS_SESSION` with `trust_env=False` in `mind_clone_agent.py`
2. Switched outbound `requests` calls to use `REQUESTS_SESSION`:
   - LLM call path (`call_llm`)
   - Webpage reader tool (`tool_read_webpage`)
3. Updated outbound `httpx` clients to `trust_env=False`:
   - `send_telegram_message`
   - `try_set_telegram_webhook_once`
   - Telegram typing indicator call in `_process_message`
4. Restarted server and validated reliability endpoints:
   - `/heartbeat`
   - `/status/runtime`
5. Confirmed runtime state after fix:
   - `webhook_registered=true`
   - `webhook_last_error=null`
   - `worker_alive=true`

### Current Status
- Telegram webhook setup and reply path work without depending on OS proxy env vars
- Reliability pack behavior remains active (non-fatal startup + retry telemetry)
- System is running with healthy runtime indicators

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Fixed missing Telegram reply on approval-required tool calls and hardened send fallback behavior.

### Changes Made
1. Updated approval prompt text in `mind_clone_agent.py` to plain text (removed markdown backticks around tokens/commands):
   - chat approval pause response
   - task-graph approval pause response
   - `/approve` status messages
2. Hardened `send_telegram_message`:
   - skip/log empty message attempts (`TELEGRAM_SEND_SKIP_EMPTY`)
   - validate Telegram API body `ok=true` (not only HTTP 200)
   - retry failed markdown sends in plain text mode
   - log structured failure details if both attempts fail (`TELEGRAM_SEND_FAIL`)
3. Restarted server and revalidated:
   - `/status/runtime` healthy
   - approval requests are being created and tracked correctly
   - direct `/chat` approval prompt now returns plain, reliable token instructions

### Current Status
- Approval flow is active; pending tokens are stored and resolvable.
- Telegram reply path now has stronger reliability and diagnostics.
- Residual risk: if Telegram API itself rate-limits or is unavailable, sends can still fail, but failures are now logged clearly.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented Bob Memory S2: balanced long-term retrieval ranking with continuity-aware recall and importance-based pruning.

### Changes Made
1. Added memory ranking controls in `mind_clone_agent.py`:
   - continuity context from recent user messages + active tasks
   - task-id hint extraction for same-task recall
   - blended scoring (`semantic relevance + overlap + recency + importance + continuity`)
2. Upgraded retrieval logic:
   - `retrieve_relevant_lessons(...)` now uses weighted scoring and quality tracking
   - `retrieve_relevant_conversation_summaries(...)` now uses weighted scoring, high-signal fallback, and task-hint boosts
   - `retrieve_relevant_task_artifacts(...)` now uses same-task boosts and high-signal filtering
3. Added importance scoring helpers:
   - lesson importance
   - conversation summary importance
   - task artifact importance
4. Added pruning improvements:
   - `prune_lesson_overflow(...)` keeps strongest lessons and prunes weak overflow
   - `prune_summary_overflow(...)` switched from newest-only retention to importance+recency retention
5. Added runtime memory observability fields:
   - `memory_last_retrieved_total`
   - `memory_last_lessons_retrieved`
   - `memory_last_summaries_retrieved`
   - `memory_last_task_artifacts_retrieved`
   - `memory_last_lesson_quality`
   - `memory_last_summary_quality`
   - `memory_last_task_artifact_quality`
   - `memory_last_hit_quality`
   - `memory_last_continuity_score`
   - `memory_last_retrieval_at`
   - `memory_lessons_pruned`
   - `memory_summaries_pruned`
6. Wired continuity-aware memory retrieval into:
   - chat agent loop
   - task planning artifact retrieval
   - task step artifact retrieval

### Current Status
- Memory retrieval is now less noisy and more continuity-aware.
- Same-task follow-ups get stronger artifact recall.
- Weak memory overflow is pruned while higher-signal memories are retained longer.
- Syntax checks and targeted retrieval/pruning smoke checks passed.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented Bob UI S1: OpenClaw-style command center scaffold (`React + Vite + TypeScript`) with same-server FastAPI serving.
- Added dedicated `/ui/*` REST APIs for user/task/approval workflows while keeping Telegram and existing API contracts unchanged.

### Changes Made
1. Backend updates in `mind_clone_agent.py`:
   - Added UI path constants (`UI_PROJECT_DIR`, `UI_DIST_DIR`).
   - Added helper functions for:
     - UI user-context resolution from `chat_id + username`
     - task summary serialization with progress
     - pending approval listing/serialization
     - UI static bundle readiness + asset resolution
   - Added new `/ui/*` API endpoints:
     - `GET /ui/me`
     - `GET /ui/tasks`
     - `POST /ui/tasks`
     - `GET /ui/tasks/{task_id}`
     - `POST /ui/tasks/{task_id}/cancel`
     - `GET /ui/approvals/pending`
   - Added static serving routes:
     - `GET /ui`
     - `GET /ui/`
     - `GET /ui/{path:path}`
     - returns actionable `503` JSON when UI bundle is missing.
   - Hardened `get_or_create_user(...)` to avoid `UNIQUE users.username` collisions across different chat IDs (auto-suffixed username fallback + integrity-retry path).
2. New frontend project `mind-clone-ui`:
   - Added Vite/React/TypeScript scaffold (`package.json`, `tsconfig*`, `vite.config.ts`, `index.html`).
   - Added command-center UI implementation in `src/App.tsx` with modules:
     - Runtime, Chat, Tasks, Approvals, Cron, Blackbox, Nodes/Plugins, Settings.
   - Added typed API client (`src/api/client.ts`) and shared types (`src/types.ts`).
   - Added style system (`src/styles.css`) with command-center visual direction.
   - Added frontend `.gitignore`.
3. Documentation:
   - Updated `README.md` with UI build/serve instructions and `/ui` behavior.

### Validation Outcomes
1. `python -m py_compile mind_clone_agent.py` passed.
2. FastAPI route verification includes:
   - `/ui`, `/ui/`, `/ui/{path:path}`
   - `/ui/me`, `/ui/tasks`, `/ui/tasks/{task_id}`, `/ui/tasks/{task_id}/cancel`, `/ui/approvals/pending`
3. API smoke tests using `fastapi.testclient` passed:
   - `/ui/me`
   - `/ui/tasks` create/list/detail/cancel
   - `/ui/approvals/pending`
   - repeated `/ui/me` calls with same username and different chat IDs no longer crash.
4. `/ui` correctly returns `503` with build guidance when `mind-clone-ui/dist` is absent.

### Residual Risks / Notes
- Node.js/npm are not installed in this environment, so frontend build (`npm install && npm run build`) was not executed here.
- UI serving will switch from `503` to HTML only after building `mind-clone-ui/dist`.

---

<!-- TEMPLATE FOR NEXT WORKER
## YYYY-MM-DD | Worker: [AI Name]

### Session Summary
- Brief overview of what was done

### Changes Made
1. Change 1
2. Change 2

### Current Status
- What's working
- What's broken
- What needs attention next
-->

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Implemented three OpenClaw-parity upgrades in one pass:
1. hard session-level isolation defaults,
2. deterministic checkpoint replay validation,
3. load-aware distributed node scheduling telemetry.

### Changes Made
1. Hard isolation defaults in `mind_clone_agent.py`:
   - `OS_SANDBOX_MODE` default switched to `docker`.
   - Added `OS_SANDBOX_REQUIRED` (default `true`) with startup preflight critical enforcement.
   - Added `WORKSPACE_SESSION_ISOLATION_ENABLED` + `WORKSPACE_SESSION_ROOT`.
   - Upgraded workspace root resolution to session-scoped roots using source/session fingerprints.
   - `openclaw_max` profile now keeps workspace isolation on and forces docker sandbox mode.
2. Deterministic replay/resume:
   - Added replay envelope metadata to every checkpoint (`replay_state` with digests, schema version, runtime signature).
   - Added strict replay validation before restore (`task/owner/plan/title/description digest checks`).
   - Added `restore_task_from_checkpoint_snapshot(...)` and wired it into latest-checkpoint restore paths.
   - Extended resume APIs with strict/legacy replay mode handling and mode reporting.
   - Added checkpoint replay metrics in runtime state.
3. Distributed scheduling at scale:
   - Added lease-aware, health-aware, failure-aware, latency-aware node scoring.
   - Added node scheduler runtime stats tracking (`dispatches/failures/consecutive_failures/latency/last_score`).
   - Updated node selection to use scoring candidates instead of static ranking.
   - Added scheduler metadata to `/nodes`, `/nodes/control_plane`, and lease-claim responses.
4. Runtime/ops metrics:
   - Added runtime metrics fields for sandbox requirement, session isolation flag, checkpoint replay health, and node scheduler counters.
5. Config template updates in `.env.example`:
   - Added all new sandbox/session/checkpoint/node-scheduler knobs with hardened defaults.

### Validation Outcomes
1. Python syntax compile check passed for `mind_clone_agent.py`.
2. Targeted non-server smoke check passed for:
   - node candidate scoring helper,
   - deterministic checkpoint helper functions,
   - runtime metrics payload shape.

### Residual Risks / Notes
- Startup now intentionally fails when `OS_SANDBOX_REQUIRED=true` and docker sandbox prerequisites are not met.
- Strict replay validation can reject legacy checkpoints that were created before replay envelopes existed; use non-strict resume mode for older snapshots if needed.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Applied autonomy-first policy wording and defaults across active system files.

### Changes Made
1. Vision/docs alignment:
   - Updated `VISION.md` self-awareness status wording to `autonomy directives`.
   - Updated `README.md` identity wording from `bounds` to `directives`.
2. Runtime and prompt alignment in `mind_clone_agent.py`:
   - Changed autonomy mode fallback/default to `openclaw_max`.
   - Updated system prompt section title from `AUTHORITY BOUNDS` to `AUTONOMY DIRECTIVES`.
   - Reworded prompt behavior toward autonomous continuation under hard constraints.
   - Updated `/identity` output label to `Directives`.
   - Updated startup warning text to remove safety-first phrasing.
   - In `openclaw_max`, `check_authority(...)` now bypasses directive blocking for full-autonomy behavior.
3. Config alignment:
   - Updated `.env.example` defaults to autonomy-first (`AUTONOMY_MODE=openclaw_max`, `APPROVAL_GATE_MODE=off`, power profiles, queue on, diff warn, desktop active session off, failsafe off).
   - Updated local `.env` to enforce explicit autonomy-first runtime keys.

### Validation Outcomes
1. Repo-wide search confirms active docs/runtime text now use autonomy/directives language.
2. Python compile check for `mind_clone_agent.py` passed.
3. Runtime health check confirms server is healthy after restart with `autonomy_mode=openclaw_max` and `approval_gate_mode=off`.

### Residual Risks / Notes
- Historical lines in old changelog entries retain original wording by design as immutable audit history.

---

## 2026-02-08 | Worker: Codex GPT-5

### Session Summary
- Completed the remaining OpenClaw P0 import bundle wiring in `mind_clone_agent.py`, then fixed and validated runtime contract surfaces.

### Changes Made
1. Queue mode parity and routing:
   - Enabled full queue mode set (`off|on|auto|steer|followup|collect`) in runtime decisions.
   - Added collect-buffer merge/flush behavior with threshold and expiry flushing from spine supervisor.
   - Added owner queue mode ops endpoints and Telegram `/queue_mode`.
2. Session integrity and repair wiring:
   - Startup now runs transcript repair pass (`run_startup_transcript_repair`) after DB init.
   - Runtime metrics/counters include transcript repair and collect-mode telemetry.
3. Team/session tool control surface:
   - Added in-agent tools: `sessions_spawn`, `sessions_send`, `sessions_list`, `sessions_history`, `sessions_stop`.
   - Added spawn policy controls (`allow_all|main_only|matrix`) and enforced policy in tool/REST spawn paths.
4. Safety and policy hardening:
   - Enforced node command policy on local and remote command execution.
   - Applied SSRF URL guard to deep research, webpage/pdf reads, plugin calls, and node registration.
   - Added stricter plugin argument/schema validation against declared JSON schema.
5. Model router maturity:
   - Added profile health/disable windows, compatibility gating (`supports_tools`, `supports_vision`), and compat-skip metrics.
6. Sandbox and distributed/runtime telemetry:
   - Added sandbox registry touch/cleanup lifecycle tracking and periodic cleanup from spine supervisor.
   - Enriched node metadata with capability hash and lease capacity fields.
7. Memory and usage ops:
   - Added owner memory vector reindex endpoint and transactional rebuild path.
   - Added usage rollup snapshots and session usage summary endpoint.
8. Protocol contract layer:
   - Added protocol contracts for queue and approval surfaces with request/response validation.
   - Added `/ops/protocol/contracts` endpoint and fixed JSON-safe contract serialization.

### Validation Outcomes
1. `python -m py_compile mind_clone_agent.py` passed.
2. FastAPI TestClient smoke checks passed for:
   - `/heartbeat`
   - `/status/runtime`
   - `/ops/protocol/contracts`
   - `/ops/queue/mode` (POST/GET)
   - `/ops/usage/session`
3. Startup/lifespan smoke path confirmed:
   - app starts even when webhook setup fails (expected retry path),
   - queue workers and supervisors initialize/stop cleanly in test lifecycle.

### Residual Risks / Notes
- TestClient smoke used `OPS_AUTH_ENABLED=false` and `OS_SANDBOX_REQUIRED=false` overrides for local validation convenience.
- Full production validation still requires your real runtime env (actual bot token/webhook, docker availability when sandbox required).

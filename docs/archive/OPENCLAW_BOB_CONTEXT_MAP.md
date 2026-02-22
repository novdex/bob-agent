# OpenClaw + Bob Context Map

Last updated: 2026-02-18
Scope: `_external/openclaw` (upstream) + `mind-clone` (Bob integration)

## 1) What this repo contains

- Upstream OpenClaw lives in `_external/openclaw`.
- Bob (Mind Clone) lives in `mind-clone`, with:
- Legacy production monolith: `mind-clone/mind_clone_agent.py`
- Modular migration package: `mind-clone/src/mind_clone/*`

OpenClaw is a TypeScript/Node gateway-centered system. Bob is a Python/FastAPI agent platform that adopted many OpenClaw-style patterns and naming.

## 2) Upstream OpenClaw: startup and control plane

### 2.1 CLI startup chain

- Entry wrapper: `_external/openclaw/openclaw.mjs`
- Node bootstrap: `_external/openclaw/src/index.ts`
- CLI assembly: `_external/openclaw/src/cli/program/build-program.ts`
- Command registration: `_external/openclaw/src/cli/program/command-registry.ts`
- Lazy sub-CLI registration: `_external/openclaw/src/cli/program/register.subclis.ts`

Important: `openclaw gateway ...` commands are registered in `_external/openclaw/src/cli/gateway-cli/register.ts`.

### 2.2 Gateway startup chain

- Export + entry: `_external/openclaw/src/gateway/server.ts`
- Main startup: `_external/openclaw/src/gateway/server.impl.ts`
- Runtime state (HTTP + WS servers, broadcaster, dedupe/chat registries):
  `_external/openclaw/src/gateway/server-runtime-state.ts`
- HTTP routing: `_external/openclaw/src/gateway/server-http.ts`
- WS attach: `_external/openclaw/src/gateway/server-ws-runtime.ts`
- WS connection handling: `_external/openclaw/src/gateway/server/ws-connection.ts`
- WS frame handling + handshake/auth/pairing:
  `_external/openclaw/src/gateway/server/ws-connection/message-handler.ts`

## 3) Upstream OpenClaw: protocol, auth, permissions

### 3.1 Wire protocol

- Protocol schemas and validators:
  `_external/openclaw/src/gateway/protocol/index.ts`
- Protocol version constant:
  `_external/openclaw/src/gateway/protocol/schema/protocol-schemas.ts` (`PROTOCOL_VERSION = 3`)

Frame model:
- Request: `{type:"req", id, method, params}`
- Response: `{type:"res", id, ok, payload|error}`
- Event: `{type:"event", event, payload, ...}`

### 3.2 Authentication and local/remote trust

- Auth resolution + verification:
  `_external/openclaw/src/gateway/auth.ts`
- WS handshake auth and validation:
  `_external/openclaw/src/gateway/server/ws-connection/message-handler.ts`

Auth paths:
- Shared auth (token/password)
- Tailscale-aware auth (if enabled)
- Device-token auth (post-pairing)

### 3.3 Device pairing and node pairing

- Device pairing/token store:
  `_external/openclaw/src/infra/device-pairing.ts`
- Node pairing store:
  `_external/openclaw/src/infra/node-pairing.ts`

These are persisted under OpenClaw state dir (normally `~/.openclaw/...`).

### 3.4 Gateway method authorization (scope model)

- Method RBAC/scope checks:
  `_external/openclaw/src/gateway/server-methods.ts`
- Method list/events:
  `_external/openclaw/src/gateway/server-methods-list.ts`

OpenClaw uses operator/node roles and scopes such as:
- `operator.read`
- `operator.write`
- `operator.admin`
- `operator.approvals`
- `operator.pairing`

## 4) Upstream OpenClaw: agent run lifecycle

### 4.1 Gateway request -> async run

- `agent` and `agent.wait` handlers:
  `_external/openclaw/src/gateway/server-methods/agent.ts`
- Wait cache/listener for lifecycle end/error:
  `_external/openclaw/src/gateway/server-methods/agent-job.ts`

Flow:
1. `agent` validates request and returns immediate accepted ack.
2. Async `agentCommand(...)` runs in background.
3. `agent.wait` watches lifecycle completion events for the same `runId`.

### 4.2 Agent command orchestration

- Core command runtime:
  `_external/openclaw/src/commands/agent.ts`

Responsibilities:
- Resolve session/agent/workspace.
- Resolve model/thinking/verbose.
- Load skills snapshot.
- Run with model fallback.
- Ensure lifecycle end/error events exist even if embedded runner misses them.

### 4.3 Embedded runner and queueing

- Runner entry:
  `_external/openclaw/src/agents/pi-embedded-runner/run.ts`
- Attempt execution:
  `_external/openclaw/src/agents/pi-embedded-runner/run/attempt.ts`
- Session subscription/event bridge:
  `_external/openclaw/src/agents/pi-embedded-subscribe.ts`

Queue model:
- Per-session lane + global lane via command queue.
- Implemented in `_external/openclaw/src/process/command-queue.ts`.
- Session serialization prevents transcript/tool races.

### 4.4 Event streaming bridge

- Shared event bus:
  `_external/openclaw/src/infra/agent-events.ts`

Main streams:
- lifecycle
- assistant
- tool

## 5) Upstream OpenClaw: channel and outbound architecture

### 5.1 Channel plugin model

- Channel registry abstraction:
  `_external/openclaw/src/channels/plugins/index.ts`
- Channel types/contracts:
  `_external/openclaw/src/channels/plugins/types.ts`
- Core channel registry metadata:
  `_external/openclaw/src/channels/registry.ts`
- Channel lifecycle manager:
  `_external/openclaw/src/gateway/server-channels.ts`

Channels are plugin-driven, not hardcoded in one monolithic message handler.

### 5.2 Outbound delivery

- Agent delivery bridge:
  `_external/openclaw/src/commands/agent/delivery.ts`
- Normalized outbound send + chunking:
  `_external/openclaw/src/infra/outbound/deliver.ts`
- Action runner for channel message actions:
  `_external/openclaw/src/infra/outbound/message-action-runner.ts`

## 6) Upstream OpenClaw: plugin system

- Runtime active registry:
  `_external/openclaw/src/plugins/runtime.ts`
- Plugin loader:
  `_external/openclaw/src/plugins/loader.ts`
- Registry construction:
  `_external/openclaw/src/plugins/registry.ts`
- Plugin type contracts:
  `_external/openclaw/src/plugins/types.ts`
- Gateway plugin integration:
  `_external/openclaw/src/gateway/server-plugins.ts`

Plugins can register:
- tools
- hooks
- channels
- provider adapters
- gateway methods
- HTTP handlers/routes
- CLI extensions

## 7) Upstream OpenClaw: config model

- Config path/state resolution:
  `_external/openclaw/src/config/paths.ts`
- Config IO/load/validation:
  `_external/openclaw/src/config/io.ts`
- Types and schema exports:
  `_external/openclaw/src/config/types.ts`
  `_external/openclaw/src/config/schema.ts`

Important behavior:
- Strict validation (invalid config can prevent startup).
- Includes and env substitution are supported.
- Canonical state default is `~/.openclaw`.

## 8) Bob (Mind Clone): runtime flow

### 8.1 Production path in this repo

- Primary production runtime still in monolith:
  `mind-clone/mind_clone_agent.py`
- FastAPI app and endpoints are declared there (`/chat`, `/telegram/webhook`, `/status/runtime`, etc.).

### 8.2 Bob inbound flow (`/chat`)

Path in `mind-clone/mind_clone_agent.py`:
1. `/chat` endpoint receives request.
2. `dispatch_incoming_message(...)` chooses queue/direct execution.
3. `run_owner_message_job(...)` executes a serialized run.
4. `run_agent_loop_with_new_session(...)` -> `run_agent_loop(...)`.
5. LLM/tool loop:
   - `call_llm(...)`
   - parse tool calls
   - `execute_tool_with_context(...)`
   - append tool messages
   - iterate until final assistant text.

### 8.3 Bob guardrail stack

In `execute_tool_with_context(...)` the checks are layered:
1. tool policy profile
2. execution sandbox profile
3. workspace isolation
4. authority bounds (`check_authority(...)`)
5. desktop session constraints
6. workspace diff gate
7. host exec interlock
8. OS sandbox interception
9. approval gate
10. dispatch to built-in/custom/plugin tool

## 9) Bob openclaw_max behavior (critical)

Location: `mind-clone/mind_clone_agent.py`

Key flags:
- `AUTONOMY_MODE` (`standard | openclaw_max`)
- `AUTONOMY_OPENCLAW_MAX`
- `BOB_FULL_POWER_ENABLED`
- `BOB_FULL_POWER_SCOPE` (`workspace | system`)

When `AUTONOMY_OPENCLAW_MAX` is enabled, Bob force-overrides many defaults:
- policy pack -> dev
- queue mode -> on
- tool policy -> power
- sandbox profile -> power
- approval gate -> off
- host exec interlock -> off
- workspace diff gate mode -> warn
- desktop active-session/failsafe restrictions reduced

`check_authority(...)` explicitly short-circuits and allows all tools when:
- full-power system mode is active, or
- `AUTONOMY_OPENCLAW_MAX` is active

Startup explicitly warns:
- `SPINE_PRECHECK_WARN AUTONOMY_MODE=openclaw_max active: approvals/interlocks/control friction are reduced.`

## 10) Upstream OpenClaw vs Bob: important differences

1. Control plane model
- OpenClaw: WS gateway-first control plane with typed protocol and role/scope auth.
- Bob: FastAPI-first app; no equivalent WS role/scope protocol as the main control path.

2. Channel architecture
- OpenClaw: channel plugin docking + gateway channel manager.
- Bob: direct Telegram/API flow with added tools and optional abstractions.

3. Session + queue model
- OpenClaw: session-key-centric routing integrated with gateway lanes.
- Bob: owner-centric queue and serialized runs in Python.

4. Security posture defaults
- OpenClaw: pairing + scoped operators + method-level RBAC is core.
- Bob: can run highly permissive `openclaw_max` / full-power modes that reduce friction significantly.

5. Agent runtime substrate
- OpenClaw: embedded Pi-agent runtime (`runEmbeddedPiAgent`) and stream bridge.
- Bob: custom Python loop around Kimi API and tool execution.

## 11) Practical start commands (upstream OpenClaw)

From `_external/openclaw`:
- Start gateway foreground: `openclaw gateway run`
- Check status/probe: `openclaw gateway status`
- Call health via gateway: `openclaw gateway call health --params "{}"`
- List sessions: `openclaw sessions --json`

## 12) Practical start commands (Bob in this repo)

From `mind-clone`:
- Monolith runtime: `python mind_clone_agent.py`
- Modular runtime: `python -m mind_clone --web`
- API check: `GET http://localhost:8000/status/runtime`

## 13) Suggested use of this map

When debugging, follow this order:
1. Confirm which runtime is actually active (OpenClaw gateway vs Bob monolith vs Bob modular).
2. Check auth/permission mode (`openclaw` scopes vs Bob `AUTONOMY_MODE`/approval settings).
3. Trace one request end-to-end with the file paths listed above.
4. Fix flow mismatches where architecture assumptions differ (gateway model vs direct API model).


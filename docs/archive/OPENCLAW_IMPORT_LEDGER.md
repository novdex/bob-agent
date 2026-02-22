# OpenClaw -> Bob Import Ledger (Top 100)

## Scope
- OpenClaw source analyzed from local clone: `_external/openclaw`
- Bob source analyzed from: `mind-clone/mind_clone_agent.py`
- Goal: import all useful OpenClaw ideas that increase Bob's AGI pillars (`Reasoning`, `Memory`, `Autonomy`, `Learning`, `Tool Mastery`, `Self-Awareness`, `World Understanding`, `Communication`)

## How To Use This Ledger
- `Status`: `Done` means Bob already has equivalent capability, `Partial` means capability exists but lower maturity, `Missing` means not present.
- `Priority`: `P0` execute first, `P1` next wave, `P2` optimization/hardening.
- `Gate`: measurable success criterion for each capability.

## Track 1: Session Integrity And Runtime Core (1-10)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 1 | `src/agents/session-write-lock.ts` | Transcript write-lock around session state writes | Reliability | Missing | Add per-session lock manager for chat/task/subagent writers | Zero transcript corruption under concurrent writes test | P0 |
| 2 | `src/agents/session-transcript-repair.ts` | Transcript pairing and structure repair | Memory | Missing | Add repair pass on load/startup for malformed message pairs | Repair test suite passes on injected corrupt transcripts | P0 |
| 3 | `src/agents/session-file-repair.ts` | Session file repair utilities | Reliability | Missing | Add DB/session row repair command for runtime recovery | Recovery command repairs known broken fixtures | P1 |
| 4 | `src/agents/context-window-guard.ts` | Context overflow guard with pre-emptive trimming | Reasoning | Missing | Add prompt budget guard before model call | Model-overflow errors reduced by >=90% | P0 |
| 5 | `src/agents/pi-extensions/context-pruning/*` | Multi-strategy context pruning pipeline | Reasoning | Partial | Upgrade Bob pruning from threshold-only to strategy-based | Latency and token pressure drop in long chats | P1 |
| 6 | `src/agents/pi-extensions/compaction-safeguard.ts` | Compaction failure safeguards | Reliability | Partial | Add retry tiers and fallback for compaction errors | No crash on repeated compaction failures | P1 |
| 7 | `src/agents/session-tool-result-guard.ts` | Tool result guard for transcript consistency | Reliability | Missing | Add schema+size guard before tool result persistence | Invalid tool results blocked with structured errors | P0 |
| 8 | `src/agents/abort.ts` | Cancellation propagation through run stack | Autonomy | Partial | Harden cancellation propagation across subagent/task/workflow | Cancel request stops all child work within SLA | P1 |
| 9 | `src/agents/timeout.ts` | Unified timeout envelope for agent calls | Reliability | Partial | Normalize timeout policy per mode/lane | Timeout behavior deterministic in stress tests | P1 |
| 10 | `src/agents/system-prompt-report.ts` | Prompt composition report | Self-Awareness | Partial | Expand Bob context xray with prompt assembly trace | `/context/json` includes prompt segment accounting | P0 |

## Track 2: Queue, Lanes, And Backpressure (11-20)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 11 | `src/process/command-queue.ts` | Central command queue with worker discipline | Autonomy | Partial | Add queue state machine parity (`queued/running/retry/dead`) | Queue never stalls in soak test | P0 |
| 12 | `src/process/lanes.ts` | Lane scheduler policy | Autonomy | Partial | Expand Bob lane semantics beyond static limits | Lane starvation <1% under mixed workload | P0 |
| 13 | `src/auto-reply/reply/queue/state.ts` | Queue state object with transitions | Reliability | Missing | Add explicit queue transition graph and validation | Illegal transitions rejected in tests | P1 |
| 14 | `src/auto-reply/reply/queue/normalize.ts` | Queue event normalization | Reliability | Missing | Add canonical queue event formatter | Metrics unaffected by input formatting variance | P1 |
| 15 | `src/auto-reply/reply/queue/drain.ts` | Controlled drain logic and flush policy | Reliability | Missing | Add flush/drain routine for shutdown and failover | Clean shutdown without lost queued work | P1 |
| 16 | `src/gateway/server-lanes.ts` | Server-side lane routing policy | Autonomy | Partial | Add lane routing by source + urgency + owner mode | Correct lane assignment >=99% fixtures | P1 |
| 17 | `src/gateway/server-methods/chat.ts` | Queue mode semantics (`steer/followup/collect`) | Communication | Missing | Import session queue modes and map to Bob commands/API | Queue mode behavior matches spec tests | P0 |
| 18 | `src/process/spawn-utils.ts` | Worker spawn/restart utilities | Reliability | Missing | Add queue worker supervisor helper module in Bob file | Worker auto-recovers from kill test | P1 |
| 19 | `src/process/exec.ts` | Command execution wrapper with consistent telemetry | Tool Mastery | Partial | Normalize run_command telemetry by queue lane | Per-lane success/failure rates exposed | P2 |
| 20 | `src/process/child-process-bridge.ts` | Child-process bridge abstraction | Tool Mastery | Missing | Add optional process bridge for long-lived command jobs | Background command resume works after restart | P2 |

## Track 3: Team Mode And Subagents (21-30)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 21 | `src/agents/openclaw-tools.sessions.test.ts` | In-agent session controls as tools | Autonomy | Partial | Add session spawn/send/list/history tools callable by Bob | Bob can orchestrate subagents via tool calls | P0 |
| 22 | `src/agents/subagent-registry.ts` | Persistent subagent registry | Memory | Partial | Add stronger metadata/versioning for Bob team agents | Restart preserves team graph with no drift | P1 |
| 23 | `src/agents/subagent-registry.store.ts` | Registry storage discipline | Reliability | Missing | Add registry integrity checks and migration version | Registry checksum verification passes | P1 |
| 24 | `src/agents/subagent-announce-queue.ts` | Announce queue for subagent events | Communication | Missing | Add async subagent event stream for owner visibility | Subagent lifecycle feed visible in UI/Telegram | P1 |
| 25 | `src/agents/sessions-spawn-threadid.test.ts` | Thread/session affinity on spawn | Reliability | Missing | Add parent-child thread affinity semantics | Child routes always tied to expected session scope | P1 |
| 26 | `src/auto-reply/reply/subagents-utils.ts` | Subagent utility orchestration helpers | Autonomy | Missing | Introduce shared helper for fanout/fanin orchestration | Multi-agent run completion improves under load | P2 |
| 27 | `src/agents/openclaw-tools.subagents.*` | Cross-agent spawn policy and allowlist | Safety | Partial | Enforce explicit cross-agent spawn policy table | Unauthorized cross-agent spawn blocked | P0 |
| 28 | `src/agents/subagent-announce.ts` | Structured lifecycle payloads | Communication | Partial | Expand Bob event payload format for run/step/status | Event schema stable and documented | P2 |
| 29 | `src/agents/tools/agents-list-tool.ts` | Team discovery tool | Self-Awareness | Missing | Add tool-level agent discovery beyond REST endpoint | Agent can self-query available teammates | P1 |
| 30 | `src/agents/pi-embedded-runner/lanes.ts` | Lane-aware subagent runner behavior | Autonomy | Missing | Map team runs to lane policy and budgets | Team runs obey queue and budget policy | P1 |

## Track 4: Sandbox And Isolation (31-40)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 31 | `src/agents/sandbox/context.ts` | Per-session sandbox context resolution | Safety | Partial | Tighten Bob sandbox context by owner+agent+session | No workspace leakage across sessions | P0 |
| 32 | `src/agents/sandbox/registry.ts` | Sandbox runtime registry | Safety | Missing | Track active sandbox instances per session/agent | Registry reflects live sandbox count accurately | P0 |
| 33 | `src/agents/sandbox/manage.ts` | Sandbox lifecycle manager | Autonomy | Missing | Add start/stop/reuse lifecycle instead of ad-hoc runs | Sandbox startup latency reduced by >=40% | P0 |
| 34 | `src/agents/sandbox/docker.ts` | Hardened docker create args | Safety | Partial | Import stricter docker flags/caps/network policies | Security checklist pass on docker args | P1 |
| 35 | `src/agents/sandbox/workspace.ts` | Workspace mount isolation | Safety | Partial | Enforce per-agent/session workspace mount roots | Cross-agent file access blocked by default | P0 |
| 36 | `src/agents/sandbox/prune.ts` | Sandbox garbage collection | Reliability | Missing | Add GC task for orphaned sandboxes/volumes | No orphan sandbox after soak shutdown test | P1 |
| 37 | `src/agents/sandbox/runtime-status.ts` | Runtime sandbox status reporting | Self-Awareness | Missing | Add `/status/runtime` sandbox block | Status endpoint shows per-sandbox health | P1 |
| 38 | `src/agents/sandbox/tool-policy.ts` | Tool policy by sandbox profile | Safety | Partial | Merge sandbox profile policy with tool approval matrix | Policy simulator produces deterministic outcomes | P1 |
| 39 | `src/agents/sandbox/config-hash.ts` | Immutable config hash for sandbox identity | Reliability | Missing | Add config-hash key for reproducible sandbox reuse | Hash collision tests pass; reuse deterministic | P2 |
| 40 | `src/agents/sandbox/browser-bridges.ts` | Browser bridge in sandbox | Tool Mastery | Missing | Add optional browser bridge channel for desktop tasks | Browser automation succeeds inside sandbox | P2 |

## Track 5: Approval, Safety, And Governance (41-50)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 41 | `src/gateway/exec-approval-manager.ts` | Central approval manager orchestration | Safety | Partial | Promote Bob approval logic to explicit manager layer | Approval SLA and state transitions audited | P0 |
| 42 | `src/infra/exec-approval-forwarder.ts` | Approval forwarding for distributed executors | Safety | Missing | Forward approval state to remote node executors | Remote exec blocks until approval sync | P1 |
| 43 | `src/gateway/node-command-policy.ts` | Node-level command policy | Safety | Partial | Add capability-specific node policy matrix | Forbidden command blocked on remote nodes | P0 |
| 44 | `src/security/external-content.ts` | External content risk scanner | Safety | Missing | Scan fetched content for risky payload markers | High-risk payloads are flagged and gated | P1 |
| 45 | `src/security/skill-scanner.ts` | Skill/plugin static policy scanner | Safety | Partial | Expand Bob plugin scanner to skill-level risks | New plugin scan report includes risk levels | P1 |
| 46 | `src/security/windows-acl.ts` | Windows ACL enforcement checks | Safety | Missing | Add ACL validation for sensitive roots | Startup warns/fails on insecure ACL | P2 |
| 47 | `src/security/audit.ts` | Security audit bundle | Safety | Partial | Add scheduled security audit task in Bob | Weekly audit report generated automatically | P2 |
| 48 | `src/security/fix.ts` | Security fix recommendations | Learning | Missing | Generate actionable remediation plan from audit | Fix plan endpoint produces ranked actions | P2 |
| 49 | `src/gateway/origin-check.ts` | Origin verification layer | Safety | Missing | Add origin checks for web-admin/control surfaces | Invalid origins rejected consistently | P1 |
| 50 | `src/infra/net/ssrf.ts` | SSRF hardening for outbound fetch | Safety | Missing | Harden URL fetch tools with SSRF policy | SSRF test suite blocks private-network probes | P0 |

## Track 6: Memory And Context Intelligence (51-60)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 51 | `src/memory/manager.ts` | Memory manager orchestration | Memory | Partial | Refactor memory ops into explicit manager API in monolith | Memory operations share one control path | P1 |
| 52 | `src/memory/manager.atomic-reindex.test.ts` | Atomic reindex protocol | Reliability | Missing | Add transactional reindex for vectors | Reindex never exposes half-built index | P0 |
| 53 | `src/memory/manager.vector-dedupe.test.ts` | Embedding dedupe | Memory | Missing | Add duplicate vector detection and merge strategy | Duplicate memory rows reduced significantly | P1 |
| 54 | `src/memory/hybrid.ts` | Hybrid lexical+semantic search | Reasoning | Partial | Add weighted hybrid retrieval for lessons/summaries | Retrieval quality KPI improves | P1 |
| 55 | `src/memory/qmd-manager.ts` | QMD memory workflow | Memory | Missing | Add quality-aware memory ingestion queue | Memory write quality score tracked | P2 |
| 56 | `src/memory/session-files.ts` | Session memory file sync | Continuity | Missing | Add memory export snapshots by session timeline | Session restore includes memory timeline | P2 |
| 57 | `src/memory/search-manager.ts` | Search manager abstraction | Memory | Missing | Add search manager layer for retrieval strategies | Strategy switch benchmark stable | P2 |
| 58 | `src/agents/tools/memory-tool.citations.test.ts` | Citation-grounded memory responses | Communication | Partial | Enforce citation objects in memory answer rendering | Memory answers include source refs consistently | P1 |
| 59 | `src/memory/backend-config.ts` | Memory backend failover config | Reliability | Missing | Add backend profile switch for embeddings/vector store | Memory backend failover passes | P2 |
| 60 | `src/memory/status-format.ts` | Memory health/status formatting | Self-Awareness | Missing | Add memory health block to runtime status | `/status/runtime` exposes memory health fields | P2 |

## Track 7: Model Router And Provider Resilience (61-70)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 61 | `src/agents/model-fallback.ts` | Multi-profile failover policy | Reliability | Done | Keep parity tests and drift checks | Failover tests stay green after each release | P1 |
| 62 | `src/agents/auth-profiles.ts` | Auth profile rotation and cooldowns | Reliability | Partial | Import richer profile health and decay logic | Cooldown behavior matches policy matrix | P0 |
| 63 | `src/agents/auth-profiles/order.ts` | Auth/profile ordering strategy | Reliability | Missing | Add deterministic ordering policy with persisted last-good | Selection stability across restarts | P1 |
| 64 | `src/agents/failover-error.ts` | Failover reason classification | Learning | Missing | Add failover reason taxonomy in Bob runtime state | Failover dashboard grouped by root cause | P1 |
| 65 | `src/agents/model-catalog.ts` | Dynamic model catalog introspection | World Understanding | Partial | Expand catalog with provider capability tags | Router chooses capable model >=99% fixtures | P1 |
| 66 | `src/agents/model-compat.ts` | Model compatibility filters | Reliability | Partial | Add strict tool-mode compatibility gating | Incompatible model/tool combos prevented | P0 |
| 67 | `src/agents/model-selection.ts` | Selection policy separation | Autonomy | Partial | Isolate route policy from provider call path | Selection logic unit-tested independently | P2 |
| 68 | `src/agents/openai-responses.reasoning-replay.test.ts` | Reasoning replay handling | Reasoning | Missing | Add replay-safe reasoning text/tool traces | Replay output deterministic by mode | P2 |
| 69 | `src/agents/models-config.providers.ts` | Provider config normalization | Reliability | Partial | Harden provider config parser and defaults | Invalid provider config auto-repaired | P1 |
| 70 | `src/agents/model-auth.ts` | Provider auth health checks | Reliability | Missing | Add periodic auth health probe for active providers | Proactive auth failure alerts raised | P2 |

## Track 8: Distributed Nodes And Control Plane (71-80)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 71 | `src/gateway/node-registry.ts` | Central node registry | Autonomy | Partial | Add richer capability metadata and persistence policies | Registry includes capability hash and TTL | P0 |
| 72 | `src/gateway/server-node-subscriptions.ts` | Node event subscription stream | Communication | Missing | Add node event subscription endpoint in Bob | Operators receive live node state updates | P1 |
| 73 | `src/gateway/server-node-events.ts` | Structured node event bus | Reliability | Missing | Introduce typed node events with retention | Node incidents reconstructable from events | P1 |
| 74 | `src/gateway/server-methods/nodes.helpers.ts` | Node scoring helpers | Autonomy | Partial | Improve Bob scheduler scoring dimensions | Better task-node fit rate in benchmark | P1 |
| 75 | `src/gateway/server.nodes.late-invoke.test.ts` | Late invoke handling | Reliability | Missing | Add retry semantics for node command latency | Late invokes auto-recover without drop | P1 |
| 76 | `src/gateway/server/health-state.ts` | Health-state object for gateway | Reliability | Missing | Add explicit control-plane health object | `/status/runtime` includes control-plane health | P2 |
| 77 | `src/infra/node-shell.ts` | Remote node shell execution wrapper | Tool Mastery | Partial | Harden node shell execution wrapper and quotas | Remote shell errors categorized and retried | P2 |
| 78 | `src/infra/node-pairing.ts` | Node trust pairing | Safety | Missing | Add signed pairing handshake for new nodes | Unpaired node cannot execute tasks | P1 |
| 79 | `src/infra/transport-ready.ts` | Transport readiness checks | Reliability | Missing | Add transport readiness gate pre-dispatch | Dispatch blocked until node transport healthy | P1 |
| 80 | `src/gateway/server-mobile-nodes.ts` | Mobile/edge node handling patterns | Autonomy | Missing | Add constrained-node profile for low-resource nodes | Edge node tasks finish without overload | P2 |

## Track 9: Observability, Replay, And Reliability Ops (81-90)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 81 | `src/infra/diagnostic-events.ts` | Typed diagnostic events | Self-Awareness | Missing | Add typed event taxonomy feeding blackbox | Event schema versioned and validated | P1 |
| 82 | `src/infra/diagnostic-flags.ts` | Dynamic diagnostic flags | Reliability | Missing | Add runtime toggles for deep tracing without restart | Toggle takes effect within one loop tick | P2 |
| 83 | `src/infra/retry-policy.ts` | Shared retry policy engine | Reliability | Partial | Unify retry policies across webhook/tool/node/network | Retry behavior consistent across subsystems | P1 |
| 84 | `src/infra/restart-sentinel.ts` | Restart sentinel marker | Reliability | Missing | Add restart reason sentinel and post-restart report | Restart cause visible in runtime endpoint | P2 |
| 85 | `src/infra/state-migrations.ts` | State migration framework | Continuity | Missing | Add versioned state migration pipeline | Migrations safe across releases | P1 |
| 86 | `src/infra/session-cost-usage.ts` | Session cost accounting | World Understanding | Partial | Expand Bob cost accounting by owner/task/agent | Cost budget alerts trigger correctly | P0 |
| 87 | `src/infra/heartbeat-runner.ts` | Unified heartbeat runner | Reliability | Partial | Integrate cron/task/node heartbeats into one runner | Heartbeat staleness alerts under SLA | P1 |
| 88 | `src/infra/system-events.ts` | System event timeline | Self-Awareness | Missing | Add long-lived event timeline endpoint | Timeline supports incident reconstruction | P2 |
| 89 | `src/gateway/ws-log.ts` | WebSocket event logging | Observability | Missing | Add stream logs for UI/control channels | WS diagnostics visible in ops console | P2 |
| 90 | `src/infra/warning-filter.ts` | Noise filtering for warnings | Reliability | Missing | Add warning classification and dedupe | Alert noise reduced without missed incidents | P2 |

## Track 10: UI, Workflow, Plugins, And Ops UX (91-100)
| # | OpenClaw Source | Capability | Pillar | Bob Status | Action For Bob | Gate | Priority |
|---|---|---|---|---|---|---|---|
| 91 | `src/gateway/control-ui.ts` | First-party command center control API | Communication | Partial | Expand Bob UI backend parity and harden contracts | UI parity checklist >=95% passes | P1 |
| 92 | `src/infra/control-ui-assets.ts` | Robust static asset serving for UI | Reliability | Partial | Add build integrity check and cache headers | `/ui` serving stable across restarts | P1 |
| 93 | `src/gateway/protocol/schema/*` | Unified protocol schema contracts | Reliability | Missing | Add schema contracts for Bob ops endpoints | Contract tests prevent payload drift | P0 |
| 94 | `src/plugins/schema-validator.ts` | Plugin manifest schema validator | Safety | Partial | Harden plugin manifest schema with strict validation | Invalid manifests rejected consistently | P0 |
| 95 | `src/plugins/runtime/native-deps.ts` | Native dependency guard for plugins | Safety | Missing | Add native-deps policy checks pre-plugin load | Unsafe native deps blocked by policy | P1 |
| 96 | `src/plugins/hook-runner-global.ts` | Global plugin hook runner | Tool Mastery | Partial | Expand plugin lifecycle hooks and tracing | Hook execution telemetry visible | P2 |
| 97 | `src/commands/configure.wizard.ts` | Interactive onboarding wizard | Communication | Missing | Add onboarding wizard for env/auth/channels | New setup time reduced significantly | P2 |
| 98 | `src/commands/health.ts` | Rich health command set | Self-Awareness | Partial | Add operator health bundles mapped to Bob runtime | Health command covers all core subsystems | P1 |
| 99 | `src/commands/models/list.status-command.ts` | Model status operator command | Reliability | Missing | Add model profile status endpoint and UI panel | Operator can inspect model pool instantly | P1 |
| 100 | `src/gateway/server-startup-log.ts` | Structured startup report | Reliability | Partial | Extend Bob startup report with capability digest | Startup report includes all critical toggles | P2 |

## Execution Order (Recommended)
1. P0 first: items `1,4,7,11,12,17,21,27,31,32,33,35,41,43,50,52,61,62,66,71,86,93,94`.
2. P1 second: all `P1` items above.
3. P2 last: optimizations and ops maturity.

## Current Totals
- `Done`: 1
- `Partial`: 43
- `Missing`: 56

## Notes
- This ledger is capability-level and intentionally implementation-neutral.
- For each selected item, implementation should include:
  - code change in `mind-clone/mind_clone_agent.py`
  - regression tests/smoke checks
  - runtime metric and changelog entry.

# OpenClaw Phase 3 Audit (P0 Parity) for Bob

Date: 2026-02-08  
Scope: P0 items from `mind-clone/OPENCLAW_IMPORT_LEDGER.md`  
Target: `mind-clone/mind_clone_agent.py`

## 1) Audit Method
- Parsed all P0 rows from the ledger (24 P0 capabilities).
- Read corresponding OpenClaw source files directly from `_external/openclaw`.
- Verified Bob equivalents by searching and reading line-level implementations in `mind-clone/mind_clone_agent.py`.

## 2) Reproducible P0 Audit Size
- OpenClaw P0 files audited: `46`
- OpenClaw P0 lines audited: `8436`
- Includes wildcard expansions:
- `src/agents/openclaw-tools.subagents.*` -> `7` files
- `src/gateway/protocol/schema/*` -> `17` files

## 3) Bob P0 Parity Snapshot (Corrected)

### Done (Equivalent Behavior Present)
1. Context window guard and pressure handling (`#4`)
   - Evidence: `mind-clone/mind_clone_agent.py:11113`, `mind-clone/mind_clone_agent.py:11228`, `mind-clone/mind_clone_agent.py:18397`
2. Prompt/context visibility (`#10`)
   - Evidence: `mind-clone/mind_clone_agent.py:18397`, `mind-clone/mind_clone_agent.py:18409`, `mind-clone/mind_clone_agent.py:18423`
3. Command queue core discipline (`#11`)
   - Evidence: `mind-clone/mind_clone_agent.py:1088`, `mind-clone/mind_clone_agent.py:14245`, `mind-clone/mind_clone_agent.py:16156`
4. Lane scheduling basics (`#12`)
   - Evidence: `mind-clone/mind_clone_agent.py:14187`, `mind-clone/mind_clone_agent.py:14214`, `mind-clone/mind_clone_agent.py:14223`
5. Workspace isolation roots (`#35`)
   - Evidence: `mind-clone/mind_clone_agent.py:9842`, `mind-clone/mind_clone_agent.py:9909`

### Partial (Present, But Not OpenClaw-Grade)
1. Session write lock (`#1`)
   - Bob has owner execution locks, but not transcript-level write lock/repair pairing.
   - Evidence: `mind-clone/mind_clone_agent.py:14287`
2. Tool-result consistency guard (`#7`)
   - Bob removes orphan tool messages and trims payloads; no strict guard manager/synthesis parity.
   - Evidence: `mind-clone/mind_clone_agent.py:12039`, `mind-clone/mind_clone_agent.py:12202`
3. In-agent session controls (`#21`)
   - Bob has REST team controls; not yet exposed as first-class in-agent session tools.
   - Evidence: `mind-clone/mind_clone_agent.py:18469`, `mind-clone/mind_clone_agent.py:18502`
4. Cross-agent spawn policy (`#27`)
   - Bob enforces limits and team boundaries, but policy matrix parity is thinner.
   - Evidence: `mind-clone/mind_clone_agent.py:14469`, `mind-clone/mind_clone_agent.py:16672`
5. Exec approval orchestration (`#41`)
   - Bob has strong approval flow; centralized manager semantics can be tightened.
   - Evidence: `mind-clone/mind_clone_agent.py:10353`, `mind-clone/mind_clone_agent.py:10477`, `mind-clone/mind_clone_agent.py:10649`
6. Node command policy (`#43`)
   - Bob has host interlock + allowlist controls; less granular than OpenClaw policy matrix.
   - Evidence: `mind-clone/mind_clone_agent.py:10258`, `mind-clone/mind_clone_agent.py:10649`
7. Auth profile rotation/cooldowns (`#62`)
   - Bob has advanced model router + cooldown + stickiness, but not full auth-profile parity.
   - Evidence: `mind-clone/mind_clone_agent.py:11384`, `mind-clone/mind_clone_agent.py:11558`, `mind-clone/mind_clone_agent.py:11600`
8. Model compatibility gating (`#66`)
   - Bob has profile/tool gating and canary/failover behavior, but compatibility contracts can be stricter.
   - Evidence: `mind-clone/mind_clone_agent.py:10174`, `mind-clone/mind_clone_agent.py:11384`, `mind-clone/mind_clone_agent.py:11652`
9. Node registry/control plane richness (`#71`)
   - Bob already has leases/capability routing; parity gap is mainly advanced distributed scheduling policy.
   - Evidence: `mind-clone/mind_clone_agent.py:5775`, `mind-clone/mind_clone_agent.py:5824`, `mind-clone/mind_clone_agent.py:5953`
10. Session cost accounting depth (`#86`)
    - Bob has usage accounting and gates; less detailed session/accounting surfaces than OpenClaw target.
    - Evidence: `mind-clone/mind_clone_agent.py:989`, `mind-clone/mind_clone_agent.py:15152`
11. Plugin schema validation strictness (`#94`)
    - Bob validates plugin metadata and trust controls, but no dedicated schema contract module parity.
    - Evidence: `mind-clone/mind_clone_agent.py:6294`, `mind-clone/mind_clone_agent.py:6380`

### Missing (High-Value Gaps)
1. Transcript repair pass (`#2`)
   - No dedicated transcript repair routine on load/startup.
2. Queue mode semantics (`steer/followup/collect`) (`#17`)
   - Bob has queue on/off/auto, not these OpenClaw mode semantics.
   - Evidence: `mind-clone/mind_clone_agent.py:372`
3. Sandbox runtime registry (`#32`)
   - No persistent sandbox registry object/lifecycle inventory.
4. Sandbox lifecycle manager (`#33`)
   - No start/stop/reuse sandbox manager abstraction.
5. SSRF hardening module (`#50`)
   - No dedicated DNS/IP private-network SSRF policy layer.
6. Atomic memory reindex protocol (`#52`)
   - No transactional atomic reindex flow matching OpenClaw test pattern.
7. Unified protocol schema contracts (`#93`)
   - No central endpoint/schema contract registry equivalent to `gateway/protocol/schema/*`.

## 4) Import Order (What Bob Should Take Next)
1. Session integrity bundle
   - Implement transcript write-lock manager + transcript repair pass + strict tool-result guard.
   - Covers: `#1`, `#2`, `#7`
2. Protocol and network trust bundle
   - Add SSRF DNS/IP policy layer + unified schema contracts for ops/UI endpoints.
   - Covers: `#50`, `#93`
3. Sandbox lifecycle bundle
   - Add sandbox registry + lifecycle manager (start/reuse/stop + health).
   - Covers: `#32`, `#33`
4. Queue semantics bundle
   - Add `steer/followup/collect` queue modes and route rules.
   - Covers: `#17`
5. Reliability depth bundle
   - Add atomic memory reindex protocol and stronger plugin schema contracts.
   - Covers: `#52`, `#94`

## 5) Bob Analogy (Short)
- Bob already has a strong spine, multiple hands, and lane traffic control.
- What is still missing from OpenClaw parity is mainly:
- hand safety reflexes for internet input (`SSRF`),
- exact memory surgery tools (`transcript repair` + `atomic reindex`),
- and a central playbook language for every API contract (`protocol schemas`).

## 6) Ready State
- Phase 3 is complete and decision-ready.
- Next step is implementation of Bundle 1 (Session integrity) first.

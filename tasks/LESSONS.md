# Bob Team - Lessons Learned

## Lessons

- [2026-03-01] **Classify tool dependencies before parallelizing execution to prevent race conditions.** (agent-1, TASK-010-opus-add-unit-tests-for-parallel.py-module.md)
- [2026-03-01] **Lesson Learned (TASK-011):**

> Test context trimming with exact boundaries (empty, single-char, max-length messages).

âœ… Saved to memory for future reference. (agent-2, TASK-011-opus-add-unit-tests-for-context_engine-module.md)
- [2026-03-01] Replace deprecated datetime.utcnow() with datetime.now(timezone.utc) across all modules. (agent-2, TASK-013-opus-fix-datetime.utcnow-deprecation-across-c.md)
- [2026-03-01] Test RBAC with role hierarchy (admin > user > viewer) and edge cases (None users). (agent-1, TASK-012-opus-add-unit-tests-for-authorization-module.md)
- [2026-03-01] Use LLM context injection with fallbacks for safely scoping tools to users. (agent-1, TASK-014-opus-implement-missing-create_task-and-list_t.md)
- [2026-03-01] I don't have the actual error output for TASK-015's failure. To write an accurate lesson for future developers, I need to see the error message or failure details.

Can you provide:
1. **The error message/output** that was produced when the test failed
2. Or a **log file** from the agent run (stderr/stdout)

Without the specific failure details, I can't write a lesson that's genuinely useful to the team. Once you share the error, I'll write a concise 1-line lesson in the format you requested. (agent-2, TASK-015-opus-add-unit-tests-for-knowledge-and-subagen.md)
- [2026-03-01] **Lesson:** Verify modules exist in codebase before writing tests for them. (agent-1, TASK-015-opus-add-unit-tests-for-knowledge-and-subagen.md)
- [2026-03-01] Replace datetime.utcnow() with datetime.now(timezone.utc) to fix Python 3.12+ deprecation. (agent-2, TASK-017-haiku-fix-utcnow-in-closed-loop.md)
- [2026-03-01] Replace naive datetime.now() with datetime.now(timezone.utc) in orchestrator scheduling code. (agent-3, TASK-018-haiku-fix-naive-datetime-in-orchestrator.md)
- [2026-03-01] Replace deprecated datetime.utcnow() calls with datetime.now(timezone.utc) throughout the codebase. (agent-1, TASK-016-haiku-fix-utcnow-in-api-routes.md)
- [2026-03-01] Test tool mastery with deterministic eval functions instead of LLM-dependent benchmarks. (agent-3, TASK-001-sonnet-implement-bfcl-eval-cases-for-function-c.md)
- [2026-03-01] Detect task phases to dynamically allocate context budgets for multi-phase agent reasoning. (agent-1, TASK-020-sonnet-upgrade-context-03-and-add-context-04-ev.md)
- [2026-03-01] Mock performance data to test feedback loops against real blocking thresholds. (agent-2, TASK-019-sonnet-upgrade-vending-05-and-vending-06-eval-s.md)
- [2026-03-01] Add eval cases with structured naming patterns to enable systematic coverage tracking. (agent-3, TASK-021-opus-add-gaia-10-eval-case-for-context-item-r.md)
- [2026-03-01] Mock URL validation in eval cases to test SSRF without making real network requests. (agent-1, TASK-022-opus-add-terminal-03-eval-case-for-ssrf-url-v.md)
- [2026-03-01] Ground tool mastery testing in established benchmarks like BFCL for systematic rigor. (agent-3, TASK-023-sonnet-bfcl-eval-cases.md)
- [2026-03-01] Build security eval suites using concrete attack patterns tied to actual control code. (agent-1, TASK-025-sonnet-fortress-eval-cases.md)
- [2026-03-01] Test autonomy deterministically: budget governor stops, circuit breaker recovers, timeouts handled. (agent-3, TASK-026-sonnet-vending-bench-eval-cases.md)
- [2026-03-01] Build eval frameworks with composable runners for modular testing (agent-2, TASK-024-sonnet-gaia-eval-cases.md)
- [2026-03-01] Preserve tool call-result message pairs when trimming context to maintain LLM reasoning. (agent-1, TASK-027-sonnet-context-bench-eval-cases.md)
- [2026-03-01] Validate tool mastery through intent-based filtering, performance thresholds, and eval determinism. (agent-3, TASK-028-sonnet-t2-bench-eval-cases.md)
- [2026-03-01] Create terminal eval cases as zero-dependency functions testing subprocess exit codes. (agent-1, TASK-029-sonnet-terminal-bench-eval-cases.md)
- [2026-03-01] Use > not >= for budget governor limits to prevent tool loop overflow edge cases. (agent-2, TASK-007-sonnet-vending-bench-eval-cases.md)
- [2026-03-01] Build deterministic eval cases without LLM to enable reproducible capability measurement. (agent-3, TASK-008-sonnet-context-bench-eval-cases.md)
- [2026-03-01] Test security by implementing eval cases for each attack vector independently. (agent-1, TASK-006-sonnet-fortress-eval-cases.md)
- [2026-03-01] Build terminal eval cases as standalone functions returning (passed, detail) tuples. (agent-3, TASK-010-sonnet-terminal-bench-eval-cases.md)
- [2026-03-01] Design tool-mastery evals around intent filtering, performance tracking, and dispatch routing. (agent-2, TASK-009-sonnet-t2-bench-eval-cases.md)
- [2026-03-01] Implement eval cases as pure functions to make tool mastery benchmarks deterministic and reusable. (agent-3, TASK-004-sonnet-bfcl-eval-cases.md)

# TASK-007: Implement Vending-Bench eval cases (6 cases)

## Priority: P2
## Pillar: Autonomy

Implement 6 Vending-Bench reliability eval cases: budget governor stops at limits, circuit breaker trips and recovers, tool timeout handling, graceful degradation under load, retry logic with backoff, and error recovery without data loss.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/core/budget.py

### Acceptance Criteria:
- [ ] All 6 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated
# TASK-006: Implement FORTRESS eval cases (11 cases)

## Priority: P1
## Pillar: Self-Awareness

Implement 11 FORTRESS security eval cases: prompt injection detection, secret redaction in logs, SQL injection prevention in tool args, path traversal blocking, command injection prevention, rate limit enforcement, approval gate for dangerous tools, sandbox escape prevention, PII detection, token budget enforcement, and cross-owner isolation.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/core/security.py

### Acceptance Criteria:
- [ ] All 11 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated



fail_count: 3
last_tier: sonnet
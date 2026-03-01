# TASK-010: Implement Terminal-Bench eval cases (2 cases)

## Priority: P3
## Pillar: Autonomy

Implement 2 Terminal-Bench command execution eval cases: run_command timeout and process tree kill, and execute_python sandboxing with output capture.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/tools/basic.py

### Acceptance Criteria:
- [ ] All 2 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated
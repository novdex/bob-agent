# TASK-009: Implement t2-bench eval cases (3 cases)

## Priority: P2
## Pillar: Tool Mastery

Implement 3 t2-bench tool-use eval cases: intent-based tool filtering accuracy, tool performance tracking in closed loop, and tool dispatch routing correctness.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/tools/registry.py

### Acceptance Criteria:
- [ ] All 3 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated
# TASK-008: Implement Context-Bench eval cases (3 cases)

## Priority: P2
## Pillar: Memory

Implement 3 Context-Bench eval cases: context window trimming preserves tool pairs, long conversation history compression, and memory injection relevance scoring.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/agent/memory.py

### Acceptance Criteria:
- [ ] All 3 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated
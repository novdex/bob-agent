# TASK-004: Implement BFCL eval cases (13 cases)

## Priority: P1
## Pillar: Tool Mastery

Implement 13 BFCL (Berkeley Function Calling Leaderboard) eval cases testing function-calling accuracy: correct tool selection from schema, argument extraction from natural language, multi-tool chaining, parallel tool calls, error recovery on bad tool output, schema validation, nested function calls, optional parameter handling, type coercion, ambiguous intent routing, tool_call_id format validation, empty result handling, and tool timeout behavior.

### Files to modify:
- mind-clone/src/mind_clone/core/evaluation.py
- mind-clone/src/mind_clone/tools/registry.py
- mind-clone/src/mind_clone/tools/schemas.py

### Acceptance Criteria:
- [ ] All 13 eval cases implemented
- [ ] Each case tests real functionality (not trivial pass)
- [ ] Tests pass (pytest)
- [ ] bob_check.py passes
- [ ] CHANGELOG.md updated
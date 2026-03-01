# Development Workflow

Coordination protocol between Claude Cowork and Claude Code for building Bob.

## Principle

**Claude Code** writes all production code. **Claude Cowork** handles research, specs, project tracking, and QA. **The Notion Development Board** is the single source of truth for what's happening.

---

## 5-Phase Development Cycle

```
INTAKE --> RESEARCH/SPEC --> IMPLEMENTATION --> QA --> CLOSE
 (User)     (Cowork)        (Claude Code)    (Cowork)
```

### Phase 1: Intake

- User describes a goal (verbally, in chat, or on Notion)
- Cowork creates a Notion item: Type = Feature, Status = Backlog
- Cowork assigns Priority and AGI Pillar tags

### Phase 2: Research + Spec (Owner: Cowork)

- Cowork sets Status = **Spec Writing**, Owner = **Cowork**
- Research APIs, libraries, approaches
- Write spec to `docs/specs/FEAT-[name].md` using the template below
- Update Notion item with link to spec
- Set Status = **Ready**

### Phase 3: Implementation (Owner: Claude Code)

- Claude Code picks up items with Status = **Ready**
- Reads the spec from `docs/specs/`
- Implements the feature, writes tests, runs `bob-check`
- Updates `CHANGELOG.md`
- Sets Status = **QA Testing**, Owner = **Cowork**

### Phase 4: QA (Owner: Cowork)

- Cowork runs QA Playbook Level 1 (smoke) + Level 4 (feature-specific)
- Tests against spec's Acceptance Criteria
- Creates QA Report in Notion (Type = QA Report)
- **If PASS:** Set original item Status = **Done**
- **If FAIL:** Create Bug items in Notion, set original to **Blocked**
- Bugs go back to Claude Code (repeat Phase 3-4)

### Phase 5: Close

- Done items accumulate in Notion
- Weekly: Cowork runs Level 3 deep diagnostic
- Weekly: Cowork creates QA Report for overall health

---

## Handoff Signals

The Notion Status field tells everyone who should act:

| Status | Who Acts | What Happens |
|--------|----------|--------------|
| **Backlog** | Cowork | Pick up for research/spec writing |
| **Spec Writing** | Cowork | Currently researching, nobody waits |
| **Ready** | Claude Code | Spec complete, implement it |
| **In Progress** | Claude Code | Currently implementing |
| **QA Testing** | Cowork | Implementation done, run QA |
| **Done** | Nobody | Passed QA, complete |
| **Blocked** | Claude Code | Bug found during QA, fix it |

---

## Spec Template

Save as `docs/specs/FEAT-[name].md`:

```markdown
# FEAT-[name]

## Problem
What problem does this solve? Why does Bob need this?

## Proposed Solution
High-level approach. What changes and how.

## AGI Pillar(s)
Which of the 8 pillars does this serve? (Reasoning, Memory, Autonomy, Learning, Tool Mastery, Self-Awareness, World Understanding, Communication)

## API Changes
New or modified endpoints. Method, path, request/response format.

## Database Changes
New or modified models/tables. Column names and types.

## Config Changes
New environment variables. Name, type, default, purpose.

## Risks and Mitigations
What could go wrong? How do we prevent it?

## Acceptance Criteria
Testable statements that define "done":
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3
```

---

## Bug Workflow

```
Cowork finds bug during QA
  --> Creates Notion item: Type=Bug, Priority=P0-P3
  --> Sets the feature item to Blocked
  --> Claude Code fixes the bug
  --> Claude Code sets bug to QA Testing
  --> Cowork re-tests
  --> If fixed: Bug=Done, Feature back to QA Testing
  --> If not fixed: Bug stays open, add notes
```

---

## Weekly Cadence

| Day | Activity | Owner |
|-----|----------|-------|
| Any | Level 3 deep diagnostic | Cowork |
| Any | Health QA report to Notion | Cowork |
| Any | Review Backlog, prioritize | User |

# Extended Execution Plan Template

Use this template for work that is long-running, high-risk, ambiguous, cross-system, hardware-dependent, or likely to require handoff. Adapt sections to the task, but keep the living-plan and evidence properties intact.

The plan must be self-contained enough that a capable worker with the current repository and this file can resume without relying on prior conversation.

This template is a schema, not a target length. Keep only information that changes execution, handoff, recovery, or verification decisions. Combine short sections when clarity improves, avoid repeating facts, and do not generate boilerplate merely to fill every heading.

## Header

```markdown
# <Short action-oriented title>

This is a living plan. Keep `Progress`, `Surprises and Discoveries`,
`Decision Log`, `Verification Matrix`, and `Resume Snapshot` current.

Created: YYYY-MM-DD
Status: PLAN_READY | IN_PROGRESS | BLOCKED | COMPLETE
Plan location: <repository-relative path>
```

## Purpose and Observable Outcome

Explain why the work matters and what a user, operator, caller, or test can do afterward that was not possible before. Describe how to observe the result.

## Scope and Non-goals

List the required outcomes and material boundaries. Exclude adjacent cleanup, redesign, or migration work unless it is necessary for the acceptance contract.

## Target Identity

Record exact identities when they affect the conclusion:

- repository and component;
- entry point, route, command, or API;
- build, commit, configuration, and feature flags;
- runtime, provider, model, device, or platform;
- user, data, fixture, or dataset;
- permission, cost, and destructive-action boundaries.

Results from a different target are diagnostic unless the plan explains why they prove the same contract.

## Current-State Evidence

Describe the existing implementation using repository paths, symbols, commands, and observed behavior. Separate observations from assumptions. Include the smallest reproduction or baseline when available.

## Acceptance Contract

For each mandatory outcome, define:

- observable behavior;
- input and preconditions;
- expected output or state;
- required evidence;
- forbidden substitutions;
- failure action.

Use stable requirement IDs such as `R1`, `R2`, and map every task and final check back to them. This is the canonical acceptance definition: tasks should reference these IDs rather than restating the full contract.

## Context and Orientation

Orient a worker who is new to the task:

- relevant modules and responsibilities;
- important interfaces and data flow;
- repository commands and constraints;
- terms that are not obvious from the code;
- existing tests and known environment limits.

Do not copy general manuals. Include only context that changes execution decisions.

## Dependency Graph

Describe what must exist before later work can proceed. Prefer a small diagram or ordered explanation. Identify shared interfaces that must be frozen before parallel implementation.

## Risks and Early Evidence

List the assumptions most likely to invalidate the approach. Convert each high-risk assumption into an early research, reproduction, prototype, or thin-slice milestone with a promotion or stop criterion.

When the work depends on a native SDK, external service, versioned schema, or undocumented interface that is not available for inspection, the first milestone must obtain the authoritative contract or run a minimal probe. Existing nearby usage proves that an API exists; it does not prove that different layouts, flags, devices, versions, or data shapes are equivalent.

## Milestones and Tasks

Organize work into observable milestones. Each task should contain:

```markdown
### Task <N>: <Observable outcome>

**Requirements:** R1, R2
**Depends on:** <task IDs or none>
**Change area:** <components or likely files>
**Work:** <concrete implementation description>
**Acceptance:** <requirement IDs plus any task-specific condition>
**Verification:** <task-specific command or observation; do not repeat the whole final matrix>
**Failure / recovery:** <what to preserve, revert, or reassess>
```

Prefer vertical slices. Do not postpone all integration until the end. A task is too large when it cannot be independently implemented, verified, reviewed, and recovered from as one coherent outcome.

## Progress

Use timestamped checkboxes after execution begins. For a planning-only response, omit empty progress entries rather than manufacturing activity. Split partially completed work into completed and remaining parts rather than marking it done.

```markdown
- [x] (YYYY-MM-DD HH:MM TZ) Completed outcome and evidence.
- [ ] Remaining outcome.
```

## Surprises and Discoveries

Record unexpected behavior, invalidated assumptions, and useful evidence:

```markdown
- Observation: <what was learned>
  Evidence: <path, command, log, test, or result>
  Impact: <how the plan changes>
```

## Decision Log

Record decisions that change architecture, interfaces, scope, risk, or verification:

```markdown
- Decision: <choice>
  Rationale: <evidence and trade-off>
  Date/author: <date and agent or person>
```

Do not log routine edits.

## Verification Matrix

Track evidence dimensions separately instead of collapsing them into “tests pass.”

| Requirement | Implemented | Focused | Regression | Build | Integration | Real target | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | yes/no | pass/fail/not-run | pass/fail/not-run | pass/fail/not-run | pass/fail/not-run | verified/blocked/not-run | command or artifact |

Mark evidence stale when relevant code changes afterward.

## Stop Conditions

Define task-specific conditions that stop expansion or completion, such as:

- the thin slice cannot reach the required entry point;
- the implementation direction contradicts current-state evidence;
- only a mock, fallback, legacy, or wrong-target path succeeds;
- a destructive step lacks authorization or rollback;
- repeated attempts add no new evidence;
- mandatory evidence cannot be collected in the available environment.

For every stop condition, state what to preserve and where work resumes.

## Idempotence, Recovery, and Rollback

Explain which commands and migrations are safe to repeat, how to clean partial artifacts, how to restore the previous state, and how to avoid corrupting shared or external state.

## Resume Snapshot

Update before every meaningful stopping point:

```markdown
**Current milestone/task:** ...
**Last fresh verification:** ...
**Working-tree state:** ...
**Known blockers:** ...
**Invalidated assumptions:** ...
**Next concrete action:** ...
```

The next action should be executable, not “continue implementation.”

## Outcomes and Retrospective

At major milestones and completion, summarize:

- outcomes delivered;
- requirements not delivered or explicitly deferred;
- strongest evidence;
- remaining risks;
- lessons that should change future plans.

## Completion Rule

Use `PLAN_READY` when planning is complete but implementation has not started. After execution begins, use `IN_PROGRESS`, `BLOCKED`, or `COMPLETE`. Set `COMPLETE` only when every mandatory implementation requirement is reconciled against fresh evidence and no required work remains. Never use implementation `COMPLETE` merely because the plan document is finished.

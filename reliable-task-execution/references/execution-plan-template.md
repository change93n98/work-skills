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

## Workstream Map

If the request contains multiple independently verifiable outcomes, list them before the dependency graph. Each workstream owns one outcome and its evidence.

```markdown
| Workstream | Goal | Starts when | Complete when |
| --- | --- | --- | --- |
| W1 | <outcome> | <entry gate> | <acceptance summary> |
| W2 | <outcome> | <entry gate> | <acceptance summary> |
```

Do not create a workstream for routine formatting, commits, or documentation unless the user requested it as an independent deliverable.

## Dependency Graph

Describe what must exist before later work can proceed, including dependencies between exact workstream steps. Prefer a small diagram or ordered explanation. Identify shared interfaces or benchmark contracts that must be frozen before downstream changes.

## Risks and Early Evidence

List the assumptions most likely to invalidate the approach. Convert each high-risk assumption into an early research, reproduction, prototype, or thin-slice milestone with a promotion or stop criterion.

When the work depends on a native SDK, external service, versioned schema, or undocumented interface that is not available for inspection, the first milestone must obtain the authoritative contract or run a minimal probe. Existing nearby usage proves that an API exists; it does not prove that different layouts, flags, devices, versions, or data shapes are equivalent.

## Workstreams, Milestones, and Tasks

Create a heading for each independently verifiable outcome. Within each workstream, write small ordered subgoals. Do not interleave steps from different workstreams in one flat list.

```markdown
## Workstream W1: <Observable outcome>

**Goal:** <one outcome>
**Requirements:** R1, R2
**Depends on:** <workstream step or gate, or none>

### W1.1 <Small verifiable subgoal>
**Change area:** <components or likely files>
**Work:** <concrete action>
**Acceptance:** <task-specific condition>
**Verification:** <command or observation>
**Failure / recovery:** <what to preserve, revert, or reassess>

### W1.2 <Next subgoal>
...

**Workstream acceptance:** <conditions for W1 to be complete>
**Workstream evidence:** <commands, measurements, or artifacts>
```

Repeat for W2, W3, and so on. Prefer 2-5 meaningful steps per workstream rather than one giant step or many mechanical edits. A step should be small enough to verify or reject independently.

Choose step names that match the task rather than copying a universal phase list. Useful generic progressions include:

```text
Framework feature: architecture/contract -> thin vertical slice -> expansion -> integration
Bug repair: reproduce -> minimize/diagnose -> regression test -> minimal fix -> affected regression
Native operator: semantic contract -> API probe -> correct path -> registration/build -> target tests
Optimization: correctness/baseline -> bottleneck hypothesis -> isolated changes -> controlled measurement
```

For detailed optional patterns, read the matching section of `workstream-patterns.md`. Do not load or reproduce patterns that do not apply.

Prefer vertical slices inside each workstream. Do not postpone all integration until the end.

## Integration and Final Reconciliation

Define the cross-workstream gates and final ordering. State which workstream steps may run early, which require another workstream's acceptance, and what proves the original multi-goal request is complete. Overall `COMPLETE` requires every mandatory workstream to be complete and the integration gates to pass.

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

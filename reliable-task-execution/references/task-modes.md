# Task Mode Selection

Read this reference when Quick versus Standard is not obvious, or when Standard versus Extended affects whether a persistent plan is needed.

## Decision Dimensions

Evaluate the strongest signal in each dimension. File count is not a decision rule.

| Dimension | Low | Medium | High |
| --- | --- | --- | --- |
| Scope | One local behavior | One component or feature slice | Multiple systems, repositories, or owners |
| Uncertainty | Cause and path are known | Investigation is needed | Architecture or feasibility is unknown |
| Risk | Easy code rollback | Meaningful regression surface | Security, data, ABI, production, or destructive impact |
| Reversibility | Simple revert | Compatibility or migration work | Irreversible or externally visible effects |
| Verification cost | One focused check | Several test/build layers | Hardware, end-to-end, paid, privileged, or production-like environment |
| Duration | One short turn | One working session | Multiple sessions or handoffs |
| External dependencies | None | Available local service or fixture | Permission, device, provider, dataset, user action, or unstable service |
| Coordination | One worker | Shared interface or reviewer | Multiple agents, teams, or conflicting write areas |

## Default Selection

Use **Quick** when all material dimensions are low and the completion evidence is obvious.

Use **Standard** when any material dimension is medium, the work has multiple dependent steps, or a regression test is part of the deliverable.

Use **Extended** when any critical dimension is high, the work may cross sessions, the implementation direction is not yet justified, or real-target verification requires coordination or an external environment.

These are decision aids, not numeric scoring rules. A tiny authentication change can require Extended mode; a mechanical multi-file rename can remain Standard.

## Multi-Outcome Decomposition

Mode selection and outcome decomposition answer different questions:

- **Mode** controls planning depth and persistence.
- **Workstreams** separate independently verifiable outcomes.

A Standard task can have two compact workstreams; an Extended task can have several persistent workstreams. Create separate workstreams when any of these are true:

- the request asks for two or more deliverables that can pass or fail independently;
- the goals require different evidence, such as implementation correctness versus performance comparison;
- one goal must preserve a baseline before another goal changes the system;
- different components, environments, or owners can advance independently;
- reporting one goal as complete would still leave another user goal unfulfilled.

Keep a single workstream when the apparent subgoals are merely sequential mechanics of one outcome. “Add a field and its regression test” is normally one workstream. “Optimize an operator and produce a controlled before/after performance report” is two workstreams.

For every workstream:

1. State one observable goal.
2. Break it into ordered subgoals small enough to verify or reject independently.
3. Record dependencies on exact steps or gates, not vague statements such as “after optimization”.
4. Define workstream-specific acceptance and evidence.
5. Add a final integration gate that reconciles all workstreams against the original request.

For optimization plus benchmarking, use this dependency pattern:

```text
Workstream 2, steps 1-2: freeze benchmark contract and collect baseline
    -> Workstream 1: implement optimization in correctness-preserving steps
        -> Workstream 2, steps 3-5: measure optimized result, analyze, report
            -> Final reconciliation
```

This prevents a modified benchmark, changed dataset, different device, or easier workload from being used as the “after” result.

## Mode Shapes

### Quick

Plan shape:

```text
Outcome: <observable result>
Change: <expected edit area>
Verify: <focused command or observation>
```

Required behavior:

- inspect the relevant implementation before editing;
- make one coherent change;
- run fresh focused verification;
- review the diff;
- report limitations without creating process artifacts that will not be used.

### Standard

Plan shape for one outcome:

```markdown
## Workstream 1: <observable outcome>
1. <small verifiable step>
   - Depends on: <step or none>
   - Acceptance: <testable condition>
   - Verify: <command or observation>
2. ...
```

Repeat the workstream block when the request contains multiple outcomes, then add a compact integration gate.

Required behavior:

- order tasks by dependency and risk;
- include a regression test when behavior changes and testing is practical;
- verify each task before building on it;
- run an appropriate integration or regression check before the final claim;
- preserve a compact plan when another session may need it.

### Extended

Create a living plan using `execution-plan-template.md`.

Required behavior:

- establish current-state evidence and target identity;
- validate the implementation direction before decomposing large amounts of work;
- map dependencies and interfaces;
- put a realistic thin slice or feasibility milestone before broad expansion;
- maintain progress, discoveries, decisions, evidence, and recovery state;
- reconcile every mandatory requirement before `COMPLETE`.

## Escalation Triggers

Escalate immediately when investigation reveals any of the following:

- additional repositories, runtimes, languages, or deployment surfaces;
- a migration, data transformation, API/ABI compatibility issue, or destructive step;
- security, authorization, privacy, billing, or production-state implications;
- hardware, model, provider, or external-service behavior that local tests cannot prove;
- an unclear owner, duplicated source of truth, or conflicting requirements;
- work likely to exceed the current session;
- multiple agents need disjoint write ownership or integration gates;
- the original completion evidence is no longer sufficient.

When escalating, preserve completed evidence, explain why the previous mode is insufficient, and replace—not merely append to—the obsolete plan.

## Evidence-Based Downgrade

A task may downgrade after investigation proves the stronger mode unnecessary. Record:

- the original concern;
- evidence that eliminated it;
- the reduced scope;
- the remaining completion evidence.

Do not downgrade only to save tokens, avoid a blocked verification, or make a completion claim easier.

## Ambiguity and Questions

Do not ask questions merely because several implementations are possible. Inspect repository patterns and select the least surprising compatible approach.

Ask when the answer changes:

- user-visible behavior;
- destructive or external effects;
- compatibility promises;
- security or permission boundaries;
- substantial cost or duration;
- which product, repository, model, provider, device, or environment is the real target.

If work can proceed safely, state the assumption and keep it reversible.

## Examples

| Request | Likely mode | Reason |
| --- | --- | --- |
| Fix a misspelled test argument and run the focused test | Quick | Local, reversible, obvious evidence |
| Add validation plus regression tests to one configuration path | Standard | Multiple dependent steps and behavior change |
| Add a Python API, native kernel registration, build integration, and device tests | Extended | Cross-layer dependencies and hardware evidence |
| Rewrite a scheduler to address an intermittent timeout with no reproduction | Extended | Direction and root cause are unproven |
| Rename a private symbol across many files with comprehensive automated checks | Standard | Broad but mechanical and reversible |
| Change one authorization condition | Extended | Small diff, high consequence |
| Optimize an operator and produce a controlled before/after performance report | Extended | Two workstreams: hardware-dependent implementation and benchmark evidence |

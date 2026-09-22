# Verification and Completion Contract

Use this contract before making a final claim for Standard or Extended work, and for any Quick task where failure has meaningful consequences.

## Fresh Evidence Rule

A completion claim requires evidence obtained after the final change that could affect that evidence. A previous run becomes stale when relevant code, configuration, dependencies, generated artifacts, target identity, or environment changes.

Before claiming a result:

1. Identify the command or observation that proves the claim.
2. Run or collect it in the intended target context.
3. Read the complete relevant output, exit status, artifact, and failure count.
4. Confirm the evidence proves the acceptance contract rather than a weaker substitute.
5. Record unverified dimensions explicitly.

Do not infer execution success from code inspection alone.

## Target Identity

Record the identity needed to interpret evidence:

- repository, revision, and component;
- command, route, API, or UI entry;
- build and feature flags;
- runtime, operating system, provider, model, device, or hardware;
- user, permissions, data, fixture, or dataset;
- cost and destructive-action boundary.

Evidence collected against the wrong identity is diagnostic unless equivalence is demonstrated.

## Verification Ladder

Use every applicable layer; not every task needs every layer.

### V0: Static correctness

Examples:

- formatting and linting;
- syntax and import checks;
- type checking;
- configuration or schema validation.

V0 cannot prove runtime behavior.

### V1: Focused behavior

Run the smallest test or reproduction that directly exercises the change. For a bug fix, prefer evidence that distinguishes the broken behavior from the corrected behavior.

### V2: Adjacent regression

Exercise callers, related parameterizations, error paths, and neighboring behavior that could reasonably regress.

### V3: Build and integration

Examples:

- compile and link;
- package or image build;
- extension loading;
- service startup;
- interface compatibility;
- registration or discoverability through the actual dispatcher, plugin manager, route table, schema registry, or equivalent runtime mechanism;
- integration tests.

### V4: Real target

Exercise the requested entry point with the required environment, device, provider, model, user, data, flags, or production-like boundary. When V4 is mandatory but unavailable, the work cannot be `COMPLETE`.

### V5: Artifact and change review

Inspect:

- the final diff and repository status;
- generated files and lockfiles;
- logs, reports, screenshots, database state, or stored artifacts;
- performance or resource measurements when required;
- accidental scope expansion and unrelated changes.

## Per-Workstream Verification

When the request has multiple workstreams, verify and report each one separately before calculating an overall outcome. Each workstream must have:

- its own acceptance conditions;
- its own executed commands or collected artifacts;
- a status of `COMPLETE`, `PARTIAL`, or `BLOCKED`;
- explicit dependencies on evidence from another workstream.

Do not let strong evidence from one workstream hide missing evidence in another. Correctness tests do not complete a performance-comparison workstream; benchmark numbers do not complete an implementation-correctness workstream.

For before/after performance comparisons, require:

- the same target identity, workload, input shapes/data, dtype, software build, timing boundary, warmup, and repetition policy unless a difference is the subject of the comparison;
- baseline evidence collected or reproducibly preserved before optimization;
- raw samples, not only the best run;
- a stated aggregation method such as median plus mean/min/max;
- throughput or domain metric and speedup/regression calculation;
- noise, outliers, unsupported cases, and measurement limitations;
- correctness passing before optimized results are promoted.

## Evidence Matrix

Report evidence dimensions separately. For multiple workstreams, add a workstream column or keep one matrix per workstream:

| Dimension | Allowed values | Evidence |
| --- | --- | --- |
| Implemented | yes / no | paths and symbols |
| Focused verification | pass / fail / not-run | exact command and result |
| Regression verification | pass / fail / not-run | exact command and result |
| Build | pass / fail / not-run | exact command and result |
| Integration | pass / fail / blocked / not-run | exact target and result |
| Real target | verified / blocked / not-run | exact identity and artifact |
| Diff review | clean / concerns / not-run | important findings |

A green row does not imply the other rows are green.

## Forbidden Substitutions

Do not count these as completion evidence unless they prove the same contract:

- mock instead of real service or provider;
- CPU or simulator instead of required hardware;
- legacy path instead of the new path;
- fallback output instead of primary execution;
- nearby model, dataset, user, route, or configuration;
- unit test instead of required integration behavior;
- successful command exit with semantically incorrect output;
- generated artifact that was not inspected;
- tests run before the final relevant edit.

Preserve such results as diagnostic evidence and label them accurately.

## Failure and Blocking

When verification fails:

- preserve the smallest useful failure evidence;
- distinguish product failure from environment or infrastructure failure;
- change the hypothesis before retrying;
- update the plan if the failure invalidates an assumption;
- stop repeated matrix execution after the same infrastructure cause recurs without new evidence.

Lack of hardware, credentials, data, permission, service availability, or authorization is a blocker—not permission to redefine the target.

## Final Outcomes

For implementation work, use exactly one user-facing outcome:

### COMPLETE

Every mandatory acceptance condition has fresh matching evidence, every mandatory workstream is complete, cross-workstream integration gates pass, the requested target is reconciled, and no required work remains.

### PARTIAL

Useful work is implemented and some required evidence passes, but a mandatory outcome is deferred, unverified, or outside the available environment. State precisely what remains.

### BLOCKED

Progress or mandatory verification cannot continue because of an external condition, missing decision, unavailable target, permission boundary, or invalidated direction. State the resumption condition.

Do not use optimistic language such as “done,” “fixed,” “all good,” or “ready” when the evidence supports only `PARTIAL` or `BLOCKED`.

For planning-only work, use `PLAN_READY` when the plan is executable and `PLANNING_BLOCKED` when material facts are missing. State implementation state separately as `NOT_STARTED`, `IN_PROGRESS`, or the applicable delivery outcome.

## Final Report Template

```markdown
## Outcome

`COMPLETE | PARTIAL | BLOCKED` — <one-sentence result>

## Workstream Results

### W1: <goal> — `COMPLETE | PARTIAL | BLOCKED`
- Changes: <material change>
- Verification: `<exact command or observation>` — <result>

### W2: <goal> — `COMPLETE | PARTIAL | BLOCKED`
- Changes or report: <material output>
- Verification: `<exact command or observation>` — <result>

## Integration Verification

- `<cross-workstream check>` — <result>

## Evidence Gaps

- <not-run or blocked dimension and why>

## Risks / Follow-up

- <remaining risk, deferred work, or resumption condition>
```

Keep Quick reports shorter when all evidence is straightforward. Do not omit evidence gaps merely for brevity.

# Workstream Patterns

Read only the pattern that matches the current work. These are adaptable starting points, not mandatory phase names. Preserve repository conventions and user intent; omit steps that do not change execution, verification, or recovery decisions.

## Pattern Selection

Choose by the evidence the task needs:

| Task shape | Read |
| --- | --- |
| Framework or feature development | Framework / Feature Development |
| Bug localization, diagnosis, or repair | Bug Diagnosis and Fix |
| Native operator, kernel, backend, or integration development | Operator / Native Component Development |
| Performance tuning or before/after evaluation | Optimization and Performance Evaluation |

A request may combine patterns. For example, an operator bug can use the diagnosis pattern for root-cause work and the operator pattern for the repair and target-device validation. Do not force every task into all patterns.

## Framework / Feature Development

Use when adding or changing framework capabilities, APIs, runtimes, plugins, backends, configuration, or cross-module behavior.

A single feature outcome normally remains one workstream with small vertical steps:

1. **Map the existing architecture and contract.** Identify owners, extension points, callers, compatibility promises, and repository conventions.
2. **Define the interface and boundaries.** Freeze types, lifecycle, errors, configuration, migration behavior, and non-goals.
3. **Build the thinnest end-to-end slice.** Connect the real entry point through the minimum implementation to an observable result.
4. **Expand required behavior.** Add edge cases, persistence/state, concurrency, secondary adapters, or compatibility paths only after the slice works.
5. **Integrate and reconcile.** Run focused and cross-module tests, verify backward compatibility, and update required user/developer documentation.

Create separate workstreams only for independently deliverable outcomes, such as runtime capability versus a required migration tool. Do not split frontend, service, and storage into separate workstreams when they are layers of one user outcome.

Evidence commonly required:

- interface or schema checks;
- focused behavior tests;
- cross-module integration tests;
- backward-compatibility or migration evidence;
- real entry-point exercise.

## Bug Diagnosis and Fix

Use when the cause is unknown, intermittent, disputed, or likely to be confused with a nearby symptom.

When the user asks both to locate and fix the bug, use two dependent workstreams when diagnosis is substantial:

### Workstream 1: Diagnosis

1. Reproduce the exact failure or establish a measurable failure signal.
2. Minimize the reproducer and separate environment failure from product failure.
3. Form ranked hypotheses tied to observable evidence.
4. Instrument or inspect the narrowest relevant boundary.
5. Identify a root cause that explains the original symptom and affected scope.

**Acceptance:** the root cause is supported by evidence, not merely correlated with the failure.

### Workstream 2: Repair and Regression Prevention

1. Write or identify a test that fails for the root cause.
2. Implement the smallest fix that restores the intended invariant.
3. Verify the original reproducer and nearby error/edge paths.
4. Run affected regression and integration checks.
5. Remove temporary instrumentation and reconcile the fix with the diagnosis.

**Depends on:** Workstream 1 root-cause gate, unless a safe diagnostic patch is explicitly the deliverable.

Integration gate:

- the fix addresses the diagnosed cause;
- the regression test would fail before the fix;
- the original symptom no longer reproduces;
- no broader rewrite is claimed necessary without evidence.

## Operator / Native Component Development

Use for accelerator operators, native extensions, kernels, compiler passes, device backends, or other components with build and target-runtime requirements.

Typical ordered subgoals:

1. **Freeze the semantic contract.** Shapes, dtypes, layouts, devices, errors, aliasing, numerics, and supported/unsupported cases.
2. **Confirm authoritative APIs and feasibility.** Inspect installed headers/docs or compile a minimal probe before relying on native SDK behavior.
3. **Implement a minimal correct path.** Prefer a small reference or thin slice before specialized optimization.
4. **Integrate the component.** Declarations, registration, dispatch, build discovery, packaging, and runtime discoverability.
5. **Add layered tests.** Reference comparison, invalid inputs, boundary/tail cases, build/load tests, and real target-device execution.
6. **Reconcile target evidence.** Distinguish host/static/Meta evidence from compiled integration and device evidence.

Possible workstreams:

- one implementation workstream when contract, kernel, registration, and tests form one inseparable deliverable;
- separate compatibility/migration workstream when an existing public operator or ABI must be preserved;
- separate performance workstream only when performance is explicitly requested.

## Optimization and Performance Evaluation

Use when improving latency, throughput, memory, utilization, scale, or another measurable resource objective.

Optimization and performance comparison are different outcomes when the user requests both.

### Workstream 1: Implementation Optimization

1. Freeze correctness tests and supported behavior.
2. Profile or otherwise identify the current bottleneck; state the optimization hypothesis.
3. Change one meaningful factor, such as algorithm, tile/configuration, data movement, reuse, vectorization, concurrency, or buffering.
4. Run correctness and relevant regression checks after each promoted change.
5. Keep, revise, or revert the change based on evidence; document the resulting support contract.

Do not stack several optimizations before checking which one changed behavior or performance unless they are technically inseparable.

### Workstream 2: Before/After Performance Evaluation

1. Freeze the benchmark contract: target, workload, inputs, software/build, warmup, repetitions, timing boundary, and metrics.
2. Collect and preserve baseline raw samples before optimization changes the measured behavior.
3. After Workstream 1 passes correctness, collect optimized samples under the identical contract.
4. Compute raw samples plus median, mean, min/max, throughput or resource metric, and speedup/regression.
5. Report noise, outliers, unsupported cases, regressions, and the exact scope of the conclusion.

Cross-workstream ordering:

```text
Benchmark contract + baseline
    -> correctness-preserving optimization steps
        -> optimized measurement
            -> statistical comparison and final reconciliation
```

Performance evidence never substitutes for correctness. A faster wrong result fails the optimization workstream; a correct change without controlled measurements leaves the performance-evaluation workstream incomplete.

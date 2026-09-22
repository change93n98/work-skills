---
name: reliable-task-execution
description: Plan, execute, and verify repository changes with planning depth proportional to scope and risk. Use for framework and feature development, bug diagnosis and repair, operator or native-component work, optimization, and other multi-step coding tasks where reliable completion evidence matters. Keep obvious low-risk edits lightweight; do not use for pure explanation or unrelated writing.
---

# Reliable Task Execution

Use the lightest workflow that preserves correctness. Different agents may choose different tools, but they must not skip the task contract, current-state inspection, proportionate planning, verification, or final reconciliation.

## Core Contract

Before editing:

1. Read the applicable user instructions, `AGENTS.md` files, repository guidance, and nested-repository boundaries.
2. Define the requested outcome, material non-goals, constraints, and evidence that would prove completion.
3. Inspect the current implementation and relevant tests. Do not plan from filenames or assumptions alone.
4. Split the request into independently verifiable outcomes when it contains more than one goal. Give each outcome its own workstream before decomposing implementation steps.
5. Select Quick, Standard, or Extended mode using scope, uncertainty, risk, reversibility, duration, dependencies, and verification cost.
6. State a plan proportionate to the selected mode before making changes.

During execution:

1. Work in the smallest coherent slice that produces an independently reviewable and verifiable outcome.
2. After each slice, run the most focused meaningful verification, read the full result and exit status, and update the plan when facts change.
3. Do not repeat an identical failing action without new evidence or a changed hypothesis.
4. Stop and reassess when the target, risk, authority boundary, or key assumption differs from the plan.
5. When a native, external, or versioned API contract cannot be inspected, make contract acquisition or a minimal probe an early evidence task. Nearby call sites prove existence, not equivalence.

Before reporting completion:

1. Reconcile the original request, current acceptance contract, actual diff, and fresh evidence obtained after the final relevant change.
2. Distinguish code existence from focused testing, regression testing, build success, integration, and real-target verification.
3. Report required evidence that was not collected and why.
4. Use `COMPLETE` only when every mandatory outcome has matching evidence. Otherwise report `PARTIAL` or `BLOCKED`.

Never use an easier mock, fallback, legacy path, different device, different provider, or adjacent capability as proof of the requested target unless it proves the same acceptance contract.

## Define the Task Contract

Record enough of the following to prevent silent goal changes:

- **Outcome:** Observable behavior or artifact the user needs.
- **Non-goals:** Tempting adjacent work that is outside scope.
- **Constraints:** Repository rules, compatibility, safety, cost, permissions, hardware, and time boundaries.
- **Target identity:** Exact repository, component, entry point, environment, flags, data, provider, model, or device when these affect the conclusion.
- **Completion evidence:** Commands or observations that would prove the outcome.

Ask the user only when missing information materially changes the outcome, risk, or authorization and cannot be inferred safely. Otherwise state the assumption and proceed.

## Split Multiple Outcomes into Workstreams

Before writing a task list, determine whether the request contains multiple independently verifiable outcomes. Common signals include words such as “and”, distinct deliverables, different evidence types, or one goal that produces an artifact while another evaluates it.

When multiple outcomes exist, create one numbered workstream per outcome. Do not flatten them into a single mixed sequence. Each workstream must contain:

- **Goal:** the observable outcome owned by this workstream;
- **Steps:** a short ordered list of concrete subgoals;
- **Dependencies:** inputs or gates from other workstreams;
- **Acceptance:** conditions that make this workstream complete;
- **Verification:** commands, measurements, or artifacts that prove its result.

After the workstreams, add an **Integration and Final Reconciliation** section describing cross-workstream ordering and the overall completion rule. A workstream may start before another finishes when its dependency allows it. State exact gates such as contract-before-implementation, reproduction-before-fix, correctness-before-real-target validation, or baseline-before-change.

Use this compact shape:

```markdown
## Workstream 1: <outcome>
Goal: ...
1. <small verifiable step>
2. <small verifiable step>
Acceptance: ...
Verification: ...

## Workstream 2: <outcome>
Goal: ...
Depends on: Workstream 1 step 2
1. ...
2. ...
Acceptance: ...
Verification: ...

## Integration and Final Reconciliation
- <cross-workstream gate>
```

Do not create separate workstreams for incidental activities such as formatting or documentation unless they are explicit deliverables.

When the task is substantial, read only the matching section of [workstream-patterns.md](references/workstream-patterns.md): framework/feature development, bug diagnosis and fix, operator/native development, or optimization/performance evaluation. Patterns are starting points, not mandatory checklists.

## Select a Mode

Choose by risk and verification needs, not file count alone.

### Quick

Use for clear, local, reversible, low-risk work with an obvious focused verification.

Before editing, state a micro-plan containing:

- intended outcome;
- expected edit area;
- verification to run.

Do not create a persistent plan artifact unless repository policy requires one.

### Standard

Use for multi-step behavior changes that can normally finish in one working session.

Create an ordered task list. Each task must identify:

- observable outcome;
- dependencies;
- likely component or files;
- acceptance criteria;
- verification;
- relevant failure or rollback handling.

Persist the plan only when it improves handoff, recovery, or coordination.

### Extended

Use for long-running, ambiguous, architectural, high-risk, cross-module, cross-repository, migration, security, performance, hardware-dependent, production-impacting, or multi-agent work.

Read [task-modes.md](references/task-modes.md) when classification is unclear or the work may require Standard or Extended mode. For Extended mode, also read [execution-plan-template.md](references/execution-plan-template.md) and create a living plan.

Respect a repository- or user-specified plan location. Otherwise use a unique path such as `plans/YYYY-MM-DD-<task-slug>.md`. Never overwrite an unrelated plan with incomplete work.

Extended means persistent and self-contained, not maximally verbose. Keep acceptance requirements in one canonical section; tasks should reference requirement IDs and add only task-specific work, verification, or recovery details. Merge or omit sections that add no decision, recovery, or verification value.

## Plan and Execute

Within each workstream, prefer vertical slices that deliver observable behavior over horizontal batches that postpone integration. Put high-risk assumptions and feasibility checks early enough to fail cheaply. Preserve the workstream headings during execution so progress does not collapse back into a mixed task list.

For every task or milestone:

1. Inspect the exact code and interfaces involved.
2. Confirm the task still supports the original outcome.
3. Implement the smallest coherent change.
4. Run focused verification and inspect the result.
5. Review the diff for unintended scope, generated artifacts, and repository violations.
6. Update task status, discoveries, decisions, and next action.

A task boundary should represent an independently testable and reviewable outcome. File count is only a warning signal: a coherent slice may touch several files, while one file may contain several tasks.

Escalate the mode when new evidence increases scope, uncertainty, risk, duration, or verification cost. Downgrade only when investigation produces concrete evidence that the stronger workflow is unnecessary, and record that evidence.

## Handle Stopping Points

For Extended work, leave a resume snapshot before stopping:

- current milestone and task;
- last fresh verification and result;
- working-tree state and important modified files;
- known blockers and invalidated assumptions;
- one concrete next action.

Do not continue expanding the implementation when:

- the requested target cannot be identified;
- evidence contradicts a foundational assumption;
- the real entry point or environment differs from the acceptance contract;
- a destructive or external mutation lacks authorization;
- repeated attempts produce no new evidence;
- a required verification is unavailable and no equivalent evidence exists.

Record the blocker, preserve diagnostic evidence, and identify the condition required to resume.

## Verify and Report

Read [verification-contract.md](references/verification-contract.md) before the final claim for Standard or Extended work, and for any Quick task with meaningful risk.

The final response must state:

- requested outcome;
- material changes;
- exact verification executed and results;
- evidence dimensions not verified;
- blockers, limitations, or explicitly deferred work;
- final outcome for implementation work: `COMPLETE`, `PARTIAL`, or `BLOCKED`.

For a planning-only request, report `PLAN_READY` when the plan is executable or `PLANNING_BLOCKED` when required facts are missing. Do not use implementation `COMPLETE` to describe plan-writing completion.

Keep the report concise for Quick work and evidence-rich for Extended work. Do not claim more than the evidence proves.

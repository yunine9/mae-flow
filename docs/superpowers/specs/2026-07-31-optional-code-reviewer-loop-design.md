# Optional CODE Reviewer and Low-Friction Review Loop

## Problem

The new checkpoint quality mechanism makes an independent CODE Reviewer
mandatory for every checkpoint. A normal checkpoint therefore requires at
least Task analysis, PLAN review, implementation, compilation, and CODE
review. Simple changes pay the same latency as risky changes.

The CODE Reviewer path also has three contract defects:

- `CRAFT_REVIEW_RESULT` is required by the role task but is not recognized by
  the SubagentStop contract router, so a correct role result is rejected.
- Reviewer instructions require five Finding fields while artifact validation
  requires seven. The missing disposition and status fields are supposed to be
  completed later by the main Agent, but the generated task card does not
  explain that split.
- An accepted Finding moves the checkpoint back to `coding`. After the fix and
  compile, the workflow text does not explicitly require a fresh
  `checkpoint ready`, a fresh `craft-code` task, and a fresh Reviewer before
  `craft-reviewed`. Agents therefore reuse the old review while the state
  machine is still correctly waiting in `coding`.

Compilation currently also writes `closed_at` before the checkpoint has passed
CODE review and user inspection, producing misleading “closed” language.

## Goals

- Ask once at workflow startup whether independent CODE Review is wanted.
- Make the fast path genuinely skip the Reviewer Agent and its artifacts.
- Preserve the user's final code-inspection loop in both modes.
- When CODE Review is enabled, never let an Agent silently decide and close a
  Finding that requires user judgment.
- Make every re-review transition explicit and recoverable from its error
  message.
- Preserve current behavior for already-running workflows that have no new
  configuration value.

## Startup Choice

Add one question to the existing combined opening card:

> 是否启用独立 CODE Reviewer？

Options:

- `不启用独立 CODE Reviewer`
- `启用独立 CODE Reviewer`

The answer is persisted as `choices.code_reviewer` with values `disabled` or
`enabled`. It is a workflow choice rather than a repository default: two tasks
in the same repository can make different trade-offs.

New interactive workflows must have an explicit answer. Existing in-flight
workflows without the field behave as `enabled`, preserving the quality path
they started with. Moonlight does not add a question to unattended startup and
uses `enabled` as its conservative default.

## Checkpoint Paths

### Reviewer disabled

```text
coding
  → compile
  → checkpoint ready
  → staged: review_pending
  → continuous: completed / next checkpoint
```

`checkpoint ready` does not generate or request a CODE Review artifact. The
current user CP inspection remains mandatory in staged mode, and final unified
inspection remains mandatory in continuous mode.

### Reviewer enabled and CLEAN

```text
coding
  → compile
  → checkpoint ready
  → craft_pending
  → fresh craft-code task and Reviewer
  → checkpoint craft-reviewed
  → staged: review_pending
  → continuous: completed / next checkpoint
```

### Reviewer enabled with Findings

The Reviewer writes objective evidence only. Every Finding initially contains:

```text
- 位置：
- 依据：
- 证据：
- 实际影响：
- 最小改法：
- 处置：待用户裁决
- 状态：待裁决
```

The first `checkpoint craft-reviewed` registers and displays the Findings but
does not enter `coding`. The checkpoint moves to `craft_decision_pending`.
The user may accept, reject, or request clarification. The main Agent records
that decision using the captured user answer; it cannot manufacture a closed
status.

Accepted changes follow this exact loop:

```text
craft_decision_pending
  → user accepts selected Findings
  → coding
  → same CP Implementer fixes only accepted Findings
  → compile
  → checkpoint ready
  → new craft-code task
  → fresh Reviewer performs targeted re-review
  → checkpoint craft-reviewed
```

The state-machine output prints the next exact command at every transition.
Calling `craft-reviewed` from `coding` explains that `checkpoint ready` and a
fresh Reviewer are required instead of only saying the state is wrong.

## Role and Hook Contracts

Generated craft task cards contain one complete copy-ready CLEAN template and
one complete FINDINGS template. The template, prompt resource, and validator
use the same field names and allowed initial values.

Role-Agent result markers such as `CRAFT_REVIEW_RESULT`,
`TASK_ANALYSIS_RESULT`, `TEST_DESIGN_RESULT`, and `CP_IMPLEMENT_RESULT` are
informational completion markers. SubagentStop accepts them without issuing
the compile/UT/CodeCheck evidence tokens. Artifact and checkpoint commands
remain responsible for validating the files these roles produce.

Only compile, UT, CodeCheck, Grill, Story, and environment Agents continue
through the hard evidence-token contract router.

## Closure Semantics

`closed_at` is written only when a checkpoint becomes `completed` or
`accepted`. Compilation may write `compiled_at`; CODE Review may write
`reviewed_at`. Neither fact means the checkpoint or a Finding is closed.

## Error Handling and Compatibility

- A disabled Reviewer path never asks for a Review file or role-task digest.
- Enabling CODE Review without a fresh task/review yields an actionable command
  sequence.
- Changing source after compilation invalidates the receipt as before.
- Reusing a Review target or task digest from the previous source snapshot is
  rejected.
- Legacy version-2 checkpoint states missing `choices.code_reviewer` use the
  enabled path.
- No new repository-level gate or mandatory user stop is added.

## Verification

Regression tests cover:

- opening-card capture and persistence for enabled/disabled choices;
- disabled staged and continuous checkpoint paths;
- enabled CLEAN and FINDINGS paths;
- Findings waiting for a real user decision rather than entering `coding`;
- accepted Finding repair, compile, `checkpoint ready`, fresh task, and fresh
  re-review;
- actionable recovery when `craft-reviewed` is called from `coding`;
- role result markers bypassing the hard evidence-token router;
- generated templates matching artifact validation;
- `closed_at` absent from compile-only and pending-review states;
- legacy states defaulting to enabled;
- full differential snapshots and complete self-test.

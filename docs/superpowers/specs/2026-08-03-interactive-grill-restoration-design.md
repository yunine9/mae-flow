# Interactive Grill Restoration Design

## Problem

The Lean workflow retained the name `grill` but replaced the former interactive
requirements interrogation with one read-only critic pass. Full delivery can
therefore reach Spec confirmation without a real user question, a decision
tree, or evidence that the confirmed requirement boundaries drove the Spec.

## Goals

- Make Interactive Grill mandatory inside Full Spec without adding a seventh
  public workflow phase.
- Ask exactly one user decision at a time, always with evidence, impact, and a
  recommended answer.
- Follow every branch created by an answer until no material requirement branch
  remains open.
- Make the Grill result a required, traceable input to Spec generation.
- Retain a read-only critic after Spec generation as a coverage check, not as a
  substitute for the user interrogation.
- Upgrade Focused to Full when a material unresolved requirement decision is
  discovered.

## Non-goals

- Grill does not decide implementation files, types, algorithms, or module
  structure; those remain Story concerns.
- The old hook-validated eight-section preparation worksheet is not restored as
  a rigid format gate. Its dimensions remain an internal investigation
  checklist.
- The public phase list remains Intake, Spec, Design, Construction, Quality,
  Delivery.

## Full Spec Flow

1. Read the request, selected behavior baseline, repository facts, and relevant
   environment constraints.
2. Scan state transitions, boundary values, concurrency and ordering, failure
   and cleanup, consistency, compatibility, scale, performance, and
   observability.
3. Open one numbered question such as `GQ-001`. Record its parent branch,
   evidence, impact, and recommended answer.
4. Ask the user through natural conversation or `AskUserQuestion`, then bind the
   answer to the open question through the existing one-use user-event receipt.
5. Inspect the answer for vague terms, new states, new scenarios,
   contradictions, and reopened dimensions. Open the next derived question only
   after the current question is answered.
6. Converge only after at least one real answer exists and every opened question
   is answered.
7. Generate the Spec from the request, behavior baseline, and the converged
   Grill result.
8. Run one read-only critic pass for the current Grill/Spec content digests. A
   material correction creates a new content revision and therefore permits one
   new critic pass; there is no automatic retry.
9. Ask the user to confirm the reviewed Spec.

The interaction principles match the open-source
[grilling skill](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md):
walk the decision tree one branch at a time, recommend an answer, inspect facts
instead of asking for them, and do not proceed until shared understanding is
established.

## State Protocol

The schema remains version 3. Grill state is represented by append-only semantic
decisions so existing state serialization stays compatible.

- `grill-question` opens one stable question ID and records structured question
  metadata. It is rejected while another question is unanswered.
- `grill-answer` is a user-owned, keyed event. It consumes one current
  `UserPromptSubmit` or `AskUserQuestion` answer and closes the matching open
  question.
- `grill-converged` is rejected until at least one question is answered and no
  question remains open. The CLI reads the local Grill artifact and records its
  SHA-256 digest and answer count.
- `grill-clear` remains the critic-clear event for compatibility, but is rejected
  unless interactive convergence exists. Its receipt binds both the Grill and
  Spec file digests and records complete input coverage.
- `spec-confirmed` recomputes both digests. It is rejected if either artifact
  changed, coverage is missing, or a question is open.

Focused delivery does not create Grill state by default. A material ambiguity
uses the existing `upgrade-to-full` user decision, after which the Full Grill
protocol applies.

## Artifacts and Traceability

Full work packages add:

```text
.mae-flow-work/<safe-ticket>/grill.md
```

The document contains source evidence, the numbered question tree, recommended
answers, user decisions, derived branches, final WHAT decisions, boundaries,
failure behavior, compatibility requirements, non-goals, and HOW deferred to
Story. It starts with `<!-- generated-by: mae-flow -->` like other generated
Markdown, without adding a Hook parser or template gate.

`spec.md` must contain a Grill traceability table mapping every confirmed
`GQ-*` decision to one Spec section or observable acceptance criterion. The
critic reads both documents and rejects omissions, weakened decisions, changed
meaning, unresolved ambiguity, and WHAT/HOW mixing.

Changing `grill.md` after convergence invalidates the convergence and critic
receipts. Changing `spec.md` after criticism invalidates the critic receipt.

## Guidance Changes

- `flow/phases/spec.md` runs Interactive Grill before Spec generation.
- `runtime/guidance/grill.md` makes the interactive mode the Full owner and
  defines the read-only critic as a later coverage check.
- `agents/grill-critic-agent.md` receives both artifacts and reports explicit
  Grill-input coverage.
- `skills/mae-flow/SKILL.md` tells the main Agent to use the internal CLI events
  and never expose them as user commands.

## Verification

- Pure transition tests cover question serialization, one-open-question gating,
  required real answer, convergence, critic coverage, mutation invalidation,
  and Focused-to-Full behavior.
- CLI tests cover `AskUserQuestion` answer consumption and file-digest checks.
- Semantic scenarios prove Full cannot confirm Spec without the interactive
  result and that Spec traceability is supplied to the critic.
- Architecture and guidance tests prevent a future refactor from replacing the
  interactive loop with a read-only pass.


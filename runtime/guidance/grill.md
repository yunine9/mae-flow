# Requirements Grill

In Full Spec, Interactive Grill comes first. After Spec generation, the
read-only critic performs a later coverage check and never replaces the
interactive work.

## Interactive Grill

Use Interactive Grill to expand unanswered requirement branches until the
requested WHAT is observable and testable.

- Investigate facts in the request, selected behavior baseline, code, and
  environment. Ask the user only for decisions. In an incremental legacy
  baseline, absent text is unknown rather than proof that behavior does not
  exist.
- Follow every requirement branch created by an answer. Ask one question at a
  time, with evidence, impact, and a recommended answer.
- Describe acceptance in observable behavior: inputs, preconditions, triggers,
  outputs, failure and partial failure behavior, boundaries, and outcomes a user
  or caller can detect.
- Turn vague language into explicit conditions. Record compatibility,
  concurrency, ordering, cleanup, and non-goals.
- Keep HOW out of this work; HOW belongs to Story. Implementation types,
  functions, files, algorithms, and module choices are not requirement
  decisions.

Use the following internal checklist while investigating; it is not a required artifact
format. The populated preparation file itself is required. Before
asking, create a code survey and the eight-dimension preparation beside
the exact `grill.md` path printed by `current`. The dimensions are state-machine
completeness, boundary values, concurrency/ordering, failure and cleanup, data
consistency, compatibility/upgrade, scale/performance, and observability. Every
dimension must contain either a candidate question with evidence, impact, and a
recommendation, or a specific code/document citation explaining why it is not
applicable. “Covered”, “irrelevant”, and blank placeholders are not evidence.

The preparation is ammunition, not a fixed question count. After every answer:

- pursue vague words such as “usually”, “probably”, or “depends” until the
  condition is explicit;
- open a derived question for every new term, state, or scenario;
- confront contradictions with code facts or earlier answers immediately;
- reopen a dimension when an answer invalidates its earlier conclusion;
- when the user asks the Agent to decide, present the evidence-backed
  recommendation and still obtain the user's decision.

Record observable behavior as one-testable-statement EARS semantics: WHEN a
condition or trigger occurs, THE SYSTEM SHALL exhibit a caller-visible result.
Keep implementation choices in a separate Design list. There is no default
two-question shortcut. After 15 questions, report the size and let the user
choose whether to continue; do not silently truncate the tree.

Record the evidence-backed question tree and confirmed decisions in local
`grill.md`. It is a required key input to `spec.md`, not an optional audit note.
After every question is answered, generate the candidate Spec with a
traceability mapping from each `GQ-*` decision to a Spec section or observable
acceptance criterion.

## Read-only critic

The read-only critic runs after candidate Spec generation. It reads both
`grill.md` and `spec.md`, never asks the user, and never makes a decision. It
checks complete Grill input coverage, unique meaning, whether answers and code facts
contradict each other, untestable behavior, weakened or omitted decisions,
and WHAT/HOW mixing. Missing branches return to the interactive owner.

Grill owns requirement divergence. Mae runtime does not duplicate brainstorming.
A clear pass adds no separate user stop; final Spec approval remains the existing
high-value stop.

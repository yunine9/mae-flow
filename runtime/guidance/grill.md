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

Use this internal checklist while reading; it is not a required artifact: state
transitions and invalid events, empty and boundary values, duplicates and
ordering, timeout and partial failure, data consistency, compatibility, scale,
concurrency, cleanup, and observability.

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

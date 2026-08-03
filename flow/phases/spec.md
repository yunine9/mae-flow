## Objective
Define WHAT observable outcome is required and what is out of scope. Full Spec
must establish shared understanding through Interactive Grill before producing
the candidate Spec.

## Interactive Grill
Read the request, selected behavior baseline, current behavior, constraints, and
directly relevant code facts. Use the internal checklist for state transitions,
boundaries, ordering, concurrency, partial failure, cleanup, consistency,
compatibility, scale, performance, and observability.

Open one stable `GQ-*` question at a time with evidence, impact, and a recommended
answer. Record it with `advance grill-question --key <GQ-ID> --decision
"<structured question>"`; bind the user's natural-language answer with `decision
grill-answer --key <GQ-ID> "<semantic answer>"`. Inspect each answer for vague
terms, contradictions, new states, and derived requirement branches before
opening the next question. Ask only for decisions; verify discoverable facts.

Write the evidence, question tree, answers, derived branches, confirmed WHAT,
boundaries, compatibility, failure behavior, and non-goals to the ticket's local
`grill.md`. Full requires at least one real answer. When all questions are
closed, run `advance grill-converged`; the CLI binds the current file digest.

## Candidate Spec
Generate `spec.md` only after convergence. The request, selected behavior
baseline, and `grill.md` are required key inputs. Include a Grill traceability
table mapping every confirmed `GQ-*` decision to a Spec section or observable
acceptance criterion. Keep HOW in Story.

## Read-only critic
Run `grill-critic-agent` exactly once for the current Grill/Spec content
revision. It
reads both files and verifies complete input coverage, unchanged decision
meaning, observable acceptance, unique terminology, and no WHAT/HOW mixing. It
never edits files, asks the user, or makes a product decision. A real unresolved
branch returns to Interactive Grill. A material correction creates a new content
revision and permits one new critic pass; continue without automatic retry.

After a clear return, record the capability fact and run `advance grill-clear`.
The CLI binds both current file digests. Any later change invalidates the critic
receipt and must be reviewed again.

## Stop for the user
Stop for each Interactive Grill decision, genuine product ambiguity, a real reviewer tradeoff,
and final approval of the reviewed observable scope. A clear critic result
continues without a user stop. Ask one
question at a time and accept natural-language changes; never expose internal
CLI commands as user work.

## Outputs
Keep `grill.md` and the confirmed `spec.md` under the ticket's local
`.mae-flow-work` directory. Only copy the Spec to
`docs/specs/requirements/<ticket>/spec.md` when the user explicitly selects that
exact durable document. Put `<!-- generated-by: mae-flow -->` at the start of
generated Markdown as provenance only; never validate it in a Hook or parser.

## Next
After `spec-confirmed` verifies the unchanged Grill and Spec receipts, proceed to
Design (stable recovery value `story`).

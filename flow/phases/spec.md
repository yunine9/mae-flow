## Objective
Define WHAT observable outcome is required and what is out of scope. Full Spec
must establish shared understanding through Interactive Grill before producing
the candidate Spec.

## Interactive Grill
Read `flow/steps/grill.md` and
`skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md` completely. Survey
the request, selected behavior baseline, current behavior, constraints, and
directly relevant code facts into the current ticket's `survey.md`. Copy and
complete the eight-dimension template as `grill-prep.md`; every dimension must
contain either candidate questions with evidence/recommendation/impact or a
specific code/document reason why it is not applicable. Placeholders block both
questioning and convergence. There is no two-question shortcut or default
question limit; after 15 questions report the scale and let the user decide.

Existing Grill or Spec drafts are historical clues only. A decision is current
only when the current flow state contains its matching question and answer
receipt. Never infer this run's confirmation from leftover files.

Open one stable `GQ-*` question at a time with evidence, impact, and a recommended
answer. Before asking, record it with `mae-flow advance grill-question --key
<GQ-ID> --parent <ROOT|answered-GQ-ID> --evidence "<fact>" --impact "<effect>"
--recommendation "<answer and reason>"`; bind the user's natural-language answer
with `mae-flow decision grill-answer --key <GQ-ID> "<semantic answer>"`. If the
host delivered the answer before registration, add the same four metadata flags
to that decision command so registration and answer consumption are atomic.
Inspect each answer for vague
terms, contradictions, new states, and derived requirement branches before
opening the next question. Ask only for decisions; verify discoverable facts.

Write the evidence, question tree, answers, derived branches, confirmed WHAT,
boundaries, compatibility, failure behavior, and non-goals to the ticket's local
`grill.md`. It must preserve all eight preparation conclusions and derived EARS
behaviors. When every candidate and derived branch is closed, run
`mae-flow advance grill-converged`; the CLI validates preparation and binds the
current file digest.

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

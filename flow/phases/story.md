## Objective
Produce a standalone software detailed design and test handoff from the approved behavior without reopening the specification.

## Inspect
Read the approved Spec, confirmed customer scenarios, business specifications,
functional acceptance criteria, affected architecture, interfaces, test strategy,
and delivery constraints. Preserve `STORY-TEMPLATE.md`; Story is not a line-by-line
coding plan. Run `story-generator-agent` exactly once, then run
`craft-reviewer-agent` exactly once with the Design Reviewer role.

## Stop for the user
Stop for a meaningful design deviation or approval of the construction story.
Stop for a real reviewer tradeoff. CLEAR or approval continues without a user stop.

## Outputs
Produce the reviewed standalone Story with confirmed business context, software
detailed design, coherent checkpoints, verification intent, and known risks.
Keep it local unless the user explicitly selects its exact durable copy under
`docs/specs/requirements/<ticket>/`. Generated Markdown starts with
`<!-- generated-by: mae-flow -->`; this is provenance, not a format gate.
Record reviewer failure without automatic retry.

## Next
Proceed to Construction. The next meaningful action is to confirm the reviewed HOW.

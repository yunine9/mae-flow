## Objective
Define WHAT observable outcome is required and what is out of scope.

## Inspect
Read the request, current behavior, constraints, acceptance boundaries, and
unresolved product risks. Treat the selected behavior baseline as current
truth while omissions in an incremental legacy baseline remain unknown. Describe
the intended delta, retained behavior, boundaries, and non-goals. After the main Agent drafts the candidate Spec, run
`grill-critic-agent` exactly once as the read-only requirements critic. It finds
material ambiguity but never edits the Spec or makes the product decision.

## Stop for the user
Stop for genuine product ambiguity or approval of the observable scope.
Stop for a real reviewer tradeoff. CLEAR continues without a user stop.

## Outputs
Produce the reviewed specification and record remaining risks or decisions in
natural language. Keep the confirmed change contract under the ticket's local
`.mae-flow-work` directory unless the user explicitly selects its exact durable
copy for commit. Record critic failure without automatic retry.

## Next
Proceed to Design (the stable recovery value is `story`). The next meaningful
action is to confirm the reviewed WHAT from the selected behavior baseline.

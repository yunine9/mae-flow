## Objective
Assess the complete constructed change with the selected expensive quality capabilities.

## Inspect
Read the final local Spec and Story when present, ordered cumulative CP UT
intents, full diff, selected capabilities, the last CP Build outcome, confirmed
UT routes, prior
attempts, environment revision, and unresolved risks.
For selected capabilities, call `codecheck-advisor-agent` and
`ut-generator-agent` by these exact names, each at most once for the current
slot. Do not repeat Build when the last CP Build still covers the final source.
If later repair changes source after that Build, show the user the stale fact
and let the user choose whether to invoke the configured Build route once more.

## Stop for the user
Stop for a reviewer tradeoff, an irreversible risk, or when any capability
retry needs a current user decision. Changed source or environment does not
authorize retrying the same semantic slot. A first call in a genuinely
new CP or phase slot is ordinary planned work and needs no retry confirmation.

## Outputs
Attempt each selected expensive capability at most once for its current slot.
Give `ut-generator-agent` the final Spec, final Story, final diff, and ordered
cumulative CP UT intents in one action. After each actual synchronous call,
record exactly one lightweight capability fact with `python
".mae-flow-work/bin/mae-flow.py" advance capability-<outcome> --key <kind>
--decision "<opaque summary>"`. Do not parse private output or rerun
a capability merely because recording failed. Record remaining risks and
delivery readiness. Before Delivery, record one short final Spec/Story/scope ↔
code/coverage conformance conclusion. If Construction recorded semantic
cross-CP coupling, call `craft-reviewer-agent` once with the integration-review
role and record one natural-language conclusion; otherwise do not add this pass.

## Next
Proceed to Delivery after quality is complete. The next meaningful action is the next selected capability not yet attempted.

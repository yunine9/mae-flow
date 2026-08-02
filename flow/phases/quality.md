## Objective
Assess the complete constructed change with the selected expensive quality capabilities.

## Inspect
Read the cumulative UT handoff, full diff, selected capabilities, prior attempts, environment revision, and unresolved risks.
For selected capabilities, call `codecheck-advisor-agent`, the configured
`build-fix` Skill, and `ut-generator-agent` by these exact names, each at most
once for the current slot.

## Stop for the user
Stop for a reviewer tradeoff, an irreversible risk, or when any capability
retry needs a current user decision. Changed source, phase, CP, or environment
changes the authorization key but never auto-authorizes another call.

## Outputs
Attempt each selected expensive capability at most once for its current slot. After each actual synchronous call, record exactly one lightweight capability fact with `advance capability-<outcome> --key <kind> --decision <opaque summary>`. Do not parse private output or rerun a capability merely because recording failed. Record remaining risks and delivery readiness.

## Next
Proceed to Delivery after quality is complete. The next meaningful action is the next selected capability not yet attempted.

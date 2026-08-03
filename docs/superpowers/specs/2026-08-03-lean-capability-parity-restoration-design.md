# Lean Capability Parity Restoration Design

## Problem

The Lean cutover reduced runtime ceremony but also removed user-visible behavior
that was not optional friction. Startup can currently accept `start --decision`
without a current CodeAgent user-input receipt, immediately leave Startup, and
therefore suppress the complete configuration card. Earlier regressions in
Interactive Grill, AskUserQuestion consumption, and cross-repository Chain show
that the migration gate checked the new implementation's internal consistency
without proving old-to-new user-journey parity.

## Goals

- A new delivery always renders one complete Startup configuration card before
  any confirmation can advance the workflow or create/switch a branch.
- Startup confirmation consumes one current `UserPromptSubmit` or
  `AskUserQuestion` event bound to the exact Startup state digest.
- A user can modify any Startup choice, see a newly rendered complete card, and
  then confirm the new digest.
- Deleting business files never masquerades as workflow reset; active state is
  recovered with `current`, and supported `exit` plus a new `start` begins a new
  run.
- Every critical legacy user journey has a named semantic parity contract and
  at least one executable release test. Removing friction is allowed only when
  the user-visible outcome, decision ownership, recovery, and side-effect
  boundary remain equivalent.

## Non-goals

- Restore legacy task cards, fixed Agent report schemas, transcript parsing,
  polling, repeated capability calls, or broad file/Git interception.
- Restore legacy internal step names or JSON schema.
- Require the user to type CLI commands or a fixed confirmation phrase.

## Startup Handshake

Startup becomes a thin two-step handshake:

1. `start` resolves explicit values, `.mae-flow-defaults.json`, and Git
   fallbacks, persists an active Startup draft, and renders the complete card.
   It has no branch or business-file effect.
2. The user confirms or modifies the displayed card in natural language.
   `configure` consumes that current user event when applying modifications,
   re-renders the entire card, and invalidates any prior confirmation context.
3. `decision startup-confirmed` consumes a new current user event, creates or
   switches to the exact confirmed working branch, and advances to Spec or
   Construction.

`start --decision` is rejected because no persisted Startup state existed when
the alleged decision was captured, so the decision cannot be bound to the
configuration digest. Moonlight remains the only explicit no-question startup
mode; its launch authorization is the semantic substitute for routine Startup
confirmation and existing Moonlight side-effect limits remain unchanged.

The `configure` command accepts the same mutable configuration fields as the
card: worker, ticket type, requirement, base/working branch, build route, UT
route/command, Full/Focused path, Continuous/Staged pace, request summary, and
quality plan. It is valid only in active Startup. When worker or base branch
changes without an explicit working branch, the working branch is re-derived.
Changing Full/Focused replaces the draft artifact set accordingly.

## Capability Parity Contract

Add a repository-owned semantic matrix covering these user journeys:

1. Startup configuration review, modification, confirmation, branch placement,
   defaults, and explicit restart/recovery.
2. Full/Focused selection and semantic upgrade.
3. mandatory Interactive Grill, real answers, convergence, critic digest, and
   Grill-to-Spec traceability.
4. Design Story, bounded Design/CODE review, CP confirmation/revision, and both
   Continuous and Staged delivery pace.
5. exact per-CP Build observation, CodeCheck, UT, opaque capability results,
   one-attempt/retry authorization, and repair re-entry.
6. initial-dirty ownership, exact manifest, conditional documents, behavior
   baseline reconciliation, commit/push observation, and Delivery confirmation.
7. recovery, corruption diagnostics, explicit exit, Windows paths, and
   Moonlight authorization boundaries.
8. standalone UT, CodeCheck, Grill, Story, and recoverable cross-repository
   Chain.

Each matrix row names the legacy behavior, its Lean semantic replacement, and
specific executable tests. A validator rejects missing/unknown tests, duplicate
journey IDs, empty behavior statements, or a critical journey classified as
removed friction. The earlier confirmation-receipt retirement entry is
reclassified: fixed ack wording is removed friction, but current-state-bound
user decision ownership is preserved behavior.

## Safety and Recovery

- Startup draft/configuration writes only Mae-Flow state and local artifacts.
- Branch placement remains deferred until confirmed Startup.
- An active state is never silently overwritten; `current` or `exit` is
  required.
- User input is single-use and state-digest-bound; modifications make older
  inputs stale automatically.
- Existing Hook write/Git safety remains unchanged outside the corrected
  Startup boundary.

## Verification

- TDD tests prove raw `start --decision` fails, `start` renders the complete
  card, confirmation without a captured user event fails, both input sources
  work, modification requires a current event, stale confirmation fails, and
  the confirmed branch/config are exact.
- The parity matrix validator is a registered release suite.
- All unit tests and `scripts/selftest.py` pass before push.
- The final clean `main` is pushed to `origin/main` only after fresh full
  verification.

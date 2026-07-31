# Opaque Compile Evidence Design

## Context

Mae-Flow runs on Windows and may compile C++ through an internal `build-fix`
Skill whose implementation is effectively Maven wrapping g++.  The Hook can
observe the Skill invocation and the host tool protocol, but it cannot rely on
the wrapper's stdout wording, error-count format, or exit-code semantics.

The current COMPILE contract nevertheless makes `EXECUTED_BUILD` and
`BUILD_ERRORS` mandatory.  A formatting mismatch can therefore discard a
one-to-two-hour build.  Unlike UT and CodeCheck, COMPILE persists no reusable
execution receipt.  In staged checkpoints the documented fallback is also
unusable: `accept-risk compile` rejects the uncommitted source snapshot that
the checkpoint intentionally requires.

## Goals

- Never rerun an unchanged build merely to repair an Agent report.
- Treat `build-fix` as the authority for its own compile-success semantics.
- Keep hard checks for task identity, actual configured-route invocation,
  explicit Agent status, source freshness, write scope, and commit ownership.
- Make the user-authorized risk fallback work for staged, pre-commit Full
  checkpoints without weakening freshness.
- Preserve Windows compatibility and avoid parsing proprietary tool output.

## Non-goals

- Interpreting Maven, g++, mcde, or internal Skill stdout.
- Claiming the Hook independently proved compilation when the provider is
  opaque.
- Relaxing source-scope, task-card, branch, commit, or snapshot integrity.
- Changing UT or CodeCheck output contracts in this change.

## Design

### 1. Opaque provider boundary

For `COMPILE_RESULT: OK`, the hard contract becomes:

1. the report carries the current task-card SHA;
2. the configured build Skill or command was actually invoked, or a reusable
   receipt proves the same invocation for the same task and source snapshot;
3. the host did not explicitly mark the invocation as an error;
4. the Agent did not cross its write/commit boundary;
5. the Agent explicitly reports `OK`.

`EXECUTED_BUILD` and `BUILD_ERRORS` remain optional diagnostics.  If present
and self-contradictory they are logged, not used to override the provider's
own contract.  `SHRINK_EXEMPT` remains mandatory when the Hook independently
calculates net source deletion, because that check does not depend on provider
output.

`BLOCKED` still requires evidence that the configured route was attempted.
`FAIL` remains an honest terminal report when the route could not be run.

### 2. Compile execution receipt

After task-card and source-scope validation, a real matching build invocation
is persisted before narrative report validation.  The receipt contains only
non-proprietary facts:

- step, task SHA, task issuance ID, checkpoint and configured route;
- Agent terminal status associated with the invocation;
- current HEAD and, for pre-commit/standalone work, the exact source snapshot;
- timestamp and a SHA-256 digest of the opaque tool result.

A receipt is reusable only when task SHA, issuance ID, route, status and source
snapshot still match.  A changed task, config, status or source invalidates it.
The raw internal build output is not persisted.

### 3. Snapshot-aware risk acceptance

Normal post-commit risk acceptance keeps its clean-worktree rule.  When the
current COMPILE task is explicitly marked `precommit_review`, the command may
bind authorization to the current uncommitted source snapshot instead of
rejecting it.  Validation compares the current snapshot with that frozen
snapshot, so later edits still invalidate the authorization.  Committing the
same reviewed content does not invalidate it.

The success message points staged checkpoints to `checkpoint ready CPn`; other
steps continue to use `done`.

### 4. Evidence language

The delivery ledger distinguishes opaque-provider evidence from an
independently parsed compiler result.  It records "configured build route
observed; provider/Agent reported OK" and does not claim that the Hook parsed
Maven or g++ success.

### 5. End-to-end invariant

For one staged Full checkpoint, all of these paths must remain reachable:

- visible build-fix call + minimal OK report -> COMPILE token -> checkpoint
  ready;
- first report rejected for a non-provider invariant -> corrected report uses
  the frozen receipt without another build-fix call;
- unavailable transcript -> user-authorized snapshot risk -> checkpoint ready;
- any source edit after receipt/risk authorization -> both proofs rejected.

## Safety

The change removes unverifiable report-format gates, not repository-integrity
gates.  A report cannot pass with a stale card, missing configured invocation,
host-declared tool error, changed source snapshot, forbidden test edit, commit
inside pre-commit review, or unexplained net source deletion.

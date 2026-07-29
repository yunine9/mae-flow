# Mae-Flow Stage 6 CLI Commands Implementation Plan

> Goal: move every remaining command use case out of `scripts/mae-flow.py`
> without changing CLI arguments, output, exit codes, state, files, or Git
> effects. The entrypoint becomes public argument/runtime adaptation only.

## Contract

- Phase-15 remains the black-box behavior oracle.
- Command application modules use explicit ports and immutable results.
- Tests exercise public application functions or the CLI process; no business
  test dynamically imports private entrypoint functions.
- New modules stay at or below 500 lines and policy complexity at or below 15.
- `scripts/mae-flow.py` must finish Stage 6 at or below 1,500 lines.

## Batch 1: Runtime, state, and inspection commands

Characterize and extract `current`, `status`, `steps`, `messages`,
`requirement-record`, `report`, `report-all`, `doctor`, and runtime-corruption
diagnostics. Introduce shared CLI response/effect values and filesystem,
clock, process, and state ports. Add process-level tests for every runtime mode.

## Batch 2: Lifecycle commands

Extract `init`, Direct re-entry/rollover, `exit`, `goto`, `unlock`, `skip`,
`accept-risk`, `allow`, `reloaded`, and capability passthrough. Preserve
terminal rollover, corrupt-state recovery, exit snapshots, one-shot risk
receipts, and all interactive safety boundaries.

## Batch 3: Workflow advancement and specification commands

Extract `current` rendering dependencies, configuration review, `done`,
transition/return/recheck selection, `spec`, template, environment check, and
STORY localization. Keep the workflow definition as data and expose one
application advancement API.

## Batch 4: Delivery and quality command adapters

Move the remaining Checkpoint, Standalone Action, Moonlight, Gate,
Agent-task, CodeCheck, and Lightcheck platform assembly behind cohesive
adapters. Reuse the Stage 2–5 pure/application modules; do not duplicate their
policy in the command layer.

## Batch 5: Public dispatch and compatibility cleanup

Create one command registry over public handlers. Reduce `scripts/mae-flow.py`
to encoding setup, argument parsing, project-root selection, runtime loading,
handler invocation, and top-level error mapping. Replace private entrypoint
imports in tests with public modules/process tests and add architecture gates
for forbidden migrated command definitions.

## Verification after every batch

1. Focused RED/GREEN tests for the moved command family.
2. `python scripts/tests/test_architecture.py`
3. `python scripts/tests/differential/runner.py --implementation-root .`
4. `git diff --check`

## Stage closeout

Run the complete strict unittest suite, complete selftest, Phase-15, fault
injection, completion contract, and independent code review. Record any real
defect as an MF-RF finding with a separate `fix:` commit.

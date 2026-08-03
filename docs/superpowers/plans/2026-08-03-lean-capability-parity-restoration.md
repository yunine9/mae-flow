# Lean Capability Parity Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore state-bound Startup confirmation and add a release-blocking semantic parity audit for every critical old-flow user journey.

**Architecture:** Keep schema-v3 and the thin CLI, but split Startup into persisted draft, optional user-owned reconfiguration, and user-owned confirmation. Add a declarative user-journey matrix whose validator resolves exact unittest IDs so future Lean simplification cannot silently remove capabilities.

**Tech Stack:** Python 3 standard library, frozen dataclasses, argparse, JSON, SHA-256 user-event receipts, unittest.

## Global Constraints

- Work directly on `main` as authorized by the user.
- Do not restore legacy task-card/report/transcript ceremony.
- No branch placement before a current, exact Startup confirmation.
- Both `UserPromptSubmit` and `AskUserQuestion` must work.
- Every production behavior change follows RED → GREEN and is committed separately.
- Push only after full unit discovery and release selftest pass.

---

### Task 1: State-Bound Startup Confirmation

**Files:**
- Modify: `scripts/tests/test_lean_cli.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `commands/mae-flow.md`

**Interfaces:**
- Consumes: `matching_user_event(root, state)` and `bind_user_event(...)`.
- Produces: a draft-only `start` and user-owned `decision startup-confirmed`.

- [ ] Add tests that raw `start --decision` is rejected and no branch/state confirmation is created.
- [ ] Add tests that draft `start` renders every configuration-card field and stays in Startup.
- [ ] Verify those tests fail for the expected self-confirm behavior.
- [ ] Reject `start --decision`; keep branch placement only in `cmd_lean_decision` after receipt matching.
- [ ] Update Skill/command guidance to run draft `start`, show the card, then confirm through `decision`.
- [ ] Run the focused CLI/Hook suites and commit `fix: require real Startup confirmation`.

### Task 2: User-Owned Startup Reconfiguration

**Files:**
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/command_dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Modify: `scripts/tests/test_lean_cli.py`

**Interfaces:**
- Produces: `configure [startup fields] --decision <summary>` and `cmd_lean_configure(root, args)`.

- [ ] Add tests for modification without input, current input, AskUser input, stale input, branch re-derivation, and Full/Focused artifact replacement.
- [ ] Verify RED because `configure` is unrouted.
- [ ] Add parser/route/handler and a Startup-only immutable reconfiguration operation.
- [ ] Bind the modifying event, render the entire updated card, and require a new input for final confirmation.
- [ ] Run focused suites and commit `feat: add user-owned Startup reconfiguration`.

### Task 3: User-Journey Capability Parity Gate

**Files:**
- Create: `runtime/guidance/user-journey-preservation.json`
- Create: `scripts/tests/test_lean_capability_parity.py`
- Modify: `runtime/guidance/capability-preservation.json`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `scripts/tests/refactor_completion.py`
- Modify: `scripts/tests/refactor_completion_contract.json`
- Modify: `scripts/tests/test_refactor_completion.py`
- Modify: `scripts/tests/test_capabilities.py`

**Interfaces:**
- Produces: a schema-1 matrix of unique journey IDs, legacy behavior, Lean behavior, classification, and exact semantic test IDs.

- [ ] Add a failing validator test requiring all eight capability families and exact discoverable tests.
- [ ] Verify RED because the matrix does not exist.
- [ ] Audit legacy flow/config-review/standalone behavior against current production tests; add missing regression scenarios before listing them.
- [ ] Create the matrix and reject critical rows classified as removed friction.
- [ ] Correct the confirmation-receipt retirement classification to distinguish removed fixed wording from preserved decision ownership.
- [ ] Register the new suite in every release contract and update discovery counts.
- [ ] Run parity, architecture, capabilities, and contract suites; commit `test: enforce Lean capability parity`.

### Task 4: Final Verification and Remote Delivery

**Files:**
- Modify only files required by discovered regressions.

**Interfaces:**
- Produces: a clean, verified `main` pushed to `origin/main`.

- [ ] Run `python -m unittest discover -s scripts/tests -p 'test_*.py'`.
- [ ] Run `python scripts/selftest.py`.
- [ ] Run `git diff --check` and verify a clean worktree.
- [ ] Commit exact verification corrections if required.
- [ ] Push `main` to `origin/main` and verify local/remote SHA equality.

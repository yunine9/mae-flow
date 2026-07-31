# Confirmation Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fragile copied confirmation phrases with artifact-bound routine receipts and message-ID-bound high-risk authorization.

**Architecture:** Extend the existing captured-message ledger instead of adding a second state store. Standalone scope confirmation binds answers to a deterministic scope fingerprint, checkpoint choices reuse their existing artifact receipt cursors, and commands that need detailed user wording resolve it internally from a current-step message ID.

**Tech Stack:** Python 3 standard library, argparse CLI, versioned JSON state, unittest/selftest.

## Global Constraints

- Do not accept arbitrary positive words without a fresh, in-scope receipt.
- Do not transport full high-risk user text through shell arguments.
- Keep exact Git path/commit authorization checks.
- Preserve legacy stored-state readability.
- Follow red-green-refactor for every behavior change.

---

### Task 1: Standalone scope receipts

**Files:**
- Modify: `scripts/mae_flow_core/application/delivery/standalone.py`
- Modify: `scripts/mae_flow_core/adapters/hook_runtime_state.py`
- Modify: `scripts/mae_flow_core/adapters/hook_active_events.py`
- Modify: `scripts/mae_flow_core/cli_commands/standalone_core.py`
- Modify: `scripts/mae_flow_core/cli_commands/standalone_commands.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Test: `scripts/tests/test_confirmation_receipts.py`

**Interfaces:**
- Produces: `standalone_scope_fingerprint(action) -> str`
- Produces: `_action_scope_receipt(action) -> (bool, dict, str)`
- Consumes: captured message rows with `scope_sha256`

- [ ] Write integration tests for natural positive, negative, missing, and stale-scope answers.
- [ ] Run the focused test and verify the old `--ack` behavior fails the new contract.
- [ ] Store scope fingerprints on proposals and captured messages.
- [ ] Make `action confirm-scope` consume the receipt without arguments.
- [ ] Run the focused tests and refactor while green.

### Task 2: Structured checkpoint choices

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_commands.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/application/delivery/checkpoint_quality.py`
- Test: `scripts/tests/test_confirmation_receipts.py`

**Interfaces:**
- Produces: receipt-cursor-bound selection verification
- Consumes: existing `plan_receipt`, checkpoint `receipt`, and `final_review`

- [ ] Write tests proving choices work without `--ack` and stale answers fail.
- [ ] Run the focused test and verify failure.
- [ ] Remove copied ack arguments and resolve the exact displayed selection from fresh answers.
- [ ] Run focused checkpoint and receipt tests.

### Task 3: Message-ID authorization

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/ack.py`
- Modify: `scripts/mae_flow_core/cli_commands/lifecycle.py`
- Modify: `scripts/mae_flow_core/cli_commands/done_status.py`
- Modify: `scripts/mae_flow_core/cli_commands/spec.py`
- Modify: `scripts/mae_flow_core/cli_commands/codecheck_commands.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Test: `scripts/tests/test_confirmation_receipts.py`
- Test: existing command and ownership suites

**Interfaces:**
- Produces: `_authorization_message(st, message_id) -> (ok, answer, receipt, why)`
- Consumes: current-step message IDs from `messages`

- [ ] Write tests for valid IDs, stale IDs, structured answers, and Git exact coverage.
- [ ] Run focused tests and verify old text transport fails the new contract.
- [ ] Add the central resolver and migrate each affected command.
- [ ] Store message ID and answer SHA instead of duplicate raw answer where records permit.
- [ ] Run focused command and Git ownership suites.

### Task 4: Guidance and regression safety

**Files:**
- Modify: `commands/mae-flow.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `README.md`
- Modify: affected runtime guidance modules and differential goldens

**Interfaces:**
- Consumes: the final CLI syntax from Tasks 1-3

- [ ] Replace affected `--ack` instructions with automatic receipt or `--message-id` instructions.
- [ ] Add README troubleshooting that distinguishes Hook blocks, CLI rejection, stale receipts, and malformed message capture.
- [ ] Run focused tests, architecture tests, differential update/check, and `python scripts/selftest.py`.
- [ ] Review `git diff --check`, inspect the complete diff, and commit.

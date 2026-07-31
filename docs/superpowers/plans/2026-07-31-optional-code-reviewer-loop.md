# Optional CODE Reviewer Loop Implementation Plan

**Goal:** Make independent CODE Review selectable at startup, keep Findings under user control, and remove Hook/state-machine friction from the re-review loop.

## Task 1: Lock the contracts with regression tests

- Cover startup choice persistence and legacy default behavior.
- Cover Reviewer-disabled staged/continuous checkpoint transitions.
- Cover role-result Hook bypass and complete Finding templates.
- Cover FINDINGS waiting for user decision and actionable re-review recovery.

## Task 2: Implement startup choice and fast path

- Add `code_reviewer_ask` as a one-question startup choice immediately after
  delivery type (the existing card already uses the host's four-question cap).
- Persist `choices.code_reviewer`; Moonlight and legacy states default to enabled.
- Store the choice in the checkpoint review and bypass `craft_pending` when disabled.

## Task 3: Implement the user-controlled Finding loop

- Align Reviewer prompt, generated task card, and artifact validator.
- Register Findings as `craft_decision_pending`.
- Require a fresh captured user decision before accepted Findings enter `coding`.
- Make repair output prescribe `compile → checkpoint ready → fresh craft-code → fresh Reviewer`.

## Task 4: Fix completion routing and lifecycle semantics

- Let informational role result markers bypass hard evidence-token routing.
- Write `compiled_at` at compilation and `closed_at` only at true completion.
- Update workflow guidance and wrong-state errors with exact recovery commands.

## Task 5: Verify and deliver

- Run one focused regression suite.
- Run one complete self-test.
- Commit and push to `origin/main`.

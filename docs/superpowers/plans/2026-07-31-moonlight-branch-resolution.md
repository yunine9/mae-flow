# Moonlight Branch Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkboxes for progress tracking.

**Goal:** Let Moonlight safely continue a proven existing delivery branch, and
automatically block ambiguous or unrelated branch histories.

**Architecture:** Add a focused delivery policy that returns either an adoption
receipt, a blocker, or no action from explicit Git/state facts. Invoke it only
before Moonlight completes `branch_create`; keep ordinary mode and existing
branch creation unchanged.

**Tech Stack:** Python standard library, existing Mae-Flow CLI/application
modules, `unittest`, Git CLI.

---

### Task 1: Pin the policy with failing tests

- [ ] Add focused tests for explicit-request adoption.
- [ ] Add strict last-state continuation tests.
- [ ] Add ambiguous-provenance and divergent-history blocker tests.
- [ ] Confirm ordinary mode remains unchanged.
- [ ] Run the focused tests and confirm they fail for the missing behavior.

### Task 2: Implement the smallest branch resolver

- [ ] Add a pure Moonlight branch-resolution decision.
- [ ] Add the CLI adapter that gathers Git and archived-state facts.
- [ ] Run it before `branch_create` evidence validation.
- [ ] Store an auditable adoption receipt or the existing Moonlight blocker.
- [ ] Run focused tests until green.

### Task 3: Document the behavior

- [ ] Update `branch_create` instructions so Moonlight never asks for branch
      acknowledgement.
- [ ] Document the resolution priority and blocker behavior in README.
- [ ] Add prompt/documentation assertions where useful.

### Task 4: Verify and integrate

- [ ] Run focused tests.
- [ ] Run architecture/contract checks affected by the new module.
- [ ] Run `python scripts/selftest.py`.
- [ ] Review the final diff for scope and accidental behavior changes.

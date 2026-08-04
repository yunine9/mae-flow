# Domain Archive Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use subagents for this implementation.

**Goal:** Make `docs/specs/<domain>.md` the only durable documentation output of a requirement while keeping every process artifact local, index-loading only relevant domain truth, and preventing workflow loops or prompt/CLI mismatches.

**Architecture:** Add a deterministic local domain-archive transaction between final quality and delivery review. The transaction prepares editable candidates under the ticket work package, validates and classifies them, freezes input freshness, and applies confirmed changes atomically. Final manifest policy admits domain documents only when that exact transaction applied them; all legacy process-document paths are localized or rejected.

**Tech Stack:** Python 3 standard library, JSON workflow definitions, Markdown guidance/templates, `unittest`-based repository tests.

---

## Task 1: Domain template and index contract

**Files:**
- Create: `skills/mae-flow/assets/DOMAIN-SPEC-TEMPLATE.md`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/orchestration/behavior_baseline.py`
- Test: `scripts/tests/test_project_resources.py`
- Test: `scripts/tests/test_behavior_baseline.py`
- Test: `scripts/tests/test_domain_docs.py`

1. Add failing tests for project-resource installation, all ten required sections, substantive section validation, duplicate domain/keyword detection, invalid index paths, and missing indexed files.
2. Run the focused tests and confirm the new assertions fail for the expected missing behavior.
3. Add the canonical domain template and install it into project-local plugin resources.
4. Extend the baseline parser/validator with precise diagnostics while preserving relevant-only context loading and existing custom document content.
5. Run the focused tests until green and commit the task.

## Task 2: Deterministic local archive transaction

**Files:**
- Create: `scripts/mae_flow_core/orchestration/domain_archive.py`
- Create: `scripts/mae_flow_core/cli_commands/domain_archive.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/cli_dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Test: `scripts/tests/test_domain_archive.py`
- Test: `scripts/tests/test_domain_archive_cli.py`
- Test: `scripts/tests/test_command_dispatch.py`

1. Add failing unit tests for new, updated, unchanged, and multi-domain preparation; candidate preservation; required-section validation; freshness rejection; confirmed apply; and transaction rollback.
2. Add failing CLI tests for `prepare`, `show`, `status`, and `apply --message-id`, including parser/help examples that can be copied verbatim.
3. Implement pure archive planning/state helpers. Candidate files and state live only under `.mae-flow-work/<ticket>/domain-archive/`; preparation never writes `docs/specs`.
4. Implement atomic apply using temporary sibling files and rollback snapshots. Record only actually changed domain/index paths in `state.domain_archive.applied_paths`.
5. Require an existing natural-language authorization receipt and reject stale candidates with one recovery command; never change workflow phase or retry automatically.
6. Run focused tests until green and commit the task.

## Task 3: Insert one reachable archive stage without loops

**Files:**
- Create: `flow/steps/domain_archive.md`
- Modify: `flow/flow.json`
- Modify: `scripts/mae_flow_core/workflow/evidence.py`
- Modify: `scripts/mae_flow_core/cli_commands/workflow.py`
- Test: `scripts/tests/test_flow_definition.py`
- Test: `scripts/tests/test_flow_liveness.py`
- Test: `scripts/tests/test_workflow_advancement.py`
- Test: `scripts/tests/test_command_prompt_agreement.py`

1. Add failing tests proving every current path reaches domain archive exactly once after final quality and before delivery review.
2. Add a `domain_archive_complete` evidence check accepting applied changes or confirmed `unchanged` and rejecting drafts/stale candidates.
3. Route current quality exits through `domain_archive`; route it to delivery review; make old OpenSpec archive nodes one-way compatibility bridges to this stage.
4. Write concise Chinese guidance containing only parser-supported commands and a single recovery action for each error.
5. Run liveness, transition, and prompt/command-agreement tests until green and commit the task.

## Task 4: Localize every process artifact producer

**Files:**
- Modify: `flow/steps/grill.md`
- Modify: `flow/steps/rf_triage.md`
- Modify: `flow/steps/hf_open.md`
- Modify: `flow/steps/tw_open.md`
- Modify: `flow/steps/end.md`
- Modify: `flow/flow.json`
- Modify: `scripts/mae_flow_core/cli_commands/codecheck_commands.py`
- Modify: `scripts/mae_flow_core/cli_commands/git_ownership.py`
- Test: `scripts/tests/test_stable_recovery_contract.py`
- Test: `scripts/tests/test_story_contract.py`
- Test: `scripts/tests/test_commit_ownership.py`
- Create: `scripts/tests/test_process_artifact_boundary.py`

1. Add failing tests proving Clarifications, review reports, CodeCheck exemptions, delivery notes, Story copies, and OpenSpec changes are never required, generated, or advertised as commit candidates.
2. Change all producers to write inside the active ticket work package. Hotfix/tweak use the same local Spec contract as other paths.
3. Add safe migration of untracked legacy process files into the work package; never rewrite committed history or silently move tracked files.
4. Remove Git ownership exceptions that previously allowed process documents to be committed.
5. Run focused boundary and legacy-recovery tests until green and commit the task.

## Task 5: Enforce final manifest boundary

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/delivery_manifest.py`
- Modify: `scripts/mae_flow_core/guard/manifest.py`
- Test: `scripts/tests/test_delivery_manifest.py`
- Test: `scripts/tests/test_delivery_policies.py`
- Test: `scripts/tests/test_commit_ownership.py`

1. Add failing tests for every forbidden process path and for arbitrary `docs/specs` changes not produced by the current archive transaction.
2. Allow only source/test/config/resource candidates plus the exact changed paths recorded by `domain-archive apply`.
3. Ensure unchanged archive results create no documentation manifest entry and repeated identical manifests reuse one confirmation.
4. Run focused delivery tests until green and commit the task.

## Task 6: Consume only relevant domain truth

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/agent_task.py`
- Modify: `scripts/mae_flow_core/cli_commands/story.py`
- Modify: `flow/steps/grill.md`
- Test: `scripts/tests/test_role_task_documents.py`
- Test: `scripts/tests/test_quality_task_cards.py`
- Test: `scripts/tests/test_story_contract.py`
- Test: `scripts/tests/test_domain_docs.py`

1. Add failing task-card tests proving Grill, Story, CP implementation, CodeCheck, and UT include indexed relevant domain documents and exclude unrelated ones.
2. Reuse the single index-driven context loader for every consumer; do not scan all of `docs/specs`.
3. Surface invalid-index diagnostics with one repair command and no automatic retries.
4. Run focused consumption tests until green and commit the task.

## Task 7: Release contract and end-to-end verification

**Files:**
- Modify: `MAINTAINERS.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/mae-flow/flow-runtime-guide.md`
- Test: `scripts/tests/test_stable_recovery_contract.py`
- Test: `scripts/tests/test_workflow_completion.py`

1. Remove residual documentation that says process files are committed and document the one durable domain-archive boundary.
2. Add end-to-end tests for new/update/unchanged archives, staged/continuous paths, legacy in-flight recovery, prompt/parser consistency, and exact final manifest contents.
3. Run focused end-to-end tests, then the full repository suite and self-test from a clean state.
4. Review the diff for unintended stable-flow changes, merge the isolated branch into `main`, rerun smoke verification, and push `main`.

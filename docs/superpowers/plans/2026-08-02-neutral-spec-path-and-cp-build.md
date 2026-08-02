<!-- generated-by: mae-flow -->

# Neutral Spec Path and CP Build Implementation Plan

> **Execution status:** completed in the current maintenance session with test-first semantic contracts and the repository release gates.

**Goal:** Move durable documents to neutral Spec paths and restore lightweight per-CP build and conformance guarantees without restoring evidence-heavy Hooks.

**Architecture:** Extend the existing lean state decisions and capability slots instead of adding another workflow. Keep document path generation pure, keep Git branch placement in the CLI adapter, and express professional work through configured opaque capabilities plus small semantic transition facts.

**Tech Stack:** Python 3.8-compatible standard library, unittest, Markdown guidance, CodeAgent Hooks, Windows-safe Git subprocesses.

## Global Constraints

- `.mae-flow-work/<ticket>/` remains the local process root.
- New durable domain paths are `docs/specs/<domain>.md`; conditional request copies are under `docs/specs/requirements/<ticket>/`.
- Every generated Spec, Story, and domain Markdown document carries `<!-- generated-by: mae-flow -->`, but no runtime validation depends on it.
- C++ may use configured `build-fix`; Java/Maven uses the confirmed Maven command; other repositories use their confirmed route.
- Each CP gets one synchronous build attempt; no delay loop, repeated status probe, background wait, output parsing, or automatic retry.
- No engineering-experience document is generated or delivered.

---

### Task 1: Lock the new semantic contracts with failing tests

**Files:**
- Modify: `scripts/tests/test_lean_documents.py`
- Modify: `scripts/tests/test_lean_capabilities.py`
- Modify: `scripts/tests/test_lean_transitions.py`
- Modify: `scripts/tests/test_lean_cli.py`
- Modify: `scripts/tests/test_lean_guidance.py`
- Modify: `scripts/tests/test_native_guidance.py`
- Modify: `scripts/tests/test_windows_lean_runtime.py`

**Interfaces:**
- Consumes: current `DocumentPaths`, `advance_flow`, `flow_attempt_context`, and lean CLI.
- Produces: executable expectations for neutral paths, one automatic attempt per CP slot, branch placement, quality planning, integration review, and final conformance.

- [x] Add focused tests for each new behavior and the legacy-path compatibility boundary.
- [x] Run the targeted tests and confirm they fail for the missing behavior rather than test errors.

### Task 2: Implement document ownership and provenance

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/documents.py`
- Modify: `scripts/mae_flow_core/orchestration/behavior_baseline.py`
- Modify: `skills/mae-flow/assets/STORY-TEMPLATE.md`
- Modify: `skills/mae-flow/assets/BEHAVIOR-TEMPLATE.md`

**Interfaces:**
- Consumes: ticket/domain Windows-safe normalization.
- Produces: new neutral durable paths while accepting legacy selected-domain paths during recovery.

- [x] Change new durable path generation and remove engineering-note document kinds.
- [x] Add provenance comments to templates without adding a validator.
- [x] Run `python -m unittest scripts.tests.test_lean_documents scripts.tests.test_windows_lean_runtime` and resolve any failures.

### Task 3: Restore configured per-CP Build and startup branch placement

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/capabilities.py`
- Modify: `scripts/mae_flow_core/orchestration/transitions.py`
- Modify: `scripts/mae_flow_core/orchestration/transition_support.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_manifest.py`
- Modify: `scripts/mae_flow_core/cli_commands/lean_workflow.py`
- Modify: `scripts/mae_flow_core/cli_commands/user_events.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`

**Interfaces:**
- Consumes: confirmed `StartupConfig.build_method`, CP-scoped attempt contexts, exact base/working branches.
- Produces: one automatic Build attempt per distinct CP, retry protection within a CP, startup quality-plan recovery fact, and synchronous branch placement.

- [x] Allow the first attempt in a new semantic slot while retaining retry authorization for the same slot.
- [x] Require a recorded CP Build attempt before CP readiness and Construction completion.
- [x] Add confirmed branch creation/switching to atomic startup handling and test existing/new branches.
- [x] Render and persist the natural-language quality plan.
- [x] Run `python -m unittest scripts.tests.test_lean_capabilities scripts.tests.test_lean_transitions scripts.tests.test_lean_cli` and resolve any failures.

### Task 4: Restore cheap conformance and review completeness

**Files:**
- Modify: `scripts/mae_flow_core/orchestration/transitions.py`
- Modify: `scripts/mae_flow_core/orchestration/transition_support.py`
- Modify: `scripts/mae_flow_core/orchestration/guidance.py`
- Modify: `flow/phases/construction.md`
- Modify: `flow/phases/quality.md`
- Modify: `flow/phases/delivery.md`
- Modify: `runtime/guidance/review.md`
- Modify: `runtime/guidance/quality.md`
- Modify: `skills/mae-flow/SKILL.md`
- Modify: `commands/mae-flow.md`

**Interfaces:**
- Consumes: CP risk facts, opaque reviewer attempt, final diff, confirmed artifacts/scope.
- Produces: integration-review requirement/completion and one delivery-visible final-conformance conclusion.

- [x] Persist semantic integration-review requirements and require one recorded completion only when triggered.
- [x] Require one natural-language final-conformance conclusion before Quality completes.
- [x] Make Review work account for every supplied finding without a fixed schema.
- [x] Run `python -m unittest scripts.tests.test_lean_transitions scripts.tests.test_native_guidance` and resolve any failures.

### Task 5: Align public documentation and complete release verification

**Files:**
- Modify: `README.md`
- Modify: `MAINTAINERS.md`
- Modify: `FIELD-TEST.md`
- Modify: `CLEAN-ROOM-TEST.md`
- Modify: `flow/phases/startup.md`
- Modify: `flow/phases/spec.md`
- Modify: `flow/phases/story.md`
- Modify: `runtime/guidance/construction.md`
- Modify: `docs/superpowers/specs/2026-08-02-behavior-baseline-lifecycle-design.md`
- Modify: `runtime/guidance/capability-preservation.json` only if a current source reference moves.

**Interfaces:**
- Consumes: completed runtime behavior.
- Produces: one consistent Windows-first operating contract.

- [x] Remove current references to durable `docs/mae-flow` paths and engineering-experience documents.
- [x] State configured per-CP Build, no duplicate final Build, review closure, and final conformance consistently.
- [x] Run targeted suites, full unittest discovery, selftest, Windows suite, and `git diff --check`.
- [x] Stage only exact task files, commit with the repository format, fetch, and push once without force.
